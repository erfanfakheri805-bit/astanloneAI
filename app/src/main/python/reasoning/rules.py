"""
Rule Engine Foundation
========================
A small, local, structured rule system for the Reasoning Engine - NOT
hundreds of hard-coded conditionals. A `Rule` is data (a name, a chain
of premises, one conclusion, a weight) rather than a Python function,
so rules are inspectable, reusable, and easy to validate - and, per
the stage spec, a natural shape for a future AEL `RULE ...` statement
to eventually produce, without this module needing to change.

A premise/conclusion is a triple (var_from, relation_type, var_to)
where var_from/var_to are variable names (any string starting with an
uppercase letter, e.g. "A", "B", "SUBJECT") that must be bound
consistently across the whole rule. This is deliberately a tiny
fragment of first-order-logic-shaped matching - forward chaining,
premises tried strictly in order, first matching outgoing relationship
per premise explored (with bounded backtracking - see
reasoning_engine.py:_try_rule) - not a general theorem prover.

Example (the stage spec's own worked example):

    Rule(
        name="is_a_used_for",
        premises=[("A", "IS_A", "B"), ("B", "USED_FOR", "C")],
        conclusion=("A", "USED_FOR", "C"),
    )

    Known:  Python IS_A "Programming Language"
            "Programming Language" USED_FOR "Software Development"
    Query:  Python USED_FOR ?
    ->      Python USED_FOR "Software Development"   (rule: is_a_used_for)

Two separate mechanisms exist on purpose (see stage spec items 5 and
6, which describe them separately):

    - TRANSITIVE_RELATION_TYPES (this module) declares which SINGLE
      relation types may be chained through themselves (A DEPENDS_ON B,
      B DEPENDS_ON C => A DEPENDS_ON C). reasoning_engine.py walks these
      directly as a cycle-safe bounded graph traversal (like
      ReasoningEngine.traverse()) rather than through this Rule
      matcher, since the chain length is open-ended and a fixed-arity
      Rule can't express "N hops of the same relation".
    - `Rule` objects (this module) express bounded, FIXED-LENGTH chains
      across DIFFERENT relation types (the Python example above). Their
      premise count is fixed at authoring time, so evaluating one can
      never run away - the reasoning limits in reasoning_engine.py exist
      for the rule *search* (how many rules/facts are examined), not to
      cap a single rule's own length.

Declaring a relation type transitive (or adding a new cross-relation
Rule) is the whole extensibility story for now - see module docstring
of reasoning_engine.py for how both are actually applied.

Stage 6 addition
------------------
This module still owns rule *data* and *validity* only - nothing below
executes a condition against the Knowledge Graph (that stays entirely
in reasoning_engine.py's _try_rule/_infer, per item 5's "do not mix
rule parsing with rule execution"). What changed:

    - `Rule` gained persistence/lifecycle metadata (id, priority,
      confidence, enabled, source, created_at, version, metadata) so a
      rule can be a genuine first-class, inspectable, storable object
      rather than just a matching fixture. `weight` is kept as an
      alias of `confidence` - existing code (reasoning_engine.py's
      confidence math, and every test that constructs a bare
      `Rule(name, premises, conclusion)`) keeps working unchanged;
      `confidence` is simply the stage-6 name for the same number.
    - `RuleEngine.rules_for_relation` now skips disabled rules and
      orders matches by priority (item 8) before registration order,
      so which rule fires first is deterministic even once many rules
      exist.
    - See reasoning/rule_registry.py for the persistent, validated,
      enable/disable/register/remove-capable Rule Registry that sits in
      front of this module - RuleRegistry.engine IS a RuleEngine
      instance from this file, kept in sync with storage.
"""

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()

# Relation types where "A REL B" and "B REL C" may be combined into "A
# REL C" purely because of what REL semantically means (a chain of
# dependencies, or of part-whole containment, really does compose).
# Deliberately NOT every relation type - e.g. USES is intentionally
# absent: "A uses B" and "B uses C" says nothing about A and C (a
# scheduler using a queue, and the queue using a mutex, doesn't mean
# the scheduler uses the mutex, in general). Extend this set (or remove
# from it) explicitly, never by assuming transitivity as a default.
TRANSITIVE_RELATION_TYPES = {"DEPENDS_ON", "PART_OF"}

# Confidence to assume for a stored relationship that has no explicit
# confidence recorded (relationships.confidence is nullable - see
# memory/memory_system.py's _migration_3). Not a random guess: it is a
# fixed, documented "moderate default" used consistently everywhere a
# missing confidence needs a number, so results stay deterministic.
DEFAULT_FACT_CONFIDENCE = 0.7

