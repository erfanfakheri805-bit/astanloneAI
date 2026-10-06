"""
Capability selection foundation (Prompt 846, Section 13 - Capability System)
=============================================================================
ONE small read-only function that picks at most one capability from the result
of the Prompt 845 `match_capability()`. It does not match anything itself:
candidates come only from `match_result["matches"]`; descriptor validity is the
Prompt 844 `validate_capability`, version parsing/ordering is Prompt 842
(`parse_capability_version`, `compare_capability_versions`) and identity is the
Prompt 842 `build_capability_identity`. Nothing is executed, registered,
enabled, disabled, replaced or modified, and nothing is invented.

  select_capability(match_result) -> selection

Input: a Prompt 845 result dict (exactly its eight keys). It is checked before
anything is selected; a result that is not well-formed is never trusted:
status/matched agree, counts are exact ints, execution_allowed and executed
are False, a non-"matched" result has no matches, and every match is exactly
{"identity": {"name"}, "version", "descriptor"} with a valid descriptor
(Prompt 844), a valid version equal to the descriptor version (Prompt 842) and
an identity equal to the Prompt 842 identity of that descriptor. One bad match
makes the whole input invalid (nothing is skipped or repaired).

Selection order among the matches:
  1. highest valid version (Prompt 842 comparison);
  2. exact identity: every match already has an identity that exactly equals
     the Prompt 842 identity of its descriptor (checked above), so this step
     never prefers anything by similarity or guesswork;
  3. stable name order (code point order of the identity name); if still tied,
     the first of the tied matches in the supplied order (deterministic).

Result (always these keys, in this order, JSON-safe, fresh on every call):

  {"status", "selected", "candidate_count", "reason", "execution_allowed", "executed"}

  status           "selected"       one capability was selected
                   "not_selected"   the match result holds no valid match
                   "invalid_input"  the match result is malformed
  selected         {"identity": {"name"}, "version", "descriptor"} - a fresh
                   copy of the explicitly matched entry, else None
  candidate_count  number of matches considered (0 unless selected)
  reason           selected:      "unique_match" / "highest_version" /
                                  "name_order"
                   not_selected:  the Prompt 845 status ("no_match",
                                  "no_valid_match", "invalid_requirement",
                                  "invalid_registry", "matching_error")
                   invalid_input: "invalid_match_result"
  execution_allowed, executed
                   always False; a selection never implies execution

Bounded (at most MAX_MATCHES matches are accepted), deterministic, never
raises. Pure Python plus the Prompt 842, 844 and 845 modules; no Core, Memory,
AEL, NLU, reasoning, execution, LLM, network or filesystem; no registry is used.
"""

import copy

from .capability_identity import (
    REL_NEWER, REL_EQUAL, build_capability_identity, compare_capability_versions,
    parse_capability_version,
)
from .capability_matching import MAX_MATCHES, STATUSES, STATUS_MATCHED
from .capability_validation import validate_capability

SELECTION_VERSION = 1

STATUS_SELECTED = "selected"
STATUS_NOT_SELECTED = "not_selected"
STATUS_INVALID_INPUT = "invalid_input"

REASON_UNIQUE = "unique_match"
REASON_VERSION = "highest_version"
REASON_NAME_ORDER = "name_order"
REASON_INVALID = "invalid_match_result"

_RESULT_KEYS = ("status", "matched", "candidate_count", "matches", "rejected", "truncated",
                "execution_allowed", "executed")
_MATCH_KEYS = ("identity", "version", "descriptor")


def _selection(status, reason, selected=None, count=0):
    return {"status": status, "selected": selected, "candidate_count": count,
            "reason": reason, "execution_allowed": False, "executed": False}


def _valid_match(match):
    """True only for an exact, internally consistent Prompt 845 match entry."""
    if type(match) is not dict or set(match) != set(_MATCH_KEYS):
        return False
    identity, version, descriptor = match["identity"], match["version"], match["descriptor"]
    if type(identity) is not dict or set(identity) != {"name"}:
        return False
    if not validate_capability(descriptor)["valid"]:
        return False
    if not parse_capability_version(version)["valid"] or version != descriptor["version"]:
        return False
    return identity == build_capability_identity(descriptor)["identity"]


def _well_formed(result):
    if type(result) is not dict or set(result) != set(_RESULT_KEYS):
        return False
    status, matches = result["status"], result["matches"]
    if type(status) is not str or status not in STATUSES:
        return False
    if result["matched"] is not (status == STATUS_MATCHED):
        return False
    count = result["candidate_count"]
    if type(count) is not int or count < 0:
        return False
    if type(matches) is not list or len(matches) > MAX_MATCHES:
        return False
    if type(result["rejected"]) is not list or type(result["truncated"]) is not bool:
        return False
    if result["execution_allowed"] is not False or result["executed"] is not False:
        return False
    if status == STATUS_MATCHED:
        return bool(matches) and all(_valid_match(m) for m in matches)
    return not matches


def select_capability(match_result=None):
    """Select at most one capability from a Prompt 845 match result."""
    try:
        if not _well_formed(match_result):
            return _selection(STATUS_INVALID_INPUT, REASON_INVALID)
        if match_result["status"] != STATUS_MATCHED:
            return _selection(STATUS_NOT_SELECTED, match_result["status"])

        matches = match_result["matches"]
        if len(matches) == 1:
            return _selection(STATUS_SELECTED, REASON_UNIQUE, copy.deepcopy(matches[0]), 1)

        top = [matches[0]]
        for match in matches[1:]:
            relation = compare_capability_versions(match["version"], top[0]["version"])["relation"]
            if relation == REL_NEWER:
                top = [match]
            elif relation == REL_EQUAL:
                top.append(match)
        if len(top) == 1:
            return _selection(STATUS_SELECTED, REASON_VERSION, copy.deepcopy(top[0]), len(matches))

        chosen = min(top, key=lambda m: m["identity"]["name"])  # first of equal names
        return _selection(STATUS_SELECTED, REASON_NAME_ORDER, copy.deepcopy(chosen), len(matches))
    except Exception:
        return _selection(STATUS_INVALID_INPUT, REASON_INVALID)
