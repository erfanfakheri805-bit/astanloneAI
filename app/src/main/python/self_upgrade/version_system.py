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

    def rollback_to(self, version_id):
        target = self.memory.query_one("SELECT * FROM versions WHERE id = ?", (version_id,))
        if not target:
            return None
        self.memory._run("UPDATE versions SET is_active = 0")
        self.memory._run("UPDATE versions SET is_active = 1 WHERE id = ?", (version_id,))
        return target
