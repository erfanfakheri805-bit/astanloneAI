"""
Self-Builder - integrity checks, manifest and startup reconciliation
====================================================================
What a restart (or a crash, or a tampered file) must never be able to break:

  verify_version()   a registered version is only trusted if its module, test
                     suite and spec files exist, match the SHA-256 recorded in
                     the registry, the spec re-validates, the module passes the
                     AST allowlist and its own stored test suite passes.
  build_manifest()   a plain JSON picture of the registry (ids, versions, file
                     names, hashes, audit head) written next to the database.
  reconcile()        run once per process, before the registry is used, while
                     holding the workspace lock (lock.py - so it can never clean
                     up behind a build that is still running in another process;
                     when that build does not finish in time the clean-up is left
                     for the next start and only verification is done):
                       * unfinished upgrades (`started`) become `interrupted`
                       * unfinished checkpoints are settled (applied/abandoned)
                       * every ACTIVE version is verified; a broken one is
                         marked `broken` and the newest healthy older version
                         is re-activated (or the capability is disabled when
                         there is none)
                       * unregistered files (crash leftovers, strays) are
                         quarantined - never deleted - and staging is cleared
                       * the audit hash chain is re-verified
                       * the manifest is rewritten

Everything here is idempotent: running it twice changes nothing the second time.
"""

import json

from . import policy, registry as reg, sandbox, spec as spec_mod, store as store_mod
from .errors import SelfBuilderError
from .store import dumps, now_iso


def _read(ws, subdir, name, limit):
    try:
        return ws.read(subdir, name, limit), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, SelfBuilderError):
        return None, "unreadable"


