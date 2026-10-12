"""
Self-Builder - persistent capability registry
=============================================
The registry answers, from persistent storage only, "which capabilities do I
have, in which version, what are their inputs/outputs/dependencies/tests/
permissions, and what would a rollback restore?" - the data behind the two
honest answers

    «این قابلیت را دارم (نسخهٔ n)»      and      «این قابلیت را فعلاً ندارم»

A capability record (`Registry.get`) contains: id, kind, title, description,
status (active | disabled), active/latest version, inputs, outputs,
dependencies, permissions, source module/spec/tests file names with SHA-256,
validation info, test summary, rollback info (previous healthy version,
checkpoint, restorable), usage counters and the full version history. Nothing
in here is cached in memory: every call reads the database, so a restarted
process sees exactly what the last one persisted.

Version statuses: active | superseded | rolled_back | broken.
"""

from . import store as store_mod
from .store import dumps, loads

CAP_ACTIVE = "active"
CAP_DISABLED = "disabled"
VER_ACTIVE = "active"
VER_SUPERSEDED = "superseded"
VER_ROLLED_BACK = "rolled_back"
VER_BROKEN = "broken"
HEALTHY_STATUSES = (VER_ACTIVE, VER_SUPERSEDED)  # a version that may be restored by a rollback


def _version_row_to_dict(row):
    d = dict(row)
    out = {
        "capability_id": d["capability_id"],
        "version": d["version"],
        "fingerprint": d["fingerprint"],
        "spec": loads(d["spec_json"], {}),
        "spec_file": d["spec_file"], "spec_sha256": d["spec_sha256"],
        "module_file": d["module_file"], "module_sha256": d["module_sha256"],
        "tests_file": d["tests_file"], "tests_sha256": d["tests_sha256"],
        "inputs": loads(d["inputs_json"], []),
        "outputs": loads(d["outputs_json"], []),
        "dependencies": loads(d["dependencies_json"], []),
        "permissions": loads(d["permissions_json"], []),
        "validation": loads(d["validation_json"], {}),
        "test_report": loads(d["test_report_json"], {}),
        "status": d["status"],
        "parent_version": d["parent_version"],
        "upgrade_id": d["upgrade_id"],
        "checkpoint_id": d.get("checkpoint_id"),
        "rollback": loads(d.get("rollback_json"), {}),
        "created_at": d["created_at"],
    }
    return out


