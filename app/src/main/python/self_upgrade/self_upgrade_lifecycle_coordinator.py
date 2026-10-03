"""
Self-Upgrade - Lifecycle Coordinator (SelfUpgradeRequest -> next action)
=========================================================================
`SelfUpgradeLifecycleCoordinator` (and the module-level function it
wraps, `build_self_upgrade_lifecycle_decision`) is the one small
orchestration/decision layer that connects the existing Self-Upgrade
stages, end to end, into a single deterministic answer to one
question: *given where a capability currently is, what is the next
valid lifecycle action?*

    SelfUpgradeRequest (self_upgrade.self_upgrade_request, Prompt 357)
        -> AdaptivePlanAnalyzer.analyze_self_upgrade_request (Prompt 358)
        -> CapabilityCreationPlan (self_upgrade.capability_creation_plan,
           Prompt 359)
        -> CapabilityImplementationSpec / CapabilityBuildSpec (Prompts
           360-361, not directly inspected here - see below)
        -> CapabilityBuilder / apply request / tests / correction /
           version / human approval / registration preparation / plan /
           approval / registration / verification (Prompts 362-378)
        -> CapabilityLifecycleState (self_upgrade.capability_lifecycle,
           Prompt 379, reused unchanged)
        -> SelfUpgradeLifecycleCoordinator
        -> SelfUpgradeLifecycleDecision{capability_name, lifecycle_status,
               decision, reason, errors, lifecycle_state}

THIS MODULE ONLY DECIDES WHAT THE NEXT ACTION LABEL IS. It never
performs that action. It never analyzes a request itself, never builds
or generates any source, never applies or writes a file, never runs a
test, never proposes or applies a correction, never creates a version
snapshot, never approves or rejects anything, never registers or
verifies anything in the live Capability Registry, and never activates
or executes a capability (or any generated code). Every one of those
actions already exists somewhere else in this project (see the chain
above) and stays exactly where it is; this coordinator reads their
already-produced results and reports which one, if any, is next.

Reuses, never duplicates:
  - `self_upgrade.capability_lifecycle.build_capability_lifecycle_state`
    (Prompt 379, unchanged) is the *only* place a capability's current
    lifecycle status is derived, for every stage from BUILT through
    VERIFIED. This module never re-derives it from raw stage results,
    and never second-guesses `ApprovalManager`/`CapabilitySystem`
    itself - it passes the same `approval_manager` through unchanged
    (constructor-supplied, or explicitly passed per call) and never
    calls `approve`/`reject`/`register`/`set_enabled` on it.
  - `self_upgrade.capability_creation_plan.build_capability_creation_plan`
    (Prompt 359, unchanged) and `self_upgrade.self_upgrade_request.
    SelfUpgradeRequest` (Prompt 357, unchanged) supply the *only* two
    "before a build_result even exists" states this coordinator
    reports on (ANALYZE / BUILD) - both read verbatim from a caller-
    supplied `CapabilityCreationPlan` dict / `SelfUpgradeRequest`
    (or its `to_dict()`), never re-run or re-validated a second way.
  - `self_upgrade.capability_evaluation.EVAL_NEEDS_CORRECTION` (Prompt
    366, unchanged) is the one, existing signal this module reads to
    tell "tests failed, but there is a correctable error" (-> CORRECT)
    apart from any other kind of FAILED - it is read straight off the
    `test_evaluation` argument this module already receives (the exact
    same one `build_capability_lifecycle_state` is given), never
    recomputed.
  - `self_upgrade.capability_registration_preparation._non_blank`
    (unchanged) is the one existing "is this a real, non-blank value"
    check, reused instead of a second one.

TARGET FLOW / decision vocabulary (`decision`, exactly one of
`ALL_COORDINATOR_DECISIONS`), produced by one fixed set of rules -
never a stage result, a test result, or a guess:

    ANALYZE                        <- a `self_upgrade_request` was
                                       supplied (and no `creation_plan`
                                       or later-stage evidence yet):
                                       REQUESTED / ANALYZING.
    BUILD                          <- a `creation_plan` was supplied
                                       (and no `build_result` yet):
                                       READY.
    VALIDATE                       <- lifecycle BUILT.
    TEST                           <- lifecycle VALIDATED.
    CORRECT                        <- lifecycle FAILED *and* the
                                       supplied `test_evaluation`
                                       itself reports NEEDS_CORRECTION -
                                       the one, existing controlled
                                       correction path
                                       (capability_correction_analysis /
                                       _apply / _verification, Prompts
                                       367-369) is what handles this
                                       next, never this module.
    VERSION                        <- lifecycle TESTED.
    WAIT_FOR_APPROVAL               <- lifecycle VERSIONED, or
                                       PENDING_APPROVAL with no
                                       registration request pending.
    PREPARE_REGISTRATION           <- lifecycle APPROVED with no
                                       registration request pending yet.
    WAIT_FOR_REGISTRATION_APPROVAL <- lifecycle APPROVED or
                                       PENDING_APPROVAL *with* a
                                       registration_request_id on
                                       record (a registration approval
                                       request exists and is still
                                       undecided - see
                                       capability_lifecycle.py's own
                                       note on why PENDING_APPROVAL and
                                       APPROVED can both still mean
                                       "registration decision pending";
                                       this module tells the two apart
                                       using the same
                                       registration_request_id the
                                       lifecycle state already carries,
                                       never a new lookup).
    REGISTER                       <- lifecycle READY_FOR_REGISTRATION.
    VERIFY_REGISTRATION            <- lifecycle REGISTERED.
    COMPLETED                      <- lifecycle VERIFIED, or a supplied
                                       `self_upgrade_request` itself
                                       already reports COMPLETED.
    BLOCKED                        <- lifecycle BLOCKED or REJECTED (a
                                       human rejection is reported as
                                       BLOCKED, exactly like
                                       `capability_lifecycle_decision`,
                                       Prompt 380, already does), a
                                       BLOCKED `creation_plan`, or a
                                       REJECTED `self_upgrade_request`.
    FAILED                          <- lifecycle FAILED (ordinary,
                                       non-correctable failure), or a
                                       `self_upgrade_request` itself
                                       already reports FAILED.
    ROLLED_BACK                    <- lifecycle ROLLED_BACK.
    INVALID                        <- lifecycle INVALID, a malformed/
                                       unrecognized `creation_plan` or
                                       `self_upgrade_request`, or a
                                       `lifecycle_state` this module
                                       cannot recognize at all.

SAFETY BOUNDARY (this module exists to enforce it, not just document
it - matches every requirement in the prompt this module was built
from):
  - A decision is never itself permission to perform the action it
    names. Nothing in this module calls `ApprovalManager.approve`/
    `.reject`/`.create_request`, `CapabilitySystem.register`/
    `set_enabled`, `register_approved_capability`,
    `verify_registered_capability`, a `CapabilityHandlerRegistry`
    handler, `execute`, `run`, or anything else that changes state.
  - A pending human approval always stops the decision at
    WAIT_FOR_APPROVAL or WAIT_FOR_REGISTRATION_APPROVAL - never
    inferred, never skipped.
  - A rejected approval always stops the decision at BLOCKED.
  - A failed validation (lifecycle BLOCKED/INVALID before TESTED) never
    reaches TEST/VERSION/CORRECT.
  - A failed test reaches CORRECT only through the existing,
    already-built correction path's own signal
    (EVAL_NEEDS_CORRECTION) - this module never proposes, applies, or
    verifies a correction itself.
  - VERIFIED is always reported as COMPLETED, never as an activation -
    there is no ACTIVE decision anywhere in `ALL_COORDINATOR_DECISIONS`,
    and nothing here can produce one.
  - This coordinator is deterministic (same inputs -> same decision,
    always), holds no mutable state of its own beyond the optional
    `approval_manager` reference it was constructed with, and is
    called explicitly, once, per decision - there is no loop, retry,
    or self-invocation anywhere in this module, so it cannot create a
    recursive or uncontrolled Self-Upgrade cycle.
  - This is not a second Self-Upgrade system: every stage it reads
    from remains the one, existing implementation of that stage: this
    module adds no new build, test, approval, or registration logic of
    its own.

Never raises: any malformed input is reported as an INVALID decision
with a non-empty `errors`, never as an exception.
"""

