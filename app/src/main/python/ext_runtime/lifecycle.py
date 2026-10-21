"""
Extension runtime - the extension manager (lifecycle)
=====================================================
propose  ->  validate + compile + run the extension's own tests (twice, in sandboxes)  ->  PENDING proposal
approve  ->  (only on an explicit user decision) write the version files atomically, register the version, record the
             permission grants, then VERIFY the installed version from disk (hashes, re-validation, re-compile, tests);
             a version that fails verification is never left active
invoke / match   ->  see calls.py
update   ->  a changed package for an existing id becomes version N+1; the previous version is kept
rollback ->  switch the active version back (after verifying the target); versions are never deleted
reconcile -> at start-up: sweep partial writes, quarantine orphan files, re-verify every active version (falling back
             to the newest healthy older one), expire stale proposals, verify the audit hash chain

Nothing becomes active without `approve()`, and `approve()` is only ever called for a proposal the user confirmed.
"""

import hashlib
import json
import os
import secrets
import threading
import time

from self_builder.errors import ApplyError
from self_builder.lock import WorkspaceLock
from self_builder.store import now_iso

from . import hubstore, intake, limits, sandbox, suite
from .calls import CallsMixin
from .errors import ManifestError, PackageError, SourceRejected
from .manifest import canonical_json, check_source_consistency, fingerprint, validate_manifest

PROPOSAL_TTL_SECONDS = 7 * 24 * 3600
CAP_ACTIVE, CAP_DISABLED = "active", "disabled"
V_ACTIVE, V_SUPERSEDED, V_ROLLED_BACK, V_FAILED = "active", "superseded", "rolled_back", "failed"
P_PENDING, P_APPROVED, P_DECLINED, P_EXPIRED, P_SUPERSEDED, P_FAILED = "pending", "approved", "declined", "expired", "superseded", "failed"
_HEALTHY = (V_SUPERSEDED, V_ROLLED_BACK)


class _Integrity(Exception):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _names(cid, version):
    return f"{cid}_v{version}.py", f"{cid}_v{version}.json"


