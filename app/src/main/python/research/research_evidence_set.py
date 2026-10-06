"""
Research Evidence Set (Prompt 870, Section 15 - Autonomous Research & Learning)
===============================================================================
A strict, JSON-safe container for a validated, ordered set of research
evidence records that all belong to ONE research request and ONE research
source. It is a data container only: it retrieves, fetches, merges, rewrites,
summarises, ranks and infers nothing, never reads claims or confidence values,
never inspects source content, and makes no network, filesystem, subprocess,
API or model call. Not connected to Core, Memory, AEL or any external service.
Nothing is repaired, generated or reordered.

  build_research_evidence_set(research_request, source, evidence_items) -> build result
  validate_research_evidence_set(result)                                -> validation result

Reuses the public validators of Prompt 863 (validate_research_request), Prompt
864 (validate_research_source), Prompt 868 (validate_research_evidence) and the
Prompt 869 boundary (validate_research_evidence_for_context). No rule of those
contracts is duplicated and no constraint syntax or parser is added.

Normalized evidence set (exactly these six keys):

  {"version", "request_id", "source_id", "evidence", "count", "execution_allowed"}

  version            exactly the string "1"
  request_id         exactly the validated request's request_id
  source_id          exactly the validated source's source_id
  evidence           1..MAX_EVIDENCE (64) fresh copies of the evidence records,
                     in the caller's order (never sorted, merged or de-duplicated)
  count              exactly len(evidence)
  execution_allowed  exactly the bool False

build_research_evidence_set(research_request, source, evidence_items)
  Checks, in this fixed order:
    1. request invalid (Prompt 863)                  -> "invalid_request"
    2. source invalid (Prompt 864)                   -> "invalid_source"
    3. evidence_items not a list, or empty           -> "invalid_evidence_set"
    4. more than MAX_EVIDENCE items                  -> "evidence_limit_exceeded"
    5. per item, in order: the Prompt 869 context validation against the same
       request and source fails (invalid evidence, wrong source_id, disabled
       source, incompatible source_type / min_trust ...) -> "invalid_evidence"
       (where "evidence_items[i]"); an evidence_id already seen earlier
       -> "duplicate_evidence" (where "evidence_items[i]" of the repeat).
       A malformed "source_type:" / "min_trust:" request constraint reported by
       Prompt 869 is a request defect -> "invalid_request" (where
       "research_request"), reported alone.
  Unexpected internal failure                        -> "build_error"
  Steps 1-4 report one error; step 5 reports every failing item (<= MAX_ERRORS).
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "evidence_set", "execution_allowed", "executed"}
  `evidence_set` is a fresh normalized object when valid, else None. The result
  flags (not part of the set object) are always False, as in Prompt 868.

validate_research_evidence_set(result)
  `result` is a normalized evidence-set object (as built above). It has no
  request or source in scope, so only what the object itself shows is checked:
  exact keys; version; request_id / source_id text; evidence a list of 1..64
  items each valid per Prompt 868, each carrying the set's source_id, with
  unique evidence_id values; count an int (not bool) equal to len(evidence);
  execution_allowed False. Nothing is repaired. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS. Build codes: invalid_request,
invalid_source, invalid_evidence_set, evidence_limit_exceeded, invalid_evidence,
duplicate_evidence, build_error. Validation codes: missing_set, set_not_dict,
too_many_fields, unexpected_field, missing_field, invalid_version,
invalid_request_id, invalid_source_id, invalid_evidence_set,
evidence_limit_exceeded, invalid_evidence, duplicate_evidence, inconsistent_set
(an item's source_id differs from the set's), invalid_count,
invalid_execution_allowed, validation_error.

Bounded work (at most MAX_EVIDENCE items are ever examined), read-only (inputs
are never modified or kept), deterministic, never raises.
"""

import copy

from research.research_evidence import validate_research_evidence
from research.research_evidence_validation import validate_research_evidence_for_context
from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH, validate_research_source

SET_VERSION = "1"

MAX_EVIDENCE = 64
MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "request_id", "source_id", "evidence", "count", "execution_allowed")


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


def _build_result(errors, evidence_set=None):
    return {"valid": not errors, "errors": errors, "evidence_set": evidence_set,
            "execution_allowed": False, "executed": False}


def _failure(code, where):
    return _build_result([{"code": code, "where": where}])


def build_research_evidence_set(research_request=None, source=None, evidence_items=None):
    """Build a fresh normalized evidence set, or report errors; no input is modified."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _failure("invalid_request", "research_request")
        if not validate_research_source(source)["valid"]:
            return _failure("invalid_source", "source")
        if type(evidence_items) is not list or not evidence_items:
            return _failure("invalid_evidence_set", "evidence_items")
        if len(evidence_items) > MAX_EVIDENCE:
            return _failure("evidence_limit_exceeded", "evidence_items")
        errors, seen = [], set()
        for index, item in enumerate(evidence_items):
            where = "evidence_items[%d]" % index
            context = validate_research_evidence_for_context(research_request, source, item)
            if context["status"] == "invalid_request":
                return _failure("invalid_request", "research_request")
            if context["status"] == "validation_error":
                return _failure("build_error", "evidence_set")
            if not context["valid"]:
                _add(errors, "invalid_evidence", where)
            elif item["evidence_id"] in seen:
                _add(errors, "duplicate_evidence", where)
            else:
                seen.add(item["evidence_id"])
        if errors:
            return _build_result(errors)
        evidence = [copy.deepcopy(item) for item in evidence_items]
        return _build_result([], {"version": SET_VERSION,
                                  "request_id": research_request["request_id"],
                                  "source_id": source["source_id"], "evidence": evidence,
                                  "count": len(evidence), "execution_allowed": False})
    except Exception:
        return _failure("build_error", "evidence_set")


def _check_evidence(errors, data):
    evidence = data["evidence"]
    if type(evidence) is not list or not evidence:
        _add(errors, "invalid_evidence_set", "evidence")
        return
    if len(evidence) > MAX_EVIDENCE:
        _add(errors, "evidence_limit_exceeded", "evidence")
        return
    seen = set()
    for index, item in enumerate(evidence):
        where = "evidence[%d]" % index
        if not validate_research_evidence(item)["valid"]:
            _add(errors, "invalid_evidence", where)
        elif item["source_id"] != data["source_id"]:
            _add(errors, "inconsistent_set", where)
        elif item["evidence_id"] in seen:
            _add(errors, "duplicate_evidence", where)
        else:
            seen.add(item["evidence_id"])


def _errors(data):
    errors = []
    if type(data) is not dict:
        _add(errors, "missing_set" if data is None else "set_not_dict", "evidence_set")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, "too_many_fields", "evidence_set")
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
    if type(data["version"]) is not str or data["version"] != SET_VERSION:
        _add(errors, "invalid_version", "version")
    for field in ("request_id", "source_id"):
        if not _is_text(data[field], MAX_ID_LENGTH):
            _add(errors, "invalid_" + field, field)
    _check_evidence(errors, data)
    count = data["count"]
    if (type(count) is not int or type(data["evidence"]) is not list
            or count != len(data["evidence"])):
        _add(errors, "invalid_count", "count")
    if data["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    return errors


def validate_research_evidence_set(result=None):
    """Validation result for a normalized evidence-set object; nothing is repaired."""
    try:
        errors = _errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "evidence_set"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
