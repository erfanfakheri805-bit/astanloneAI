"""
Capability Evolution Validation (Prompt 879, Section 16 - Capability Creation & Improvement)
============================================================================================
A pure validation boundary: decides whether a Prompt 876 evolution request, its
Prompt 877 analysis result and its Prompt 878 specification are individually
valid and mutually consistent, i.e. ready for a future evolution-planning stage.
It creates, modifies, executes, registers, loads or applies nothing, generates no
code or patch, reads no filesystem, registry, Memory, AEL, research source,
network, API or model, and never performs or allows self-modification. Nothing
is inferred, upgraded or repaired (improve_or_conflict is never turned into
improve_required).

  validate_capability_evolution(evolution_request, analysis_result, specification)
  validate_capability_evolution_result(result)

The three public validators are reused, not re-implemented:
  validate_capability_evolution_request       (Prompt 876)
  validate_capability_evolution_analysis      (Prompt 877)
  validate_capability_evolution_specification (Prompt 878)

Checks run in this exact order; the first failure decides the result:
   1 request invalid                       -> invalid_request
   2 analysis invalid                      -> invalid_analysis
   3 specification invalid                 -> invalid_specification
   4 request/analysis operation            -> context_mismatch
   5 request/analysis capability name      -> context_mismatch
   6 request/specification request id      -> context_mismatch
   7 request/specification operation       -> context_mismatch
   8 request/specification capability name -> context_mismatch
   9 analysis status / specification analysis_status        -> context_mismatch
  10 analysis existing / specification existing_capability
     (structural equality)                 -> context_mismatch
  11 analysis status not create_required / improve_required /
     improve_or_conflict                   -> not_ready
     otherwise                             -> ready
Any unexpected internal failure -> validation_error. All comparisons are exact.

Statuses: ready, not_ready, invalid_request, invalid_analysis, invalid_specification,
context_mismatch, validation_error. ("ready" is the success status; the
`ready` flag is True only for it.)

Result (exactly these nine keys, fresh every call):
  {"status", "ready", "request_id", "capability_name", "operation",
   "analysis_status", "reason", "execution_allowed", "executed"}
Identity fields come only from inputs already proven valid, else they are None:
  invalid_request, validation_error   all four fields None
  invalid_analysis                    request fields set, analysis_status None
  every other status                  all four fields set
`execution_allowed` and `executed` are always False. Reasons are fixed strings
(REASONS), one set per status.

validate_capability_evolution_result(result) validates only the normalized result
(keys, status, ready, identity fields, operation, analysis status, reason, flags)
and rejects inconsistent combinations. It returns
  {"valid", "errors", "execution_allowed", "executed"}
errors: [{"code", "where"}], at most MAX_ERRORS. Bounded work, read-only,
deterministic, never raises.
"""

from .capability_evolution_analysis import (STATUSES as ANALYSIS_STATUSES,
                                            validate_capability_evolution_analysis)
from .capability_evolution_request import validate_capability_evolution_request
from .capability_evolution_specification import (SUPPORTED_STATUSES,
                                                 validate_capability_evolution_specification)
from .capability_registry import MAX_ERRORS

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_CONTEXT_MISMATCH = "context_mismatch"
STATUS_VALIDATION_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_CONTEXT_MISMATCH, STATUS_VALIDATION_ERROR)

REASON_READY = "ready"
REASON_NOT_READY = "analysis_status_not_supported"
REASON_INVALID_REQUEST = "invalid_evolution_request"
REASON_INVALID_ANALYSIS = "invalid_analysis_result"
REASON_INVALID_SPECIFICATION = "invalid_specification"
REASON_OPERATION_ANALYSIS = "request_analysis_operation_mismatch"
REASON_NAME_ANALYSIS = "request_analysis_capability_name_mismatch"
REASON_REQUEST_ID_SPEC = "request_specification_request_id_mismatch"
REASON_OPERATION_SPEC = "request_specification_operation_mismatch"
REASON_NAME_SPEC = "request_specification_capability_name_mismatch"
REASON_STATUS = "analysis_specification_status_mismatch"
REASON_EXISTING = "analysis_specification_existing_mismatch"
REASON_VALIDATION_ERROR = "validation_error"

REASONS = {
    STATUS_READY: (REASON_READY,),
    STATUS_NOT_READY: (REASON_NOT_READY,),
    STATUS_INVALID_REQUEST: (REASON_INVALID_REQUEST,),
    STATUS_INVALID_ANALYSIS: (REASON_INVALID_ANALYSIS,),
    STATUS_INVALID_SPECIFICATION: (REASON_INVALID_SPECIFICATION,),
    STATUS_CONTEXT_MISMATCH: (REASON_OPERATION_ANALYSIS, REASON_NAME_ANALYSIS,
                              REASON_REQUEST_ID_SPEC, REASON_OPERATION_SPEC, REASON_NAME_SPEC,
                              REASON_STATUS, REASON_EXISTING),
    STATUS_VALIDATION_ERROR: (REASON_VALIDATION_ERROR,),
}

RESULT_KEYS = ("status", "ready", "request_id", "capability_name", "operation",
               "analysis_status", "reason", "execution_allowed", "executed")

# status -> operation that a supported analysis status implies
_STATUS_OPERATION = {"create_required": "create", "improve_or_conflict": "create",
                     "improve_required": "improve"}

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_READY = "invalid_ready"
ERR_INVALID_REQUEST_ID = "invalid_request_id"
ERR_INVALID_NAME = "invalid_capability_name"
ERR_INVALID_OPERATION = "invalid_operation"
ERR_INVALID_ANALYSIS_STATUS = "invalid_analysis_status"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_EXECUTION_ALLOWED = "invalid_execution_allowed"
ERR_INVALID_EXECUTED = "invalid_executed"
ERR_INCONSISTENT = "inconsistent_result"
ERR_INTERNAL = "validation_error"


