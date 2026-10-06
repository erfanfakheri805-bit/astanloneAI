"""
Capability lifecycle foundation (Prompt 843, Section 13 - Capability System)
============================================================================
A small, stateless, read-only description of the lifecycle states a
registered capability may be in and of the transitions between them. It only
EVALUATES a requested transition; it stores no state, changes no registered
capability and is not linked to the registry, descriptors, identity layer,
Core, Memory or AEL. A lifecycle state never implies that a capability can
execute: every result carries `execution_allowed=False` and `executed=False`.

  validate_lifecycle_state(value)                    -> state validation
  evaluate_lifecycle_transition(current, requested)  -> transition evaluation
  get_allowed_next_states(current)                   -> allowed targets
  list_lifecycle_states()                            -> the states, in order
  list_lifecycle_transitions()                       -> the allowed transitions

States (exact lowercase strings, canonical order):
  "defined", "validated", "enabled", "disabled", "deprecated"
They are compared by exact string equality only: no trimming, case folding,
normalisation or guessing (a str subclass, bytes, None, ... is malformed).
A state is never inferred from a capability name, version, purpose or any
other descriptor field, and the lifecycle state "enabled" is unrelated to the
descriptor's `enabled` flag.

Allowed transitions (exactly these 9; everything else is rejected):
  defined    -> validated, deprecated
  validated  -> enabled, disabled, deprecated
  enabled    -> disabled, deprecated
  disabled   -> enabled, deprecated
  deprecated -> (nothing: terminal)

Transition evaluation `evaluate_lifecycle_transition(current, requested)`:
  allowed  reason "allowed"                  errors []
  rejected reason (also the single error code, where "transition"):
    "same_state"               current == requested
    "terminal_state"           current is "deprecated" (to another state)
    "transition_not_allowed"   any other pair not in the table above
  malformed input (nothing else is concluded; one error per bad argument):
    reason "invalid_current_state" (checked first) or "invalid_requested_state"
    error codes "invalid_state_type" (not an exact str) or "unknown_state"
    (a str that is not a lifecycle state, or longer than MAX_STATE_LENGTH),
    located at "current" / "requested" / "state"

Result shapes (fixed key order, JSON-safe, fresh on every call):
  state       {"version", "valid", "state", "errors", "execution_allowed", "executed"}
  transition  {"version", "allowed", "current", "requested", "reason", "errors",
               "execution_allowed", "executed"}   (current/requested: the state
               when valid, else None)
  next        {"version", "valid", "current", "next_states", "errors",
               "execution_allowed", "executed"}
  states      {"version", "count", "states", "execution_allowed", "executed"}
  transitions {"version", "count", "transitions": [{"from", "to"}],
               "execution_allowed", "executed"}

Deterministic, bounded (constant work), never raises, nothing executed,
registered, loaded, replaced, upgraded, removed or mutated. Pure Python with
no imports; no Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem.
"""

LIFECYCLE_VERSION = 1

STATE_DEFINED = "defined"
STATE_VALIDATED = "validated"
STATE_ENABLED = "enabled"
STATE_DISABLED = "disabled"
STATE_DEPRECATED = "deprecated"

LIFECYCLE_STATES = (STATE_DEFINED, STATE_VALIDATED, STATE_ENABLED, STATE_DISABLED,
                    STATE_DEPRECATED)
MAX_STATE_LENGTH = 16

_ALLOWED = (
    (STATE_DEFINED, (STATE_VALIDATED, STATE_DEPRECATED)),
    (STATE_VALIDATED, (STATE_ENABLED, STATE_DISABLED, STATE_DEPRECATED)),
    (STATE_ENABLED, (STATE_DISABLED, STATE_DEPRECATED)),
    (STATE_DISABLED, (STATE_ENABLED, STATE_DEPRECATED)),
    (STATE_DEPRECATED, ()),
)

REASON_ALLOWED = "allowed"
REASON_SAME_STATE = "same_state"
REASON_TERMINAL = "terminal_state"
REASON_NOT_ALLOWED = "transition_not_allowed"
REASON_INVALID_CURRENT = "invalid_current_state"
REASON_INVALID_REQUESTED = "invalid_requested_state"

