"""
Capability execution boundary (Prompt 847, Section 13 - Capability System)
==========================================================================
ONE small read-only function that decides, deterministically, whether
execution of a capability MAY proceed. It never executes anything: it only
combines the existing layers - descriptor validity and the lifecycle state
check come from Prompt 844 (`validate_capability`, which composes Prompt 841
and 843) and the selected capability comes from a Prompt 846 selection result
(identity/version checks: Prompt 842). It loads no handler, tool, module or
code, and registers, enables, disables, replaces or modifies nothing.

  evaluate_capability_execution(capability, request=None) -> evaluation

Inputs (plain dicts; exact keys only, nothing is inferred or repaired):
  capability  {"descriptor", "lifecycle_state"}
              `descriptor` is a Prompt 841 descriptor; `lifecycle_state` is the
              EXPLICIT Prompt 843 state. The state is never inferred from the
              descriptor (its `enabled` flag, name, purpose, ...): permissions
              are never derived from the name, purpose or implementation.
  request     None, or {"selection": <Prompt 846 select_capability() result>}.
              Without a selection no capability is selected, so nothing is
              allowed. The request carries nothing else and is never executed.

Execution may be allowed ONLY when ALL of these hold, checked in this order:
  1. the capability input is well formed (else status "invalid_input");
  2. the descriptor is structurally valid (Prompt 844);
  3. its lifecycle state is exactly "enabled" (Prompt 843);
  4. the request holds a valid Prompt 846 selection with status "selected"
     whose selected entry is exactly this capability (identity, version and
     descriptor).
Otherwise the result is a denial with the FIRST failing reason:

  invalid_input  invalid_capability_input   capability is not exactly
                                            {"descriptor", "lifecycle_state"}
                 invalid_request            request is neither None nor
                                            exactly {"selection"}
  denied         invalid_capability         descriptor is not valid (844)
                 invalid_lifecycle_state    state is not a lifecycle state
                 lifecycle_defined / lifecycle_validated / lifecycle_disabled /
                 lifecycle_deprecated       the state is not "enabled"
                 no_selection               no request / no selection given
                 not_selected               selection result: nothing selected
                 invalid_selection          selection is malformed, or is an
                                            invalid_input selection result
                 selection_mismatch         the selected capability is not
                                            this capability
  allowed        allowed

Result (always these keys, in this order, JSON-safe, fresh on every call):

  {"status", "allowed", "reason", "capability_name", "capability_version",
   "execution_allowed", "executed"}

  status              "allowed" / "denied" / "invalid_input"
  allowed             True only for status "allowed"
  capability_name     the descriptor name when it is a valid identity name,
  capability_version  the descriptor version when it is a valid version, else
                      None (malformed values are never echoed)
  execution_allowed   equals `allowed`: the boundary check says execution MAY
                      proceed; nothing is started by it
  executed            always False

Bounded (the Prompt 841 bounds apply), read-only, deterministic, never raises.
Pure Python plus the Prompt 842-846 capability modules; no Core, Memory, AEL,
NLU, reasoning, execution, LLM, network or filesystem; no registry is used.
"""

from .capability_identity import build_capability_identity
from .capability_lifecycle import STATE_ENABLED
from .capability_matching import MAX_MATCHES
from .capability_selection import (
    REASON_NAME_ORDER, REASON_UNIQUE, REASON_VERSION, STATUS_NOT_SELECTED,
    STATUS_SELECTED, _valid_match,
)
from .capability_validation import validate_capability

EXECUTION_BOUNDARY_VERSION = 1

STATUS_ALLOWED = "allowed"
STATUS_DENIED = "denied"
STATUS_INVALID_INPUT = "invalid_input"

REASON_ALLOWED = "allowed"
REASON_INVALID_CAPABILITY_INPUT = "invalid_capability_input"
REASON_INVALID_REQUEST = "invalid_request"
REASON_INVALID_CAPABILITY = "invalid_capability"
REASON_INVALID_LIFECYCLE_STATE = "invalid_lifecycle_state"
REASON_NO_SELECTION = "no_selection"
REASON_NOT_SELECTED = "not_selected"
REASON_INVALID_SELECTION = "invalid_selection"
REASON_SELECTION_MISMATCH = "selection_mismatch"
REASON_BOUNDARY_ERROR = "boundary_error"

_CAPABILITY_KEYS = {"descriptor", "lifecycle_state"}
_REQUEST_KEYS = {"selection"}
_SELECTION_KEYS = {"status", "selected", "candidate_count", "reason",
                   "execution_allowed", "executed"}
_SELECTED_REASONS = (REASON_UNIQUE, REASON_VERSION, REASON_NAME_ORDER)


def _evaluation(status, reason, name=None, version=None):
    allowed = status == STATUS_ALLOWED
    return {"status": status, "allowed": allowed, "reason": reason,
            "capability_name": name, "capability_version": version,
            "execution_allowed": allowed, "executed": False}


def _selection_reason(selection, descriptor):
    """Denial reason for the selection, or None when it selects `descriptor`."""
    if type(selection) is not dict or set(selection) != _SELECTION_KEYS:
        return REASON_INVALID_SELECTION
    if selection["execution_allowed"] is not False or selection["executed"] is not False:
        return REASON_INVALID_SELECTION
    status = selection["status"]
    if status == STATUS_NOT_SELECTED:
        if selection["selected"] is not None or selection["candidate_count"] != 0:
            return REASON_INVALID_SELECTION
        return REASON_NOT_SELECTED
    if status != STATUS_SELECTED:
        return REASON_INVALID_SELECTION
    count = selection["candidate_count"]
    if type(count) is not int or not 1 <= count <= MAX_MATCHES:
        return REASON_INVALID_SELECTION
    if selection["reason"] not in _SELECTED_REASONS:
        return REASON_INVALID_SELECTION
    selected = selection["selected"]
    if not _valid_match(selected):
        return REASON_INVALID_SELECTION
    expected = {"identity": build_capability_identity(descriptor)["identity"],
                "version": descriptor["version"], "descriptor": descriptor}
    return None if selected == expected else REASON_SELECTION_MISMATCH


def evaluate_capability_execution(capability=None, request=None):
    """Evaluate (never perform) whether execution of `capability` may proceed."""
    try:
        if type(capability) is not dict or set(capability) != _CAPABILITY_KEYS:
            return _evaluation(STATUS_INVALID_INPUT, REASON_INVALID_CAPABILITY_INPUT)
        if request is not None and (type(request) is not dict or set(request) != _REQUEST_KEYS):
            return _evaluation(STATUS_INVALID_INPUT, REASON_INVALID_REQUEST)

        descriptor, state = capability["descriptor"], capability["lifecycle_state"]
        validation = validate_capability(descriptor, state)
        name, version = validation["name"], validation["version"]
        if not validation["valid"]:
            reason = (REASON_INVALID_LIFECYCLE_STATE if validation["lifecycle_valid"] is False
                      else REASON_INVALID_CAPABILITY)
            return _evaluation(STATUS_DENIED, reason, name, version)
        if state != STATE_ENABLED:
            return _evaluation(STATUS_DENIED, "lifecycle_" + state, name, version)

        if request is None:
            return _evaluation(STATUS_DENIED, REASON_NO_SELECTION, name, version)
        reason = _selection_reason(request["selection"], descriptor)
        if reason is not None:
            return _evaluation(STATUS_DENIED, reason, name, version)
        return _evaluation(STATUS_ALLOWED, REASON_ALLOWED, name, version)
    except Exception:
        return _evaluation(STATUS_INVALID_INPUT, REASON_BOUNDARY_ERROR)