class ExtensionManager(CallsMixin):
    def __init__(self, root, clock=time.time, web_fetch=None, id_exists=None, lock_timeout=30.0):
        self.root = os.path.abspath(root)
        self._lock = threading.RLock()
        self._files = hubstore.HubFiles(self.root)
        self._store = hubstore.open_store(self.root)
        self._wslock = WorkspaceLock(os.path.join(self.root, hubstore.HUB_LOCK))
        self.clock = clock
        self.web_fetch = web_fetch
        self.id_exists = id_exists
        self._lock_timeout = lock_timeout
        self._cache = {}
        self._trigger_cache = {}

    def close(self):
        self._store.close()

    # ------------------------------------------------------------------ small readers
    def _cap_row(self, cid):
        r = self._store.query_one("SELECT * FROM ext_capabilities WHERE capability_id = ?", (cid,))
        return dict(r) if r else None

    def _version_row(self, cid, version):
        r = self._store.query_one("SELECT * FROM ext_versions WHERE capability_id = ? AND version = ?", (cid, version))
        return dict(r) if r else None

    def _versions(self, cid):
        return [dict(r) for r in self._store.query("SELECT * FROM ext_versions WHERE capability_id = ? ORDER BY version", (cid,))]

    def _proposal(self, pid):
        r = self._store.query_one("SELECT * FROM ext_proposals WHERE proposal_id = ?", (pid,))
        return dict(r) if r else None

    def _audit(self, event, cid=None, version=None, detail=None):
        with self._store.transaction():
            self._store.audit(event, cid, version, None, detail or {})

    def _clear_caches(self):
        self._cache.clear()
        self._trigger_cache.clear()

    # ------------------------------------------------------------------ loading and verifying a stored version
    def _load_files(self, row):
        """(manifest, compiled) of a stored version, after checking both file hashes and re-validating from scratch."""
        try:
            mbytes = self._files.read(hubstore.SUB_MANIFESTS, row["manifest_file"])
            sbytes = self._files.read(hubstore.SUB_MODULES, row["source_file"])
        except (OSError, hubstore.FileError) as e:
            raise _Integrity(f"a version file is missing or unreadable ({type(e).__name__})") from None
        if _sha(mbytes) != row["manifest_sha256"]:
            raise _Integrity("the manifest file does not match its recorded SHA-256")
        if _sha(sbytes) != row["source_sha256"]:
            raise _Integrity("the source file does not match its recorded SHA-256")
        key = (row["manifest_sha256"], row["source_sha256"])
        if key in self._cache:
            return self._cache[key]
        try:
            doc = json.loads(mbytes.decode("utf-8"))
            if doc.pop("source_sha256", None) != row["source_sha256"]:
                raise _Integrity("the manifest does not belong to this source file")
            doc["source"] = sbytes.decode("utf-8")
            manifest = validate_manifest(doc)
        except (ValueError, UnicodeDecodeError):
            raise _Integrity("the stored manifest is not readable") from None
        except ManifestError as e:
            raise _Integrity("the stored manifest no longer validates: " + "; ".join(i["message"] for i in e.issues[:3])) from None
        if fingerprint(manifest) != row["fingerprint"]:
            raise _Integrity("the stored manifest does not match its recorded fingerprint")
        try:
            compiled = sandbox.compile_source(manifest["source"], [i["name"] for i in manifest["inputs"]], row["capability_id"])
        except SourceRejected as e:
            raise _Integrity("the stored source no longer validates: " + "; ".join(i["message"] for i in e.issues[:3])) from None
        problems = check_source_consistency(manifest, compiled)
        if problems:
            raise _Integrity(problems[0]["message"])
        if len(self._cache) >= 64:
            self._cache.clear()
        self._cache[key] = (manifest, compiled)
        return manifest, compiled

    def verify_version(self, cid, version, run_tests=True):
        """Is this stored version registered, loadable and callable, and does its own acceptance suite pass?"""
        row = self._version_row(cid, version)
        if row is None:
            return {"ok": False, "reason": "no such version", "checks": {}}
        checks = {"registered": True}
        try:
            manifest, compiled = self._load_files(row)
        except _Integrity as e:
            return {"ok": False, "reason": str(e), "checks": {**checks, "loadable": False}}
        checks["loadable"] = True
        if run_tests:
            report = suite.run_suite(manifest, compiled)
            checks["tests"] = {"passed": report["passed"], "total": report["total"], "deterministic": report["deterministic"]}
            checks["callable"] = report["passed"] > 0
            if not report["all_passed"]:
                return {"ok": False, "reason": "the acceptance tests do not pass", "checks": checks, "report": report}
            return {"ok": True, "reason": "", "checks": checks, "report": report}
        return {"ok": True, "reason": "", "checks": checks}

    # ------------------------------------------------------------------ propose
    def _rejected(self, stage, code, issues, cid, origin, extra=None):
        self._audit("ext.rejected", cid, None, {"stage": stage, "code": code, "origin": origin,
                                               "issues": [{k: i.get(k) for k in ("code", "path", "line", "message")} for i in issues[:10]]})
        out = {"status": "rejected", "stage": stage, "code": code, "issues": issues, "capability_id": cid}
        out.update(extra or {})
        return out

    def propose(self, data, origin="chat", expected_sha256=None):
        """Parse a package (JSON text/bytes or ZIP), then `propose_manifest`. Never activates anything."""
        try:
            obj, source, digest = intake.parse_package(data, expected_sha256)
        except PackageError as e:
            return self._rejected("package", e.code, [{"code": e.code, "path": "", "message": str(e)}], None, origin)
        return self.propose_manifest(obj, source=source, origin=origin, package_sha256=digest)

    def propose_manifest(self, obj, source=None, origin="chat", package_sha256=None):
        with self._lock:
            try:
                m = validate_manifest(obj, source)
            except ManifestError as e:
                return self._rejected("manifest", e.code, e.issues, obj.get("id") if isinstance(obj, dict) and isinstance(obj.get("id"), str) else None, origin)
            cid = m["id"]
            cap = self._cap_row(cid)
            if cap is None and self.id_exists is not None and self.id_exists(cid):
                return self._rejected("id", "E_EXT_ID_TAKEN", [{"code": "id", "path": "id", "message": f"the id {cid!r} is already used by another capability"}], cid, origin)
            try:
                compiled = sandbox.compile_source(m["source"], [i["name"] for i in m["inputs"]], cid)
            except SourceRejected as e:
                return self._rejected("source", e.code, e.issues, cid, origin)
            problems = check_source_consistency(m, compiled)
            if problems:
                return self._rejected("consistency", "E_EXT_CONSISTENCY", problems, cid, origin)
            report = suite.run_suite(m, compiled)
            if not report["all_passed"]:
                failed = [{"code": "test", "path": c["name"], "message": c["reason"]} for c in report["cases"] if not c["passed"]] \
                    or [{"code": "test", "path": "", "message": "the suite is not deterministic"}]
                return self._rejected("tests", "E_EXT_TESTS", failed, cid, origin, {"tests": report})
            fp = fingerprint(m)
            active = self._version_row(cid, cap["active_version"]) if cap and cap["active_version"] else None
            if active is not None and active["fingerprint"] == fp and cap["status"] == CAP_ACTIVE:
                return {"status": "noop_identical", "capability_id": cid, "version": active["version"], "title": m["title"]}
            planned = (cap["latest_version"] if cap else 0) + 1
            prev_perms = set(json.loads(active["permissions_json"])) if active else set()
            optional = sorted(set(m["permissions"]) - {limits.PERM_COMPUTE})
            review = {"title": m["title"], "description": m["description"], "version_label": m["version_label"],
                      "inputs": [{k: i.get(k) for k in ("name", "type", "label", "required")} for i in m["inputs"]],
                      "outputs": m["outputs"], "permissions": optional, "new_permissions": sorted(set(optional) - prev_perms),
                      "dependencies": m["dependencies"], "triggers": m["triggers"], "examples": m["examples"],
                      "source_lines": m["source"].count("\n") + 1, "source_sha256": _sha(m["source"].encode("utf-8")),
                      "fingerprint": fp, "origin": origin, "provenance": m.get("provenance", {})}
            full_report = {"tests": report, "validation": {"nodes": compiled.nodes, "functions": sorted(compiled.functions),
                                                           "helpers_used": sorted(compiled.helpers_used)}, "review": review}
            pid = "p" + secrets.token_hex(5)
            now = float(self.clock())
            with self._store.transaction():
                self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE capability_id = ? AND status = ?",
                                    (P_SUPERSEDED, now, cid, P_PENDING))
                self._store.execute(
                    "INSERT INTO ext_proposals(proposal_id, capability_id, planned_version, action, manifest_json, fingerprint, "
                    "report_json, origin, package_sha256, status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, cid, planned, "update" if cap else "create", canonical_json(m), fp, canonical_json(full_report), origin,
                     package_sha256, P_PENDING, now, now + PROPOSAL_TTL_SECONDS))
                self._store.audit("ext.proposed", cid, planned, None,
                                  {"proposal_id": pid, "action": "update" if cap else "create", "fingerprint": fp, "origin": origin,
                                   "package_sha256": package_sha256, "permissions": optional, "tests": f"{report['passed']}/{report['total']}"})
            return {"status": "pending_approval", "proposal_id": pid, "capability_id": cid, "title": m["title"],
                    "action": "update" if cap else "create", "planned_version": planned, "permissions": optional,
                    "new_permissions": review["new_permissions"], "tests": {"passed": report["passed"], "total": report["total"]},
                    "review": review, "expires_at": now + PROPOSAL_TTL_SECONDS}

    def pending(self):
        with self._lock:
            now = float(self.clock())
            rows = [dict(r) for r in self._store.query("SELECT * FROM ext_proposals WHERE status = ? ORDER BY created_at", (P_PENDING,))]
            out = []
            for r in rows:
                if now > r["expires_at"]:
                    with self._store.transaction():
                        self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?", (P_EXPIRED, now, r["proposal_id"]))
                        self._store.audit("ext.proposal_expired", r["capability_id"], r["planned_version"], None, {"proposal_id": r["proposal_id"]})
                    continue
                review = json.loads(r["report_json"]).get("review", {})
                out.append({"proposal_id": r["proposal_id"], "capability_id": r["capability_id"], "title": review.get("title"),
                            "action": r["action"], "planned_version": r["planned_version"], "permissions": review.get("permissions", []),
                            "new_permissions": review.get("new_permissions", []), "expires_at": r["expires_at"], "review": review})
            return out

    def proposal(self, pid):
        r = self._proposal(pid)
        if r is None:
            return None
        return {"proposal_id": pid, "capability_id": r["capability_id"], "status": r["status"], "action": r["action"],
                "planned_version": r["planned_version"], "review": json.loads(r["report_json"]).get("review", {})}

    def decline(self, pid, reason="user declined"):
        with self._lock:
            r = self._proposal(pid)
            if r is None:
                return {"status": "failed", "code": "E_EXT_NO_PROPOSAL"}
            if r["status"] != P_PENDING:
                return {"status": "not_pending", "proposal_status": r["status"]}
            with self._store.transaction():
                self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?", (P_DECLINED, float(self.clock()), pid))
                self._store.audit("ext.declined", r["capability_id"], r["planned_version"], None, {"proposal_id": pid, "reason": reason})
            return {"status": "declined", "capability_id": r["capability_id"]}

    # ------------------------------------------------------------------ approve = install + activate
    def approve(self, pid, approver="user"):
        try:
            with self._lock, self._wslock.held(self._lock_timeout):
                return self._approve_locked(pid, approver)
        except ApplyError:
            return {"status": "busy", "code": "E_EXT_BUSY"}

    def _fail_proposal(self, pid, r, code, detail):
        with self._store.transaction():
            self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ?, detail_json = ? WHERE proposal_id = ?",
                                (P_FAILED, float(self.clock()), json.dumps({"code": code, "detail": detail}, ensure_ascii=False), pid))
            self._store.audit("ext.activation_failed", r["capability_id"], r["planned_version"], None, {"proposal_id": pid, "code": code, "detail": detail[:300]})
        return {"status": "failed", "code": code, "detail": detail, "capability_id": r["capability_id"]}

    def _write_file(self, sub, name, data):
        """Write one version file atomically. A file with this name but different content (an orphan of an earlier
        interrupted attempt) is moved to quarantine first - never overwritten silently."""
        if self._files.exists(sub, name):
            if _sha(self._files.read(sub, name)) == _sha(data):
                return
            self._files.quarantine(sub, name, "stale")
        self._files.write(sub, name, data)

    def _approve_locked(self, pid, approver):
        r = self._proposal(pid)
        if r is None:
            return {"status": "failed", "code": "E_EXT_NO_PROPOSAL"}
        if r["status"] != P_PENDING:
            return {"status": "not_pending", "proposal_status": r["status"], "capability_id": r["capability_id"]}
        if float(self.clock()) > r["expires_at"]:
            with self._store.transaction():
                self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?", (P_EXPIRED, float(self.clock()), pid))
                self._store.audit("ext.proposal_expired", r["capability_id"], r["planned_version"], None, {"proposal_id": pid})
            return {"status": "expired", "capability_id": r["capability_id"]}
        try:
            m = validate_manifest(json.loads(r["manifest_json"]))
            if fingerprint(m) != r["fingerprint"]:
                return self._fail_proposal(pid, r, "E_EXT_FINGERPRINT", "the stored proposal was modified")
            compiled = sandbox.compile_source(m["source"], [i["name"] for i in m["inputs"]], m["id"])
        except (ValueError, ManifestError, SourceRejected) as e:
            return self._fail_proposal(pid, r, "E_EXT_REVALIDATE", f"the proposal no longer validates: {str(e)[:200]}")
        report = suite.run_suite(m, compiled)
        if not report["all_passed"]:
            return self._fail_proposal(pid, r, "E_EXT_TESTS", "the acceptance tests no longer pass")
        cid = m["id"]
        cap = self._cap_row(cid)
        version = (cap["latest_version"] if cap else 0) + 1
        prev = cap["active_version"] if cap else None
        source_bytes = m["source"].encode("utf-8")
        doc = {k: v for k, v in m.items() if k != "source"}
        doc["source_sha256"] = _sha(source_bytes)
        manifest_bytes = (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
        src_name, man_name = _names(cid, version)
        try:
            self._write_file(hubstore.SUB_MODULES, src_name, source_bytes)
            self._write_file(hubstore.SUB_MANIFESTS, man_name, manifest_bytes)
        except (OSError, hubstore.FileError) as e:
            return self._fail_proposal(pid, r, "E_EXT_WRITE", f"cannot write the version files: {type(e).__name__}")
        optional = sorted(set(m["permissions"]) - {limits.PERM_COMPUTE})
        now = now_iso()
        full = json.loads(r["report_json"])
        with self._store.transaction():
            self._store.execute(
                "INSERT INTO ext_versions(capability_id, version, fingerprint, manifest_file, manifest_sha256, source_file, source_sha256, "
                "permissions_json, report_json, origin, provenance_json, status, parent_version, proposal_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, version, r["fingerprint"], man_name, _sha(manifest_bytes), src_name, _sha(source_bytes),
                 json.dumps(m["permissions"]), canonical_json({"tests": report, "review": full.get("review", {})}), r["origin"],
                 json.dumps(m.get("provenance", {}), ensure_ascii=False), V_ACTIVE, prev, pid, now))
            if prev:
                self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ? AND status = ?",
                                    (V_SUPERSEDED, cid, prev, V_ACTIVE))
            if cap is None:
                self._store.execute("INSERT INTO ext_capabilities(capability_id, title, description, status, active_version, latest_version, "
                                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)", (cid, m["title"], m["description"], CAP_ACTIVE, version, version, now, now))
            else:
                self._store.execute("UPDATE ext_capabilities SET title = ?, description = ?, status = ?, active_version = ?, latest_version = ?, "
                                    "updated_at = ? WHERE capability_id = ?", (m["title"], m["description"], CAP_ACTIVE, version, version, now, cid))
            for perm in optional:
                self._store.execute("INSERT INTO ext_grants(capability_id, permission, granted_at, granted_by) VALUES (?,?,?,?) "
                                    "ON CONFLICT(capability_id, permission) DO UPDATE SET granted_at = excluded.granted_at, granted_by = excluded.granted_by",
                                    (cid, perm, now, approver))
            self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?", (P_APPROVED, float(self.clock()), pid))
            self._store.audit("ext.approved", cid, version, None, {"proposal_id": pid, "approver": approver, "permissions_granted": optional,
                                                                  "fingerprint": r["fingerprint"], "origin": r["origin"]})
            self._store.audit("ext.activated", cid, version, None, {"previous_version": prev, "tests": f"{report['passed']}/{report['total']}"})
        self._clear_caches()
        verdict = self.verify_version(cid, version)
        if not verdict["ok"]:
            self._undo_activation(cid, version, prev, verdict["reason"])
            return {"status": "failed", "code": "E_EXT_VERIFY", "detail": verdict["reason"], "capability_id": cid,
                    "restored_version": prev, "version": version}
        return {"status": "applied", "capability_id": cid, "version": version, "previous_version": prev, "title": m["title"],
                "permissions_granted": optional, "tests": {"passed": report["passed"], "total": report["total"]}, "verified": verdict["checks"]}

    def _undo_activation(self, cid, version, prev, reason):
        now = now_iso()
        with self._store.transaction():
            self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ?", (V_FAILED, cid, version))
            if prev and self.verify_version(cid, prev, run_tests=False)["ok"]:
                self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ?", (V_ACTIVE, cid, prev))
                self._store.execute("UPDATE ext_capabilities SET status = ?, active_version = ?, updated_at = ? WHERE capability_id = ?", (CAP_ACTIVE, prev, now, cid))
            else:
                self._store.execute("UPDATE ext_capabilities SET status = ?, active_version = NULL, updated_at = ? WHERE capability_id = ?", (CAP_DISABLED, now, cid))
            self._store.audit("ext.activation_failed", cid, version, None, {"reason": reason[:300], "restored_version": prev})
        self._clear_caches()

    # ------------------------------------------------------------------ rollback / disable / enable
    def rollback(self, cid, to_version=None, reason="user request"):
        try:
            with self._lock, self._wslock.held(self._lock_timeout):
                return self._rollback_locked(cid, to_version, reason)
        except ApplyError:
            return {"status": "busy", "code": "E_EXT_BUSY"}

    def _rollback_locked(self, cid, to_version, reason):
        cap = self._cap_row(cid)
        if cap is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        cur = cap["active_version"]
        rows = self._versions(cid)
        if to_version is None:
            cands = sorted((r["version"] for r in rows if r["status"] in _HEALTHY and (cur is None or r["version"] < cur)), reverse=True)
        else:
            row = self._version_row(cid, to_version)
            if row is None or row["status"] not in _HEALTHY:
                return {"status": "failed", "code": "E_EXT_BAD_TARGET", "detail": "that version does not exist or never passed verification"}
            cands = [to_version]
        if not cands:
            return {"status": "nothing_to_roll_back", "capability_id": cid, "active_version": cur}
        target, why = None, ""
        for v in cands:
            verdict = self.verify_version(cid, v)
            if verdict["ok"]:
                target = v
                break
            why = verdict["reason"]
        if target is None:
            self._audit("ext.rollback_failed", cid, cur, {"reason": why[:300]})
            return {"status": "failed", "code": "E_EXT_VERIFY", "detail": why, "capability_id": cid, "active_version": cur}
        now = now_iso()
        with self._store.transaction():
            if cur:
                self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ? AND status = ?", (V_ROLLED_BACK, cid, cur, V_ACTIVE))
            self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ?", (V_ACTIVE, cid, target))
            row = self._version_row(cid, target)
            self._store.execute("UPDATE ext_capabilities SET status = ?, active_version = ?, updated_at = ? WHERE capability_id = ?", (CAP_ACTIVE, target, now, cid))
            self._store.audit("ext.rolled_back", cid, target, None, {"from_version": cur, "to_version": target, "reason": reason[:200]})
        self._clear_caches()
        return {"status": "rolled_back", "capability_id": cid, "from_version": cur, "to_version": target, "title": cap["title"]}

    def disable(self, cid, reason="user request"):
        with self._lock:
            cap = self._cap_row(cid)
            if cap is None:
                return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
            with self._store.transaction():
                self._store.execute("UPDATE ext_capabilities SET status = ?, updated_at = ? WHERE capability_id = ?", (CAP_DISABLED, now_iso(), cid))
                self._store.audit("ext.disabled", cid, cap["active_version"], None, {"reason": reason[:200]})
            return {"status": "disabled", "capability_id": cid, "title": cap["title"]}

    def enable(self, cid):
        with self._lock:
            cap = self._cap_row(cid)
            if cap is None or not cap["active_version"]:
                return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
            verdict = self.verify_version(cid, cap["active_version"])
            if not verdict["ok"]:
                return {"status": "failed", "code": "E_EXT_VERIFY", "detail": verdict["reason"]}
            with self._store.transaction():
                self._store.execute("UPDATE ext_capabilities SET status = ?, updated_at = ? WHERE capability_id = ?", (CAP_ACTIVE, now_iso(), cid))
                self._store.audit("ext.enabled", cid, cap["active_version"], None, {})
            return {"status": "enabled", "capability_id": cid, "title": cap["title"]}

    # ------------------------------------------------------------------ permissions
    def grants(self, cid):
        return {r["permission"] for r in self._store.query("SELECT permission FROM ext_grants WHERE capability_id = ?", (cid,))}

    def permission_state(self, cid):
        cap = self._cap_row(cid)
        if cap is None or not cap["active_version"]:
            return {"declared": [], "granted": sorted(self.grants(cid)), "missing": []}
        row = self._version_row(cid, cap["active_version"])
        declared = sorted(set(json.loads(row["permissions_json"])) - {limits.PERM_COMPUTE})
        granted = self.grants(cid)
        return {"declared": declared, "granted": sorted(set(declared) & granted), "missing": sorted(set(declared) - granted)}

    def grant(self, cid, permission, by="user"):
        with self._lock:
            state = self.permission_state(cid)
            if permission not in state["declared"]:
                return {"status": "failed", "code": "E_EXT_PERMISSION", "detail": "the active version does not declare this permission"}
            with self._store.transaction():
                self._store.execute("INSERT INTO ext_grants(capability_id, permission, granted_at, granted_by) VALUES (?,?,?,?) "
                                    "ON CONFLICT(capability_id, permission) DO UPDATE SET granted_at = excluded.granted_at, granted_by = excluded.granted_by",
                                    (cid, permission, now_iso(), by))
                self._store.audit("ext.permission_granted", cid, None, None, {"permission": permission, "by": by})
            return {"status": "granted", "capability_id": cid, "permission": permission}

    def revoke(self, cid, permission, by="user"):
        with self._lock:
            if self._cap_row(cid) is None:
                return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
            with self._store.transaction():
                self._store.execute("DELETE FROM ext_grants WHERE capability_id = ? AND permission = ?", (cid, permission))
                self._store.audit("ext.permission_revoked", cid, None, None, {"permission": permission, "by": by})
            return {"status": "revoked", "capability_id": cid, "permission": permission}

    # ------------------------------------------------------------------ start-up recovery
    def reconcile(self):
        """Make the stored state trustworthy again after a crash/kill/corruption. Safe to run at every start."""
        with self._lock, self._wslock.held(self._lock_timeout):
            report = {"partials_removed": self._files.sweep_partials(), "quarantined": [], "fell_back": [], "disabled": [],
                      "expired_proposals": 0, "failed_versions": []}
            known = {(hubstore.SUB_MODULES, r["source_file"]) for r in self._store.query("SELECT source_file FROM ext_versions")} | \
                    {(hubstore.SUB_MANIFESTS, r["manifest_file"]) for r in self._store.query("SELECT manifest_file FROM ext_versions")}
            for sub in (hubstore.SUB_MODULES, hubstore.SUB_MANIFESTS):
                for name in self._files.listdir(sub):
                    if (sub, name) not in known:
                        q = self._files.quarantine(sub, name, "orphan")
                        if q:
                            report["quarantined"].append(q)
            for cap in [dict(r) for r in self._store.query("SELECT * FROM ext_capabilities")]:
                cid, cur = cap["capability_id"], cap["active_version"]
                if not cur:
                    continue
                verdict = self.verify_version(cid, cur)
                if verdict["ok"]:
                    continue
                report["failed_versions"].append({"capability_id": cid, "version": cur, "reason": verdict["reason"]})
                self._repair_active(cid, verdict["reason"], report)
            now = float(self.clock())
            with self._store.transaction():
                cur = self._store.execute("UPDATE ext_proposals SET status = ?, decided_at = ? WHERE status = ? AND expires_at < ?", (P_EXPIRED, now, P_PENDING, now))
                report["expired_proposals"] = cur.rowcount
            ok, bad_seq, count = self._store.verify_audit_chain()
            report["audit"] = {"ok": ok, "entries": count, "first_bad_seq": bad_seq}
            self._audit("ext.reconciled", None, None, {k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k != "audit"})
            self._clear_caches()
            return report

    def _repair_active(self, cid, reason, report=None):
        """The active version of `cid` failed verification: fall back to the newest healthy older version, else disable."""
        cap = self._cap_row(cid)
        cur = cap["active_version"]
        older = sorted((r["version"] for r in self._versions(cid) if r["status"] in _HEALTHY and (cur is None or r["version"] < cur)), reverse=True)
        target = next((v for v in older if self.verify_version(cid, v)["ok"]), None)
        now = now_iso()
        with self._store.transaction():
            if cur:
                self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ?", (V_FAILED, cid, cur))
            if target:
                self._store.execute("UPDATE ext_versions SET status = ? WHERE capability_id = ? AND version = ?", (V_ACTIVE, cid, target))
                self._store.execute("UPDATE ext_capabilities SET status = ?, active_version = ?, updated_at = ? WHERE capability_id = ?", (CAP_ACTIVE, target, now, cid))
                self._store.audit("ext.auto_rollback", cid, target, None, {"from_version": cur, "reason": reason[:300]})
            else:
                self._store.execute("UPDATE ext_capabilities SET status = ?, active_version = NULL, updated_at = ? WHERE capability_id = ?", (CAP_DISABLED, now, cid))
                self._store.audit("ext.auto_disabled", cid, cur, None, {"reason": reason[:300]})
        self._clear_caches()
        if report is not None:
            (report["fell_back"] if target else report["disabled"]).append({"capability_id": cid, "from_version": cur, "to_version": target})
        return target

    def status(self):
        with self._lock:
            caps = [dict(r) for r in self._store.query("SELECT status, COUNT(*) AS n FROM ext_capabilities GROUP BY status")]
            pend = self._store.query_one("SELECT COUNT(*) AS n FROM ext_proposals WHERE status = ?", (P_PENDING,))["n"]
            ok, bad_seq, count = self._store.verify_audit_chain()
            return {"schema_version": self._store.schema_version(), "capabilities": {c["status"]: c["n"] for c in caps},
                    "pending_proposals": pend, "audit": {"ok": ok, "entries": count, "first_bad_seq": bad_seq}}
