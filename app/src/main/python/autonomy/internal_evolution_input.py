"""
Internal Evolution Input Contract (Prompt 905, Section 18: Claude Exit / Autonomy Validation)
============================================================================================
A small deterministic DESCRIPTION of what information the existing "controlled_internal_evolution"
stage would receive, built from a valid Prompt 904 "stage_ready" result.

This is a descriptive input contract only. It does not implement or execute the evolution stage,
modify source code, generate code, grant implementation / execution permission or approval, call
Claude or any external AI, or use the network or the filesystem. It carries no source code,
patches, commands, executable instructions, keys, URLs or service calls: "goal", "inputs",
"outputs" and "constraints" are fixed descriptive labels. implementation_allowed,
execution_allowed, implementation_started and executed are ALWAYS False.

  build_internal_evolution_input(stage_decision, expected_identity=None)
  validate_internal_evolution_input(result)

The supplied Prompt 904 result is never trusted: it is re-checked with the real Prompt 904
validator (validate_internal_stage_decision). Evaluation order (first match decides):
   any permission / execution / approval flag truthy (at any depth) .... forbidden_execution_state
   not a dict / malformed / forged / wrong stage ....................... invalid_stage_decision
   optional expected_identity differs from the decision identity ....... context_mismatch
   structurally valid Prompt 904 result that is not stage_ready ......... not_ready
   stage_ready, valid, decision and next_stage correct ................. ready
   unexpected internal failure .......................................... validation_error

Result (exactly these sixteen keys, a fresh dict per call, primitive values / lists of str only):
  {"version", "status", "valid", "request_id", "implementation_request_id", "capability_name",
   "operation", "stage", "goal", "inputs", "outputs", "constraints", "implementation_allowed",
   "execution_allowed", "implementation_started", "executed"}
valid is True only for ready. Only then are identity, stage, goal, inputs, outputs and constraints
populated; otherwise identity / stage / goal are None and the three lists are empty.

validate_internal_evolution_input(result) returns {"valid", "errors", "execution_allowed",
"executed"}; it independently re-verifies every field (never trusts "valid"); structural,
read-only, never raises.
"""

from autonomy.claude_exit_readiness import FALSE_FLAGS, IDENTITY_KEYS
from autonomy.internal_stage_decision import (
    DECISION, STATUS_READY as DECISION_READY, validate_internal_stage_decision)
from autonomy.internal_next_stage import NEXT_STAGE

RESULT_VERSION = 1

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID = "invalid_stage_decision"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID, STATUS_CONTEXT,
            STATUS_FORBIDDEN, STATUS_ERROR)

STAGE = NEXT_STAGE  # "controlled_internal_evolution"
GOAL = "controlled_capability_evolution"
INPUTS = ("validated_capability_context", "validated_evolution_request",
          "validated_stage_decision")
OUTPUTS = ("future_evolution_result_description",)
CONSTRAINTS = ("no_automatic_execution", "no_automatic_self_modification",
               "no_external_ai_dependency", "controlled_validation_required")

RESULT_KEYS = ("version", "status", "valid", "request_id", "implementation_request_id",
               "capability_name", "operation", "stage", "goal", "inputs", "outputs",
               "constraints", "implementation_allowed", "execution_allowed",
               "implementation_started", "executed")

_FORBIDDEN_KEYS = FALSE_FLAGS + (
    "approved", "approval_granted", "authorized", "authorization_granted",
    "permission_granted", "implementation_approved", "execution_approved")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_STAGE = "invalid_stage"
ERR_INVALID_GOAL = "invalid_goal"
ERR_INVALID_INPUTS = "invalid_inputs"
ERR_INVALID_OUTPUTS = "invalid_outputs"
ERR_INVALID_CONSTRAINTS = "invalid_constraints"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"

