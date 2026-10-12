"""
Self-Builder - mirror into the application's existing registries
================================================================
The Self-Builder's own store (`self_builder.db` + its files) is the source of
truth for built capabilities. The application already has three older,
persistent registries in `memory.db`, used by its diagnostics, planner and the
AEL `UPGRADE` / `ROLLBACK` statements:

  capabilities   (CapabilitySystem)  name, description, enabled, status
  upgrades       (UpgradeSystem)     one row per upgrade run: stage, status, payload
  versions       (VersionSystem)     one row per installed upgrade, one active

so that those keep telling the truth, every applied build/rollback is mirrored
into them - best effort and idempotent: a failure here is reported in the
result (`mirror.error`) and never undoes or blocks the real change.

A mirrored `versions` row carries the Self-Builder coordinates in its snapshot
(`{"self_builder": {"capability_id", "version", "upgrade_id"}}`), which is what
lets the existing `ROLLBACK <version_id>` statement restore a capability
version for real (see self_upgrade/version_system.py).
"""

import json
from datetime import datetime, timezone

# Self-Builder stage -> the stage vocabulary of the older UpgradeSystem
_STAGE_MAP = (
    ("request", "input"), ("analyze", "analyze"), ("spec", "analyze"), ("check_capabilities", "understand"),
    ("identify_gap", "understand"), ("plan", "plan"), ("generate", "create"), ("validate", "validate"),
    ("test", "sandbox_test"), ("retest", "sandbox_test"), ("checkpoint", "install"), ("apply", "install"),
    ("persist", "install"), ("register", "install"), ("version", "version"), ("audit", "version"),
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def stage_log(result):
    """Self-Builder stage records -> the `log` list shape of UpgradeSystem.propose_upgrade."""
    legacy = dict(_STAGE_MAP)
    log = []
    for st in result.get("stages", []):
        detail = dict(st.get("detail") or {})
        detail["ok"] = st.get("ok", True)
        log.append({"stage": legacy.get(st["stage"], st["stage"]), "self_builder_stage": st["stage"],
                    "detail": detail})
    return log


def _failed_stage(result):
    for st in result.get("stages", []):
        if not st.get("ok", True):
            return dict(_STAGE_MAP).get(st["stage"], "sandbox_test")
    return "sandbox_test"


def mirror_capability(memory, record):
    """Row in the older `capabilities` table for a built capability."""
    from capabilities.capability_system import CapabilitySystem
    caps = CapabilitySystem(memory)
    active = record["status"] == "active" and record.get("version") is not None
    caps.register(record["id"], record["title"], enabled=active, status="active" if active else "disabled")
    caps.set_enabled(record["id"], active, status="active" if active else "disabled")
    return {"capability": record["id"], "enabled": active}


def mirror_upgrade(memory, name, description, result, record=None):
    """`upgrades` (+ `versions` when applied) rows for one Self-Builder run."""
    from self_upgrade.version_system import VersionSystem
    status = result.get("status")
    now = _now()
    payload = {"self_builder": {"capability_id": result.get("capability_id"), "version": result.get("version"),
                                "upgrade_id": result.get("upgrade_id"), "status": status,
                                "action": result.get("action")}}
    if status == "applied":
        stage, row_status = "version", "installed"
    elif status == "noop_identical":
        stage, row_status = "understand", "installed"
    elif status == "needs_confirmation":
        stage, row_status = "plan", "pending"
    else:
        stage, row_status = _failed_stage(result), "failed"
    memory._run(
        "INSERT INTO upgrades (name, description, stage, status, payload, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, description, stage, row_status, json.dumps(payload, ensure_ascii=False), now, now))
    upgrade_row = memory.query_one("SELECT * FROM upgrades WHERE name = ? ORDER BY id DESC LIMIT 1", (name,))
    version_row = None
    if status == "applied":
        snapshot = {"self_builder": {"capability_id": result["capability_id"], "version": result["version"],
                                     "upgrade_id": result["upgrade_id"], "action": result.get("action")},
                    "title": result.get("title"), "kind": result.get("kind")}
        version_row = VersionSystem(memory).create_version(
            upgrade_row["id"], f"{result['capability_id']}@v{result['version']}", snapshot=snapshot)
    return upgrade_row, version_row


def mirror_rollback(memory, record, result):
    """After a rollback: keep `capabilities` and `versions` consistent."""
    mirror_capability(memory, record)
    if record.get("version") is None:  # disabled: nothing is active any more
        return {"disabled": True}
    from self_upgrade.version_system import VersionSystem
    versions = VersionSystem(memory)
    label = f"{record['id']}@v{record['version']}"
    row = memory.query_one("SELECT * FROM versions WHERE version_label = ? ORDER BY id DESC LIMIT 1", (label,))
    if row is not None:
        memory._run("UPDATE versions SET is_active = 0")
        memory._run("UPDATE versions SET is_active = 1 WHERE id = ?", (row["id"],))
    else:  # the restored version predates mirroring: record it so history stays complete
        memory._run(
            "INSERT INTO upgrades (name, description, stage, status, payload, created_at, updated_at) "
            "VALUES (?, ?, 'version', 'installed', ?, ?, ?)",
            (record["id"], f"rollback to {label}",
             json.dumps({"self_builder": {"capability_id": record["id"], "version": record["version"],
                                          "action": "rollback"}}, ensure_ascii=False), _now(), _now()))
        up = memory.query_one("SELECT * FROM upgrades ORDER BY id DESC LIMIT 1")
        versions.create_version(up["id"], label, snapshot={"self_builder": {
            "capability_id": record["id"], "version": record["version"], "action": "rollback"}})
    return {"version_label": label}


__all__ = ["mirror_capability", "mirror_upgrade", "mirror_rollback", "stage_log"]
