"""
Self-Diagnostics / Health System
==================================
Inspects the application's own subsystems and reports a real, computed
status - HEALTHY / WARNING / DEGRADED / ERROR - instead of a hard-coded
string. Every check below is a genuine, cheap, side-effect-free probe
of a real subsystem:

- database:   a real SELECT against the live connection.
- ael:        parses (never executes) a fixed self-test line through
              the actual tokenizer/parser.
- skills:     confirms the skill-definitions directory exists and is
              writable (write+delete a throwaway probe file).
- sandbox:    runs the actual (static, non-executing) Sandbox check
              against a well-formed dummy payload.
- versioning: confirms an active version row exists.

There are no decorative fake metrics here, and no component is ever
reported healthy without actually being checked. Status meanings:

    HEALTHY   - everything checked came back clean.
    WARNING   - a check produced an unexpected-but-recoverable result.
    DEGRADED  - a non-critical component check failed outright, but the
                database (and therefore the app) is still usable.
    ERROR     - the database itself is unreachable; nothing works
                without persistence, so this is the most severe state.
"""

import os

from ael.ael_parser import parse_line
from self_upgrade.sandbox import Sandbox

_RANK = {"HEALTHY": 0, "WARNING": 1, "DEGRADED": 2, "ERROR": 3}


class HealthSystem:
    def __init__(self, memory, skill_system, version_system):
        self.memory = memory
        self.skill_system = skill_system
        self.version_system = version_system

    def check(self):
        components = [
            self._check_database(),
            self._check_ael(),
            self._check_skills(),
            self._check_sandbox(),
            self._check_versioning(),
        ]
        overall = "HEALTHY"
        for component in components:
            if _RANK.get(component["status"], 0) > _RANK.get(overall, 0):
                overall = component["status"]
        return {"overall": overall, "components": components}

    def _check_database(self):
        try:
            row = self.memory.query_one("SELECT 1 AS ok")
            if row and row["ok"] == 1:
                return {"name": "database", "status": "HEALTHY", "detail": "SQLite reachable and responsive."}
            return {"name": "database", "status": "ERROR", "detail": "Unexpected query result."}
        except Exception as e:
            return {"name": "database", "status": "ERROR", "detail": f"Database unreachable: {e}"}

    def _check_ael(self):
        try:
            instruction = parse_line("TEACH healthcheck IS a self-test concept")
            if instruction is not None and instruction.kind == "TEACH":
                return {"name": "ael", "status": "HEALTHY", "detail": "Tokenizer/parser self-test passed."}
            return {"name": "ael", "status": "WARNING", "detail": "Self-test parsed to an unexpected instruction."}
        except Exception as e:
            return {"name": "ael", "status": "DEGRADED", "detail": f"AEL self-test failed: {e}"}

    def _check_skills(self):
        try:
            path = self.skill_system.definitions_dir
            if not os.path.isdir(path):
                return {"name": "skills", "status": "DEGRADED", "detail": "Skill definitions directory missing."}
            probe = os.path.join(path, ".healthcheck")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return {"name": "skills", "status": "HEALTHY", "detail": "Skill definitions directory is writable."}
        except Exception as e:
            return {"name": "skills", "status": "DEGRADED", "detail": f"Skill storage problem: {e}"}

    def _check_sandbox(self):
        try:
            result = Sandbox().run({"name": "healthcheck", "description": "self-test"})
            if result.passed:
                return {"name": "sandbox", "status": "HEALTHY", "detail": "Static sandbox self-test passed."}
            return {"name": "sandbox", "status": "DEGRADED", "detail": f"Sandbox self-test failed: {result.details}"}
        except Exception as e:
            return {"name": "sandbox", "status": "DEGRADED", "detail": f"Sandbox unavailable: {e}"}

    def _check_versioning(self):
        try:
            version = self.version_system.current_version()
            if version:
                return {"name": "versioning", "status": "HEALTHY", "detail": f"Active version: {version['version_label']}"}
            return {"name": "versioning", "status": "DEGRADED", "detail": "No active version recorded."}
        except Exception as e:
            return {"name": "versioning", "status": "ERROR", "detail": f"Version system error: {e}"}