from self_upgrade.capability_creation_plan import (
    STATUS_READY as PLAN_STATUS_READY,
    STATUS_BLOCKED as PLAN_STATUS_BLOCKED,
    STATUS_INVALID as PLAN_STATUS_INVALID,
)
from self_upgrade.capability_evaluation import EVAL_NEEDS_CORRECTION
from self_upgrade.capability_lifecycle import (
    build_capability_lifecycle_state,
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
from self_upgrade.capability_registration_preparation import _non_blank
from self_upgrade.self_upgrade_request import (
    STATUS_REQUESTED as REQUEST_STATUS_REQUESTED,
    STATUS_ANALYZING as REQUEST_STATUS_ANALYZING,
    STATUS_COMPLETED as REQUEST_STATUS_COMPLETED,
    STATUS_FAILED as REQUEST_STATUS_FAILED,
    STATUS_REJECTED as REQUEST_STATUS_REJECTED,
    ALL_STATUSES as ALL_REQUEST_STATUSES,
)

DECISION_ANALYZE = "ANALYZE"
DECISION_BUILD = "BUILD"
DECISION_VALIDATE = "VALIDATE"
DECISION_TEST = "TEST"
DECISION_CORRECT = "CORRECT"
DECISION_VERSION = "VERSION"
DECISION_WAIT_FOR_APPROVAL = "WAIT_FOR_APPROVAL"
DECISION_PREPARE_REGISTRATION = "PREPARE_REGISTRATION"
DECISION_WAIT_FOR_REGISTRATION_APPROVAL = "WAIT_FOR_REGISTRATION_APPROVAL"
DECISION_REGISTER = "REGISTER"
DECISION_VERIFY_REGISTRATION = "VERIFY_REGISTRATION"
DECISION_COMPLETED = "COMPLETED"
DECISION_BLOCKED = "BLOCKED"
DECISION_FAILED = "FAILED"
DECISION_ROLLED_BACK = "ROLLED_BACK"
DECISION_INVALID = "INVALID"

ALL_COORDINATOR_DECISIONS = (
    DECISION_ANALYZE,
    DECISION_BUILD,
    DECISION_VALIDATE,
    DECISION_TEST,
    DECISION_CORRECT,
    DECISION_VERSION,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_PREPARE_REGISTRATION,
    DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
    DECISION_REGISTER,
    DECISION_VERIFY_REGISTRATION,
    DECISION_COMPLETED,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)

# Decisions that never perform, permit, or imply any registration,
# activation, or execution on their own - listed here only as a single,
# explicit, importable source of truth for tests/callers, exactly like
# `capability_lifecycle_decision.NON_ACTIONABLE_DECISIONS`. Not used by
# `build_self_upgrade_lifecycle_decision` itself.
NON_ACTIONABLE_DECISIONS = (
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
    DECISION_BLOCKED,
    DECISION_FAILED,
    DECISION_ROLLED_BACK,
    DECISION_INVALID,
)

# The fixed status -> decision table for every lifecycle status this
# module does NOT need extra context to resolve (see module docstring
# for FAILED / APPROVED / PENDING_APPROVAL, handled separately below).
_LIFECYCLE_STATUS_TO_DECISION = {
    LIFECYCLE_BUILT: DECISION_VALIDATE,
    LIFECYCLE_VALIDATED: DECISION_TEST,
    LIFECYCLE_TESTED: DECISION_VERSION,
    LIFECYCLE_VERSIONED: DECISION_WAIT_FOR_APPROVAL,
    LIFECYCLE_READY_FOR_REGISTRATION: DECISION_REGISTER,
    LIFECYCLE_REGISTERED: DECISION_VERIFY_REGISTRATION,
    LIFECYCLE_VERIFIED: DECISION_COMPLETED,
    LIFECYCLE_BLOCKED: DECISION_BLOCKED,
    LIFECYCLE_REJECTED: DECISION_BLOCKED,
    LIFECYCLE_ROLLED_BACK: DECISION_ROLLED_BACK,
    LIFECYCLE_INVALID: DECISION_INVALID,
}

# Statuses handled with extra context instead of the fixed table above:
# FAILED (CORRECT vs FAILED, from test_evaluation), APPROVED and
# PENDING_APPROVAL (WAIT_FOR_REGISTRATION_APPROVAL vs
# PREPARE_REGISTRATION/WAIT_FOR_APPROVAL, from registration_request_id).
_SPECIAL_CASED_STATUSES = (LIFECYCLE_FAILED, LIFECYCLE_APPROVED, LIFECYCLE_PENDING_APPROVAL)

# Defensive, module-load-time check: every lifecycle status Prompt 379
# recognizes must be resolvable here - either through the fixed table
# or through one of the special-cased statuses above - and nothing
# here may invent a status Prompt 379 does not itself recognize.
assert set(_LIFECYCLE_STATUS_TO_DECISION) | set(_SPECIAL_CASED_STATUSES) == \
    set(ALL_LIFECYCLE_STATUSES)

_REASONS = {
    DECISION_ANALYZE: (
        "A SelfUpgradeRequest has been captured but not yet analyzed; "
        "AdaptivePlanAnalyzer.analyze_self_upgrade_request runs next."),
    DECISION_BUILD: (
        "The request has been analyzed into a READY CapabilityCreationPlan; "
        "the CapabilityBuilder runs next."),
    DECISION_VALIDATE: "The capability was built; its generated source is validated next.",
    DECISION_TEST: "The generated capability source passed validation; its tests run next.",
    DECISION_CORRECT: (
        "The capability's tests failed with a correctable error; the existing "
        "controlled correction path (analysis / apply / verification) runs next."),
    DECISION_VERSION: "The capability's tests passed; a version snapshot is taken next.",
    DECISION_WAIT_FOR_APPROVAL: (
        "An approval request is waiting on an explicit human decision. This "
        "coordinator never infers approval; it only waits."),
    DECISION_PREPARE_REGISTRATION: (
        "A human explicitly approved the capability, but registration has not "
        "been prepared, planned, or requested yet."),
    DECISION_WAIT_FOR_REGISTRATION_APPROVAL: (
        "A registration approval request is waiting on an explicit human "
        "decision. This coordinator never infers approval; it only waits."),
    DECISION_REGISTER: "Registration was explicitly approved; registration runs next.",
    DECISION_VERIFY_REGISTRATION: (
        "The capability is registered (disabled) but not yet verified; "
        "verification runs next. It is not activated or executed."),
    DECISION_COMPLETED: (
        "The registration was verified against the approved registration "
        "information. This is not activation; nothing here executes the "
        "capability."),
    DECISION_BLOCKED: "The lifecycle is blocked, or was rejected by a human.",
    DECISION_FAILED: "A lifecycle stage failed with nothing usable to correct from.",
    DECISION_ROLLED_BACK: "The change behind this capability was rolled back to its previous version.",
    DECISION_INVALID: "The supplied state is invalid, malformed, or missing.",
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


def _as_dict(value):
    """A plain dict for `value`, using its own `to_dict()` when it has
    one (e.g. a real `SelfUpgradeRequest` instance) - never a guess at
    its shape otherwise."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return value if isinstance(value, dict) else None


def _judge_creation_plan(capability_name, creation_plan):
    """Returns (decision, reason, errors, resolved_capability_name)."""
    if not isinstance(creation_plan, dict):
        return (DECISION_INVALID, "creation_plan must be a CapabilityCreationPlan dict.",
                ["creation_plan must be a CapabilityCreationPlan dict."], capability_name)

    name = creation_plan.get("capability_name") or capability_name
    status = creation_plan.get("status")
    blockers = list(creation_plan.get("blockers") or [])

    if status == PLAN_STATUS_READY:
        return (DECISION_BUILD, _REASONS[DECISION_BUILD], [], name)
    if status == PLAN_STATUS_BLOCKED:
        return (DECISION_BLOCKED,
                "The CapabilityCreationPlan is BLOCKED; required information is missing.",
                [b.get("description") if isinstance(b, dict) else b for b in blockers], name)
    if status == PLAN_STATUS_INVALID:
        return (DECISION_INVALID, "The CapabilityCreationPlan is INVALID.",
                [b.get("description") if isinstance(b, dict) else b for b in blockers], name)
    return (DECISION_INVALID, f"creation_plan status {status!r} is not recognized.",
            [f"creation_plan status {status!r} is not recognized."], name)


def _judge_self_upgrade_request(capability_name, self_upgrade_request):
    """Returns (decision, reason, errors, resolved_capability_name)."""
    request = _as_dict(self_upgrade_request)
    if request is None:
        return (DECISION_INVALID, "self_upgrade_request must be a SelfUpgradeRequest or dict.",
                ["self_upgrade_request must be a SelfUpgradeRequest or dict."], capability_name)

    name = request.get("requested_capability") or capability_name
    status = request.get("status")

    if status not in ALL_REQUEST_STATUSES:
        return (DECISION_INVALID, f"self_upgrade_request status {status!r} is not recognized.",
                [f"self_upgrade_request status {status!r} is not recognized."], name)
    if status in (REQUEST_STATUS_REQUESTED, REQUEST_STATUS_ANALYZING):
        return (DECISION_ANALYZE, _REASONS[DECISION_ANALYZE], [], name)
    if status == REQUEST_STATUS_REJECTED:
        return (DECISION_BLOCKED, "The self-upgrade request was rejected by a human.",
                ["The self-upgrade request was rejected by a human."], name)
    if status == REQUEST_STATUS_FAILED:
        return (DECISION_FAILED, "The self-upgrade request already reports FAILED.",
                ["The self-upgrade request already reports FAILED."], name)
    # status == REQUEST_STATUS_COMPLETED
    return (DECISION_COMPLETED, "The self-upgrade request already reports COMPLETED.", [], name)


def _judge_lifecycle_state(lifecycle_state, test_evaluation):
    """Returns (decision, reason, errors) from an already-derived
    CapabilityLifecycleState - see module docstring for the special
    cases (FAILED/CORRECT, APPROVED+PENDING_APPROVAL/registration)."""
    status = lifecycle_state.get("current_status")
    errors = list(lifecycle_state.get("errors") or [])

    if status == LIFECYCLE_FAILED:
        if isinstance(test_evaluation, dict) \
                and test_evaluation.get("evaluation_status") == EVAL_NEEDS_CORRECTION:
            return (DECISION_CORRECT, _REASONS[DECISION_CORRECT], errors)
        return (DECISION_FAILED, _REASONS[DECISION_FAILED], errors)

    if status in (LIFECYCLE_APPROVED, LIFECYCLE_PENDING_APPROVAL):
        if _non_blank(lifecycle_state.get("registration_request_id")):
            return (DECISION_WAIT_FOR_REGISTRATION_APPROVAL,
                    _REASONS[DECISION_WAIT_FOR_REGISTRATION_APPROVAL], [])
        if status == LIFECYCLE_APPROVED:
            return (DECISION_PREPARE_REGISTRATION, _REASONS[DECISION_PREPARE_REGISTRATION], [])
        return (DECISION_WAIT_FOR_APPROVAL, _REASONS[DECISION_WAIT_FOR_APPROVAL], [])

    if status not in _LIFECYCLE_STATUS_TO_DECISION:
        return (DECISION_INVALID, f"Unrecognized lifecycle current_status: {status!r}.",
                [f"current_status {status!r} is not one of ALL_LIFECYCLE_STATUSES."])

    decision = _LIFECYCLE_STATUS_TO_DECISION[status]
    carry_errors = decision in (DECISION_BLOCKED, DECISION_ROLLED_BACK, DECISION_INVALID)
    return (decision, _REASONS[decision], errors if carry_errors else [])


def build_self_upgrade_lifecycle_decision(
        capability_name=None, self_upgrade_request=None, creation_plan=None,
        build_result=None, apply_request=None, test_evaluation=None,
        human_approval_request=None, approval_manager=None, approval_request_id=None,
        registration_request_id=None, registration_plan=None, registration_result=None,
        verification_result=None, rollback_result=None):
    """Inspect the current Self-Upgrade lifecycle context and determine
    the next valid `SelfUpgradeLifecycleDecision`. See module docstring
    for the full decision vocabulary and the safety boundary. Read-only
    and side-effect free: never activates, executes, approves, rejects,
    registers, builds, tests, corrects, versions, or modifies anything;
    never raises.

    Arguments:
      capability_name          - optional; resolved from
                                  `creation_plan`/`self_upgrade_request`
                                  when not given.
      self_upgrade_request     - a `self_upgrade.self_upgrade_request.
                                  SelfUpgradeRequest` (or its
                                  `to_dict()`/an equivalent dict) - only
                                  consulted when `creation_plan` and
                                  `build_result` are both absent.
      creation_plan             - a `self_upgrade.
                                  capability_creation_plan.
                                  build_capability_creation_plan` result -
                                  only consulted when `build_result` is
                                  absent.
      Every other argument is passed straight through, unchanged, to
      `self_upgrade.capability_lifecycle.build_capability_lifecycle_state`
      (Prompt 379) - see that function's own docstring for what each
      one is and which stage's result it expects.

    Always returns a `SelfUpgradeLifecycleDecision` dict with exactly:
        capability_name, lifecycle_status (the underlying
        CapabilityLifecycleState's current_status, or None when the
        decision was reached before one was derived), decision (one of
        `ALL_COORDINATOR_DECISIONS`), reason, errors, lifecycle_state
        (the full CapabilityLifecycleState this decision was derived
        from, or None for an ANALYZE/BUILD/pre-pipeline decision).
    """
    try:
        return _decide(
            capability_name, self_upgrade_request, creation_plan, build_result, apply_request,
            test_evaluation, human_approval_request, approval_manager, approval_request_id,
            registration_request_id, registration_plan, registration_result,
            verification_result, rollback_result)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(
            capability_name, None, DECISION_INVALID,
            "Unexpected error while deciding the self-upgrade lifecycle decision.",
            [f"Unexpected error: {type(exc).__name__}: {exc}"], None)


def _decide(capability_name, self_upgrade_request, creation_plan, build_result, apply_request,
            test_evaluation, human_approval_request, approval_manager, approval_request_id,
            registration_request_id, registration_plan, registration_result,
            verification_result, rollback_result):
    # Pre-pipeline stages: nothing has been built yet, so this
    # coordinator never consults build_capability_lifecycle_state at
    # all - there is no build_result (or anything later) for it to
    # read yet.
    if build_result is None:
        if creation_plan is not None:
            decision, reason, errors, name = _judge_creation_plan(capability_name, creation_plan)
            return _result(name, None, decision, reason, errors, None)
        if self_upgrade_request is not None:
            decision, reason, errors, name = _judge_self_upgrade_request(
                capability_name, self_upgrade_request)
            return _result(name, None, decision, reason, errors, None)

    resolved_name = capability_name
    if resolved_name is None and isinstance(creation_plan, dict):
        resolved_name = creation_plan.get("capability_name")
    if resolved_name is None:
        request = _as_dict(self_upgrade_request)
        if request is not None:
            resolved_name = request.get("requested_capability")

    lifecycle_state = build_capability_lifecycle_state(
        resolved_name, build_result=build_result, apply_request=apply_request,
        test_evaluation=test_evaluation, human_approval_request=human_approval_request,
        approval_manager=approval_manager, approval_request_id=approval_request_id,
        registration_request_id=registration_request_id, registration_plan=registration_plan,
        registration_result=registration_result, verification_result=verification_result,
        rollback_result=rollback_result)

    decision, reason, errors = _judge_lifecycle_state(lifecycle_state, test_evaluation)
    return _result(
        lifecycle_state.get("capability_name"), lifecycle_state.get("current_status"),
        decision, reason, errors, lifecycle_state)


class SelfUpgradeLifecycleCoordinator:
    """Thin, stateless-except-for-its-collaborator wrapper around
    `build_self_upgrade_lifecycle_decision` - the same "small class
    wired to the collaborator it reads from, module function does the
    real work" shape already used by `execution.
    plan_execution_coordinator.PlanExecutionCoordinator` and by
    `AgentLoop`'s own Self-Upgrade wrapper methods (e.g.
    `AgentLoop.get_capability_lifecycle_decision`).

    Holds only an optional `approval_manager` reference so repeated
    calls don't require passing it every time - never a private
    registry, approval store, or version system of its own. Never
    mutates, approves, registers, or executes anything; see module
    docstring for the full safety boundary."""

    def __init__(self, approval_manager=None):
        self.approval_manager = approval_manager

    def decide(
            self, capability_name=None, self_upgrade_request=None, creation_plan=None,
            build_result=None, apply_request=None, test_evaluation=None,
            human_approval_request=None, approval_manager=None, approval_request_id=None,
            registration_request_id=None, registration_plan=None, registration_result=None,
            verification_result=None, rollback_result=None):
        """Determine the next valid lifecycle action. See
        `build_self_upgrade_lifecycle_decision` for the full argument
        and return-value documentation. `approval_manager`, if not
        given here, falls back to the one this coordinator was
        constructed with (either may be `None`)."""
        manager = approval_manager if approval_manager is not None else self.approval_manager
        return build_self_upgrade_lifecycle_decision(
            capability_name=capability_name, self_upgrade_request=self_upgrade_request,
            creation_plan=creation_plan, build_result=build_result, apply_request=apply_request,
            test_evaluation=test_evaluation, human_approval_request=human_approval_request,
            approval_manager=manager, approval_request_id=approval_request_id,
            registration_request_id=registration_request_id, registration_plan=registration_plan,
            registration_result=registration_result, verification_result=verification_result,
            rollback_result=rollback_result)

    # ------------------------------------------------------------------
    # Persistent execution context integration (Prompt 382) - small on
    # purpose. See self_upgrade.self_upgrade_execution_context for the
    # `SelfUpgradeExecutionContext` model/store this wraps, and for the
    # full context rules. Neither method here changes anything about
    # `decide`/`build_self_upgrade_lifecycle_decision` above; both are
    # thin additions that let a caller resume across a restart instead
    # of re-supplying every raw stage result again.
    # ------------------------------------------------------------------
    def resume(self, context):
        """The next action a persisted `context` (self_upgrade.
        self_upgrade_execution_context.SelfUpgradeExecutionContext)
        already recorded, read straight off it - no stage result is
        re-supplied, re-derived, or re-validated, so resuming never
        restarts a stage that already completed. Read-only: never
        calls `decide`, an `ApprovalManager`, or a `CapabilitySystem`.

        Returns the same `SelfUpgradeLifecycleDecision` shape `decide`
        returns, or `None` if `context` is not a valid execution
        context or has no recorded decision yet (a freshly-built
        context - call `advance` with its first available input, e.g.
        a `self_upgrade_request`, to get one)."""
        if not isinstance(context, dict) or not context.get("upgrade_request_id"):
            return None
        action = context.get("current_action")
        if action is None:
            return None
        lifecycle_state = context.get("current_lifecycle_state")
        return _result(
            context.get("capability_name"),
            lifecycle_state.get("current_status") if isinstance(lifecycle_state, dict) else None,
            action, _REASONS.get(action, "Resumed from a persisted execution context."),
            [], lifecycle_state)

    def advance(
            self, context, capability_name=None, self_upgrade_request=None, creation_plan=None,
            build_result=None, apply_request=None, test_evaluation=None,
            human_approval_request=None, approval_manager=None, approval_request_id=None,
            registration_request_id=None, registration_plan=None, registration_result=None,
            verification_result=None, rollback_result=None, build_spec=None,
            implementation_spec=None, error=None):
        """Compute the next `decide(...)` decision from the given stage
        results and fold it into `context` via
        `self_upgrade_execution_context.apply_successful_transition`
        (which itself routes an `INVALID` decision to a failed
        transition - context rule 3). If `error` is given directly
        (the action itself failed for a reason no stage result
        captures, e.g. an unexpected exception), `decide` is never
        called at all and the previous successful state in `context` is
        preserved unchanged apart from that error being recorded.

        Returns `(new_context, decision)` - `decision` is `None` when
        `error` short-circuited the call. Never mutates `context` in
        place; never raises. `context` should usually come from
        `self_upgrade_execution_context.SelfUpgradeExecutionContextStore
        .get_or_create`, and the returned `new_context` still needs an
        explicit `.save(new_context)` call to persist it - this method
        does not touch storage itself."""
        # Local import: avoids a module-load cycle (self_upgrade_execution_context
        # imports DECISION_INVALID from this module).
        from self_upgrade.self_upgrade_execution_context import (
            apply_failed_transition, apply_successful_transition,
        )

        if error is not None:
            return apply_failed_transition(context, error), None

        decision = self.decide(
            capability_name=capability_name or (context or {}).get("capability_name"),
            self_upgrade_request=self_upgrade_request, creation_plan=creation_plan,
            build_result=build_result, apply_request=apply_request,
            test_evaluation=test_evaluation, human_approval_request=human_approval_request,
            approval_manager=approval_manager, approval_request_id=approval_request_id,
            registration_request_id=registration_request_id, registration_plan=registration_plan,
            registration_result=registration_result, verification_result=verification_result,
            rollback_result=rollback_result)
        new_context = apply_successful_transition(
            context, decision, build_spec=build_spec, implementation_spec=implementation_spec)
        return new_context, decision
