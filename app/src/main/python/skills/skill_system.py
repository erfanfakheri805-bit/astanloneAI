"""
Skill System
=============
A Skill represents something the AI has learned how to do.

Skills are stored independently from the core application logic: each
skill is a small JSON definition file under skills/definitions/, plus a
row in the `skills` table (memory) that tracks its status and version.
This means new skills can be added later (by the Learning System, by an
AEL SKILL instruction, or eventually by a self-generated upgrade) without
touching or redeploying the core program.

A skill definition looks like:
{
    "name": "greet",
    "description": "Recognize a greeting and respond politely.",
    "trigger": {"type": "keyword", "keywords": ["hi", "hello", "hey"]},
    "response": "Hello! I'm still learning - teach me more with AEL."
}

For this foundation stage, skills are declarative (trigger -> response).
Executable/code-based skills are part of the Capability System's future
scope, not this stage.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_layer import get_platform

# A skill's name becomes part of a filename (see add_skill below). AEL
# already restricts SKILL names to this same charset (see ael/validator.py),
# but this check is enforced here too, independently, as defense-in-depth:
# SkillSystem must never trust a caller to have already sanitized `name`,
# since a future stage may add another path into add_skill (e.g. a direct
# API endpoint) that doesn't go through the AEL validator.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _default_definitions_dir():
    """Resolved lazily (not at import time) so a set_platform() call
    made before SkillSystem() is constructed is honored."""
    return get_platform().skill_definitions_dir()


class SkillSystem:
    def __init__(self, memory, definitions_dir=None):
        self.memory = memory
        self.definitions_dir = definitions_dir or _default_definitions_dir()
        os.makedirs(self.definitions_dir, exist_ok=True)

    def add_skill(self, name, description, trigger, response, source="user"):
        if not _SAFE_NAME_RE.match(name or ""):
            raise ValueError(
                f"Skill name must contain only letters, numbers, '_' or '-' (got: {name!r})"
            )

        definition = {
            "name": name,
            "description": description,
            "trigger": trigger,
            "response": response,
        }
        path = os.path.join(self.definitions_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(definition, f, indent=2)

        existing = self.memory.query_one("SELECT * FROM skills WHERE name = ?", (name,))
        now = _now()
        if existing:
            self.memory._run(
                "UPDATE skills SET description = ?, definition_path = ?, "
                "version = version + 1, updated_at = ? WHERE name = ?",
                (description, path, now, name),
            )
        else:
            self.memory._run(
                "INSERT INTO skills (name, description, definition_path, status, version, "
                "created_at, updated_at) VALUES (?, ?, ?, 'active', 1, ?, ?)",
                (name, description, path, now, now),
            )
        return definition

    def get_skill_definition(self, name):
        path = os.path.join(self.definitions_dir, f"{name}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def all_skills(self):
        rows = self.memory.query("SELECT * FROM skills ORDER BY name")
        return rows

    def find_matching_skill(self, text):
        """Very simple keyword-trigger matching for this foundation stage.

        Matches on whole words (`\\b`-bounded), not raw substring
        containment: a bare `in` check on a short keyword like "hi"
        would also "match" it appearing inside an unrelated word (e.g.
        "hi" inside "Echo Shift" or "this") - a real false-positive
        this project's own tests were already working around (see
        test_understanding_engine.py's TestCoreIntegration comment)
        rather than fixing at the source. Still deterministic, still
        no semantic understanding - just word-boundary-aware instead
        of naive substring containment.
        """
        text_lower = text.lower()
        for row in self.all_skills():
            if row["status"] != "active":
                continue
            definition = self.get_skill_definition(row["name"])
            if not definition:
                continue
            trigger = definition.get("trigger", {})
            if trigger.get("type") == "keyword":
                for kw in trigger.get("keywords", []):
                    if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text_lower):
                        return definition
        return None

    def seed_default_skills(self):
        """Only the bare minimum: a greeting skill. Everything else is learned later.
        Source of truth is the memory table (not just the definition file), so a
        leftover definition file from a wiped database doesn't block re-seeding."""
        already_registered = self.memory.query_one("SELECT * FROM skills WHERE name = ?", ("greet",))
        if not already_registered:
            self.add_skill(
                name="greet",
                description="Recognize a greeting and respond politely.",
                trigger={"type": "keyword", "keywords": ["hi", "hello", "hey", "greetings"]},
                response="Hello! I'm a very early version of myself right now - "
                         "I don't know much yet. Teach me things using AEL and I'll remember them.",
                source="system",
            )
