"""
Research Learning Acceptance Contract (Prompt 874, Section 15 - Autonomous Research & Learning)
================================================================================================
A strict, JSON-safe ACCEPTANCE record for a learning-record candidate that has
passed the Prompt 873 learning boundary. It is only a validated in-memory data
structure: nothing is written to Memory, persisted, taught, retrieved,
researched or executed, and no AEL or capability is touched or created. No
claim is rewritten, summarised, merged, ranked or inferred. No network,
filesystem, subprocess, API, model or Core. Nothing is generated: the
acceptance id is always supplied by the caller.

  build_research_learning_acceptance(research_request, learning_record,
                                     boundary_result, acceptance_id=None)
  validate_research_learning_acceptance(acceptance)

Reuses the public validators of Prompt 863 (validate_research_request),
Prompt 872 (validate_research_learning_record) and Prompt 873
(validate_research_learning_boundary_result); their rules are not repeated.

Normalized acceptance (exactly these ten keys):

  {"version", "acceptance_id", "learning_record_id", "request_id", "synthesis_id",
   "source_id", "claims", "evidence_count", "status", "execution_allowed"}

  version             exactly the string "1"
  acceptance_id       text, <= MAX_ID_LENGTH, supplied by the caller
  learning_record_id / request_id / synthesis_id / source_id
                      exactly the validated learning record's values
  claims              the record's claims, exact order and content
  evidence_count      exactly the record's evidence_count (== len(claims))
  status              exactly "accepted"
  execution_allowed   exactly the bool False

build_research_learning_acceptance
  Checks, in this fixed order; the first failure is the only error reported:
    1. request invalid (Prompt 863)                       -> "invalid_request"
    2. learning record invalid (Prompt 872)               -> "invalid_learning_record"
    3. boundary result invalid (Prompt 873)               -> "invalid_boundary_result"
    4. record.request_id or boundary.request_id differs
       from request.request_id                            -> "request_mismatch"
    5. boundary.learning_record_id differs from
       record.learning_record_id                          -> "learning_record_mismatch"
    6. boundary status != "ready" or ready is not True    -> "boundary_not_ready"
    7. acceptance_id None                                 -> "missing_acceptance_id"
    8. acceptance_id not valid text                       -> "invalid_acceptance_id"
  Unexpected internal failure                             -> "build_error"
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "acceptance", "execution_allowed", "executed"}
  errors: [{"code", "where"}]. `acceptance` is a fresh normalized object when
  valid, else None. The result flags are always False and are not part of the
  acceptance object.

validate_research_learning_acceptance(acceptance)
  Validates only the normalized object (no request, record or boundary result
  needed): exact keys; version; the five ids; claims a non-empty list of at
  most MAX_EVIDENCE text claims; evidence_count an int (not bool) equal to
  len(claims); status "accepted"; execution_allowed False. Nothing is
  repaired. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_acceptance, acceptance_not_dict, too_many_fields,
  unexpected_field, missing_field, invalid_version, invalid_acceptance_id,
  invalid_learning_record_id, invalid_request_id, invalid_synthesis_id,
  invalid_source_id, invalid_claims, empty_claims, evidence_limit_exceeded,
  invalid_claim (where "claims[i]"), invalid_evidence_count, invalid_status,
  invalid_execution_allowed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_evidence import MAX_CLAIM_LENGTH
from research.research_evidence_set import MAX_EVIDENCE
from research.research_learning_boundary import (STATUS_READY,
                                                 validate_research_learning_boundary_result)
from research.research_learning_record import validate_research_learning_record
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH

ACCEPTANCE_VERSION = "1"
STATUS_ACCEPTED = "accepted"

MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "acceptance_id", "learning_record_id", "request_id", "synthesis_id",
          "source_id", "claims", "evidence_count", "status", "execution_allowed")


def _is_text(value, limit):
    """Exact non-empty str, no outer whitespace, no control chars, bounded."""
    if type(value) is not str or not value or len(value) > limit:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _build_result(errors, acceptance=None):
    return {"valid": not errors, "errors": errors, "acceptance": acceptance,
            "execution_allowed": False, "executed": False}


def _failure(code, where):
    return _build_result([{"code": code, "where": where}])


def build_research_learning_acceptance(research_request=None, learning_record=None,
                                       boundary_result=None, acceptance_id=None):
    """Build a fresh normalized acceptance, or report one error; no input is modified."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _failure("invalid_request", "research_request")
        if not validate_research_learning_record(learning_record)["valid"]:
            return _failure("invalid_learning_record", "learning_record")
        if not validate_research_learning_boundary_result(boundary_result)["valid"]:
            return _failure("invalid_boundary_result", "boundary_result")
        request_id = research_request["request_id"]
        if learning_record["request_id"] != request_id:
            return _failure("request_mismatch", "learning_record")
        if boundary_result["request_id"] != request_id:
            return _failure("request_mismatch", "boundary_result")
        if boundary_result["learning_record_id"] != learning_record["learning_record_id"]:
            return _failure("learning_record_mismatch", "boundary_result")
        if boundary_result["status"] != STATUS_READY or boundary_result["ready"] is not True:
            return _failure("boundary_not_ready", "boundary_result")
        if acceptance_id is None:
            return _failure("missing_acceptance_id", "acceptance_id")
        if not _is_text(acceptance_id, MAX_ID_LENGTH):
            return _failure("invalid_acceptance_id", "acceptance_id")
        return _build_result([], {
            "version": ACCEPTANCE_VERSION, "acceptance_id": acceptance_id,
            "learning_record_id": learning_record["learning_record_id"],
            "request_id": request_id, "synthesis_id": learning_record["synthesis_id"],
            "source_id": learning_record["source_id"],
            "claims": list(learning_record["claims"]),
            "evidence_count": learning_record["evidence_count"],
            "status": STATUS_ACCEPTED, "execution_allowed": False})
    except Exception:
        return _failure("build_error", "acceptance")


def _check_claims(errors, data):
    claims = data["claims"]
    claims_ok = type(claims) is list
    if not claims_ok:
        _add(errors, "invalid_claims", "claims")
    elif not claims:
        _add(errors, "empty_claims", "claims")
    elif len(claims) > MAX_EVIDENCE:
        _add(errors, "evidence_limit_exceeded", "claims")
    else:
        for index, value in enumerate(claims):
            if not _is_text(value, MAX_CLAIM_LENGTH):
                _add(errors, "invalid_claim", "claims[%d]" % index)
    count = data["evidence_count"]
    if type(count) is not int or (claims_ok and count != len(claims)):
        _add(errors, "invalid_evidence_count", "evidence_count")


def _errors(data):
    errors = []
    if type(data) is not dict:
        _add(errors, "missing_acceptance" if data is None else "acceptance_not_dict", "acceptance")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, "too_many_fields", "acceptance")
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
    if type(data["version"]) is not str or data["version"] != ACCEPTANCE_VERSION:
        _add(errors, "invalid_version", "version")
    for field in ("acceptance_id", "learning_record_id", "request_id", "synthesis_id",
                  "source_id"):
        if not _is_text(data[field], MAX_ID_LENGTH):
            _add(errors, "invalid_" + field, field)
    _check_claims(errors, data)
    if type(data["status"]) is not str or data["status"] != STATUS_ACCEPTED:
        _add(errors, "invalid_status", "status")
    if data["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    return errors


def validate_research_learning_acceptance(acceptance=None):
    """Validation result for a normalized acceptance object; nothing is repaired."""
    try:
        errors = _errors(acceptance)
    except Exception:
        errors = [{"code": "validation_error", "where": "acceptance"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
