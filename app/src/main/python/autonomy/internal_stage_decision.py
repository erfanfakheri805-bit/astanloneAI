"""
Controlled Internal Stage Decision (Prompt 904, Section 18: Claude Exit / Autonomy Validation)
=============================================================================================
A small deterministic DESCRIPTIVE decision over a Prompt 903 "ready_for_internal_stage" result:
may the system proceed to the next controlled internal stage ("controlled_internal_evolution")?

This is a planning / readiness decision only. It does NOT implement, execute, modify, generate or
authorize anything, and it is NOT an approval: "stage_ready" does not mean implementation is
allowed, execution is allowed, approval was granted, or code may be changed.
implementation_allowed, execution_allowed, implementation_started and executed are ALWAYS False.

  build_internal_stage_decision(next_stage, expected_identity=None)
  validate_internal_stage_decision(result)

The supplied Prompt 903 result is never trusted: it is re-checked with the real Prompt 903
validator (validate_internal_next_stage). Evaluation order (first match decides):
   any permission / execution / approval flag truthy (at any depth) .... forbidden_execution_state
   not a dict / malformed / forged / wrong next_stage ................... invalid_next_stage
   optional expected_identity differs from the result identity ......... context_mismatch
   structurally valid Prompt 903 result that is not ready ............... not_ready
   ready_for_internal_stage, valid, next_stage correct ................. stage_ready
   unexpected internal failure .......................................... validation_error

Result (exactly these fourteen keys, a fresh dict per call, primitive values only):
  {"version", "status", "valid", "decision", "request_id", "implementation_request_id",
   "capability_name", "operation", "next_stage", "reason", "implementation_allowed",
   "execution_allowed", "implementation_started", "executed"}
valid is True only for stage_ready; decision is "proceed_to_controlled_internal_stage" only then
(else None); identity and next_stage are carried only for stage_ready (None otherwise).

validate_internal_stage_decision(result) returns {"valid", "errors", "execution_allowed",
"executed"}; it independently re-verifies every field (never trusts "valid"); structural,
read-only, never raises.
"""

from autonomy.claude_exit_readiness import FALSE_FLAGS, IDENTITY_KEYS
from autonomy.internal_next_stage import (
    NEXT_STAGE, STATUS_READY_STAGE, validate_internal_next_stage)

RESULT_VERSION = 1

STATUS_READY = "stage_ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID = "invalid_next_stage"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID, STATUS_CONTEXT,
            STATUS_FORBIDDEN, STATUS_ERROR)

DECISION = "proceed_to_controlled_internal_stage"

RESULT_KEYS = ("version", "status", "valid", "decision", "request_id",
               "implementation_request_id", "capability_name", "operation", "next_stage",
               "reason", "implementation_allowed", "execution_allowed",
               "implementation_started", "executed")

# any truthy value under one of these keys (at any depth) is a forbidden state
_FORBIDDEN_KEYS = FALSE_FLAGS + (
    "approved", "approval_granted", "authorized", "authorization_granted",
    "permission_granted", "implementation_approved", "execution_approved")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_DECISION = "invalid_decision"
ERR_INVALID_NEXT_STAGE = "invalid_next_stage"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"

_MAX_ERRORS = 20
_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _result(status, source=None):
    ready = status == STATUS_READY
    out = {"version": RESULT_VERSION, "status": status, "valid": ready,
           "decision": DECISION if ready else None}
    for key in IDENTITY_KEYS:
        out[key] = source[key] if ready else None
    out.update({"next_stage": NEXT_STAGE if ready else None, "reason": status,
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


def build_internal_stage_decision(next_stage=None, expected_identity=None):
    """Stage decision for a Prompt 903 result (descriptive only; never raises)."""
    try:
        if _forbidden_state(next_stage):
            return _result(STATUS_FORBIDDEN)
        if type(next_stage) is not dict or not validate_internal_next_stage(next_stage)["valid"]:
            return _result(STATUS_INVALID)
        if next_stage["status"] != STATUS_READY_STAGE:
            return _result(STATUS_NOT_READY)
        if next_stage["valid"] is not True or next_stage["next_stage"] != NEXT_STAGE:
            return _result(STATUS_INVALID)
        if expected_identity is not None and _identity_differs(next_stage, expected_identity):
            return _result(STATUS_CONTEXT)
        return _result(STATUS_READY, next_stage)
    except Exception:
        return _result(STATUS_ERROR)


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
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors
    expected_decision = DECISION if ready else None
    if type(result["decision"]) is not type(expected_decision) \
            or result["decision"] != expected_decision:
        add(ERR_INVALID_DECISION, "decision")
    expected_stage = NEXT_STAGE if ready else None
    if type(result["next_stage"]) is not type(expected_stage) \
            or result["next_stage"] != expected_stage:
        add(ERR_INVALID_NEXT_STAGE, "next_stage")

    if not ready:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    # identity rules are the Prompt 903 (-> 902) rules, reused rather than re-implemented
    view = {"version": 1, "status": STATUS_READY_STAGE, "valid": True}
    for key in IDENTITY_KEYS:
        view[key] = result[key]
    view.update({"next_stage": NEXT_STAGE, "reason": STATUS_READY_STAGE})
    view.update(dict.fromkeys(FALSE_FLAGS, False))
    for error in validate_internal_next_stage(view)["errors"]:
        if error["code"] == "invalid_identity":
            add(ERR_INVALID_IDENTITY, error["where"])
    return errors


def validate_internal_stage_decision(result=None):
    """Validation result for a stage-decision result (structural, never raises)."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
