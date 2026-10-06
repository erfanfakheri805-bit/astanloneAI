"""
Internal Evolution Result Contract (Prompt 906, Section 18: Claude Exit / Autonomy Validation)
=============================================================================================
A small deterministic DESCRIPTION of what the future "controlled_internal_evolution" stage would
report after evaluating a capability-evolution request, built from a valid Prompt 905 "ready"
input result.

This is a descriptive result only. It performs no evolution: it does not generate source code or
patches, modify files, execute commands or capabilities, grant implementation / execution
permission, call Claude or any external AI, or use the network or filesystem. "evaluated" does NOT
mean the capability was implemented or improved; it only means a structured evaluation result was
produced. implementation_allowed, execution_allowed, implementation_started and executed are
ALWAYS False. summary / requirements_met / requirements_missing are fixed plain labels: no code,
patches, commands, keys, URLs or service references.

  build_internal_evolution_result(evolution_input, expected_identity=None)
  validate_internal_evolution_result(result)

The supplied Prompt 905 result is never trusted: it is re-checked with the real Prompt 905
validator (validate_internal_evolution_input). Evaluation order (first match decides):
   any permission / execution / approval flag truthy (at any depth) .... forbidden_execution_state
   not a dict / malformed / forged / wrong stage / code-like identity .. invalid_evolution_input
   optional expected_identity differs from the input identity .......... context_mismatch
   structurally valid Prompt 905 result that is not ready .............. not_ready
   ready, valid, stage correct ......................................... evaluated
   unexpected internal failure .......................................... validation_error

Result (exactly these sixteen keys, a fresh dict per call, primitive values / lists of str only):
  {"version", "status", "valid", "request_id", "implementation_request_id", "capability_name",
   "operation", "stage", "result_type", "summary", "requirements_met", "requirements_missing",
   "implementation_allowed", "execution_allowed", "implementation_started", "executed"}
valid is True only for evaluated. Only then are identity, stage, result_type, summary and the two
requirement lists populated; otherwise those are None / empty lists.

validate_internal_evolution_result(result) returns {"valid", "errors", "execution_allowed",
"executed"}; it independently re-verifies every field (never trusts "valid"); structural,
read-only, never raises.
"""

from autonomy.claude_exit_readiness import FALSE_FLAGS, IDENTITY_KEYS
from autonomy.internal_evolution_input import (
    STAGE, STATUS_READY as INPUT_READY, validate_internal_evolution_input)

RESULT_VERSION = 1

STATUS_EVALUATED = "evaluated"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID = "invalid_evolution_input"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_EVALUATED, STATUS_NOT_READY, STATUS_INVALID, STATUS_CONTEXT,
            STATUS_FORBIDDEN, STATUS_ERROR)

RESULT_TYPE = "descriptive_evaluation"
SUMMARY = ("Descriptive evaluation of the capability evolution request only; "
           "nothing was implemented, improved or executed.")
REQUIREMENTS_MET = ("stage_decision_validated", "evolution_input_validated",
                    "identity_context_consistent", "execution_constraints_preserved")
REQUIREMENTS_MISSING = ("implementation_permission", "execution_permission",
                        "controlled_validation_of_future_result")

RESULT_KEYS = ("version", "status", "valid", "request_id", "implementation_request_id",
               "capability_name", "operation", "stage", "result_type", "summary",
               "requirements_met", "requirements_missing", "implementation_allowed",
               "execution_allowed", "implementation_started", "executed")

_FORBIDDEN_KEYS = FALSE_FLAGS + (
    "approved", "approval_granted", "authorized", "authorization_granted",
    "permission_granted", "implementation_approved", "execution_approved")

# code / patch / command / key / URL look-alikes, rejected in identity text
_CODE_MARKERS = ("://", "http", "www.", "```", "def ", "class ", "import ", "sudo", "rm -",
                 "curl", "wget", "api_key", "apikey", "secret", "token", "diff --git", "@@",
                 "#!", "exec(", "eval(", "subprocess", "$(", "&&", "||", ";", "|", "<", ">",
                 "{", "}", "\n", "\r", "\t", "`")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_STAGE = "invalid_stage"
