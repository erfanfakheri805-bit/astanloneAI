"""
Reasoning - capability contract foundation (Prompt 838)
=======================================================
A small deterministic foundation that can RECEIVE a validated reasoning
decision (Prompt 837, `reasoning.reasoning_decision.decide_reasoning`) and
turn explicitly supplied capability information into a capability contract.
Nothing is executed, registered or modified, and nothing is invented.

  build_capability_contract(decision, spec)   -> build result
  validate_capability_contract(contract)      -> validation result

Capability contract (always these keys, in this order, JSON-safe):

  {"version", "name", "purpose", "required_inputs", "expected_outputs",
   "constraints", "execution_allowed"}

  name              stable capability name, supplied as-is: lowercase
                    snake_case, 1..MAX_NAME_LENGTH chars (it is never
                    normalised or derived)
  purpose           non-empty text, no surrounding whitespace, no control
                    characters, at most MAX_TEXT_LENGTH chars
  required_inputs   list of unique snake_case identifiers (may be empty)
  expected_outputs  list of unique snake_case identifiers (at least one)
  constraints       list of unique texts like `purpose` (may be empty)
  execution_allowed always False

Lists hold at most MAX_ITEMS entries; constraint texts at most
MAX_CONSTRAINT_LENGTH chars.

Spec (the explicitly supplied information) is a dict with the keys name,
purpose, required_inputs, expected_outputs, constraints; "version" and
"execution_allowed" (only False) are tolerated. Anything else - a tool, an
implementation, a handler - is an unexpected field and is rejected, never
kept.

Build result (always the same keys, in this order):

  {"version", "status", "reason", "contract", "validation", "executed"}

  status  "built"         a validated contract is in `contract`
          "unknown"       no usable decision, or no capability was specified
                          (nothing is created)
          "insufficient"  the decision is ready for nothing yet: it needs
                          clarification or information (nothing is created)
          "incomplete"    the spec lacks required fields (missing_field only)
          "invalid"       the spec is malformed
  reason  "built"; "decision_invalid" (not a well-formed, validated
          decision, or an invalid_plan decision); the decision string for
          "insufficient" ("needs_clarification" / "needs_information");
          "capability_unspecified" (no spec); "spec_not_dict"; otherwise the
          first validation error code
  contract    the contract for "built", else None
  validation  the validation result of the candidate contract when one was
              checked, else None
  executed    always False

Only a decision that is "ready" (validated, nothing executed) lets a
contract be built; the decision itself supplies no capability information.

Bounded work (at most MAX_FIELDS fields and MAX_ITEMS items per list are
examined), read-only (inputs are never modified), deterministic, always a
fresh result, never raises. Pure stdlib; no Memory, AEL, Core, NLU change,
registry, execution, LLM or network.
"""

import copy
import itertools
import re

CONTRACT_VERSION = 1
BUILD_VERSION = 1
VALIDATION_VERSION = 1

MAX_NAME_LENGTH = 64
MAX_TEXT_LENGTH = 200
MAX_CONSTRAINT_LENGTH = 120
MAX_ITEMS = 16
MAX_ERRORS = 16
MAX_FIELDS = 8

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"

BUILD_BUILT = "built"
BUILD_UNKNOWN = "unknown"
BUILD_INSUFFICIENT = "insufficient"
BUILD_INCOMPLETE = "incomplete"
BUILD_INVALID = "invalid"

REASON_BUILT = "built"
REASON_DECISION_INVALID = "decision_invalid"
REASON_CAPABILITY_UNSPECIFIED = "capability_unspecified"
REASON_SPEC_NOT_DICT = "spec_not_dict"

ERR_NOT_DICT = "contract_not_dict"
ERR_MISSING_FIELD = "missing_field"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_NAME = "invalid_name"
ERR_INVALID_PURPOSE = "invalid_purpose"
ERR_INVALID_REQUIRED_INPUTS = "invalid_required_inputs"
ERR_INVALID_EXPECTED_OUTPUTS = "invalid_expected_outputs"
ERR_INVALID_CONSTRAINTS = "invalid_constraints"
ERR_NO_EXPECTED_OUTPUTS = "no_expected_outputs"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
ERR_DUPLICATE_ITEM = "duplicate_item"
ERR_EXECUTION_NOT_FALSE = "execution_allowed_not_false"
ERR_VALIDATOR = "validator_error"

_CONTRACT_FIELDS = ("version", "name", "purpose", "required_inputs",
                    "expected_outputs", "constraints", "execution_allowed")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_DECISIONS = ("ready", "needs_clarification", "needs_information", "invalid_plan")


# ---------------------------------------------------------------- helpers

def _is_text(value, limit):
    """Non-empty str, no outer whitespace, no control characters, bounded."""
    if not isinstance(value, str) or not value or len(value) > limit:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _is_identifier(value, limit):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and _IDENTIFIER.match(value) is not None)


def _where(key):
    return key if isinstance(key, str) and 0 < len(key) <= 40 else "<field>"


class _Errors:
    def __init__(self):
        self.items = []
        self._seen = set()
        self.truncated = False

    def add(self, code, where):
        if (code, where) in self._seen:
            return
        if len(self.items) >= MAX_ERRORS:
            self.truncated = True
            return
        self._seen.add((code, where))
        self.items.append({"code": code, "where": where})


