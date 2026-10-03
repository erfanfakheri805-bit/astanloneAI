"""
Self-Upgrade - Capability Lifecycle Decision (AgentLoop integration)
=======================================================================
`build_capability_lifecycle_decision` is the one, small mapping from an
already-derived `CapabilityLifecycleState` (self_upgrade.
capability_lifecycle.build_capability_lifecycle_state, Prompt 379) onto
the fixed, structured decision `AgentLoop` (agent.agent_loop, Prompt
380: `AgentLoop.get_capability_lifecycle_decision`) is allowed to
report about what is currently allowed to happen next for a
capability. It decides nothing new and performs nothing: every
decision is read off `current_status` alone, through one fixed table -
never a stage result, never a test result, never a guess, and never a
second lifecycle-state system.

    CapabilityLifecycleState (Prompt 379, build_capability_lifecycle_state)
        -> build_capability_lifecycle_decision(...)
        -> CapabilityLifecycleDecision{capability_name, lifecycle_status,
               decision, reason, errors, lifecycle_state}

THIS STEP ONLY MAPS A STATUS TO A DECISION LABEL. It never activates a
capability, never executes one (or any generated code), never
approves or rejects anything, never registers or modifies anything in
the live Capability Registry, never creates or applies a correction,
never creates or rolls back a version, and never starts another
Self-Upgrade cycle. Nothing here calls `ApprovalManager.approve`/
`.reject`/`.create_request`, `CapabilitySystem.register`/
`set_enabled`, `register_approved_capability`, `verify_registered_capability`,
`execute`, `run`, or anything else that changes state - it reads a
`CapabilityLifecycleState` dict `build_capability_lifecycle_state`
already produced and nothing else.

Reuses, never duplicates:
  - `self_upgrade.capability_lifecycle.build_capability_lifecycle_state`
    (Prompt 379, unchanged) is the *only* source of lifecycle state;
    this module never re-derives it from raw stage results itself.
  - `self_upgrade.capability_lifecycle.ALL_LIFECYCLE_STATUSES` (Prompt
    379, unchanged) is the exact, existing status vocabulary this
    module's table is keyed on - a status this project's lifecycle
    module does not itself recognize can never appear here either.

Decisions (`decision`, exactly one of `ALL_CAPABILITY_DECISIONS`),
produced by one fixed table (`_LIFECYCLE_STATUS_TO_DECISION`) - the
*only* place this mapping exists:

    CONTINUE_BUILD          <- BUILT, VALIDATED, TESTED, VERSIONED
                                (still working through the existing
                                build/validate/test/version stages; no
                                approval request is waiting yet).
    WAITING_FOR_APPROVAL    <- PENDING_APPROVAL (rule: this is the
                                *only* lifecycle status that ever
                                produces this decision - AgentLoop
                                never infers a human decision, it only
                                reports that one is still pending).
    REGISTRATION_REQUIRED   <- APPROVED (a human explicitly approved
                                the capability itself, but registration
                                has not been requested or approved yet;
                                registration preparation/plan/approval -
                                each already requiring its own,
                                separate, explicit human decision -
                                must still happen before registration
                                can even be considered).
    READY_FOR_REGISTRATION  <- READY_FOR_REGISTRATION (registration was
                                explicitly approved; the capability is
                                still not registered - this decision is
                                never, by itself, a registration, and
                                nothing here performs one).
    VERIFICATION_REQUIRED   <- REGISTERED (a REGISTERED capability is
                                never activated or executed by this
                                module or by AgentLoop; verification is
                                the next, separate, still-to-run step).
    VERIFIED                <- VERIFIED (recognized and reported - never
                                treated as ACTIVE and never a reason to
                                register, activate, or execute anything).
    BLOCKED                 <- BLOCKED, REJECTED (a human rejection is
                                reported as BLOCKED; both are terminal -
                                nothing here or in AgentLoop ever turns
                                a REJECTED lifecycle back into an
                                approval or a fresh request).
    FAILED                  <- FAILED
    ROLLED_BACK             <- ROLLED_BACK
    INVALID                 <- INVALID, an unrecognized current_status,
                                or a `lifecycle_state` that is not a
                                well-formed CapabilityLifecycleState
                                dict at all.

Never raises: any malformed `lifecycle_state` is reported as INVALID
with a non-empty `errors`, never as an exception.
"""

