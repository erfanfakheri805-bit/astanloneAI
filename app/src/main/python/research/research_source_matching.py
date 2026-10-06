"""
Research Source Matching (Prompt 865, Section 15 - Autonomous Research & Learning)
==================================================================================
A small, deterministic, read-only selection of which DECLARED research sources
are compatible with a Research Request. It never opens, accesses, resolves or
retrieves any source: `location` is never looked at. No fuzzy or semantic
matching, no aliases, no URL or network checks, no trust guessing, no source
discovery, no policy engine; no filesystem, network, LLM, Core, Memory or AEL.

  match_research_sources(research_request, sources) -> match result
  validate_research_source_match(result)            -> validation result

Reuses the public validators of Prompt 863 (validate_research_request) and
Prompt 864 (validate_research_source).

Inputs
  research_request  must pass validate_research_request.
  sources           an exact list of at most MAX_SOURCES records, each passing
                    validate_research_source, with unique source_id values.
                    A malformed list or record is rejected as a whole (never
                    skipped or repaired).

Explicit rules (the only ones; all comparisons are exact, case-sensitive)
  A. enabled        the source must have enabled == True.
  B. source type    request constraints may declare source types, as exact
                    strings:
                      "source_type:<type>"      allow-list entry
                      "not:source_type:<type>"  exclusion entry
                    <type> must be one of SOURCE_TYPES (Prompt 864), otherwise
                    the request is rejected (invalid_request). If the request
                    has no "source_type:" entry every type is allowed (an
                    enabled valid source is compatible); with one or more
                    entries the source_type must equal one of them. An
                    excluded type is never compatible.
  C. no conflict    a source constraint conflicts with a request constraint
                    only when one is exactly "<text>" and the other is exactly
                    "not:<text>" (exact negation). Nothing else is a conflict.
  Per source the first failing rule decides the rejection reason, checked in
  the order enabled, source_type_excluded, source_type_not_allowed,
  constraint_conflict. Matching sources keep their declaration order.

Match result (exactly these seven keys, fixed order, fresh on every call):

  {"status", "matched", "candidate_count", "matches", "rejected",
   "execution_allowed", "executed"}

  status            one of STATUSES:
                      "matched"        at least one source is compatible
                      "no_match"       sources were evaluated, none compatible
                      "no_valid_match" the sources list is empty (no candidate)
                      "invalid_request" request invalid (Prompt 863 rules or a
                                       malformed source-type constraint)
                      "invalid_sources" sources not a valid list of unique
                                       valid sources (or over MAX_SOURCES)
                      "matching_error" unexpected internal failure
  matched           True only when status is "matched"
  candidate_count   number of sources evaluated (0 for every non-evaluated
                    status), == len(matches) + len(rejected)
  matches           fresh copies of the compatible sources, declaration order
  rejected          [{"source_id", "reason"}] in declaration order; reason one
                    of REASONS: disabled, source_type_excluded,
                    source_type_not_allowed, constraint_conflict
  execution_allowed always exactly False
  executed          always exactly False

validate_research_source_match(result)
  Structural and consistency check, never repairs: exact keys and types, known
  status, `matched` agreeing with status, candidate_count an int (not bool) in
  0..MAX_SOURCES equal to len(matches)+len(rejected), every match a valid
  enabled Research Source, every rejection exactly {source_id, reason} with a
  known reason, unique source_ids across both lists, per-status shape
  (matched: matches non-empty; no_match: matches empty, rejected non-empty;
  every other status: both empty and candidate_count 0), flags exactly False.
  Result (fixed keys, fresh): {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_result, result_not_dict, too_many_fields, unexpected_field,
  missing_field, invalid_status, invalid_matched, invalid_candidate_count,
  invalid_matches, invalid_match, invalid_rejected, invalid_rejection,
  too_many_items, duplicate_source_id, inconsistent_result,
  invalid_execution_allowed, invalid_executed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the public Prompt 863 / 864 validators.
"""

from research.research_request import validate_research_request
from research.research_source import SOURCE_TYPES, validate_research_source

MAX_SOURCES = 32
MAX_ERRORS = 16
MAX_FIELDS = 16

STATUS_MATCHED = "matched"
STATUS_NO_MATCH = "no_match"
STATUS_NO_VALID_MATCH = "no_valid_match"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_SOURCES = "invalid_sources"
STATUS_MATCHING_ERROR = "matching_error"
STATUSES = (STATUS_MATCHED, STATUS_NO_MATCH, STATUS_NO_VALID_MATCH, STATUS_INVALID_REQUEST,
            STATUS_INVALID_SOURCES, STATUS_MATCHING_ERROR)

REASON_DISABLED = "disabled"
REASON_EXCLUDED = "source_type_excluded"
REASON_NOT_ALLOWED = "source_type_not_allowed"
REASON_CONFLICT = "constraint_conflict"
REASONS = (REASON_DISABLED, REASON_EXCLUDED, REASON_NOT_ALLOWED, REASON_CONFLICT)

ALLOW_PREFIX = "source_type:"
EXCLUDE_PREFIX = "not:source_type:"
NEGATION_PREFIX = "not:"