def verify_version(ws, row, run_tests=True):
    """(ok, info) for one registry version row (see registry._version_row_to_dict)."""
    info = {"capability_id": row["capability_id"], "version": row["version"], "module": row["module_file"]}

    def fail(code, **extra):
        info.update(ok=False, error=code, **extra)
        return False, info

    module_bytes, problem = _read(ws, policy.SUBDIR_MODULES, row["module_file"], policy.MAX_SOURCE_BYTES)
    if module_bytes is None:
        return fail("E_VERIFY_MODULE_" + problem.upper())
    if sandbox.sha256_bytes(module_bytes) != row["module_sha256"]:
        return fail("E_VERIFY_MODULE_HASH")
    tests_bytes, problem = _read(ws, policy.SUBDIR_TESTS, row["tests_file"], policy.MAX_TESTS_BYTES)
    if tests_bytes is None:
        return fail("E_VERIFY_TESTS_" + problem.upper())
    if sandbox.sha256_bytes(tests_bytes) != row["tests_sha256"]:
        return fail("E_VERIFY_TESTS_HASH")
    spec_bytes, problem = _read(ws, policy.SUBDIR_SPECS, row["spec_file"], policy.MAX_TESTS_BYTES)
    if spec_bytes is None:
        return fail("E_VERIFY_SPEC_" + problem.upper())
    if sandbox.sha256_bytes(spec_bytes) != row["spec_sha256"]:
        return fail("E_VERIFY_SPEC_HASH")
    try:
        spec = json.loads(spec_bytes.decode("utf-8"))
        spec_mod.validate_spec(spec)
        if spec_mod.spec_fingerprint(spec) != row["fingerprint"]:
            return fail("E_VERIFY_SPEC_FINGERPRINT")
        suite = json.loads(tests_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return fail("E_VERIFY_JSON")
    except SelfBuilderError as e:
        return fail("E_VERIFY_SPEC_INVALID", spec_error=e.code)
    try:
        loaded = sandbox.load_module(ws.root, policy.SUBDIR_MODULES, row["module_file"], spec["kind"],
                                     row["capability_id"], row["version"], expected_sha256=row["module_sha256"])
    except SelfBuilderError as e:
        return fail("E_VERIFY_LOAD", load_error=e.code)
    info.update(ok=True)
    if run_tests:
        result = sandbox.run_suite(loaded, suite)
        info["tests"] = {"total": result["total"], "passed": result["passed"], "ok": result["ok"]}
        if not result["ok"]:
            return fail("E_VERIFY_TESTS_FAILED", failed=[f["name"] for f in result["failed"]][:10])
    return True, info


def build_manifest(store, registry):
    """Plain-data manifest of the whole registry (JSON-serialisable)."""
    caps = {}
    for row in store.query("SELECT * FROM capabilities ORDER BY capability_id"):
        cid = row["capability_id"]
        versions = {}
        for v in registry.versions(cid):
            versions[str(v["version"])] = {
                "status": v["status"], "created_at": v["created_at"], "fingerprint": v["fingerprint"],
                "module": v["module_file"], "module_sha256": v["module_sha256"],
                "tests": v["tests_file"], "tests_sha256": v["tests_sha256"],
                "spec": v["spec_file"], "spec_sha256": v["spec_sha256"],
                "parent_version": v["parent_version"],
            }
        caps[cid] = {"kind": row["kind"], "title": row["title"], "status": row["status"],
                     "active_version": row["active_version"], "latest_version": row["latest_version"],
                     "versions": versions}
    return {
        "schema": policy.SCHEMA_VERSION,
        "database_schema": store.schema_version(),
        "generated_at": now_iso(),
        "audit_head": store.last_audit_hash(),
        "capabilities": caps,
    }


def write_manifest(ws, store, registry):
    """Best effort: the manifest is a derived artefact, the database is the truth."""
    try:
        ws.write_manifest(build_manifest(store, registry))
        return True
    except (OSError, SelfBuilderError):
        return False


def _referenced_files(store):
    refs = {policy.SUBDIR_MODULES: set(), policy.SUBDIR_TESTS: set(), policy.SUBDIR_SPECS: set()}
    for row in store.query("SELECT module_file, tests_file, spec_file FROM capability_versions"):
        refs[policy.SUBDIR_MODULES].add(row["module_file"])
        refs[policy.SUBDIR_TESTS].add(row["tests_file"])
        refs[policy.SUBDIR_SPECS].add(row["spec_file"])
    return refs


def _quarantine(ws, subdir, name, reason):
    """Quarantine one file; a problem with that single file must never stop the start-up."""
    try:
        return ws.quarantine(subdir, name, reason)
    except (OSError, SelfBuilderError):
        return None


def _new_report():
    return {"partials_removed": [], "staging_cleared": [], "interrupted_upgrades": 0,
            "checkpoints_settled": {"applied": 0, "abandoned": 0}, "verified": [], "fallbacks": [],
            "disabled": [], "quarantined": [], "audit_chain": None, "manifest_written": False, "deferred": False}


def reconcile(ws, store, registry, lock_timeout=None):
    """Bring disk and database back into agreement. Returns a report dict.

    The whole run holds the workspace lock. If another build/rollback keeps it
    for `lock_timeout` seconds (default policy.RECONCILE_LOCK_SECONDS) nothing
    is cleaned or changed - the report says `deferred: True` and carries the
    read-only verification only."""
    timeout = policy.RECONCILE_LOCK_SECONDS if lock_timeout is None else lock_timeout
    if not ws.lock.acquire(timeout):
        return _reconcile_deferred(ws, store, registry)
    try:
        return _reconcile_locked(ws, store, registry)
    finally:
        ws.lock.release()


def _reconcile_deferred(ws, store, registry):
    report = _new_report()
    report["deferred"] = True
    for cap in store.query("SELECT * FROM capabilities WHERE active_version IS NOT NULL"):
        row = registry.version_row(cap["capability_id"], cap["active_version"])
        ok, info = (False, {"error": "E_VERIFY_NO_ROW"}) if row is None else verify_version(ws, row)
        report["verified"].append({"capability_id": cap["capability_id"], "version": cap["active_version"], "ok": ok,
                                   "error": None if ok else info.get("error")})
    chain_ok, bad_seq, count = store.verify_audit_chain()
    report["audit_chain"] = {"ok": chain_ok, "entries": count, "first_bad_seq": bad_seq}
    return report


def _reconcile_locked(ws, store, registry):
    report = _new_report()

    # 1. filesystem leftovers of interrupted writes / builds
    report["partials_removed"] = ws.sweep_partials()
    report["staging_cleared"] = ws.clear_staging()

    # 2. orphan files (never deleted: moved to quarantine)
    refs = _referenced_files(store)
    for subdir in (policy.SUBDIR_MODULES, policy.SUBDIR_TESTS, policy.SUBDIR_SPECS):
        for name in ws.listdir(subdir):
            if name not in refs[subdir]:
                moved = _quarantine(ws, subdir, name, "orphan")
                if moved is not None:        # a directory or an unmovable entry is left alone (and never loaded)
                    report["quarantined"].append({"dir": subdir, "name": name, "as": moved, "reason": "orphan"})

    # 3. verify every active version; fall back to the newest healthy older one
    fallbacks = []
    for cap in store.query("SELECT * FROM capabilities WHERE active_version IS NOT NULL"):
        cid = cap["capability_id"]
        row = registry.version_row(cid, cap["active_version"])
        ok, info = (False, {"error": "E_VERIFY_NO_ROW"}) if row is None else verify_version(ws, row)
        report["verified"].append({"capability_id": cid, "version": cap["active_version"], "ok": ok,
                                   "error": None if ok else info.get("error")})
        if ok:
            continue
        # tampered/corrupt module bytes are evidence: move them out of modules/
        if row is not None and info.get("error") in ("E_VERIFY_MODULE_HASH", "E_VERIFY_LOAD"):
            moved = _quarantine(ws, policy.SUBDIR_MODULES, row["module_file"], "integrity")
            report["quarantined"].append({"dir": policy.SUBDIR_MODULES, "name": row["module_file"],
                                          "as": moved, "reason": "integrity"})
        target = None
        target_info = None
        for older in sorted((v for v in registry.versions(cid) if v["version"] < cap["active_version"]
                             and v["status"] in reg.HEALTHY_STATUSES), key=lambda v: -v["version"]):
            ok2, info2 = verify_version(ws, older)
            if ok2:
                target, target_info = older, info2
                break
        fallbacks.append((cid, cap["active_version"], info, target, target_info))

    with store.transaction():
        # 4. unfinished upgrades and checkpoints
        cur = store.execute("UPDATE upgrade_log SET result = 'interrupted', finished_at = ? "
                            "WHERE result = 'started'", (now_iso(),))
        report["interrupted_upgrades"] = cur.rowcount or 0
        if report["interrupted_upgrades"]:
            store.audit("reconcile_interrupted", None, None, None, {"count": report["interrupted_upgrades"]})
        for ck in store.query("SELECT * FROM checkpoints WHERE status = 'pending'"):
            registered = store.query_one(
                "SELECT 1 AS x FROM capability_versions WHERE capability_id = ? AND version = ?",
                (ck["capability_id"], ck["to_version"]))
            status = "applied" if registered else "abandoned"
            store.execute("UPDATE checkpoints SET status = ? WHERE checkpoint_id = ?", (status, ck["checkpoint_id"]))
            report["checkpoints_settled"][status] += 1
        # 5. broken active versions
        for cid, version, info, target, target_info in fallbacks:
            store.execute("UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                          (reg.VER_BROKEN, cid, version))
            if target is not None:
                store.execute("UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                              (reg.VER_ACTIVE, cid, target["version"]))
                store.execute("UPDATE capabilities SET active_version = ?, status = ?, updated_at = ? "
                              "WHERE capability_id = ?", (target["version"], reg.CAP_ACTIVE, now_iso(), cid))
                store.audit("reconcile_fallback", cid, target["version"], None,
                            {"broken_version": version, "error": info.get("error"), "restored_version": target["version"]})
                report["fallbacks"].append({"capability_id": cid, "broken_version": version,
                                            "restored_version": target["version"], "error": info.get("error")})
            else:
                store.execute("UPDATE capabilities SET active_version = NULL, status = ?, updated_at = ? "
                              "WHERE capability_id = ?", (reg.CAP_DISABLED, now_iso(), cid))
                store.audit("reconcile_disabled", cid, version, None,
                            {"broken_version": version, "error": info.get("error")})
                report["disabled"].append({"capability_id": cid, "broken_version": version,
                                           "error": info.get("error")})
        if report["quarantined"]:
            store.audit("reconcile_quarantine", None, None, None, {"files": [q["name"] for q in report["quarantined"]]})
        if any(report[k] for k in ("fallbacks", "disabled", "quarantined")) or report["interrupted_upgrades"]:
            store.audit("reconcile_done", None, None, None, {
                "fallbacks": len(report["fallbacks"]), "disabled": len(report["disabled"]),
                "quarantined": len(report["quarantined"]), "interrupted": report["interrupted_upgrades"]})

    ok, bad_seq, count = store.verify_audit_chain()
    report["audit_chain"] = {"ok": ok, "entries": count, "first_bad_seq": bad_seq}
    report["manifest_written"] = write_manifest(ws, store, registry)
    return report


__all__ = ["verify_version", "build_manifest", "write_manifest", "reconcile", "dumps"]