from self_upgrade.capability_lifecycle import (
    ALL_LIFECYCLE_STATUSES,
    LIFECYCLE_BUILT,
    LIFECYCLE_VALIDATED,
    LIFECYCLE_TESTED,
    LIFECYCLE_VERSIONED,
    LIFECYCLE_PENDING_APPROVAL,
    LIFECYCLE_APPROVED,
    LIFECYCLE_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED,
    LIFECYCLE_VERIFIED,
    LIFECYCLE_INVALID,
    LIFECYCLE_BLOCKED,
    LIFECYCLE_REJECTED,
    LIFECYCLE_FAILED,
    LIFECYCLE_ROLLED_BACK,
)

DECISION_CONTINUE_BUILD = "CONTINUE_BUILD"
DECISION_WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
DECISION_REGISTRATION_REQUIRED = "REGISTRATION_REQUIRED"
DECISION_READY_FOR_REGISTRATION = "READY_FOR_REGISTRATION"
DECISION_VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
DECISION_VERIFIED = "VERIFIED"
DECISION_BLOCKED = "BLOCKED"
DECISION_FAILED = "FAILED"
DECISION_ROLLED_BACK = "ROLLED_BACK"
DECISION_INVALID = "INVALID"

ALL_CAPABILITY_DECISIONS = (
    DECISION_CONTINUE_BUILD,
    DECISION_WAITING_FOR_APPROVAL,
    DECISION_REGISTRATION_REQUIRED,
    DECISION_READY_FOR_REGISTRATION,
    DECISION_VERIFICATION_REQUIRED,
    DECISION_VERIFIED,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)

# Decisions that never perform, permit, or imply any registration,
# activation, or execution on their own - listed here only for tests /
# callers that want a single, explicit, importable source of truth
# rather than re-deriving it. Not used by build_capability_lifecycle_decision
# itself (it never branches on this list).
NON_ACTIONABLE_DECISIONS = (
    DECISION_WAITING_FOR_APPROVAL,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)

# The one, fixed status -> decision table. Nothing else may ever
# influence `decision` - not a test result, not a fresh
# ApprovalManager/CapabilitySystem call, not a rollback check:
# `build_capability_lifecycle_decision` only ever reads
# `lifecycle_state["current_status"]` against this map.
_LIFECYCLE_STATUS_TO_DECISION = {
    LIFECYCLE_BUILT: DECISION_CONTINUE_BUILD,
    LIFECYCLE_VALIDATED: DECISION_CONTINUE_BUILD,
    LIFECYCLE_TESTED: DECISION_CONTINUE_BUILD,
    LIFECYCLE_VERSIONED: DECISION_CONTINUE_BUILD,
    LIFECYCLE_PENDING_APPROVAL: DECISION_WAITING_FOR_APPROVAL,
    LIFECYCLE_APPROVED: DECISION_REGISTRATION_REQUIRED,
    LIFECYCLE_READY_FOR_REGISTRATION: DECISION_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED: DECISION_VERIFICATION_REQUIRED,
    LIFECYCLE_VERIFIED: DECISION_VERIFIED,
    LIFECYCLE_BLOCKED: DECISION_BLOCKED,
    LIFECYCLE_REJECTED: DECISION_BLOCKED,
    LIFECYCLE_FAILED: DECISION_FAILED,
    LIFECYCLE_ROLLED_BACK: DECISION_ROLLED_BACK,
    LIFECYCLE_INVALID: DECISION_INVALID,
}

# Defensive, module-load-time check: every lifecycle status Prompt 379
# recognizes must be mapped exactly once here, and this table must
# never invent a status Prompt 379 does not itself recognize.
assert set(_LIFECYCLE_STATUS_TO_DECISION) == set(ALL_LIFECYCLE_STATUSES)