_MAX_ERRORS = 20
_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _result(status, source=None):
    ready = status == STATUS_READY
    out = {"version": RESULT_VERSION, "status": status, "valid": ready}
    for key in IDENTITY_KEYS:
        out[key] = source[key] if ready else None
    out.update({"stage": STAGE if ready else None, "goal": GOAL if ready else None,
                "inputs": list(INPUTS) if ready else [],
                "outputs": list(OUTPUTS) if ready else [],
                "constraints": list(CONSTRAINTS) if ready else [],
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _forbidden_state(obj):
    """True if any dict (at any depth) sets a permission / execution / approval flag."""
    stack = [(obj, 0)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > _MAX_SCAN_NODES or depth > _MAX_SCAN_DEPTH:
            continue
        if type(node) is dict:
            for key, value in node.items():
                if type(key) is str and key in _FORBIDDEN_KEYS:
                    try:
                        if bool(value):
                            return True
                    except Exception:
                        return True
                stack.append((value, depth + 1))
        elif type(node) in (list, tuple):
            for value in node:
                stack.append((value, depth + 1))
    return False


def _identity_differs(source, expected):
    if type(expected) is not dict:
        return True
    for key in IDENTITY_KEYS:
        if key in expected and (type(expected[key]) is not type(source[key])
                                or expected[key] != source[key]):
            return True
    return any(type(k) is not str or k not in IDENTITY_KEYS for k in expected)


def build_internal_evolution_input(stage_decision=None, expected_identity=None):
    """Evolution-stage input description for a Prompt 904 result (never raises)."""
    try:
        if _forbidden_state(stage_decision):
            return _result(STATUS_FORBIDDEN)
        if type(stage_decision) is not dict \
                or not validate_internal_stage_decision(stage_decision)["valid"]:
            return _result(STATUS_INVALID)
        if stage_decision["status"] != DECISION_READY:
            return _result(STATUS_NOT_READY)
        if stage_decision["valid"] is not True or stage_decision["decision"] != DECISION \
                or stage_decision["next_stage"] != STAGE:
            return _result(STATUS_INVALID)
        if expected_identity is not None and _identity_differs(stage_decision, expected_identity):
            return _result(STATUS_CONTEXT)
        return _result(STATUS_READY, stage_decision)
    except Exception:
        return _result(STATUS_ERROR)


def _exact_list(value, expected):
    return type(value) is list and len(value) == len(expected) \
        and all(type(v) is str for v in value) and tuple(value) == expected


def _result_errors(result):
    errors = []

    def add(code, where):
        if len(errors) < _MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(result) is not dict:
        add(ERR_NOT_DICT, "result")
        return errors
    for key in RESULT_KEYS:
        if key not in result:
            add(ERR_MISSING_KEY, key)
    for key in result:
        if type(key) is not str or key not in RESULT_KEYS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(result["version"]) is not int or result["version"] != RESULT_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    ready = status_ok and status == STATUS_READY
    if type(result["valid"]) is not bool or (status_ok and result["valid"] != ready):
        add(ERR_INVALID_VALID, "valid")
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    for key, expected, code in (("stage", STAGE, ERR_INVALID_STAGE),
                                ("goal", GOAL, ERR_INVALID_GOAL)):
        want = expected if ready else None
        if type(result[key]) is not type(want) or result[key] != want:
            add(code, key)
    for key, expected, code in (("inputs", INPUTS, ERR_INVALID_INPUTS),
                                ("outputs", OUTPUTS, ERR_INVALID_OUTPUTS),
                                ("constraints", CONSTRAINTS, ERR_INVALID_CONSTRAINTS)):
        if not _exact_list(result[key], expected if ready else ()):
            add(code, key)

    if not ready:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    # identity rules are the Prompt 904 (-> 903 -> 902) rules, reused rather than re-implemented
    view = {"version": 1, "status": DECISION_READY, "valid": True, "decision": DECISION}
    for key in IDENTITY_KEYS:
        view[key] = result[key]
    view.update({"next_stage": NEXT_STAGE, "reason": DECISION_READY})
    view.update(dict.fromkeys(FALSE_FLAGS, False))
    for error in validate_internal_stage_decision(view)["errors"]:
        if error["code"] == "invalid_identity":
            add(ERR_INVALID_IDENTITY, error["where"])
    return errors


def validate_internal_evolution_input(result=None):
    """Validation result for an evolution-input result (structural, never raises)."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
