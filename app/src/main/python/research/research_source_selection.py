"""
Research Source Selection (Prompt 866, Section 15 - Autonomous Research & Learning)
===================================================================================
A small, deterministic, read-only choice of ONE source from the valid matches of
a Prompt 865 match result. It never opens, accesses, loads, fetches or executes
anything from a source. No fuzzy or semantic matching, no aliases, no URL
discovery, no source discovery, no network, no filesystem; no Core, Memory or AEL.

  select_research_source(match_result)              -> selection result
  validate_research_source_selection(result)        -> validation result

Reuses the public validator of Prompt 865 (validate_research_source_match) and
the public source contract of Prompt 864 (validate_research_source, TRUST_LEVELS).
Source matching is not reimplemented.

Rules (the only ones)
  1. An invalid match result selects nothing (status "invalid_input").
  2. A valid match result whose status is not "matched", or with no matches,
     selects nothing (status "not_selected").
  3. Otherwise the match with the highest trust_level is selected:
     "trusted" > "standard" > "untrusted".
  4. Equal trust levels keep the original match order (the first one wins).

Selection result (exactly these six keys, fixed order, fresh on every call):

  {"status", "selected", "candidate_count", "reason", "execution_allowed", "executed"}

  status            one of STATUSES: "selected", "not_selected", "invalid_input",
                    "selection_error"
  selected          a deep copy of the selected source, else None
  candidate_count   number of matches considered (0 unless a source was selected)
  reason            one of REASONS, fixed per status
  execution_allowed always exactly False
  executed          always exactly False

validate_research_source_selection(result)
  Structural and consistency check, never repairs. Result (fixed keys, fresh):
  {"valid", "errors", "execution_allowed", "executed"}. Codes: missing_result,
  result_not_dict, too_many_fields, unexpected_field, missing_field,
  invalid_status, invalid_selected, invalid_candidate_count, invalid_reason,
  inconsistent_result, invalid_execution_allowed, invalid_executed,
  validation_error.

Bounded work, read-only (the input is never modified or kept), deterministic,
never raises. Pure Python.
"""

import copy

from research.research_source import TRUST_LEVELS, validate_research_source
from research.research_source_matching import (
    MAX_SOURCES, STATUS_MATCHED, validate_research_source_match)

MAX_ERRORS = 16
MAX_FIELDS = 16

STATUS_SELECTED = "selected"
STATUS_NOT_SELECTED = "not_selected"
STATUS_INVALID_INPUT = "invalid_input"
STATUS_SELECTION_ERROR = "selection_error"
STATUSES = (STATUS_SELECTED, STATUS_NOT_SELECTED, STATUS_INVALID_INPUT, STATUS_SELECTION_ERROR)

REASON_TRUST = "highest_trust_level"
REASON_NOT_MATCHED = "match_status_not_matched"
REASON_NO_MATCHES = "no_matches"
REASON_INVALID = "invalid_match_result"
REASON_ERROR = "selection_error"
REASONS = (REASON_TRUST, REASON_NOT_MATCHED, REASON_NO_MATCHES, REASON_INVALID, REASON_ERROR)

_REASON_OF_STATUS = {STATUS_SELECTED: (REASON_TRUST,),
                     STATUS_NOT_SELECTED: (REASON_NOT_MATCHED, REASON_NO_MATCHES),
                     STATUS_INVALID_INPUT: (REASON_INVALID,),
                     STATUS_SELECTION_ERROR: (REASON_ERROR,)}

FIELDS = ("status", "selected", "candidate_count", "reason", "execution_allowed", "executed")


def _result(status, reason, selected=None, candidate_count=0):
    return {"status": status, "selected": selected, "candidate_count": candidate_count,
            "reason": reason, "execution_allowed": False, "executed": False}


def select_research_source(match_result=None):
    """Fresh selection result; the input is never modified and no source is accessed."""
    try:
        if not validate_research_source_match(match_result)["valid"]:
            return _result(STATUS_INVALID_INPUT, REASON_INVALID)
        if match_result["status"] != STATUS_MATCHED:
            return _result(STATUS_NOT_SELECTED, REASON_NOT_MATCHED)
        matches = match_result["matches"]
        if not matches:
            return _result(STATUS_NOT_SELECTED, REASON_NO_MATCHES)
        best = matches[0]
        for candidate in matches[1:]:
            # strictly greater only, so equal trust keeps the earlier match
            if TRUST_LEVELS.index(candidate["trust_level"]) > TRUST_LEVELS.index(best["trust_level"]):
                best = candidate
        return _result(STATUS_SELECTED, REASON_TRUST, copy.deepcopy(best), len(matches))
    except Exception:
        return _result(STATUS_SELECTION_ERROR, REASON_ERROR)


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
    reason_ok = type(reason) is str and reason in REASONS
    if not reason_ok:
        _add(errors, "invalid_reason", "reason")
    selected, count = result["selected"], result["candidate_count"]
    if selected is not None and not validate_research_source(selected)["valid"]:
        _add(errors, "invalid_selected", "selected")
    elif selected is not None and selected["enabled"] is not True:
        _add(errors, "invalid_selected", "selected")
    if type(count) is not int or not 0 <= count <= MAX_SOURCES:
        _add(errors, "invalid_candidate_count", "candidate_count")
    for field in ("execution_allowed", "executed"):
        if result[field] is not False:
            _add(errors, "invalid_" + field, field)
    if not errors:
        chosen = status == STATUS_SELECTED
        if (reason not in _REASON_OF_STATUS[status] or (selected is not None) != chosen
                or (count >= 1) != chosen):
            _add(errors, "inconsistent_result", "result")
    return errors


def validate_research_source_selection(result=None):
    """Validation result for a selection result; nothing is repaired."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