# How much confidence is discounted per additional hop of inference
# (item 9: "reduce confidence as inference depth increases"). Applied
# as DEPTH_DECAY ** (depth - 1), so a single-hop (depth=1) conclusion
# is never discounted for depth at all.
DEPTH_DECAY = 0.9


class Rule:
    """A structured, inspectable inference rule. `weight` is a fixed,
    author-set multiplier in (0.0, 1.0] applied to the confidence of
    every conclusion this rule produces - a way to mark some rules as
    inherently less reliable than a 1:1 pass-through of their weakest
    premise, still fully deterministic (never learned/adjusted at
    runtime by this stage - see module docstring of
    reasoning_engine.py, item 18)."""

    def __init__(self, name, premises, conclusion, description="", weight=1.0,
                 id=None, priority=0, confidence=None, enabled=True,
                 source="system", created_at=None, version=1, metadata=None):
        self.id = id
        self.name = name
        self.premises = premises        # list[(var_from, relation_type, var_to)]
        self.conclusion = conclusion    # (var_from, relation_type, var_to)
        self.description = description
        # `confidence` and `weight` are deliberately the same number under
        # two names - see module docstring. Whichever one a caller passes
        # wins; if both are passed they must agree in spirit, so we simply
        # prefer the explicit `confidence` kwarg when given.
        self.confidence = weight if confidence is None else confidence
        self.weight = self.confidence
        self.priority = priority              # higher runs first - see RuleEngine.rules_for_relation
        self.enabled = enabled
        self.source = source                  # e.g. "system" | "user" | "ael" | "inference"
        self.created_at = created_at or _now()
        self.version = version
        self.metadata = metadata or {}

    def __repr__(self):
        return f"Rule({self.name!r}, premises={self.premises}, conclusion={self.conclusion})"

    # Plural aliases matching the stage-6 spec's field names, without
    # duplicating storage - `premises`/`conclusion` (singular conclusion)
    # remain the actual attributes everything else in this file/
    # reasoning_engine.py reads and writes.
    @property
    def conditions(self):
        return self.premises

    @property
    def conclusions(self):
        return [self.conclusion]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "premises": self.premises,
            "conditions": self.premises,
            "conclusion": self.conclusion,
            "priority": self.priority,
            "confidence": self.confidence,
            "weight": self.weight,
            "enabled": self.enabled,
            "source": self.source,
            "created_at": self.created_at,
            "version": self.version,
            "metadata": self.metadata,
        }


def validate_rule(rule):
    """Static validation of a Rule's shape - run once at registration
    time (RuleEngine.register), separate from the per-application
    checks in reasoning_engine.py:_try_rule (which verify the *facts*
    a specific attempt needs actually exist). Returns a list of error
    strings; empty means valid. Never raises."""
    errors = []

    if not rule.name or not isinstance(rule.name, str):
        errors.append("rule must have a non-empty string name")

    if not rule.premises:
        errors.append(f"rule '{rule.name}' has no premises")

    for i, premise in enumerate(rule.premises):
        if not (isinstance(premise, tuple) and len(premise) == 3):
            errors.append(f"rule '{rule.name}' premise {i} is not a (var_from, relation_type, var_to) triple")
        else:
            var_from, rel, var_to = premise
            if not (isinstance(var_from, str) and var_from) or not (isinstance(rel, str) and rel) \
                    or not (isinstance(var_to, str) and var_to):
                errors.append(f"rule '{rule.name}' premise {i} has an empty or non-string field: {premise!r}")

    if not (isinstance(rule.conclusion, tuple) and len(rule.conclusion) == 3):
        errors.append(f"rule '{rule.name}' conclusion is not a (var_from, relation_type, var_to) triple")
        return errors  # nothing further can be checked safely

    concl_from_raw, concl_rel_raw, concl_to_raw = rule.conclusion
    if not (isinstance(concl_from_raw, str) and concl_from_raw) or \
            not (isinstance(concl_rel_raw, str) and concl_rel_raw) or \
            not (isinstance(concl_to_raw, str) and concl_to_raw):
        errors.append(f"rule '{rule.name}' conclusion has an empty or non-string field: {rule.conclusion!r}")

    # Circular/unsafe definition (item 7 & 12): a rule that "concludes"
    # exactly one of its own premises is a no-op/self-referential
    # definition, not a real inference - reject it outright rather than
    # letting it silently loop-proof itself at evaluation time only.
    if rule.conclusion in rule.premises:
        errors.append(
            f"rule '{rule.name}' conclusion {rule.conclusion!r} is identical to one of its own "
            f"premises - this is a circular/no-op rule definition"
        )

    # Every variable the conclusion names must actually be resolvable
    # from the premise chain - otherwise the rule could "conclude"
    # something about a variable it never actually bound to real
    # knowledge (spec item 7: "verify variables can be resolved").
    premise_vars = set()
    for premise in rule.premises:
        if isinstance(premise, tuple) and len(premise) == 3:
            premise_vars.add(premise[0])
            premise_vars.add(premise[2])

    concl_from, _concl_rel, concl_to = rule.conclusion
    if concl_from not in premise_vars:
        errors.append(f"rule '{rule.name}' conclusion variable '{concl_from}' never appears in its premises")
    if concl_to not in premise_vars:
        errors.append(f"rule '{rule.name}' conclusion variable '{concl_to}' never appears in its premises")

    if not (0.0 < rule.weight <= 1.0):
        errors.append(f"rule '{rule.name}' weight must be in (0.0, 1.0], got {rule.weight}")

    # Stage-6 lifecycle/metadata fields - only checked when present with an
    # obviously wrong type, so a plain `Rule(name, premises, conclusion)`
    # (every pre-stage-6 call site, including the existing test suite)
    # still validates exactly as before.
    if not isinstance(rule.priority, int):
        errors.append(f"rule '{rule.name}' priority must be an integer, got {rule.priority!r}")
    if not isinstance(rule.enabled, bool):
        errors.append(f"rule '{rule.name}' enabled must be a boolean, got {rule.enabled!r}")
    if not rule.source or not isinstance(rule.source, str):
        errors.append(f"rule '{rule.name}' source must be a non-empty string")
    if not isinstance(rule.metadata, dict):
        errors.append(f"rule '{rule.name}' metadata must be a dict, got {rule.metadata!r}")

    return errors