def _check_items(errors, field, value, bad_code, item_ok, require_one=False):
    if not isinstance(value, list):
        errors.add(bad_code, field)
        return
    if len(value) > MAX_ITEMS:
        errors.add(ERR_TOO_MANY_ITEMS, field)
    if require_one and not value:
        errors.add(ERR_NO_EXPECTED_OUTPUTS, field)
    seen = set()
    for index, item in enumerate(value[:MAX_ITEMS]):
        where = "%s[%d]" % (field, index)
        if not item_ok(item):
            errors.add(ERR_INVALID_ITEM, where)
        elif item in seen:
            errors.add(ERR_DUPLICATE_ITEM, where)
        else:
            seen.add(item)


def _validation(errors):
    return {"version": VALIDATION_VERSION, "valid": not errors.items,
            "status": STATUS_INVALID if errors.items else STATUS_VALID,
            "error_count": len(errors.items), "errors": errors.items,
            "truncated": errors.truncated}


# -------------------------------------------------------------- validator

def validate_capability_contract(contract):
    """Validation result for `contract` (see module docstring). Only reads
    the contract; never raises."""
    try:
        errors = _Errors()
        if not isinstance(contract, dict):
            errors.add(ERR_NOT_DICT, "contract")
            return _validation(errors)

        for field in _CONTRACT_FIELDS:
            if field not in contract:
                errors.add(ERR_MISSING_FIELD, field)
        for key in itertools.islice(contract, MAX_FIELDS + 1):
            if key not in _CONTRACT_FIELDS:
                errors.add(ERR_UNEXPECTED_FIELD, _where(key))

        if "version" in contract:
            v = contract["version"]
            if isinstance(v, bool) or not isinstance(v, int) or v != CONTRACT_VERSION:
                errors.add(ERR_INVALID_VERSION, "version")
        if "name" in contract and not _is_identifier(contract["name"], MAX_NAME_LENGTH):
            errors.add(ERR_INVALID_NAME, "name")
        if "purpose" in contract and not _is_text(contract["purpose"], MAX_TEXT_LENGTH):
            errors.add(ERR_INVALID_PURPOSE, "purpose")
        if "required_inputs" in contract:
            _check_items(errors, "required_inputs", contract["required_inputs"],
                         ERR_INVALID_REQUIRED_INPUTS,
                         lambda x: _is_identifier(x, MAX_NAME_LENGTH))
        if "expected_outputs" in contract:
            _check_items(errors, "expected_outputs", contract["expected_outputs"],
                         ERR_INVALID_EXPECTED_OUTPUTS,
                         lambda x: _is_identifier(x, MAX_NAME_LENGTH), require_one=True)
        if "constraints" in contract:
            _check_items(errors, "constraints", contract["constraints"],
                         ERR_INVALID_CONSTRAINTS,
                         lambda x: _is_text(x, MAX_CONSTRAINT_LENGTH))
        if "execution_allowed" in contract and contract["execution_allowed"] is not False:
            errors.add(ERR_EXECUTION_NOT_FALSE, "execution_allowed")
        return _validation(errors)
    except Exception:  # pragma: no cover - defensive
        return {"version": VALIDATION_VERSION, "valid": False, "status": STATUS_INVALID,
                "error_count": 1, "errors": [{"code": ERR_VALIDATOR, "where": "contract"}],
                "truncated": False}


# ---------------------------------------------------------------- builder

def _result(status, reason, contract=None, validation=None):
    return {"version": BUILD_VERSION, "status": status, "reason": reason,
            "contract": contract, "validation": validation, "executed": False}


def _decision_state(decision):
    """'ready', 'needs_clarification', 'needs_information' or None (unusable)."""
    if not isinstance(decision, dict):
        return None
    name = decision.get("decision")
    if not isinstance(name, str) or name not in _DECISIONS or name == "invalid_plan":
        return None
    if decision.get("executed") is not False:
        return None
    validation = decision.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        return None
    return name


def _candidate(spec):
    """Candidate contract from the spec's own fields only (no defaults for
    the five content fields). Unexpected spec keys are carried over so the
    validator reports them."""
    candidate = {}
    if "version" not in spec:
        candidate["version"] = CONTRACT_VERSION
    for key in itertools.islice(spec, MAX_FIELDS + 1):
        candidate[key] = spec[key]
    if "execution_allowed" not in candidate:
        candidate["execution_allowed"] = False
    return candidate


def build_capability_contract(decision, spec=None):
    """Capability contract build result for a validated reasoning `decision`
    and an explicit capability `spec` (see module docstring). Executes,
    registers and modifies nothing; never raises."""
    try:
        state = _decision_state(decision)
        if state is None:
            return _result(BUILD_UNKNOWN, REASON_DECISION_INVALID)
        if state != "ready":
            return _result(BUILD_INSUFFICIENT, state)
        if spec is None:
            return _result(BUILD_UNKNOWN, REASON_CAPABILITY_UNSPECIFIED)
        if not isinstance(spec, dict):
            return _result(BUILD_INVALID, REASON_SPEC_NOT_DICT)

        candidate = _candidate(spec)
        validation = validate_capability_contract(candidate)
        if not validation["valid"]:
            codes = [e["code"] for e in validation["errors"]]
            status = (BUILD_INCOMPLETE if codes and all(c == ERR_MISSING_FIELD for c in codes)
                      else BUILD_INVALID)
            return copy.deepcopy(_result(status, codes[0], None, validation))

        contract = {key: copy.deepcopy(candidate[key]) for key in _CONTRACT_FIELDS}
        return copy.deepcopy(_result(BUILD_BUILT, REASON_BUILT, contract, validation))
    except Exception:  # pragma: no cover - defensive
        return _result(BUILD_UNKNOWN, REASON_DECISION_INVALID)
