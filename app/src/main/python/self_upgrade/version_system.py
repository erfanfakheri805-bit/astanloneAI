"""
Version System
================
Every upgrade must be versioned, and the previous working version must
never be directly destroyed. This system records version snapshots and
supports rollback by marking a prior version active again.

For this foundation stage, a "snapshot" is a small JSON metadata blob
(what changed, when, from which upgrade) rather than a full binary image
of the application - real filesystem/code snapshotting is future scope,
but the interface is already shaped for it (see `snapshot` field).

A version created for a capability the Self-Builder built carries its
coordinates in the snapshot (`{"self_builder": {"capability_id", "version"}}`).
Rolling back to such a version really restores that capability version
(verified and re-tested before it is activated again, see self_builder/);
if the Self-Builder cannot restore it, nothing is reported as rolled back.
"""

import json
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


class VersionSystem:
    def __init__(self, memory):
        self.memory = memory

    def current_version(self):
        return self.memory.query_one(
            "SELECT * FROM versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )

    def create_version(self, upgrade_id, version_label, snapshot=None):
        self.memory._run("UPDATE versions SET is_active = 0")
        self.memory._run(
            "INSERT INTO versions (upgrade_id, version_label, snapshot, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (upgrade_id, version_label, json.dumps(snapshot or {}), _now()),
        )
        return self.current_version()

    def history(self, limit=50):
        return self.memory.query(
            "SELECT * FROM versions ORDER BY id DESC LIMIT ?", (limit,)
        )

    @staticmethod
    def _self_builder_coordinates(target):
        """(capability_id, version) of a Self-Builder version row, else None."""
        try:
            snapshot = json.loads(target["snapshot"] or "{}")
            coords = snapshot.get("self_builder") if isinstance(snapshot, dict) else None
            if isinstance(coords, dict) and coords.get("capability_id") and isinstance(coords.get("version"), int):
                return coords["capability_id"], coords["version"]
        except (TypeError, ValueError, KeyError):
            pass
        return None

    def _restore_self_builder(self, capability_id, version):
        """Really restore a Self-Builder capability version; True only if it is
        the active one afterwards."""
        try:
            from self_builder import service as sb_service
            service = sb_service.get_service(self.memory)
            record = service.capability(capability_id) if service is not None else None
            if record is None:
                return False
            if record.get("status") == "active" and record.get("version") == version:
                return True  # already the active version
            result = service.rollback(capability_id, to_version=version, reason="ael_rollback")
            return result.get("status") == "applied"
        except Exception as e:
            try:
                self.memory.log_error("version_rollback", f"{type(e).__name__}: {e}"[:300], capability_id)
            except Exception:
                pass
            return False

    def rollback_to(self, version_id):
        target = self.memory.query_one("SELECT * FROM versions WHERE id = ?", (version_id,))
        if not target:
            return None
        coords = self._self_builder_coordinates(target)
        if coords is not None and not self._restore_self_builder(*coords):
            return None  # never report a rollback the Self-Builder could not perform
        self.memory._run("UPDATE versions SET is_active = 0")
        self.memory._run("UPDATE versions SET is_active = 1 WHERE id = ?", (version_id,))
        return target