ERR_INVALID_RESULT_TYPE = "invalid_result_type"
ERR_INVALID_SUMMARY = "invalid_summary"
ERR_INVALID_MET = "invalid_requirements_met"
ERR_INVALID_MISSING = "invalid_requirements_missing"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"

_MAX_ERRORS = 20
_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


def _result(status, source=None):
    ok = status == STATUS_EVALUATED
    out = {"version": RESULT_VERSION, "status": status, "valid": ok}
    for key in IDENTITY_KEYS:
        out[key] = source[key] if ok else None
    out.update({"stage": STAGE if ok else None, "result_type": RESULT_TYPE if ok else None,
                "summary": SUMMARY if ok else None,
                "requirements_met": list(REQUIREMENTS_MET) if ok else [],
                "requirements_missing": list(REQUIREMENTS_MISSING) if ok else [],
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _code_like(source):
    for key in IDENTITY_KEYS:
        value = source[key].lower()
        if any(marker in value for marker in _CODE_MARKERS):
            return True
    return False


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


def build_internal_evolution_result(evolution_input=None, expected_identity=None):
    """Descriptive evaluation result for a Prompt 905 result (never raises)."""
    try:
        if _forbidden_state(evolution_input):
            return _result(STATUS_FORBIDDEN)
        if type(evolution_input) is not dict \
                or not validate_internal_evolution_input(evolution_input)["valid"]:
            return _result(STATUS_INVALID)
        if evolution_input["status"] != INPUT_READY:
            return _result(STATUS_NOT_READY)
        if evolution_input["valid"] is not True or evolution_input["stage"] != STAGE \
                or _code_like(evolution_input):
            return _result(STATUS_INVALID)
        if expected_identity is not None and _identity_differs(evolution_input, expected_identity):
            return _result(STATUS_CONTEXT)
        return _result(STATUS_EVALUATED, evolution_input)
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
    ok = status_ok and status == STATUS_EVALUATED
    if type(result["valid"]) is not bool or (status_ok and result["valid"] != ok):
        add(ERR_INVALID_VALID, "valid")
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    for key, expected, code in (("stage", STAGE, ERR_INVALID_STAGE),
                                ("result_type", RESULT_TYPE, ERR_INVALID_RESULT_TYPE),
                                ("summary", SUMMARY, ERR_INVALID_SUMMARY)):
        want = expected if ok else None
        if type(result[key]) is not type(want) or result[key] != want:
            add(code, key)
    for key, expected, code in (("requirements_met", REQUIREMENTS_MET, ERR_INVALID_MET),
                                ("requirements_missing", REQUIREMENTS_MISSING,
                                 ERR_INVALID_MISSING)):
        if not _exact_list(result[key], expected if ok else ()):
            add(code, key)

    if not ok:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    # identity rules are the Prompt 905 (-> 904 -> 903 -> 902) rules plus a code-like check
    view = {"version": 1, "status": INPUT_READY, "valid": True}
    for key in IDENTITY_KEYS:
        view[key] = result[key]
    from_input = validate_internal_evolution_input(
        dict(view, stage=STAGE, goal="controlled_capability_evolution",
             inputs=["validated_capability_context", "validated_evolution_request",
                     "validated_stage_decision"],
             outputs=["future_evolution_result_description"],
             constraints=["no_automatic_execution", "no_automatic_self_modification",
                          "no_external_ai_dependency", "controlled_validation_required"],
             **dict.fromkeys(FALSE_FLAGS, False)))
    for error in from_input["errors"]:
        if error["code"] == "invalid_identity":
            add(ERR_INVALID_IDENTITY, error["where"])
    if not errors:
        for key in IDENTITY_KEYS:
            if any(marker in result[key].lower() for marker in _CODE_MARKERS):
                add(ERR_INVALID_IDENTITY, key)
    return errors


def validate_internal_evolution_result(result=None):
    """Validation result for an evolution result (structural, never raises)."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