ERR_STATE_TYPE = "invalid_state_type"
ERR_STATE_UNKNOWN = "unknown_state"
ERR_INTERNAL = "lifecycle_error"


def _targets(current):
    """Allowed target states of a valid state `current`, as a tuple."""
    for source, targets in _ALLOWED:
        if source == current:
            return targets
    return ()


def _state_error(value):
    """Error code for a malformed state, or None when it is a lifecycle state."""
    if type(value) is not str:
        return ERR_STATE_TYPE
    if len(value) > MAX_STATE_LENGTH or value not in LIFECYCLE_STATES:
        return ERR_STATE_UNKNOWN
    return None


def _state_result(valid, state, errors):
    return {"version": LIFECYCLE_VERSION, "valid": valid, "state": state,
            "errors": errors, "execution_allowed": False, "executed": False}


def validate_lifecycle_state(value):
    """Validation result for one lifecycle state."""
    try:
        code = _state_error(value)
        if code is not None:
            return _state_result(False, None, [{"code": code, "where": "state"}])
        return _state_result(True, value, [])
    except Exception:
        return _state_result(False, None, [{"code": ERR_INTERNAL, "where": "state"}])


def _transition_result(allowed, current, requested, reason, errors):
    return {"version": LIFECYCLE_VERSION, "allowed": allowed, "current": current,
            "requested": requested, "reason": reason, "errors": errors,
            "execution_allowed": False, "executed": False}


def evaluate_lifecycle_transition(current, requested):
    """Evaluate (never perform) a transition from `current` to `requested`."""
    try:
        errors = []
        cur_code, req_code = _state_error(current), _state_error(requested)
        if cur_code is not None:
            errors.append({"code": cur_code, "where": "current"})
        if req_code is not None:
            errors.append({"code": req_code, "where": "requested"})
        if errors:
            reason = REASON_INVALID_CURRENT if cur_code is not None else REASON_INVALID_REQUESTED
            return _transition_result(
                False, current if cur_code is None else None,
                requested if req_code is None else None, reason, errors)

        if current == requested:
            reason = REASON_SAME_STATE
        elif requested in _targets(current):
            return _transition_result(True, current, requested, REASON_ALLOWED, [])
        elif current == STATE_DEPRECATED:
            reason = REASON_TERMINAL
        else:
            reason = REASON_NOT_ALLOWED
        return _transition_result(False, current, requested, reason,
                                  [{"code": reason, "where": "transition"}])
    except Exception:
        return _transition_result(False, None, None, ERR_INTERNAL,
                                  [{"code": ERR_INTERNAL, "where": "transition"}])


def get_allowed_next_states(current):
    """The states a capability in `current` may be moved to (canonical order)."""
    try:
        code = _state_error(current)
        if code is not None:
            return {"version": LIFECYCLE_VERSION, "valid": False, "current": None,
                    "next_states": [], "errors": [{"code": code, "where": "current"}],
                    "execution_allowed": False, "executed": False}
        return {"version": LIFECYCLE_VERSION, "valid": True, "current": current,
                "next_states": list(_targets(current)), "errors": [],
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"version": LIFECYCLE_VERSION, "valid": False, "current": None,
                "next_states": [], "errors": [{"code": ERR_INTERNAL, "where": "current"}],
                "execution_allowed": False, "executed": False}


def list_lifecycle_states():
    """The five lifecycle states in canonical order (a fresh list)."""
    return {"version": LIFECYCLE_VERSION, "count": len(LIFECYCLE_STATES),
            "states": list(LIFECYCLE_STATES), "execution_allowed": False, "executed": False}


def list_lifecycle_transitions():
    """Every allowed transition, in canonical order (fresh dicts)."""
    pairs = [{"from": source, "to": target} for source, targets in _ALLOWED for target in targets]
    return {"version": LIFECYCLE_VERSION, "count": len(pairs), "transitions": pairs,
            "execution_allowed": False, "executed": False}
