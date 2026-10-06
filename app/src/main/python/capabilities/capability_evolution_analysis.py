"""
Capability Evolution Analysis (Prompt 877, Section 16 - Capability Creation & Improvement)
==========================================================================================
Decides, purely structurally, whether a capability evolution request asks for
a NEW capability or the IMPROVEMENT of an existing one, by comparing the
request's capability name with a caller-supplied list of capability
descriptors. It is analysis only: it creates, modifies, executes, loads or
registers nothing, generates no code and no patch, reads no filesystem or
global registry, and touches no Memory, AEL, network, API or model. It never
performs or allows self-modification.

  analyze_capability_evolution(evolution_request, capabilities) -> analysis result
  validate_capability_evolution_analysis(result)               -> validation result

Inputs
  evolution_request  a normalized request accepted by
                     capabilities.capability_evolution_request
                     .validate_capability_evolution_request (Prompt 876).
  capabilities       a list (<= MAX_CAPABILITIES) of descriptors, each accepted
                     by capabilities.capability_registry
                     .validate_capability_descriptor. Nothing else is read.

Matching: exact, case-sensitive equality of request["capability_name"] and
descriptor["name"]. No fuzzy or substring matching, aliases, normalization or
inference. Only descriptors whose name equals the requested name count as
matches. Two or more such matches make the capability list invalid; one is
never silently selected.

Statuses (operation -> status):
  create  + 0 matches  create_required
  create  + 1 match    improve_or_conflict
  improve + 1 match    improve_required
  improve + 0 matches  missing_target
  (any)   invalid evolution request            invalid_request
  (any)   malformed list / duplicate matches   invalid_capabilities
  (any)   unexpected internal failure          analysis_error

Result (exactly these eight keys, fresh on every call):
  {"status", "operation", "capability_name", "existing", "matching_count",
   "reason", "execution_allowed", "executed"}
  existing           a deep copy of the single matching descriptor, else None
  matching_count     number of exact name matches (non-negative int)
  operation / name   exactly as in the request; None only for invalid_request
                     and analysis_error (no trustworthy request exists)
  execution_allowed  always False       executed  always False

Reasons are fixed strings, one per case (see REASONS). Checks run in a fixed
order: the request first, then the capability list, then the match.

validate_capability_evolution_analysis(result) validates only the normalized
result (key set, status, operation, name, existing descriptor, matching_count,
reason, execution flags) and rejects inconsistent combinations. It returns
  {"valid", "errors", "execution_allowed", "executed"}
with errors [{"code", "where"}] (at most MAX_ERRORS), and never raises.

Bounded work, read-only (neither input is modified or retained), deterministic,
never raises.
"""

import copy

from .capability_evolution_request import OPERATIONS, validate_capability_evolution_request
from .capability_registry import (MAX_CAPABILITIES, MAX_ERRORS, MAX_NAME_LENGTH,
                                  validate_capability_descriptor)

STATUS_CREATE_REQUIRED = "create_required"
STATUS_IMPROVE_OR_CONFLICT = "improve_or_conflict"
STATUS_IMPROVE_REQUIRED = "improve_required"
STATUS_MISSING_TARGET = "missing_target"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_CAPABILITIES = "invalid_capabilities"
STATUS_ANALYSIS_ERROR = "analysis_error"

STATUSES = (STATUS_CREATE_REQUIRED, STATUS_IMPROVE_OR_CONFLICT, STATUS_IMPROVE_REQUIRED,
            STATUS_MISSING_TARGET, STATUS_INVALID_REQUEST, STATUS_INVALID_CAPABILITIES,
            STATUS_ANALYSIS_ERROR)

REASON_CREATE_REQUIRED = "no_existing_capability_for_create"
REASON_IMPROVE_OR_CONFLICT = "existing_capability_found_for_create"
REASON_IMPROVE_REQUIRED = "existing_capability_found_for_improve"
REASON_MISSING_TARGET = "no_existing_capability_for_improve"
REASON_INVALID_REQUEST = "invalid_evolution_request"
REASON_INVALID_LIST = "invalid_capability_list"
REASON_DUPLICATE_MATCH = "duplicate_matching_capability_name"
REASON_ANALYSIS_ERROR = "analysis_error"

REASONS = {
    STATUS_CREATE_REQUIRED: (REASON_CREATE_REQUIRED,),
    STATUS_IMPROVE_OR_CONFLICT: (REASON_IMPROVE_OR_CONFLICT,),
    STATUS_IMPROVE_REQUIRED: (REASON_IMPROVE_REQUIRED,),
    STATUS_MISSING_TARGET: (REASON_MISSING_TARGET,),
    STATUS_INVALID_REQUEST: (REASON_INVALID_REQUEST,),
    STATUS_INVALID_CAPABILITIES: (REASON_INVALID_LIST, REASON_DUPLICATE_MATCH),
    STATUS_ANALYSIS_ERROR: (REASON_ANALYSIS_ERROR,),
}

RESULT_KEYS = ("status", "operation", "capability_name", "existing", "matching_count",
               "reason", "execution_allowed", "executed")