# --------------------------------------------------------------- validation

def _result(status, reason, request=None, analysis_status=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"status": status, "ready": status == STATUS_READY, "request_id": ids[0],
            "capability_name": ids[1], "operation": ids[2], "analysis_status": analysis_status,
            "reason": reason, "execution_allowed": False, "executed": False}


def validate_capability_evolution(evolution_request=None, analysis_result=None,
                                  specification=None):
    """Mutual-consistency and readiness result for the three evolution documents."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        if not validate_capability_evolution_request(request)["valid"]:
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_REQUEST)
        if not validate_capability_evolution_analysis(analysis)["valid"]:
            return _result(STATUS_INVALID_ANALYSIS, REASON_INVALID_ANALYSIS, request)
        status = analysis["status"]
        if not validate_capability_evolution_specification(spec)["valid"]:
            return _result(STATUS_INVALID_SPECIFICATION, REASON_INVALID_SPECIFICATION,
                           request, status)

        checks = (
            (analysis["operation"] != request["operation"], REASON_OPERATION_ANALYSIS),
            (analysis["capability_name"] != request["capability_name"], REASON_NAME_ANALYSIS),
            (spec["request_id"] != request["request_id"], REASON_REQUEST_ID_SPEC),
            (spec["operation"] != request["operation"], REASON_OPERATION_SPEC),
            (spec["capability_name"] != request["capability_name"], REASON_NAME_SPEC),
            (spec["analysis_status"] != status, REASON_STATUS),
            (spec["existing_capability"] != analysis["existing"], REASON_EXISTING),
        )
        for failed, reason in checks:
            if failed:
                return _result(STATUS_CONTEXT_MISMATCH, reason, request, status)
        if status not in SUPPORTED_STATUSES:
            return _result(STATUS_NOT_READY, REASON_NOT_READY, request, status)
        return _result(STATUS_READY, REASON_READY, request, status)
    except Exception:
        return _result(STATUS_VALIDATION_ERROR, REASON_VALIDATION_ERROR)


def _identity_errors(result):
    """Reuse the Prompt 876 validator for request_id / operation / capability_name."""
    view = {"version": "1", "request_id": result["request_id"],
            "operation": result["operation"], "capability_name": result["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    codes = {"request_id": ERR_INVALID_REQUEST_ID, "operation": ERR_INVALID_OPERATION,
             "capability_name": ERR_INVALID_NAME}
    return [(codes[e["where"]], e["where"])
            for e in validate_capability_evolution_request(view)["errors"]
            if e["where"] in codes]


def _result_errors(result):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(result) is not dict:
        add(ERR_NOT_DICT, "result")
        return errors
    for key in RESULT_KEYS:
        if key not in result:
            add(ERR_MISSING_KEY, key)
    for key in result:
        if type(key) is not str or key not in RESULT_KEYS:
            add(ERR_UNEXPECTED_KEY, key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    status, ready, reason = result["status"], result["ready"], result["reason"]
    analysis_status = result["analysis_status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(ready) is not bool:
        add(ERR_INVALID_READY, "ready")
    if result["execution_allowed"] is not False:
        add(ERR_INVALID_EXECUTION_ALLOWED, "execution_allowed")
    if result["executed"] is not False:
        add(ERR_INVALID_EXECUTED, "executed")
    if type(reason) is not str or not reason:
        add(ERR_INVALID_REASON, "reason")
    if analysis_status is not None and (
            type(analysis_status) is not str or analysis_status not in ANALYSIS_STATUSES):
        add(ERR_INVALID_ANALYSIS_STATUS, "analysis_status")

    fields = ("request_id", "capability_name", "operation")
    if all(result[f] is None for f in fields):
        identity_none, identity_set = True, False
    elif all(result[f] is not None for f in fields):
        identity_none, identity_set = False, True
        for code, where in _identity_errors(result):
            add(code, where)
    else:
        identity_none = identity_set = False
        add(ERR_INCONSISTENT, "identity")
    if errors or not status_ok:
        return errors

    # cross-field consistency (every field is individually well formed here)
    if ready != (status == STATUS_READY):
        add(ERR_INCONSISTENT, "ready")
    if reason not in REASONS[status]:
        add(ERR_INCONSISTENT, "reason")
    if status in (STATUS_INVALID_REQUEST, STATUS_VALIDATION_ERROR):
        if not identity_none or analysis_status is not None:
            add(ERR_INCONSISTENT, "identity")
    elif not identity_set:
        add(ERR_INCONSISTENT, "identity")
    elif status == STATUS_INVALID_ANALYSIS:
        if analysis_status is not None:
            add(ERR_INCONSISTENT, "analysis_status")
    elif analysis_status is None:
        add(ERR_INCONSISTENT, "analysis_status")
    elif status == STATUS_READY:
        if analysis_status not in SUPPORTED_STATUSES:
            add(ERR_INCONSISTENT, "analysis_status")
        elif _STATUS_OPERATION[analysis_status] != result["operation"]:
            add(ERR_INCONSISTENT, "operation")
    elif status == STATUS_NOT_READY and analysis_status in SUPPORTED_STATUSES:
        add(ERR_INCONSISTENT, "analysis_status")
    return errors


def validate_capability_evolution_result(result=None):
    """Validation result for a normalized capability evolution validation result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
