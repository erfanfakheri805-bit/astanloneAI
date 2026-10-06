"""
Research Evidence Validation Boundary (Prompt 869, Section 15 - Autonomous Research & Learning)
================================================================================================
A small, deterministic, read-only check of whether ONE research evidence record
is acceptable for a given research request and research source. It retrieves
nothing, looks up no source (the source is the object passed in), reads no
source content, and makes no network, filesystem, subprocess, API or model
call. Nothing is repaired: the evidence, source and request are never modified.
No fuzzy or semantic matching, aliases or general constraint parser; no
learning; no Core, Memory or AEL.

  validate_research_evidence_for_context(research_request, source, evidence) -> context result
  validate_research_evidence_context_result(result)                          -> validation result

Reuses the public validators of Prompt 863 (validate_research_request), Prompt
864 (validate_research_source) and Prompt 868 (validate_research_evidence), and
the existing Section 15 constraint rules through their public functions:
  "source_type:<t>" / "not:source_type:<t>"  Prompt 865 match_research_sources
  "min_trust:<level>"                        Prompt 867 evaluate_research_source_trust
No constraint syntax is added, and no rule is re-implemented here. Prompt 865's
separate source-versus-request exact-negation ("constraint_conflict") rule is
deliberately NOT applied: only source type and minimum trust are checked, and
evidence constraints are not interpreted.

Checks, in this fixed order (the first failure decides the result)
  1. request invalid (Prompt 863)                  -> "invalid_request"
  2. source invalid (Prompt 864)                   -> "invalid_source"
  3. evidence invalid (Prompt 868)                 -> "invalid_evidence"
  4. malformed "source_type:" / "min_trust:" entry -> "invalid_request"
     (reason "invalid_constraint"; a request defect, never guessed)
  5. source not enabled                            -> "context_mismatch" (source_disabled)
  6. evidence.source_id != source.source_id        -> "context_mismatch" (source_id_mismatch)
  7. source_type excluded / not in the allow-list  -> "context_mismatch"
                                                     (source_type_excluded / source_type_not_allowed)
  8. trust_level below the declared minimum        -> "context_mismatch" (min_trust_not_met)
  9. otherwise                                     -> "valid" (evidence_accepted)
  Any unexpected internal failure                  -> "validation_error"

Context result (exactly these seven keys, fixed order, fresh on every call):

  {"status", "valid", "evidence_id", "source_id", "reason",
   "execution_allowed", "executed"}

  status            one of STATUSES
  valid             True only when status is "valid"
  evidence_id       exact evidence_id, only for "valid" and "context_mismatch"
                    (both objects are then known to be valid), else None
  source_id         exact source.source_id, same rule (equal to the evidence's
                    source_id when status is "valid")
  reason            one of REASONS, fixed per status
  execution_allowed always exactly False
  executed          always exactly False

validate_research_evidence_context_result(result)
  Structural and consistency check, never repairs. Result (fixed keys, fresh):
  {"valid", "errors", "execution_allowed", "executed"}. Codes: missing_result,
  result_not_dict, too_many_fields, unexpected_field, missing_field,
  invalid_status, invalid_valid, invalid_evidence_id, invalid_source_id,
  invalid_reason, inconsistent_result, invalid_execution_allowed,
  invalid_executed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_evidence import validate_research_evidence
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH, validate_research_source
from research.research_source_matching import match_research_sources
from research.research_source_trust import evaluate_research_source_trust

MAX_ERRORS = 16
MAX_FIELDS = 16

STATUS_VALID = "valid"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_SOURCE = "invalid_source"
STATUS_INVALID_EVIDENCE = "invalid_evidence"
STATUS_MISMATCH = "context_mismatch"
STATUS_ERROR = "validation_error"
STATUSES = (STATUS_VALID, STATUS_INVALID_REQUEST, STATUS_INVALID_SOURCE,
            STATUS_INVALID_EVIDENCE, STATUS_MISMATCH, STATUS_ERROR)

REASON_ACCEPTED = "evidence_accepted"
REASON_INVALID_REQUEST = "invalid_request"
REASON_INVALID_CONSTRAINT = "invalid_constraint"
REASON_INVALID_SOURCE = "invalid_source"
REASON_INVALID_EVIDENCE = "invalid_evidence"
REASON_DISABLED = "source_disabled"
REASON_ID_MISMATCH = "source_id_mismatch"
REASON_TYPE_EXCLUDED = "source_type_excluded"
REASON_TYPE_NOT_ALLOWED = "source_type_not_allowed"
REASON_TRUST = "min_trust_not_met"
REASON_ERROR = "validation_error"
_MISMATCH_REASONS = (REASON_DISABLED, REASON_ID_MISMATCH, REASON_TYPE_EXCLUDED,
                     REASON_TYPE_NOT_ALLOWED, REASON_TRUST)
REASONS = (REASON_ACCEPTED, REASON_INVALID_REQUEST, REASON_INVALID_CONSTRAINT,
           REASON_INVALID_SOURCE, REASON_INVALID_EVIDENCE, *_MISMATCH_REASONS, REASON_ERROR)

_REASONS_OF_STATUS = {STATUS_VALID: (REASON_ACCEPTED,),
                      STATUS_INVALID_REQUEST: (REASON_INVALID_REQUEST, REASON_INVALID_CONSTRAINT),
                      STATUS_INVALID_SOURCE: (REASON_INVALID_SOURCE,),
                      STATUS_INVALID_EVIDENCE: (REASON_INVALID_EVIDENCE,),
                      STATUS_MISMATCH: _MISMATCH_REASONS,
                      STATUS_ERROR: (REASON_ERROR,)}
_EXPOSES_IDS = (STATUS_VALID, STATUS_MISMATCH)

FIELDS = ("status", "valid", "evidence_id", "source_id", "reason", "execution_allowed", "executed")


def _result(status, reason, evidence=None, source=None):
    return {"status": status, "valid": status == STATUS_VALID,
            "evidence_id": evidence["evidence_id"] if evidence else None,
            "source_id": source["source_id"] if source else None,
            "reason": reason, "execution_allowed": False, "executed": False}


def validate_research_evidence_for_context(research_request=None, source=None, evidence=None):
    """Fresh context result; no input is modified and nothing is retrieved or looked up."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_REQUEST)
        if not validate_research_source(source)["valid"]:
            return _result(STATUS_INVALID_SOURCE, REASON_INVALID_SOURCE)
        if not validate_research_evidence(evidence)["valid"]:
            return _result(STATUS_INVALID_EVIDENCE, REASON_INVALID_EVIDENCE)
        typed = match_research_sources(research_request, [source])
        trust = evaluate_research_source_trust(research_request, source)
        if "invalid_request" in (typed["status"], trust["status"]):
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_CONSTRAINT)

        def mismatch(reason):
            return _result(STATUS_MISMATCH, reason, evidence, source)

        if source["enabled"] is not True:
            return mismatch(REASON_DISABLED)
        if evidence["source_id"] != source["source_id"]:
            return mismatch(REASON_ID_MISMATCH)
        if typed["status"] == "no_match":
            reason = typed["rejected"][0]["reason"]
            if reason in (REASON_TYPE_EXCLUDED, REASON_TYPE_NOT_ALLOWED):
                return mismatch(reason)
            if reason != "constraint_conflict":  # that rule is intentionally not applied here
                raise ValueError("unexpected match rejection")
        elif typed["status"] != "matched":
            raise ValueError("unexpected match status")
        if trust["status"] == "not_trusted":
            return mismatch(REASON_TRUST)
        if trust["status"] != "trusted":
            raise ValueError("unexpected trust status")
        return _result(STATUS_VALID, REASON_ACCEPTED, evidence, source)
    except Exception:
        return _result(STATUS_ERROR, REASON_ERROR)


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _result_errors(result):
    errors = []
    if type(result) is not dict:
        _add(errors, "missing_result" if result is None else "result_not_dict", "result")
        return errors
    if len(result) > MAX_FIELDS:
        _add(errors, "too_many_fields", "result")
        return errors
    for key in result:
        if type(key) is not str or key not in FIELDS:
            _add(errors, "unexpected_field", key if type(key) is str and 0 < len(key) <= 40
                 else "<field>")
    for field in FIELDS:
        if field not in result:
            _add(errors, "missing_field", field)
    if errors:
        return errors
    status, reason = result["status"], result["reason"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        _add(errors, "invalid_status", "status")
    if type(result["valid"]) is not bool or (status_ok and result["valid"] != (status == STATUS_VALID)):
        _add(errors, "invalid_valid", "valid")
    if not (type(reason) is str and reason in REASONS):
        _add(errors, "invalid_reason", "reason")
    for field in ("evidence_id", "source_id"):
        value = result[field]
        if status_ok and status not in _EXPOSES_IDS:
            ok = value is None
        else:
            ok = type(value) is str and 0 < len(value) <= MAX_ID_LENGTH
        if not ok:
            _add(errors, "invalid_" + field, field)
    for field in ("execution_allowed", "executed"):
        if result[field] is not False:
            _add(errors, "invalid_" + field, field)
    if not errors and reason not in _REASONS_OF_STATUS[status]:
        _add(errors, "inconsistent_result", "result")
    return errors


def validate_research_evidence_context_result(result=None):
    """Validation result for a context result; nothing is repaired."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
