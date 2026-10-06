"""
Research Learning Boundary (Prompt 873, Section 15 - Autonomous Research & Learning)
====================================================================================
A deterministic, side-effect-free validation boundary for the Prompt 872
learning-record CANDIDATE. It only reports whether a request / candidate pair
is ready for a later stage; it never approves, stores, persists, applies,
teaches, retrieves or executes anything, and touches no Memory, AEL or
capability. No network, filesystem, subprocess, API, model or Core.

  evaluate_research_learning_boundary(research_request, learning_record)
  validate_research_learning_boundary_result(result)

Reuses the public validators of Prompt 863 (validate_research_request) and
Prompt 872 (validate_research_learning_record); their rules are not repeated.

Checks, in this fixed order; the first failing check decides the result:
  1. request invalid                                  -> "invalid_request"
  2. learning record invalid                          -> "invalid_learning_record"
  3. learning_record.request_id != request.request_id -> "context_mismatch"
  4. learning_record.status != "candidate"            -> "not_ready"
  all pass                                            -> "ready"
  unexpected internal failure                         -> "validation_error"
(Prompt 872 allows only the "candidate" status, so check 4 is a defensive
second line: a non-candidate record is normally already "invalid_learning_record".)

Normalized result (exactly these seven keys, fresh on every call):

  {"status", "ready", "learning_record_id", "request_id", "reason",
   "execution_allowed", "executed"}

  status             one of ready, not_ready, invalid_request,
                     invalid_learning_record, context_mismatch, validation_error
  ready              True only for status "ready"
  learning_record_id the record's id for ready / not_ready / context_mismatch,
                     else None
  request_id         the request's id for ready / not_ready / context_mismatch /
                     invalid_learning_record, else None (only values from a
                     validated object are ever reported)
  reason             the fixed string for the status (REASONS)
  execution_allowed  always False
  executed           always False

validate_research_learning_boundary_result(result) validates only the result
object: exact keys, status, ready/status consistency, reason, id presence per
status, flags. Nothing is repaired. Result (fixed keys, fresh):
  {"valid", "errors", "execution_allowed", "executed"}
Codes: missing_result, result_not_dict, too_many_fields, unexpected_field,
missing_field, invalid_status, invalid_ready, status_ready_mismatch,
invalid_learning_record_id, invalid_request_id, invalid_reason,
invalid_execution_allowed, invalid_executed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_learning_record import (STATUS_CANDIDATE,
                                               validate_research_learning_record)
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_RECORD = "invalid_learning_record"
STATUS_CONTEXT_MISMATCH = "context_mismatch"
STATUS_VALIDATION_ERROR = "validation_error"

REASONS = {
    STATUS_READY: "learning record is a candidate for the research request",
    STATUS_NOT_READY: "learning record status is not candidate",
    STATUS_INVALID_REQUEST: "research request is invalid",
    STATUS_INVALID_RECORD: "learning record is invalid",
    STATUS_CONTEXT_MISMATCH: "learning record request_id does not match research request",
    STATUS_VALIDATION_ERROR: "unexpected validation failure",
}

# Which ids a result of each status carries: (learning_record_id, request_id).
_IDS = {
    STATUS_READY: (True, True),
    STATUS_NOT_READY: (True, True),
    STATUS_CONTEXT_MISMATCH: (True, True),
    STATUS_INVALID_RECORD: (False, True),
    STATUS_INVALID_REQUEST: (False, False),
    STATUS_VALIDATION_ERROR: (False, False),
}

MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("status", "ready", "learning_record_id", "request_id", "reason",
          "execution_allowed", "executed")


def _result(status, learning_record_id=None, request_id=None):
    return {"status": status, "ready": status == STATUS_READY,
            "learning_record_id": learning_record_id, "request_id": request_id,
            "reason": REASONS[status], "execution_allowed": False, "executed": False}


def evaluate_research_learning_boundary(research_request=None, learning_record=None):
    """Return a fresh normalized boundary result; no input is modified."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _result(STATUS_INVALID_REQUEST)
        request_id = research_request["request_id"]
        if not validate_research_learning_record(learning_record)["valid"]:
            return _result(STATUS_INVALID_RECORD, None, request_id)
        record_id = learning_record["learning_record_id"]
        if learning_record["request_id"] != request_id:
            return _result(STATUS_CONTEXT_MISMATCH, record_id, request_id)
        if learning_record["status"] != STATUS_CANDIDATE:
            return _result(STATUS_NOT_READY, record_id, request_id)
        return _result(STATUS_READY, record_id, request_id)
    except Exception:
        return _result(STATUS_VALIDATION_ERROR)


def _is_text(value):
    """Exact non-empty str, no outer whitespace, no control chars, bounded."""
    if type(value) is not str or not value or len(value) > MAX_ID_LENGTH:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _check_id(errors, data, field, required):
    value = data[field]
    if required and not _is_text(value):
        _add(errors, "invalid_" + field, field)
    elif not required and value is not None:
        _add(errors, "invalid_" + field, field)


def _errors(data):
    errors = []
    if type(data) is not dict:
        _add(errors, "missing_result" if data is None else "result_not_dict", "result")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, "too_many_fields", "result")
        return errors
    for key in data:
        if type(key) is not str or key not in FIELDS:
            _add(errors, "unexpected_field", key if type(key) is str and 0 < len(key) <= 40
                 else "<field>")
    for field in FIELDS:
        if field not in data:
            _add(errors, "missing_field", field)
    if errors:
        return errors
    status = data["status"]
    known = type(status) is str and status in REASONS
    if not known:
        _add(errors, "invalid_status", "status")
    if type(data["ready"]) is not bool:
        _add(errors, "invalid_ready", "ready")
    elif known and data["ready"] != (status == STATUS_READY):
        _add(errors, "status_ready_mismatch", "ready")
    if known:
        need_record, need_request = _IDS[status]
        _check_id(errors, data, "learning_record_id", need_record)
        _check_id(errors, data, "request_id", need_request)
        if data["reason"] != REASONS[status] or type(data["reason"]) is not str:
            _add(errors, "invalid_reason", "reason")
    if data["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    if data["executed"] is not False:
        _add(errors, "invalid_executed", "executed")
    return errors


def validate_research_learning_boundary_result(result=None):
    """Validation result for a normalized boundary result; nothing is repaired."""
    try:
        errors = _errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
