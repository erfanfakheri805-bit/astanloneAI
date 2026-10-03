"""
Rule Registry
==============
Stage 6's persistence/lifecycle layer for structured rules:

    RULE STORAGE -> RULE VALIDATION -> RULE REGISTRY -> REASONING ENGINE

`RuleRegistry` is the single place a rule is created, validated, made
durable (via MemorySystem's `rules` table - see memory/memory_system.py
_migration_4), inspected, enabled/disabled, or removed. It deliberately
does NOT evaluate a rule against the Knowledge Graph itself - matching a
rule's premises against stored facts, binding variables, and producing a
conclusion all stay in reasoning/rules.py (`Rule`/`RuleEngine`) and
reasoning/reasoning_engine.py (`_try_rule`/`_infer`), exactly as before
this stage. This module only ever hands reasoning_engine.py a plain,
in-memory `rules.RuleEngine` (via `self.engine`) already filtered/ordered
by what storage currently says is enabled - see reload() below. That is
the whole integration: reasoning_engine.py's existing rule-matching code
does not need to know a registry exists at all.

Every mutating call here (register/enable/disable/remove) re-derives
`self.engine.rules` from the database afterward, so `self.engine` is
always a faithful, current view of storage - a caller never needs to
remember to call reload() themselves.
"""

import json
from datetime import datetime, timezone

from .rules import Rule, RuleEngine, validate_rule, default_rules


def _now():
    return datetime.now(timezone.utc).isoformat()


class RuleValidationError(ValueError):
    """Raised by RuleRegistry.register for a malformed rule definition.
    A plain ValueError subclass - not a new exception hierarchy - so
    existing generic `except ValueError` handling (e.g. ael/interpreter.py's
    per-instruction try/except) keeps working unchanged for this new
    instruction kind too."""