FIELDS = ("status", "matched", "candidate_count", "matches", "rejected",
          "execution_allowed", "executed")


def _result(status, candidate_count=0, matches=None, rejected=None):
    return {"status": status, "matched": status == STATUS_MATCHED,
            "candidate_count": candidate_count, "matches": matches or [],
            "rejected": rejected or [], "execution_allowed": False, "executed": False}


def _type_rules(request):
    """(allowed, excluded) source-type sets from the request constraints, or None if malformed."""
    allowed, excluded = set(), set()
    for constraint in request["constraints"]:
        if constraint.startswith(EXCLUDE_PREFIX):
            value, target = constraint[len(EXCLUDE_PREFIX):], excluded
        elif constraint.startswith(ALLOW_PREFIX):
            value, target = constraint[len(ALLOW_PREFIX):], allowed
        else:
            continue
        if value not in SOURCE_TYPES:
            return None
        target.add(value)
    return allowed, excluded


def _conflicts(source_constraints, request_constraints):
    for s in source_constraints:
        for r in request_constraints:
            if s == NEGATION_PREFIX + r or r == NEGATION_PREFIX + s:
                return True
    return False


def _rejection(source, allowed, excluded, request_constraints):
    if source["enabled"] is not True:
        return REASON_DISABLED
    if source["source_type"] in excluded:
        return REASON_EXCLUDED
    if allowed and source["source_type"] not in allowed:
        return REASON_NOT_ALLOWED
    if _conflicts(source["constraints"], request_constraints):
        return REASON_CONFLICT
    return None


def _sources_valid(sources):
    if type(sources) is not list or len(sources) > MAX_SOURCES:
        return False
    seen = set()
    for source in sources:
        if not validate_research_source(source)["valid"] or source["source_id"] in seen:
            return False
        seen.add(source["source_id"])
    return True


def match_research_sources(research_request=None, sources=None):
    """Fresh match result; inputs are never modified and no source is accessed."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _result(STATUS_INVALID_REQUEST)
        rules = _type_rules(research_request)
        if rules is None:
            return _result(STATUS_INVALID_REQUEST)
        if not _sources_valid(sources):
            return _result(STATUS_INVALID_SOURCES)
        if not sources:
            return _result(STATUS_NO_VALID_MATCH)
        allowed, excluded = rules
        matches, rejected = [], []
        for source in sources:
            reason = _rejection(source, allowed, excluded, research_request["constraints"])
            if reason is None:
                copy = dict(source)
                copy["constraints"] = list(source["constraints"])
                matches.append(copy)
            else:
                rejected.append({"source_id": source["source_id"], "reason": reason})
        return _result(STATUS_MATCHED if matches else STATUS_NO_MATCH, len(sources),
                       matches, rejected)
    except Exception:
        return _result(STATUS_MATCHING_ERROR)


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _check_lists(errors, result):
    matches, rejected = result["matches"], result["rejected"]
    ids = []
    if type(matches) is not list:
        _add(errors, "invalid_matches", "matches")
    elif len(matches) > MAX_SOURCES:
        _add(errors, "too_many_items", "matches")
    else:
        for index, item in enumerate(matches):
            if not validate_research_source(item)["valid"] or item["enabled"] is not True:
                _add(errors, "invalid_match", "matches[%d]" % index)
            else:
                ids.append(item["source_id"])
    if type(rejected) is not list:
        _add(errors, "invalid_rejected", "rejected")
    elif len(rejected) > MAX_SOURCES:
        _add(errors, "too_many_items", "rejected")
    else:
        for index, item in enumerate(rejected):
            if (type(item) is dict and list(item) == ["source_id", "reason"]
                    and type(item["source_id"]) is str and item["source_id"]
                    and type(item["reason"]) is str and item["reason"] in REASONS):
                ids.append(item["source_id"])
            else:
                _add(errors, "invalid_rejection", "rejected[%d]" % index)
    if not errors and len(set(ids)) != len(ids):
        _add(errors, "duplicate_source_id", "matches")


def _check_consistency(errors, result):
    status, matches, rejected = result["status"], result["matches"], result["rejected"]
    count = result["candidate_count"]
    if status == STATUS_MATCHED:
        ok = bool(matches) and count == len(matches) + len(rejected)
    elif status == STATUS_NO_MATCH:
        ok = not matches and bool(rejected) and count == len(rejected)
    else:
        ok = not matches and not rejected and count == 0
    if not ok:
        _add(errors, "inconsistent_result", "result")


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
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        _add(errors, "invalid_status", "status")
    if type(result["matched"]) is not bool or (status_ok and result["matched"] != (status == STATUS_MATCHED)):
        _add(errors, "invalid_matched", "matched")
    count = result["candidate_count"]
    if type(count) is not int or not 0 <= count <= MAX_SOURCES:
        _add(errors, "invalid_candidate_count", "candidate_count")
    for field in ("execution_allowed", "executed"):
        if result[field] is not False:
            _add(errors, "invalid_" + field, field)
    _check_lists(errors, result)
    if not errors:
        _check_consistency(errors, result)
    return errors


def validate_research_source_match(result=None):
    """Validation result for a match result; nothing is repaired."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
