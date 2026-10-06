"""
Research Learning Record Contract (Prompt 872, Section 15 - Autonomous Research & Learning)
============================================================================================
A strict, JSON-safe CANDIDATE learning record built from an already validated
research synthesis. It is only a structured candidate: nothing is learned,
stored, persisted, retrieved, approved, applied or executed, and no capability
changes. No claim is rewritten, summarised, merged, ranked, inferred or
reinterpreted; no language model or external service is used. No network,
filesystem, subprocess, API, Core, Memory or AEL. Nothing is generated or
repaired: the learning record id is always supplied by the caller.

  build_research_learning_record(research_request, synthesis, learning_record_id=None)
  validate_research_learning_record(record)

Reuses the public validators of Prompt 863 (validate_research_request) and
Prompt 871 (validate_research_synthesis); bounds are reused from Prompt 864,
868 and 870. `learning_record_id` is an optional third parameter, so the
two-argument call reports a missing id (an id is never generated).

Normalized learning record (exactly these nine keys):

  {"version", "learning_record_id", "request_id", "synthesis_id", "source_id",
   "claims", "evidence_count", "status", "execution_allowed"}

  version             exactly the string "1"
  learning_record_id  text, <= MAX_ID_LENGTH, supplied by the caller
  request_id          exactly the validated request's request_id
  synthesis_id        exactly the validated synthesis's synthesis_id
  source_id           exactly the validated synthesis's source_id
  claims              the synthesis claims, exact order and content
  evidence_count      exactly the synthesis evidence_count (== len(claims))
  status              exactly "candidate" (the only status at this stage)
  execution_allowed   exactly the bool False

build_research_learning_record
  Checks, in this fixed order; the first failure is the only error reported:
    1. request invalid (Prompt 863)                      -> "invalid_request"
    2. synthesis invalid (Prompt 871)                    -> "invalid_synthesis"
    3. synthesis.request_id != request.request_id        -> "request_mismatch"
    4. learning_record_id None                           -> "missing_learning_record_id"
       learning_record_id not valid text                 -> "invalid_learning_record_id"
  Unexpected internal failure                            -> "build_error"
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "learning_record", "execution_allowed", "executed"}
  errors: [{"code", "where"}]. `learning_record` is a fresh normalized object
  when valid, else None. The result flags are always False and are not part of
  the learning record object.

validate_research_learning_record(record)
  Validates only the normalized object (no request or synthesis needed): exact
  keys; version; learning_record_id / request_id / synthesis_id / source_id
  text; claims a non-empty list of at most MAX_EVIDENCE text claims;
  evidence_count an int (not bool) equal to len(claims); status "candidate";
  execution_allowed False. Nothing is repaired. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_record, record_not_dict, too_many_fields, unexpected_field,
  missing_field, invalid_version, invalid_learning_record_id, invalid_request_id,
  invalid_synthesis_id, invalid_source_id, invalid_claims, empty_claims,
  evidence_limit_exceeded, invalid_claim (where "claims[i]"),
  invalid_evidence_count, invalid_status, invalid_execution_allowed,
  validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_evidence import MAX_CLAIM_LENGTH
from research.research_evidence_set import MAX_EVIDENCE
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH
from research.research_synthesis import validate_research_synthesis

LEARNING_RECORD_VERSION = "1"
STATUS_CANDIDATE = "candidate"

MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "learning_record_id", "request_id", "synthesis_id", "source_id",
          "claims", "evidence_count", "status", "execution_allowed")


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


def _build_result(errors, learning_record=None):
    return {"valid": not errors, "errors": errors, "learning_record": learning_record,
            "execution_allowed": False, "executed": False}


def _failure(code, where):
    return _build_result([{"code": code, "where": where}])


def build_research_learning_record(research_request=None, synthesis=None, learning_record_id=None):
    """Build a fresh normalized candidate record, or report one error; no input is modified."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _failure("invalid_request", "research_request")
        if not validate_research_synthesis(synthesis)["valid"]:
            return _failure("invalid_synthesis", "synthesis")
        if synthesis["request_id"] != research_request["request_id"]:
            return _failure("request_mismatch", "synthesis")
        if learning_record_id is None:
            return _failure("missing_learning_record_id", "learning_record_id")
        if not _is_text(learning_record_id, MAX_ID_LENGTH):
            return _failure("invalid_learning_record_id", "learning_record_id")
        return _build_result([], {
            "version": LEARNING_RECORD_VERSION, "learning_record_id": learning_record_id,
            "request_id": research_request["request_id"],
            "synthesis_id": synthesis["synthesis_id"], "source_id": synthesis["source_id"],
            "claims": list(synthesis["claims"]),
            "evidence_count": synthesis["evidence_count"],
            "status": STATUS_CANDIDATE, "execution_allowed": False})
    except Exception:
        return _failure("build_error", "learning_record")


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
        _add(errors, "missing_record" if data is None else "record_not_dict", "learning_record")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, "too_many_fields", "learning_record")
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
    if type(data["version"]) is not str or data["version"] != LEARNING_RECORD_VERSION:
        _add(errors, "invalid_version", "version")
    for field in ("learning_record_id", "request_id", "synthesis_id", "source_id"):
        if not _is_text(data[field], MAX_ID_LENGTH):
            _add(errors, "invalid_" + field, field)
    _check_claims(errors, data)
    if type(data["status"]) is not str or data["status"] != STATUS_CANDIDATE:
        _add(errors, "invalid_status", "status")
    if data["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    return errors


def validate_research_learning_record(record=None):
    """Validation result for a normalized learning record; nothing is repaired."""
    try:
        errors = _errors(record)
    except Exception:
        errors = [{"code": "validation_error", "where": "learning_record"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
