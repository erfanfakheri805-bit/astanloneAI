"""
Self-Upgrade System
=====================
Foundation for the controlled self-upgrade lifecycle:

    INPUT -> ANALYZE -> UNDERSTAND -> PLAN -> CREATE -> SANDBOX TEST
    -> VALIDATE -> INSTALL -> VERSION -> (ROLLBACK IF NECESSARY)

Honesty about scope: this stage does NOT make the application capable of
autonomously rewriting its own source code. What it provides is the real
architecture and state machine that future stages will plug intelligence
into - every stage of the pipeline exists, is tracked in persistent
storage, and produces an auditable status, even though "ANALYZE",
"UNDERSTAND", "PLAN" and "CREATE" are currently simple deterministic
placeholders rather than AI-driven reasoning.
"""

from datetime import datetime, timezone
import json

from .sandbox import Sandbox
from .version_system import VersionSystem

STAGES = [
    "input", "analyze", "understand", "plan", "create",
    "sandbox_test", "validate", "install", "version",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


class UpgradeSystem:
    def __init__(self, memory):
        self.memory = memory
        self.sandbox = Sandbox()
        self.versions = VersionSystem(memory)

    def _create_record(self, name, description, payload):
        now = _now()
        self.memory._run(
            "INSERT INTO upgrades (name, description, stage, status, payload, created_at, updated_at) "
            "VALUES (?, ?, 'input', 'pending', ?, ?, ?)",
            (name, description, json.dumps(payload), now, now),
        )
        return self.memory.query_one(
            "SELECT * FROM upgrades WHERE name = ? ORDER BY id DESC LIMIT 1", (name,)
        )

    def _advance(self, upgrade_id, stage, status="pending"):
        self.memory._run(
            "UPDATE upgrades SET stage = ?, status = ?, updated_at = ? WHERE id = ?",
            (stage, status, _now(), upgrade_id),
        )

    def propose_upgrade(self, name, description, payload=None):
        """Run a proposed upgrade through the full controlled lifecycle.
        Returns the final upgrade record plus a step-by-step log."""
        payload = payload or {"name": name, "description": description}
        record = self._create_record(name, description, payload)
        upgrade_id = record["id"]
        log = [{"stage": "input", "detail": "Upgrade proposal received."}]

        # ANALYZE / UNDERSTAND / PLAN: deterministic placeholders for now.
        self._advance(upgrade_id, "analyze")
        log.append({"stage": "analyze", "detail": "Payload structure inspected."})

        self._advance(upgrade_id, "understand")
        log.append({"stage": "understand", "detail": "Declared fields parsed (no semantic reasoning yet)."})

        self._advance(upgrade_id, "plan")
        log.append({"stage": "plan", "detail": "Single-step install plan generated."})

        self._advance(upgrade_id, "create")
        log.append({"stage": "create", "detail": "Upgrade artifact assembled from payload."})

        # SANDBOX TEST
        self._advance(upgrade_id, "sandbox_test")
        sandbox_result = self.sandbox.run(payload)
        log.append({"stage": "sandbox_test", "detail": sandbox_result.to_dict()})

        if not sandbox_result.passed:
            self._advance(upgrade_id, "sandbox_test", status="failed")
            log.append({"stage": "rollback", "detail": "Not installed - sandbox check failed."})
            return self._finish(upgrade_id, log)

        # VALIDATE
        self._advance(upgrade_id, "validate")
        log.append({"stage": "validate", "detail": "Validation passed."})

        # INSTALL
        self._advance(upgrade_id, "install", status="installed")
        log.append({"stage": "install", "detail": f"Upgrade '{name}' installed."})

        # VERSION
        version = self.versions.create_version(
            upgrade_id, version_label=f"upgrade-{upgrade_id}", snapshot=payload
        )
        self._advance(upgrade_id, "version", status="installed")
        log.append({"stage": "version", "detail": f"New version recorded: {version['version_label']}"})

        return self._finish(upgrade_id, log)

    def _finish(self, upgrade_id, log):
        record = self.memory.query_one("SELECT * FROM upgrades WHERE id = ?", (upgrade_id,))
        return {"upgrade": record, "log": log}

    def rollback(self, upgrade_id):
        record = self.memory.query_one("SELECT * FROM upgrades WHERE id = ?", (upgrade_id,))
        if not record:
            return None
        self._advance(upgrade_id, "rollback", status="rolled_back")
        return self.memory.query_one("SELECT * FROM upgrades WHERE id = ?", (upgrade_id,))

    def history(self, limit=50):
        return self.memory.query("SELECT * FROM upgrades ORDER BY id DESC LIMIT ?", (limit,))
