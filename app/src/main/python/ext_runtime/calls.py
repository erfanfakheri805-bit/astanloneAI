"""
Extension runtime - calling, matching and describing installed extensions
=========================================================================
Mixed into ExtensionManager (lifecycle.py). `match()` maps a chat sentence to an active extension and its inputs
using only the manifests' trigger patterns; `invoke()` runs ONE active extension in the sandbox, after re-checking
its files' hashes and its permission grants, and returns a result dict that never raises for user-level problems.
"""

import json

from self_builder import fa_text
from self_builder.errors import ApplyError
from self_builder.store import loads, now_iso

from . import hubstore, limits, patterns, sandbox
from .errors import ExtError
from .manifest import check_outputs, coerce_inputs, render_answer
from .suite import check_key, check_value

_TITLE_FILLER = frozenset(fa_text.words("را رو با برای از به و ی که این آن اون یک یه قابلیت افزونه"))


class _LiveCtx:
    """The host services one live call may use (only the ones its permissions were granted for are exposed)."""

    def __init__(self, mgr, cid):
        self._m, self._cid = mgr, cid

    def clock(self):
        return float(self._m.clock())

    def store_get(self, key, default=None):
        check_key(key)
        row = self._m._store.query_one("SELECT value_json FROM ext_kv WHERE capability_id = ? AND key = ?", (self._cid, key))
        return json.loads(row["value_json"]) if row else default

    def store_put(self, key, value):
        check_key(key)
        check_value(value)
        s = self._m._store
        with s.transaction():
            exists = s.query_one("SELECT 1 FROM ext_kv WHERE capability_id = ? AND key = ?", (self._cid, key))
            if not exists and s.query_one("SELECT COUNT(*) AS n FROM ext_kv WHERE capability_id = ?", (self._cid,))["n"] >= limits.MAX_KV_KEYS:
                raise ValueError("too many stored keys")
            s.execute("INSERT INTO ext_kv(capability_id, key, value_json, updated_at) VALUES (?,?,?,?) "
                      "ON CONFLICT(capability_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                      (self._cid, key, json.dumps(value, ensure_ascii=False), now_iso()))

    def store_delete(self, key):
        check_key(key)
        self._m._store.execute("DELETE FROM ext_kv WHERE capability_id = ? AND key = ?", (self._cid, key))

    def store_keys(self):
        return [r["key"] for r in self._m._store.query("SELECT key FROM ext_kv WHERE capability_id = ? ORDER BY key", (self._cid,))]

    def web_fetch_text(self, url):
        fetch = self._m.web_fetch
        if fetch is None:
            raise RuntimeError("network access is not available in this app build")
        try:
            text = fetch(url)
        except Exception as e:                                           # the host's message, never a traceback
            raise RuntimeError(str(e)[:200] or "the page could not be fetched") from None
        return str(text)[:limits.MAX_FETCH_TEXT]


class CallsMixin:
    # ------------------------------------------------------------------ usage / description
    def _usage(self, cid, version, ok):
        with self._store.transaction():
            self._store.execute(
                "INSERT INTO ext_usage(capability_id, version, calls, failures, last_used_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(capability_id, version) DO UPDATE SET calls = calls + 1, failures = failures + ?, last_used_at = excluded.last_used_at",
                (cid, version, 1, 0 if ok else 1, now_iso(), 0 if ok else 1))

    def usage(self, cid):
        return [dict(r) for r in self._store.query("SELECT version, calls, failures, last_used_at FROM ext_usage WHERE capability_id = ? ORDER BY version", (cid,))]

    def _tested(self, row):
        rep = loads(row["report_json"], {}) if row else {}
        t = rep.get("tests", {})
        return bool(t.get("all_passed"))

    def _summary(self, cap):
        row = self._version_row(cap["capability_id"], cap["active_version"]) if cap["active_version"] else None
        perms = self.permission_state(cap["capability_id"])
        state = "active"
        if cap["status"] != "active" or row is None:
            state = "disabled"
        elif perms["missing"]:
            state = "permission_blocked"
        else:
            try:
                self._load_files(row)
            except Exception:
                state = "broken"
        info = {"capability_id": cap["capability_id"], "kind": "extension", "title": cap["title"], "description": cap["description"],
                "status": cap["status"], "state": state, "active_version": cap["active_version"], "latest_version": cap["latest_version"],
                "permissions": perms, "tested": self._tested(row), "created_at": cap["created_at"], "updated_at": cap["updated_at"],
                "triggers": [], "examples": [], "inputs": [], "outputs": []}
        if row is not None and state != "broken":
            try:
                manifest, _ = self._load_files(row)
                info.update(triggers=manifest["triggers"], examples=manifest["examples"], inputs=manifest["inputs"], outputs=manifest["outputs"])
            except Exception:
                pass
        return info

    def list_capabilities(self):
        with self._lock:
            return [self._summary(dict(r)) for r in self._store.query("SELECT * FROM ext_capabilities ORDER BY capability_id")]

    def get(self, cid):
        with self._lock:
            cap = self._cap_row(cid)
            return None if cap is None else self._summary(cap)

    def versions(self, cid):
        with self._lock:
            out = []
            for r in self._versions(cid):
                rep = loads(r["report_json"], {})
                t = rep.get("tests", {})
                out.append({"version": r["version"], "status": r["status"], "fingerprint": r["fingerprint"][:12], "origin": r["origin"],
                            "parent_version": r["parent_version"], "created_at": r["created_at"],
                            "permissions": sorted(set(loads(r["permissions_json"], [])) - {limits.PERM_COMPUTE}),
                            "tests": f"{t.get('passed', 0)}/{t.get('total', 0)}", "tested": bool(t.get("all_passed"))})
            return out

    def history(self, cid=None, limit=30):
        with self._lock:
            return [{"seq": e["seq"], "ts": e["ts"], "event": e["event"], "capability_id": e["capability_id"], "version": e["version"],
                     "detail": loads(e["detail_json"], {})} for e in self._store.audit_entries(limit, cid)]

    def find_capability(self, text):
        """The installed extension a sentence refers to by id or by title, or None."""
        toks = set(fa_text.words(text))
        raw = str(text or "").lower()
        best, best_score = None, 0.0
        with self._lock:
            for r in self._store.query("SELECT capability_id, title FROM ext_capabilities"):
                cid = r["capability_id"]
                if cid in raw.replace("-", "_").split() or f" {cid} " in f" {raw} ":
                    return cid
                words = [w for w in fa_text.words(r["title"]) if w not in _TITLE_FILLER]
                if not words:
                    continue
                score = sum(1 for w in words if w in toks) / len(words)
                if score >= 0.8 and score > best_score:
                    best, best_score = cid, score
        return best

    # ------------------------------------------------------------------ matching
    def _triggers_for(self, row):
        key = (row["manifest_sha256"], row["source_sha256"])
        cached = self._trigger_cache.get(key)
        if cached is not None:
            return cached
        manifest, _ = self._load_files(row)                                  # raises _Integrity: caller skips this extension
        types = {i["name"]: i["type"] for i in manifest["inputs"]}
        trigs = [patterns.compile_trigger(t, types) for t in manifest["triggers"]]
        if len(self._trigger_cache) >= 128:
            self._trigger_cache.clear()
        self._trigger_cache[key] = trigs
        return trigs

    def match(self, text, include_disabled=False):
        """Which extension (if any) does this sentence ask for, and with which inputs?"""
        prep = patterns.prepare(text)
        if not prep.tokens:
            return {"status": "none"}
        best, best_disabled = None, None
        with self._lock:
            for cap in [dict(r) for r in self._store.query("SELECT * FROM ext_capabilities WHERE active_version IS NOT NULL ORDER BY capability_id")]:
                row = self._version_row(cap["capability_id"], cap["active_version"])
                if row is None:
                    continue
                enabled = cap["status"] == "active"
                if not enabled and not include_disabled:
                    continue
                try:
                    trigs = self._triggers_for(row)
                except Exception:
                    continue
                hit = patterns.best_match(trigs, prep)
                if hit is None:
                    continue
                idx, values, trig = hit
                score = (trig.literals, len(values))
                slot = (score, cap, row, values, trig)
                if enabled:
                    if best is None or score > best[0]:
                        best = slot
                elif best_disabled is None or score > best_disabled[0]:
                    best_disabled = slot
            chosen = best or best_disabled
            if chosen is None:
                return {"status": "none"}
            _, cap, row, values, trig = chosen
            manifest, _compiled = self._load_files(row)
            inputs, problems = coerce_inputs(manifest, values)
            base = {"capability_id": cap["capability_id"], "version": row["version"], "title": cap["title"], "trigger": trig.source}
            if chosen is best_disabled and best is None:
                return {"status": "disabled", **base}
            missing = [p for p in problems if p["code"] == "missing"]
            if missing and len(missing) == len(problems):
                by_name = {i["name"]: i for i in manifest["inputs"]}
                return {"status": "needs_inputs", **base, "have": inputs if not problems else {k: v for k, v in values.items()},
                        "missing": [{"name": p["name"], "label": by_name[p["name"]]["label"], "type": by_name[p["name"]]["type"]} for p in missing]}
            if problems:
                return {"status": "invalid_inputs", **base, "problems": problems}
            return {"status": "invoke", **base, "inputs": inputs}

    # ------------------------------------------------------------------ invoking
    def invoke(self, cid, inputs):
        """Run the ACTIVE version of `cid`. Returns {"ok": bool, "status": ..., ...}; never raises for user-level problems."""
        out = self._invoke_once(cid, inputs)
        if out.get("status") == "integrity_failed" and out.get("repaired_to"):
            again = self._invoke_once(cid, inputs)
            again["fallback_from"] = out.get("failed_version")
            again["fallback_reason"] = out.get("reason")
            return again
        return out

    def _invoke_once(self, cid, inputs):
        from .lifecycle import _Integrity            # circular at import time only
        with self._lock:
            cap = self._cap_row(cid)
            if cap is None:
                return {"ok": False, "status": "not_found", "capability_id": cid}
            if cap["status"] != "active" or not cap["active_version"]:
                return {"ok": False, "status": "disabled", "capability_id": cid, "title": cap["title"]}
            version = cap["active_version"]
            row = self._version_row(cid, version)
            perms = self.permission_state(cid)
            if perms["missing"]:
                return {"ok": False, "status": "blocked_permission", "capability_id": cid, "title": cap["title"], "version": version,
                        "missing_permissions": perms["missing"]}
            try:
                manifest, compiled = self._load_files(row)
            except _Integrity as e:
                reason = str(e)
                try:
                    with self._wslock.held(self._lock_timeout):
                        target = self._repair_active(cid, reason)
                except ApplyError:
                    target = None
                return {"ok": False, "status": "integrity_failed", "capability_id": cid, "title": cap["title"], "failed_version": version,
                        "reason": reason, "repaired_to": target}
        ins, problems = coerce_inputs(manifest, inputs)
        if problems:
            return {"ok": False, "status": "invalid_inputs", "capability_id": cid, "title": cap["title"], "version": version, "problems": problems}
        res = sandbox.run(compiled, ins, ctx=_LiveCtx(self, cid), granted=frozenset(perms["granted"]))
        if not res["ok"]:
            self._usage(cid, version, False)
            kind = "limit" if res["error"]["code"] == "E_EXT_LIMIT" else "runtime_error"
            return {"ok": False, "status": kind, "capability_id": cid, "title": cap["title"], "version": version, "error": res["error"]}
        try:
            outputs = check_outputs(manifest, res["value"])
        except ExtError as e:
            self._usage(cid, version, False)
            return {"ok": False, "status": "bad_output", "capability_id": cid, "title": cap["title"], "version": version, "error": {"detail": str(e)[:200]}}
        self._usage(cid, version, True)
        return {"ok": True, "status": "ok", "capability_id": cid, "title": cap["title"], "version": version, "inputs": ins,
                "outputs": outputs, "answer": render_answer(manifest, ins, outputs), "fuel_used": res["fuel_used"]}