# statuses whose result carries no trustworthy request
_NO_REQUEST = (STATUS_INVALID_REQUEST, STATUS_ANALYSIS_ERROR)
# statuses that require exactly one existing descriptor
_ONE_EXISTING = (STATUS_IMPROVE_OR_CONFLICT, STATUS_IMPROVE_REQUIRED)
# status -> required operation, where the status fixes it
_STATUS_OPERATION = {STATUS_CREATE_REQUIRED: "create", STATUS_IMPROVE_OR_CONFLICT: "create",
                     STATUS_IMPROVE_REQUIRED: "improve", STATUS_MISSING_TARGET: "improve"}

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_OPERATION = "invalid_operation"
ERR_INVALID_NAME = "invalid_capability_name"
ERR_INVALID_EXISTING = "invalid_existing"
ERR_INVALID_COUNT = "invalid_matching_count"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_EXECUTION_ALLOWED = "invalid_execution_allowed"
ERR_INVALID_EXECUTED = "invalid_executed"
ERR_INCONSISTENT = "inconsistent_result"
ERR_INTERNAL = "validation_error"


# ---------------------------------------------------------------- analysis

def _result(status, reason, operation=None, name=None, existing=None, count=0):
    return {"status": status, "operation": operation, "capability_name": name,
            "existing": existing, "matching_count": count, "reason": reason,
            "execution_allowed": False, "executed": False}


def _capabilities_valid(capabilities):
    """True only for a bounded list of valid descriptors."""
    if type(capabilities) is not list or len(capabilities) > MAX_CAPABILITIES:
        return False
    return all(validate_capability_descriptor(item)["valid"] for item in capabilities)


def analyze_capability_evolution(evolution_request=None, capabilities=None):
    """Structural analysis of `evolution_request` against `capabilities`."""
    try:
        if not validate_capability_evolution_request(evolution_request)["valid"]:
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_REQUEST)
        operation = evolution_request["operation"]
        name = evolution_request["capability_name"]

        if not _capabilities_valid(capabilities):
            return _result(STATUS_INVALID_CAPABILITIES, REASON_INVALID_LIST, operation, name)

        matches = [item for item in capabilities if item["name"] == name]
        count = len(matches)
        if count > 1:
            return _result(STATUS_INVALID_CAPABILITIES, REASON_DUPLICATE_MATCH,
                           operation, name, None, count)

        existing = copy.deepcopy(matches[0]) if count == 1 else None
        if operation == "create":
            if existing is None:
                return _result(STATUS_CREATE_REQUIRED, REASON_CREATE_REQUIRED,
                               operation, name)
            return _result(STATUS_IMPROVE_OR_CONFLICT, REASON_IMPROVE_OR_CONFLICT,
                           operation, name, existing, count)
        if existing is None:
            return _result(STATUS_MISSING_TARGET, REASON_MISSING_TARGET, operation, name)
        return _result(STATUS_IMPROVE_REQUIRED, REASON_IMPROVE_REQUIRED,
                       operation, name, existing, count)
    except Exception:
        return _result(STATUS_ANALYSIS_ERROR, REASON_ANALYSIS_ERROR)


# -------------------------------------------------------------- validation

def _is_name(value):
    if type(value) is not str or not value or len(value) > MAX_NAME_LENGTH:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _is_count(value):
    return type(value) is int and value >= 0


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

    status = result["status"]
    operation = result["operation"]
    name = result["capability_name"]
    existing = result["existing"]
    count = result["matching_count"]
    reason = result["reason"]

    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    no_request = status_ok and status in _NO_REQUEST

    if no_request:
        if operation is not None:
            add(ERR_INVALID_OPERATION, "operation")
        if name is not None:
            add(ERR_INVALID_NAME, "capability_name")
    else:
        if type(operation) is not str or operation not in OPERATIONS:
            add(ERR_INVALID_OPERATION, "operation")
        if not _is_name(name):
            add(ERR_INVALID_NAME, "capability_name")

    existing_ok = existing is None
    if existing is not None:
        existing_ok = (type(existing) is dict
                       and validate_capability_descriptor(existing)["valid"])
        if not existing_ok:
            add(ERR_INVALID_EXISTING, "existing")

    count_ok = _is_count(count)
    if not count_ok:
        add(ERR_INVALID_COUNT, "matching_count")

    reason_ok = type(reason) is str and bool(reason)
    if not reason_ok:
        add(ERR_INVALID_REASON, "reason")

    if result["execution_allowed"] is not False:
        add(ERR_INVALID_EXECUTION_ALLOWED, "execution_allowed")
    if result["executed"] is not False:
        add(ERR_INVALID_EXECUTED, "executed")

    if errors or not status_ok:
        return errors

    # cross-field consistency (every field is individually well formed here)
    if reason not in REASONS[status]:
        add(ERR_INCONSISTENT, "reason")
    required_operation = _STATUS_OPERATION.get(status)
    if required_operation is not None and operation != required_operation:
        add(ERR_INCONSISTENT, "operation")
    if status in _ONE_EXISTING:
        if existing is None or count != 1:
            add(ERR_INCONSISTENT, "existing")
        elif existing["name"] != name:
            add(ERR_INCONSISTENT, "capability_name")
    else:
        if existing is not None:
            add(ERR_INCONSISTENT, "existing")
        if status == STATUS_INVALID_CAPABILITIES:
            if reason == REASON_DUPLICATE_MATCH and count < 2:
                add(ERR_INCONSISTENT, "matching_count")
            if reason == REASON_INVALID_LIST and count != 0:
                add(ERR_INCONSISTENT, "matching_count")
        elif count != 0:
            add(ERR_INCONSISTENT, "matching_count")
    return errors


def validate_capability_evolution_analysis(result=None):
    """Validation result for a normalized analysis result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
