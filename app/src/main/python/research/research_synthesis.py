"""
Research Synthesis Contract (Prompt 871, Section 15 - Autonomous Research & Learning)
=====================================================================================
A strict, JSON-safe, purely STRUCTURAL aggregation of an already validated
research evidence set: the evidence ids and the evidence claims, side by side,
in the evidence set's original order. It is NOT semantic synthesis and NOT
text generation: no claim is rewritten, merged, summarised, ranked,
de-duplicated or inferred, no language model or external service is used, and
nothing is retrieved, fetched, searched or learned. No network, filesystem,
subprocess, API, Core, Memory or AEL. Nothing is generated or repaired: the
synthesis id is always supplied by the caller.

  build_research_synthesis(research_request, evidence_set, synthesis_id=None) -> build result
  validate_research_synthesis(synthesis)                                      -> validation result

Reuses the public validators of Prompt 863 (validate_research_request) and
Prompt 870 (validate_research_evidence_set); bounds are reused from Prompt 864,
868 and 870. `synthesis_id` is an optional third parameter, so the two-argument
call build_research_synthesis(research_request, evidence_set) is valid and
reports a missing synthesis id (an id is never generated).

Normalized synthesis (exactly these eight keys):

  {"version", "synthesis_id", "request_id", "source_id", "evidence_ids",
   "evidence_count", "claims", "execution_allowed"}

  version            exactly the string "1"
  synthesis_id       text, <= MAX_ID_LENGTH, supplied by the caller
  request_id         exactly the validated request's request_id
  source_id          exactly the evidence set's source_id
  evidence_ids       the evidence_id of every evidence record, in the evidence
                     set's exact order (1..MAX_EVIDENCE, unique)
  evidence_count     exactly len(evidence_ids)
  claims             the claim of every evidence record, in the exact same
                     order, one per evidence_id (duplicates and wording kept)
  execution_allowed  exactly the bool False

build_research_synthesis
  Checks, in this fixed order; the first failure is the only error reported:
    1. request invalid (Prompt 863)                 -> "invalid_request"
    2. evidence set invalid (Prompt 870; this also covers a non-dict set and an
       empty evidence list)                         -> "invalid_evidence_set"
    3. evidence_set.request_id != request.request_id -> "request_mismatch"
    4. synthesis_id None                            -> "missing_synthesis_id"
       synthesis_id not valid text                  -> "invalid_synthesis_id"
  Unexpected internal failure                       -> "build_error"
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "synthesis", "execution_allowed", "executed"}
  errors: [{"code", "where"}]. `synthesis` is a fresh normalized object when
  valid, else None. The result flags are always False (not part of the
  synthesis object), as in Prompts 868 and 870.

validate_research_synthesis(synthesis)
  Validates only the normalized object (no request or evidence set needed):
  exact keys; version; synthesis_id / request_id / source_id text;
  evidence_ids a non-empty list of at most MAX_EVIDENCE unique text ids;
  claims a list of text of the same length (one claim per evidence id, by
  position); evidence_count an int (not bool) equal to len(evidence_ids);
  execution_allowed False. Nothing is repaired. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_synthesis, synthesis_not_dict, too_many_fields,
  unexpected_field, missing_field, invalid_version, invalid_synthesis_id,
  invalid_request_id, invalid_source_id, invalid_evidence_ids, empty_evidence,
  evidence_limit_exceeded (where "evidence_ids" or "claims"), invalid_evidence_id
  (where "evidence_ids[i]"), duplicate_evidence_id, invalid_claims,
  invalid_claim (where "claims[i]"), length_mismatch, invalid_evidence_count,
  invalid_execution_allowed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_evidence import MAX_CLAIM_LENGTH
from research.research_evidence_set import MAX_EVIDENCE, validate_research_evidence_set
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH

SYNTHESIS_VERSION = "1"

MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "synthesis_id", "request_id", "source_id", "evidence_ids",
          "evidence_count", "claims", "execution_allowed")


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


def _build_result(errors, synthesis=None):
    return {"valid": not errors, "errors": errors, "synthesis": synthesis,
            "execution_allowed": False, "executed": False}


def _failure(code, where):
    return _build_result([{"code": code, "where": where}])


def build_research_synthesis(research_request=None, evidence_set=None, synthesis_id=None):
    """Build a fresh normalized synthesis, or report one error; no input is modified."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _failure("invalid_request", "research_request")
        if not validate_research_evidence_set(evidence_set)["valid"]:
            return _failure("invalid_evidence_set", "evidence_set")
        if evidence_set["request_id"] != research_request["request_id"]:
            return _failure("request_mismatch", "evidence_set")
        if synthesis_id is None:
            return _failure("missing_synthesis_id", "synthesis_id")
        if not _is_text(synthesis_id, MAX_ID_LENGTH):
            return _failure("invalid_synthesis_id", "synthesis_id")
        evidence_ids = [item["evidence_id"] for item in evidence_set["evidence"]]
        claims = [item["claim"] for item in evidence_set["evidence"]]
        return _build_result([], {
            "version": SYNTHESIS_VERSION, "synthesis_id": synthesis_id,
            "request_id": research_request["request_id"], "source_id": evidence_set["source_id"],
            "evidence_ids": evidence_ids, "evidence_count": len(evidence_ids),
            "claims": claims, "execution_allowed": False})
    except Exception:
        return _failure("build_error", "synthesis")


def _check_lists(errors, data):
    ids, claims = data["evidence_ids"], data["claims"]
    ids_ok = type(ids) is list
    if not ids_ok:
        _add(errors, "invalid_evidence_ids", "evidence_ids")
    elif not ids:
        _add(errors, "empty_evidence", "evidence_ids")
    elif len(ids) > MAX_EVIDENCE:
        _add(errors, "evidence_limit_exceeded", "evidence_ids")
    else:
        seen = set()
        for index, value in enumerate(ids):
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_evidence_id", "evidence_ids[%d]" % index)
            elif value in seen:
                _add(errors, "duplicate_evidence_id", "evidence_ids[%d]" % index)
            else:
                seen.add(value)
    claims_ok = type(claims) is list
    if not claims_ok:
        _add(errors, "invalid_claims", "claims")
    elif len(claims) > MAX_EVIDENCE:
        _add(errors, "evidence_limit_exceeded", "claims")
    else:
        for index, value in enumerate(claims):
            if not _is_text(value, MAX_CLAIM_LENGTH):
                _add(errors, "invalid_claim", "claims[%d]" % index)
    if ids_ok and claims_ok and len(ids) != len(claims):
        _add(errors, "length_mismatch", "claims")
    count = data["evidence_count"]
    if type(count) is not int or (ids_ok and count != len(ids)):
        _add(errors, "invalid_evidence_count", "evidence_count")


def _errors(data):
    errors = []
    if type(data) is not dict:
        _add(errors, "missing_synthesis" if data is None else "synthesis_not_dict", "synthesis")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, "too_many_fields", "synthesis")
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
    if type(data["version"]) is not str or data["version"] != SYNTHESIS_VERSION:
        _add(errors, "invalid_version", "version")
    for field in ("synthesis_id", "request_id", "source_id"):
        if not _is_text(data[field], MAX_ID_LENGTH):
            _add(errors, "invalid_" + field, field)
    _check_lists(errors, data)
    if data["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    return errors


def validate_research_synthesis(synthesis=None):
    """Validation result for a normalized synthesis object; nothing is repaired."""
    try:
        errors = _errors(synthesis)
    except Exception:
        errors = [{"code": "validation_error", "where": "synthesis"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