def default_rules():
    """A small, deliberately short starter set - per the stage spec,
    "do NOT implement hundreds of rules". Extending the system means
    appending more Rule(...) objects here (or registering additional
    ones via RuleEngine.register elsewhere) - nothing else changes."""
    return [
        Rule(
            name="is_a_used_for",
            premises=[("A", "IS_A", "B"), ("B", "USED_FOR", "C")],
            conclusion=("A", "USED_FOR", "C"),
            description=(
                "If A is a kind of B, and B is used for C, then A can be used for C "
                "(e.g. Python IS_A Programming Language; Programming Language USED_FOR "
                "Software Development => Python USED_FOR Software Development)."
            ),
        ),
        Rule(
            name="part_of_contained_in",
            premises=[("A", "PART_OF", "B"), ("B", "CONTAINED_IN", "C")],
            conclusion=("A", "CONTAINED_IN", "C"),
            description="If A is part of B, and B is contained in C, then A is contained in C.",
        ),
    ]


class RuleEngine:
    """Owns the registered rule set. Holds no knowledge-graph state
    itself and no storage handle - reasoning_engine.py supplies facts
    when it walks a rule's premises, keeping this module purely about
    rule *data* and rule *validity*, per the stage spec's separation of
    concerns."""

    def __init__(self, rules=None):
        self.rules = []
        for rule in (default_rules() if rules is None else rules):
            self.register(rule)

    def register(self, rule):
        """Validate and add a rule. Raises ValueError (at registration
        time, not silently at query time) if the rule is malformed -
        an invalid rule should never even make it into the pool that
        query-time evaluation picks from."""
        errors = validate_rule(rule)
        if errors:
            raise ValueError("; ".join(errors))
        self.rules.append(rule)
        return rule

    def rules_for_relation(self, relation_type):
        """Rules whose CONCLUSION produces `relation_type` - the set
        reasoning_engine.py tries when asked "does X <relation_type>
        Y?" and no direct fact answers it. Disabled rules (item 21)
        never participate. Item 8 (priority): matches are returned
        highest-priority-first, ties broken by registration order, so
        which rule fires first is deterministic even once many rules
        can answer the same relation type."""
        indexed = list(enumerate(self.rules))
        matches = [
            (i, r) for i, r in indexed
            if r.conclusion[1] == relation_type and r.enabled
        ]
        matches.sort(key=lambda pair: (-pair[1].priority, pair[0]))
        return [r for _, r in matches]

    def all(self):
        return list(self.rules)

    def get(self, rule_id):
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    def get_by_name(self, name):
        for r in self.rules:
            if r.name == name:
                return r
        return None
