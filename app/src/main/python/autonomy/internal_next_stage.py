"""
Internal Next-Stage Readiness Contract (Prompt 903, Section 18: Claude Exit / Autonomy Validation)
================================================================================================
A small deterministic DESCRIPTION of the next controlled internal stage for a request whose
Prompt 902 result is "ready_without_claude" with claude_independent=True.

This is planning / readiness only. Nothing here executes, modifies source code, generates code,
grants implementation or execution permission, calls Claude or any external AI, uses the network
or the filesystem, or modifies the project. "ready_for_internal_stage" does NOT mean
implementation is allowed: it only says the request passed the current structural readiness
boundary. implementation_allowed, execution_allowed, implementation_started and executed are
ALWAYS False.

  build_internal_next_stage(readiness, expected_identity=None)
  validate_internal_next_stage(result)

The supplied Prompt 902 result is never trusted: it is re-checked with the real Prompt 902
validator (validate_claude_exit_readiness), so a forged or inconsistent "ready" result is
rejected. Evaluation order (first match decides):
   not a dict / malformed / forged (fails the Prompt 902 validator) ..... invalid_readiness
   any permission / execution flag truthy (at any depth) ............... forbidden_execution_state
   optional expected_identity differs from the readiness identity ...... context_mismatch
   valid Prompt 902 result that is not ready_without_claude ............ not_ready
   ready_without_claude, valid, claude_independent .................... ready_for_internal_stage
   unexpected internal failure ........................................ validation_error
(The forbidden-flag check runs first, before the structural check, so a flag set to True is always
reported as forbidden_execution_state.)

Result (exactly these thirteen keys, a fresh dict per call, primitive values only):
  {"version", "status", "valid", "request_id", "implementation_request_id", "capability_name",
   "operation", "next_stage", "reason", "implementation_allowed", "execution_allowed",
   "implementation_started", "executed"}
valid is True only for ready_for_internal_stage; next_stage is "controlled_internal_evolution" only
then (else None); reason equals the status; identity fields are copied only for the ready status
(None otherwise).

validate_internal_next_stage(result) returns {"valid", "errors", "execution_allowed", "executed"};
structural, read-only, never raises.
"""

from autonomy.claude_exit_readiness import (
    FALSE_FLAGS, IDENTITY_KEYS, STATUS_READY, validate_claude_exit_readiness)

RESULT_VERSION = 1

STATUS_READY_STAGE = "ready_for_internal_stage"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID = "invalid_readiness"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY_STAGE, STATUS_NOT_READY, STATUS_INVALID, STATUS_CONTEXT,
            STATUS_FORBIDDEN, STATUS_ERROR)

NEXT_STAGE = "controlled_internal_evolution"

RESULT_KEYS = ("version", "status", "valid", "request_id", "implementation_request_id",
               "capability_name", "operation", "next_stage", "reason", "implementation_allowed",
               "execution_allowed", "implementation_started", "executed")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_NEXT_STAGE = "invalid_next_stage"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"

_MAX_ERRORS = 20
_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _result(status, identity=None):
    ready = status == STATUS_READY_STAGE
    out = {"version": RESULT_VERSION, "status": status, "valid": ready}
    for key in IDENTITY_KEYS:
        out[key] = identity[key] if ready else None
    out.update({"next_stage": NEXT_STAGE if ready else None, "reason": status,
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _forbidden_state(obj):
    """True if any dict (at any depth) sets a permission / execution flag."""
    stack = [(obj, 0)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > _MAX_SCAN_NODES or depth > _MAX_SCAN_DEPTH:
            continue
        if type(node) is dict:
            for key, value in node.items():
                if type(key) is str and key in FALSE_FLAGS:
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


def _identity_differs(readiness, expected):
    if type(expected) is not dict:
        return True
    for key in IDENTITY_KEYS:
        if key in expected and (type(expected[key]) is not type(readiness[key])
                                or expected[key] != readiness[key]):
            return True
    return any(type(k) is not str or k not in IDENTITY_KEYS for k in expected)


def build_internal_next_stage(readiness=None, expected_identity=None):
    """Next-stage description for a Prompt 902 result (descriptive only; never raises)."""
    try:
        if _forbidden_state(readiness):
            return _result(STATUS_FORBIDDEN)
        if type(readiness) is not dict or not validate_claude_exit_readiness(readiness)["valid"]:
            return _result(STATUS_INVALID)
        if readiness["status"] != STATUS_READY:
            return _result(STATUS_NOT_READY)
        if readiness["valid"] is not True or readiness["claude_independent"] is not True:
            return _result(STATUS_INVALID)
        if expected_identity is not None and _identity_differs(readiness, expected_identity):
            return _result(STATUS_CONTEXT)
        return _result(STATUS_READY_STAGE, readiness)
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
    ready = status_ok and status == STATUS_READY_STAGE
    if type(result["valid"]) is not bool or (status_ok and result["valid"] != ready):
        add(ERR_INVALID_VALID, "valid")
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if status_ok:
        expected_stage = NEXT_STAGE if ready else None
        if type(result["next_stage"]) is not type(expected_stage) \
                or result["next_stage"] != expected_stage:
            add(ERR_INVALID_NEXT_STAGE, "next_stage")
    if not status_ok:
        return errors

    if not ready:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    # identity text/operation rules are the Prompt 902 rules (reused, not re-implemented)
    view = {"version": 1, "status": STATUS_READY, "valid": True, "claude_independent": True,
            "reason": STATUS_READY, "missing_requirements": []}
    for key in IDENTITY_KEYS:
        view[key] = result[key]
    view.update(dict.fromkeys(FALSE_FLAGS, False))
    ordered = {k: view[k] for k in ("version", "status", "valid", "claude_independent",
                                     "request_id", "implementation_request_id",
                                     "capability_name", "operation", "reason",
                                     "missing_requirements") + FALSE_FLAGS}
    for error in validate_claude_exit_readiness(ordered)["errors"]:
        if error["code"] == "invalid_identity":
            add(ERR_INVALID_IDENTITY, error["where"])
    return errors


def validate_internal_next_stage(result=None):
    """Validation result for a next-stage result (structural, never raises)."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
