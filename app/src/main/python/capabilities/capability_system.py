"""
Capability System
===================
A Capability represents an actual ability of the application itself
(as opposed to a Skill, which is something the conversational AI has
learned to say/do). Capabilities are the architecture-level hooks that
future stages will fill in: image input, file input, code generation,
code analysis, UI modification, project creation, 3D development, game
development, etc.

For this foundation stage, capabilities are registered but disabled -
they exist as named, tracked placeholders with a status, not as working
features. This lets the developer panel and future upgrade pipeline
refer to them consistently without the core program needing to change
shape every time a new capability is turned on.
"""

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


# Capabilities the architecture is designed to eventually support.
# `enabled=False` for all of them in this first stage - see project rules.
PLANNED_CAPABILITIES = [
    ("image_input", "Accept and interpret image input."),
    ("file_input", "Accept and process uploaded files."),
    ("code_generation", "Generate source code on request."),
    ("code_analysis", "Analyze and review existing source code."),
    ("ui_modification", "Modify the application's own interface."),
    ("project_creation", "Scaffold new software projects."),
    ("development_3d", "Assist with 3D application development."),
    ("game_development", "Assist with game development."),
]


class CapabilitySystem:
    def __init__(self, memory):
        self.memory = memory

    def register(self, name, description, enabled=False, status="planned"):
        existing = self.memory.query_one("SELECT * FROM capabilities WHERE name = ?", (name,))
        now = _now()
        if existing:
            return existing
        self.memory._run(
            "INSERT INTO capabilities (name, description, enabled, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, int(enabled), status, now, now),
        )
        return self.memory.query_one("SELECT * FROM capabilities WHERE name = ?", (name,))

    def set_enabled(self, name, enabled, status=None):
        now = _now()
        if status:
            self.memory._run(
                "UPDATE capabilities SET enabled = ?, status = ?, updated_at = ? WHERE name = ?",
                (int(enabled), status, now, name),
            )
        else:
            self.memory._run(
                "UPDATE capabilities SET enabled = ?, updated_at = ? WHERE name = ?",
                (int(enabled), now, name),
            )

    def all(self):
        return self.memory.query("SELECT * FROM capabilities ORDER BY name")

    def seed_planned_capabilities(self):
        for name, description in PLANNED_CAPABILITIES:
            self.register(name, description, enabled=False, status="planned")
