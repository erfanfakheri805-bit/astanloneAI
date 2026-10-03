"""
AEL Validator
==============
Sanity-checks a parsed Instruction before the interpreter is allowed to
execute it. Separating validation from both parsing and execution means
future, more advanced validation (permission checks, resource limits,
conflict detection against existing knowledge) can be added here without
touching the parser or interpreter.
"""

import re

# Shared by every field that must be a safe, unambiguous identifier
# rather than arbitrary free text - either because it becomes part of a
# file path (Skill names - see skills/skill_system.py) or because
# keeping names structurally simple avoids ambiguity across the whole
# Knowledge Graph. Free-text fields (TEACH's description, SKILL's
# response, UPGRADE's description) are intentionally NOT restricted -
# only identifier-like fields are.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ValidationResult:
    def __init__(self, valid, errors=None):
        self.valid = valid
        self.errors = errors or []

    def __bool__(self):
        return self.valid


REQUIRED_ARGS = {
    "TEACH": ["name", "description"],
    "RELATE": ["from", "to", "relation"],
    "SKILL": ["name", "keywords", "response"],
    "ASK": ["name"],
    "UPGRADE": ["name", "description"],
    "ROLLBACK": ["version_id"],
    "RULE": ["name", "conditions", "conclusion"],
}

# Which fields, per instruction kind, must pass the safe-identifier check.
# RULE's "conditions"/"conclusion" are lists of triples, not flat fields -
# they get their own dedicated checks in validate() below instead of
# going through this generic per-field loop.
SAFE_NAME_FIELDS = {
    "TEACH": ["name"],
    "RELATE": ["from", "to", "relation"],
    "SKILL": ["name"],
    "ASK": ["name"],
    "UPGRADE": ["name"],
    "ROLLBACK": [],
    "RULE": ["name"],
}


def _is_safe_name(value):
    return bool(_SAFE_NAME_RE.match(value))


def validate(instruction):
    errors = []

    if instruction.kind not in REQUIRED_ARGS:
        errors.append(f"Unknown instruction kind: {instruction.kind}")
        return ValidationResult(False, errors)

    for field in REQUIRED_ARGS[instruction.kind]:
        value = instruction.args.get(field)
        if value in (None, "", []):
            errors.append(f"Missing required field '{field}' for {instruction.kind}")

    for field in SAFE_NAME_FIELDS.get(instruction.kind, []):
        value = instruction.args.get(field)
        if value and not _is_safe_name(value):
            errors.append(
                f"'{field}' must contain only letters, numbers, '_' or '-' (got: {value!r})"
            )

    if instruction.kind == "ROLLBACK":
        version_id = instruction.args.get("version_id")
        if version_id is not None and not str(version_id).isdigit():
            errors.append("'version_id' must be a positive whole number")

    if instruction.kind == "RULE":
        errors.extend(_validate_rule_fields(instruction.args))

    return ValidationResult(len(errors) == 0, errors)


def _validate_triple(label, triple):
    """AEL-level check for one (var_from, relation, var_to) triple: every
    field must be present and a safe identifier. Deeper semantic checks
    (variables actually resolvable, no circular conclusion, etc.) are
    reasoning/rule_registry.py's job at registration time - see item 5's
    "do not mix rule parsing with rule execution", which extends to
    "don't mix syntax-level validation with semantic validation" too."""
    errors = []
    if not (isinstance(triple, (tuple, list)) and len(triple) == 3):
        return [f"{label} must be a (var_from, relation, var_to) triple, got {triple!r}"]
    for field_name, value in zip(("var_from", "relation", "var_to"), triple):
        if not value or not _is_safe_name(str(value)):
            errors.append(
                f"{label} field '{field_name}' must contain only letters, numbers, "
                f"'_' or '-' (got: {value!r})"
            )
    return errors


def _validate_rule_fields(args):
    errors = []
    conditions = args.get("conditions")
    if not conditions:
        errors.append("RULE must have at least one condition")
    elif not isinstance(conditions, list):
        errors.append("RULE 'conditions' must be a list of triples")
    else:
        for i, cond in enumerate(conditions):
            errors.extend(_validate_triple(f"RULE condition {i}", cond))

    conclusion = args.get("conclusion")
    if conclusion:
        errors.extend(_validate_triple("RULE conclusion", conclusion))

    return errors