_REASONS = {
    DECISION_CONTINUE_BUILD: (
        "The capability has not reached an approval request yet; the "
        "existing build/validate/test/version stages continue."),
    DECISION_WAITING_FOR_APPROVAL: (
        "An approval request is waiting on an explicit human decision. "
        "AgentLoop never infers approval; it only waits."),
    DECISION_REGISTRATION_REQUIRED: (
        "The capability itself was explicitly approved, but "
        "registration has not been requested or approved; registration "
        "preparation/plan/approval - each requiring its own explicit "
        "human decision - must still happen before registration."),
    DECISION_READY_FOR_REGISTRATION: (
        "Registration was explicitly approved. The capability is still "
        "not registered; registration is never performed automatically."),
    DECISION_VERIFICATION_REQUIRED: (
        "The capability is registered (disabled) but not yet verified. "
        "It is not activated or executed."),
    DECISION_VERIFIED: (
        "The registration was verified against the approved "
        "registration information. This is not activation, and nothing "
        "here executes the capability."),
    DECISION_BLOCKED: "The capability's lifecycle is blocked, or was rejected by a human.",
    DECISION_FAILED: "A lifecycle stage failed.",
    DECISION_ROLLED_BACK: "The change behind this capability was rolled back to its previous version.",
    DECISION_INVALID: "The lifecycle state is invalid, malformed, or missing.",
}


def _result(capability_name, lifecycle_status, decision, reason, errors, lifecycle_state):
    return {
        "capability_name": capability_name,
        "lifecycle_status": lifecycle_status,
        "decision": decision,
        "reason": reason,
        "errors": list(errors or []),
        "lifecycle_state": lifecycle_state,
    }


def build_capability_lifecycle_decision(lifecycle_state):
    """Map an already-derived `CapabilityLifecycleState` dict
    (self_upgrade.capability_lifecycle.build_capability_lifecycle_state,
    Prompt 379) onto a fixed `CapabilityLifecycleDecision`. See module
    docstring for the full decision vocabulary, the fixed mapping
    table, and the safety boundary. Read-only and side-effect free:
    never activates, executes, approves, rejects, registers, or
    modifies anything; never raises.

    `lifecycle_state` must be the dict `build_capability_lifecycle_state`
    already produced - this function never rebuilds it, never accepts
    raw stage results, and never re-consults `ApprovalManager`/
    `CapabilitySystem` itself.

    Always returns a `CapabilityLifecycleDecision` dict with exactly:
        {
            "capability_name": <str or None>,
            "lifecycle_status": <the input's current_status, or None>,
            "decision": <one of ALL_CAPABILITY_DECISIONS>,
            "reason": <short, fixed, human-readable explanation>,
            "errors": <list of str - the lifecycle_state's own errors,
                carried through unchanged for BLOCKED/FAILED/INVALID;
                empty for every other decision>,
            "lifecycle_state": <the input, unchanged>,
        }
    """
    try:
        return _decide(lifecycle_state)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(
            None, None, DECISION_INVALID,
            "Unexpected error while deciding the lifecycle decision.",
            [f"Unexpected error: {type(exc).__name__}: {exc}"], lifecycle_state)


def _decide(lifecycle_state):
    if not isinstance(lifecycle_state, dict):
        return _result(
            None, None, DECISION_INVALID,
            "lifecycle_state must be a CapabilityLifecycleState dict.",
            ["lifecycle_state must be a CapabilityLifecycleState dict."],
            lifecycle_state)

    capability_name = lifecycle_state.get("capability_name")
    status = lifecycle_state.get("current_status")

    if status not in _LIFECYCLE_STATUS_TO_DECISION:
        return _result(
            capability_name, status, DECISION_INVALID,
            f"Unrecognized lifecycle current_status: {status!r}.",
            [f"current_status {status!r} is not one of ALL_LIFECYCLE_STATUSES."],
            lifecycle_state)

    decision = _LIFECYCLE_STATUS_TO_DECISION[status]
    carry_errors = decision in (
        DECISION_BLOCKED, DECISION_FAILED, DECISION_ROLLED_BACK, DECISION_INVALID)
    errors = list(lifecycle_state.get("errors") or []) if carry_errors else []
    return _result(
        capability_name, status, decision, _REASONS[decision], errors, lifecycle_state)
