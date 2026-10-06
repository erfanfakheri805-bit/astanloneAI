"""
Capability readiness boundary (Prompt 848, Section 13 - Capability System)
==========================================================================
ONE small read-only composition function that reports whether a capability is
fully READY to cross the execution boundary. It only composes results that the
existing layers already produce; it adds no validation, matching or selection
logic of its own, performs no matching or selection, and never executes,
loads, registers, enables, disables, replaces or modifies anything.

  evaluate_capability_readiness(capability, match_result=None,
                                selection_result=None) -> readiness

Inputs (supplied by the caller, used exactly as given, never repaired):
  capability        {"descriptor", "lifecycle_state"} (Prompt 847 input)
  match_result      a Prompt 845 `match_capability()` result
  selection_result  a Prompt 846 `select_capability()` result

Reused layers: descriptor validity and the lifecycle state come from the
Prompt 847 execution boundary (which composes Prompt 844 validation and
Prompt 843 lifecycle); the match-result shape check is the Prompt 846 input
check; selection validity and "selected capability == this capability" are
the Prompt 847 execution boundary evaluated with the supplied selection.

Ready ONLY when all hold, checked in this order (first failure is reported):
  1. the capability is structurally valid;
  2. its lifecycle state is exactly "enabled";
  3. a valid, well-formed match result with status "matched" exists;
  4. a valid selection result exists whose status is "selected";
  5. the selected capability exactly equals the supplied capability;
  6. the selection reason is "unique_match" (one candidate);
  7. the selection is the one made from this match result (its single match
     equals the selected entry);
  8. the execution boundary allows execution.

  status invalid_input  reason invalid_capability_input / invalid_match_result /
                        invalid_selection_result  (malformed input)
         not_ready      reason invalid_capability, invalid_lifecycle_state,
                        lifecycle_defined / lifecycle_validated /
                        lifecycle_disabled / lifecycle_deprecated,
                        missing_match_result, match_not_matched,
                        missing_selection_result, not_selected,
                        selection_mismatch, selection_not_unique,
                        match_selection_inconsistent, execution_not_allowed
         ready          reason ready

Result (always these keys, in this order, JSON-safe, fresh on every call):
  {"status", "ready", "reason", "capability_name", "capability_version",
   "execution_allowed", "executed"}
  ready is True only for status "ready"; execution_allowed equals ready (it
  says execution MAY proceed; nothing is started); executed is always False.
  The name/version are the Prompt 847 values (None when not valid).

Bounded, deterministic, never raises. Pure Python plus the Prompt 846 and 847
capability modules; no Core, Memory, AEL, NLU, reasoning, execution, LLM,
network or filesystem; no registry is used.
"""

from .capability_execution_boundary import (
    REASON_INVALID_CAPABILITY_INPUT, REASON_INVALID_SELECTION, REASON_NOT_SELECTED,
    REASON_SELECTION_MISMATCH, STATUS_ALLOWED, STATUS_INVALID_INPUT as _BOUNDARY_INVALID,
    evaluate_capability_execution,
)
from .capability_matching import STATUS_MATCHED
from .capability_selection import REASON_UNIQUE, _well_formed

READINESS_VERSION = 1

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID_INPUT = "invalid_input"

REASON_READY = "ready"
REASON_INVALID_MATCH_RESULT = "invalid_match_result"
REASON_INVALID_SELECTION_RESULT = "invalid_selection_result"
REASON_MISSING_MATCH = "missing_match_result"
REASON_MATCH_NOT_MATCHED = "match_not_matched"
REASON_MISSING_SELECTION = "missing_selection_result"
REASON_SELECTION_NOT_UNIQUE = "selection_not_unique"
REASON_INCONSISTENT = "match_selection_inconsistent"
REASON_EXECUTION_NOT_ALLOWED = "execution_not_allowed"
REASON_READINESS_ERROR = "readiness_error"

_NO_SELECTION = "no_selection"


def _readiness(status, reason, name=None, version=None):
    ready = status == STATUS_READY
    return {"status": status, "ready": ready, "reason": reason,
            "capability_name": name, "capability_version": version,
            "execution_allowed": ready, "executed": False}


def evaluate_capability_readiness(capability=None, match_result=None, selection_result=None):
    """Evaluate (never perform) whether `capability` is ready for execution."""
    try:
        # 1-2: capability validity and lifecycle, via the execution boundary
        base = evaluate_capability_execution(capability, None)
        name, version = base["capability_name"], base["capability_version"]
        if base["status"] == _BOUNDARY_INVALID:
            return _readiness(STATUS_INVALID_INPUT, REASON_INVALID_CAPABILITY_INPUT)
        if base["reason"] != _NO_SELECTION:
            return _readiness(STATUS_NOT_READY, base["reason"], name, version)

        # 3: a valid match result
        if match_result is None:
            return _readiness(STATUS_NOT_READY, REASON_MISSING_MATCH, name, version)
        if not _well_formed(match_result):
            return _readiness(STATUS_INVALID_INPUT, REASON_INVALID_MATCH_RESULT, name, version)
        if match_result["status"] != STATUS_MATCHED:
            return _readiness(STATUS_NOT_READY, REASON_MATCH_NOT_MATCHED, name, version)

        # 4-5: a valid selection that selects exactly this capability
        if selection_result is None:
            return _readiness(STATUS_NOT_READY, REASON_MISSING_SELECTION, name, version)
        boundary = evaluate_capability_execution(capability, {"selection": selection_result})
        reason = boundary["reason"]
        if reason == REASON_INVALID_SELECTION:
            return _readiness(STATUS_INVALID_INPUT, REASON_INVALID_SELECTION_RESULT, name, version)
        if reason in (REASON_NOT_SELECTED, REASON_SELECTION_MISMATCH):
            return _readiness(STATUS_NOT_READY, reason, name, version)

        # 6-7: a unique selection that belongs to this match result
        if selection_result["reason"] != REASON_UNIQUE:
            return _readiness(STATUS_NOT_READY, REASON_SELECTION_NOT_UNIQUE, name, version)
        matches = match_result["matches"]
        if len(matches) != 1 or matches[0] != selection_result["selected"]:
            return _readiness(STATUS_NOT_READY, REASON_INCONSISTENT, name, version)

        # 8: the execution boundary must allow execution
        if boundary["status"] != STATUS_ALLOWED or boundary["allowed"] is not True:
            return _readiness(STATUS_NOT_READY, REASON_EXECUTION_NOT_ALLOWED, name, version)
        return _readiness(STATUS_READY, REASON_READY, name, version)
    except Exception:
        return _readiness(STATUS_INVALID_INPUT, REASON_READINESS_ERROR)