class Registry:
    def __init__(self, store):
        self.store = store

    # ------------------------------------------------------------------ reads
    def count(self):
        return self.store.query_one("SELECT COUNT(*) AS n FROM capabilities")["n"]

    def count_active(self):
        return self.store.query_one(
            "SELECT COUNT(*) AS n FROM capabilities WHERE status = ? AND active_version IS NOT NULL",
            (CAP_ACTIVE,))["n"]

    def _row(self, capability_id):
        return self.store.query_one("SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,))

    def version_row(self, capability_id, version):
        row = self.store.query_one(
            "SELECT * FROM capability_versions WHERE capability_id = ? AND version = ?", (capability_id, version))
        return _version_row_to_dict(row) if row else None

    def versions(self, capability_id):
        rows = self.store.query(
            "SELECT * FROM capability_versions WHERE capability_id = ? ORDER BY version", (capability_id,))
        return [_version_row_to_dict(r) for r in rows]

    def active_version_row(self, capability_id):
        cap = self._row(capability_id)
        if cap is None or cap["active_version"] is None:
            return None
        return self.version_row(capability_id, cap["active_version"])

    def previous_healthy(self, capability_id, before_version):
        """Newest healthy version older than `before_version` (a rollback target)."""
        rows = self.store.query(
            "SELECT * FROM capability_versions WHERE capability_id = ? AND version < ? AND status IN (?, ?) "
            "ORDER BY version DESC LIMIT 1", (capability_id, before_version, VER_ACTIVE, VER_SUPERSEDED))
        return _version_row_to_dict(rows[0]) if rows else None

    def usage(self, capability_id, version=None):
        if version is None:
            row = self.store.query_one(
                "SELECT COALESCE(SUM(calls),0) AS calls, COALESCE(SUM(failures),0) AS failures, "
                "MAX(last_used_at) AS last_used_at FROM usage WHERE capability_id = ?", (capability_id,))
        else:
            row = self.store.query_one(
                "SELECT calls, failures, last_used_at FROM usage WHERE capability_id = ? AND version = ?",
                (capability_id, version))
        if row is None:
            return {"calls": 0, "failures": 0, "last_used_at": None}
        return {"calls": row["calls"], "failures": row["failures"], "last_used_at": row["last_used_at"]}

    def get(self, capability_id):
        """Full record of one capability, or None."""
        cap = self._row(capability_id)
        if cap is None:
            return None
        versions = self.versions(capability_id)
        active = next((v for v in versions if v["version"] == cap["active_version"]), None)
        record = {
            "id": cap["capability_id"],
            "kind": cap["kind"],
            "title": cap["title"],
            "description": cap["description"],
            "status": cap["status"],
            "version": cap["active_version"],
            "latest_version": cap["latest_version"],
            "created_at": cap["created_at"],
            "updated_at": cap["updated_at"],
            "usage": self.usage(capability_id),
            "versions": [{"version": v["version"], "status": v["status"], "created_at": v["created_at"],
                          "fingerprint": v["fingerprint"], "parent_version": v["parent_version"],
                          "upgrade_id": v["upgrade_id"]} for v in versions],
        }
        if active is not None:
            tr = active["test_report"] or {}
            previous = self.previous_healthy(capability_id, active["version"])
            record.update({
                "inputs": active["inputs"],
                "outputs": active["outputs"],
                "dependencies": active["dependencies"],
                "permissions": active["permissions"],
                "source": {"module": active["module_file"], "module_sha256": active["module_sha256"],
                           "spec": active["spec_file"], "spec_sha256": active["spec_sha256"],
                           "tests": active["tests_file"], "tests_sha256": active["tests_sha256"]},
                "validation": active["validation"],
                "tests": {"total": tr.get("total"), "passed": tr.get("passed"), "ok": tr.get("ok"),
                          "duration_ms": tr.get("duration_ms")},
                "rollback": {"previous_version": previous["version"] if previous else None,
                             "checkpoint_id": active["checkpoint_id"],
                             "restorable": previous is not None},
                "spec": active["spec"],
            })
        return record

    def list(self, include_disabled=True):
        rows = self.store.query("SELECT capability_id FROM capabilities ORDER BY created_at, capability_id")
        out = []
        for r in rows:
            rec = self.get(r["capability_id"])
            if rec is None:
                continue
            if not include_disabled and rec["status"] != CAP_ACTIVE:
                continue
            out.append(rec)
        return out

    def find_identical(self, fingerprint):
        """(capability_id, version) of an ACTIVE version with this behaviour fingerprint, or None."""
        row = self.store.query_one(
            "SELECT v.capability_id AS cid, v.version AS ver FROM capability_versions v "
            "JOIN capabilities c ON c.capability_id = v.capability_id AND c.active_version = v.version "
            "WHERE v.fingerprint = ? AND c.status = ?", (fingerprint, CAP_ACTIVE))
        return (row["cid"], row["ver"]) if row else None

    def summary(self):
        """Small plain-data summary used by status/diagnostic commands."""
        caps = self.list()
        return {
            "total": len(caps),
            "active": sum(1 for c in caps if c["status"] == CAP_ACTIVE),
            "by_kind": _count_by(caps, "kind"),
            "capabilities": [{"id": c["id"], "title": c["title"], "kind": c["kind"], "status": c["status"],
                              "version": c["version"], "latest_version": c["latest_version"]} for c in caps],
        }

    # ----------------------------------------------------------------- writes
    def record_usage(self, capability_id, version, ok):
        ts = store_mod.now_iso()
        with self.store.transaction():
            self.store.execute(
                "INSERT INTO usage(capability_id, version, calls, failures, last_used_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(capability_id, version) DO UPDATE SET calls = calls + 1, "
                "failures = failures + excluded.failures, last_used_at = excluded.last_used_at",
                (capability_id, version, 1, 0 if ok else 1, ts))

    def record_feedback(self, capability_id, version, polarity, text=None):
        with self.store.transaction():
            self.store.execute(
                "INSERT INTO feedback(ts, capability_id, version, polarity, text) VALUES (?,?,?,?,?)",
                (store_mod.now_iso(), capability_id, version, polarity, (text or "")[:500]))
            self.store.audit("feedback", capability_id, version, None, {"polarity": polarity})

    def feedback_summary(self, capability_id, version):
        rows = self.store.query(
            "SELECT polarity, COUNT(*) AS n FROM feedback WHERE capability_id = ? AND version = ? GROUP BY polarity",
            (capability_id, version))
        return {r["polarity"]: r["n"] for r in rows}


def _count_by(items, key):
    out = {}
    for it in items:
        out[it[key]] = out.get(it[key], 0) + 1
    return out


__all__ = ["Registry", "CAP_ACTIVE", "CAP_DISABLED", "VER_ACTIVE", "VER_SUPERSEDED", "VER_ROLLED_BACK",
           "VER_BROKEN", "HEALTHY_STATUSES", "dumps"]