def validate_rule_definition(name, premises, conclusion, priority=0, confidence=1.0,
                              enabled=True, source="system", metadata=None):
    """Full validation of a *proposed* rule, before anything is persisted.
    Reuses rules.validate_rule (the shape/variable-resolution/circularity
    checks - item 7) via a throwaway Rule object so that logic is never
    duplicated, then adds the registry-only checks (priority/confidence/
    enabled/source/metadata types) that a bare in-memory Rule used
    directly by reasoning_engine.py/tests doesn't need enforced with
    persistence in mind. Returns a list of error strings; empty means
    valid. Never raises."""
    errors = []

    try:
        premises_t = [tuple(p) for p in (premises or [])]
        conclusion_t = tuple(conclusion) if conclusion else None
        temp_rule = Rule(name=name, premises=premises_t, conclusion=conclusion_t, weight=1.0)
        errors.extend(validate_rule(temp_rule))
    except Exception as e:
        errors.append(f"could not construct rule '{name}' for validation: {e}")
        return errors

    if not isinstance(priority, int) or isinstance(priority, bool):
        errors.append(f"rule '{name}' priority must be an integer, got {priority!r}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not (0.0 <= float(confidence) <= 1.0):
        errors.append(f"rule '{name}' confidence must be a number in [0.0, 1.0], got {confidence!r}")
    if not isinstance(enabled, bool):
        errors.append(f"rule '{name}' enabled must be a boolean, got {enabled!r}")
    if not source or not isinstance(source, str):
        errors.append(f"rule '{name}' source must be a non-empty string")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(f"rule '{name}' metadata must be a JSON object (dict) if provided")

    return errors


class RuleRegistry:
    """Owns persistence, validation, and lifecycle for structured rules,
    and keeps a live `rules.RuleEngine` (`self.engine`) in sync with what
    storage currently says is enabled - `self.engine` is the object a
    caller hands to `ReasoningEngine(knowledge, rule_engine=registry.engine)`
    (or `rule_registry=registry` - see reasoning_engine.py). On first use
    against an empty database, the same small starter rule set
    rules.default_rules() already shipped with is seeded as persisted,
    `source="system"` rows - so reasoning behavior is unchanged the very
    first time a RuleRegistry-backed Core starts up."""

    def __init__(self, memory, rule_engine=None):
        self.memory = memory
        self.engine = rule_engine if rule_engine is not None else RuleEngine(rules=[])
        self._seed_if_empty()
        self.reload()

    # ------------------------------------------------------------------
    def _seed_if_empty(self):
        existing = self.memory.query_one("SELECT COUNT(*) AS c FROM rules")
        if existing and existing["c"] > 0:
            return
        for rule in default_rules():
            self._insert(
                name=rule.name, description=rule.description,
                conditions=rule.premises, conclusion=rule.conclusion,
                priority=0, confidence=rule.weight, enabled=True,
                source="system", metadata={},
            )

    def _insert(self, name, description, conditions, conclusion, priority, confidence,
                enabled, source, metadata, created_at=None):
        now = created_at or _now()
        self.memory._run(
            "INSERT INTO rules (name, description, conditions, conclusion, priority, confidence, "
            "enabled, source, version, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (name, description, json.dumps([list(c) for c in conditions]),
             json.dumps(list(conclusion)), priority, float(confidence),
             1 if enabled else 0, source, json.dumps(metadata or {}), now, now),
        )

    # ------------------------------------------------------------------
    # Registration (register/get/list/enable/disable/remove - item 6)
    # ------------------------------------------------------------------
    def register(self, name, premises, conclusion, description="", priority=0,
                 confidence=1.0, enabled=True, source="user", metadata=None):
        """Validate + persist a rule. Upserts by name - re-registering an
        existing rule name updates it in place (bumping `version`,
        matching the "teach it again and it updates" pattern
        skills/skill_system.py's add_skill already uses) rather than
        erroring on a collision. Raises RuleValidationError - never
        partially writes an invalid rule into the active registry (item 7:
        "do not silently accept malformed rules"). Returns the stored
        rule as a dict (see get())."""
        premises = [tuple(p) for p in (premises or [])]
        conclusion = tuple(conclusion) if conclusion else None
        metadata = metadata or {}

        errors = validate_rule_definition(
            name, premises, conclusion, priority=priority, confidence=confidence,
            enabled=enabled, source=source, metadata=metadata,
        )
        if errors:
            raise RuleValidationError("; ".join(errors))

        existing = self.memory.query_one("SELECT id FROM rules WHERE name = ?", (name,))
        now = _now()
        if existing:
            self.memory._run(
                "UPDATE rules SET description = ?, conditions = ?, conclusion = ?, priority = ?, "
                "confidence = ?, enabled = ?, source = ?, metadata = ?, version = version + 1, "
                "updated_at = ? WHERE name = ?",
                (description, json.dumps([list(p) for p in premises]), json.dumps(list(conclusion)),
                 priority, float(confidence), 1 if enabled else 0, source, json.dumps(metadata),
                 now, name),
            )
        else:
            self._insert(name, description, premises, conclusion, priority, confidence,
                          enabled, source, metadata, created_at=now)

        self.reload()
        return self.get_by_name(name)

    def get(self, rule_id):
        row = self.memory.query_one("SELECT * FROM rules WHERE id = ?", (rule_id,))
        return self._row_to_dict(row) if row else None

    def get_by_name(self, name):
        row = self.memory.query_one("SELECT * FROM rules WHERE name = ?", (name,))
        return self._row_to_dict(row) if row else None

    def list(self, enabled_only=False):
        sql = "SELECT * FROM rules" + (" WHERE enabled = 1" if enabled_only else "")
        sql += " ORDER BY priority DESC, id ASC"
        return [self._row_to_dict(r) for r in self.memory.query(sql)]

    def find_for_relation(self, relation_type):
        """Registry-level (dict-returning) counterpart to
        rules.RuleEngine.rules_for_relation() - for inspection/diagnostics/
        UI callers (item 18). The Reasoning Engine itself never calls this;
        it evaluates `self.engine` (a RuleEngine) directly, unchanged from
        before this stage."""
        return [r for r in self.list(enabled_only=True) if r["conclusion"][1] == relation_type]

    def enable(self, rule_id):
        """Re-enable a disabled rule - it becomes available to reasoning
        again immediately (next reload(), done here automatically)."""
        return self._set_enabled(rule_id, True)

    def disable(self, rule_id):
        """Disable a rule without deleting it (item 21) - it stops
        participating in reasoning immediately but its definition and
        history are preserved."""
        return self._set_enabled(rule_id, False)

    def _set_enabled(self, rule_id, enabled):
        row = self.memory.query_one("SELECT id FROM rules WHERE id = ?", (rule_id,))
        if not row:
            return None
        self.memory._run(
            "UPDATE rules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), rule_id),
        )
        self.reload()
        return self.get(rule_id)

    def remove(self, rule_id):
        """Permanently delete a rule. Returns True if a rule was removed,
        False if no rule with that id existed."""
        row = self.memory.query_one("SELECT id FROM rules WHERE id = ?", (rule_id,))
        if not row:
            return False
        self.memory._run("DELETE FROM rules WHERE id = ?", (rule_id,))
        self.reload()
        return True

    # ------------------------------------------------------------------
    def reload(self):
        """Rebuild `self.engine.rules` from storage - the one place
        persisted state becomes the `rules.Rule` objects reasoning_engine.py
        actually evaluates. Mutates `self.engine.rules` in place (rather
        than replacing `self.engine` with a new RuleEngine instance) so a
        ReasoningEngine constructed once with `rule_engine=registry.engine`
        (or `rule_registry=registry`) keeps seeing live updates across
        register/enable/disable/remove calls without being reconstructed."""
        rows = self.memory.query("SELECT * FROM rules ORDER BY priority DESC, id ASC")
        rule_objects = []
        for row in rows:
            conditions = [tuple(c) for c in json.loads(row["conditions"])]
            conclusion = tuple(json.loads(row["conclusion"]))
            rule_objects.append(Rule(
                name=row["name"], premises=conditions, conclusion=conclusion,
                description=row["description"] or "", confidence=row["confidence"],
                id=row["id"], priority=row["priority"], enabled=bool(row["enabled"]),
                source=row["source"], created_at=row["created_at"], version=row["version"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            ))
        self.engine.rules = rule_objects

    @staticmethod
    def _row_to_dict(row):
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "conditions": [tuple(c) for c in json.loads(row["conditions"])],
            "conclusion": tuple(json.loads(row["conclusion"])),
            "priority": row["priority"],
            "confidence": row["confidence"],
            "enabled": bool(row["enabled"]),
            "source": row["source"],
            "version": row["version"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
