"""
Self-Upgrade - Controlled Resume (Prompt 383)
================================================
`SelfUpgradeResumeManager` (and the module-level function it wraps,
`resume_self_upgrade`) answers exactly one question for one persisted
upgrade: *given what was already recorded, what is safe to do next -
and is it even safe to look?*

    SelfUpgradeExecutionContextStore.load(upgrade_request_id)  (Prompt 382)
        -> validate_execution_context(context)                (Prompt 382)
        -> SelfUpgradeLifecycleCoordinator.resume(context)     (Prompt 381/382)
        -> SelfUpgradeResumeDecision{upgrade_request_id, capability_name,
               resume_status, last_completed_action, decision, errors}

THIS MODULE ONLY REPORTS WHERE TO RESUME FROM. It never runs a stage,
never builds or generates anything, never approves or rejects an
approval request, never registers or verifies anything in the live
Capability Registry, and never activates or executes a capability (or
any generated code) - exactly the same boundary
`self_upgrade_lifecycle_coordinator` and `self_upgrade_execution_context`
already draw for themselves (see their module docstrings). Resuming is
read-only, start to finish: `load`, `validate_execution_context`, and
`SelfUpgradeLifecycleCoordinator.resume` are each already read-only, and
nothing in this module adds a write, an approval, a registration call,
or an execution anywhere in that chain. Calling `resume` twice, or a
hundred times, in a row for the same persisted context always returns
the same answer and changes nothing - the same "no automatic retry, no
duplicate registration/approval/snapshot" idempotency the prompt this
module was built from requires falls straight out of that.

Reuses, never duplicates:
  - `self_upgrade.self_upgrade_execution_context
    .SelfUpgradeExecutionContextStore.load` (Prompt 382, unchanged) is
    the *only* way this module reads a persisted context. No second
    storage lookup, no direct `memory.get_state` call here.
  - `self_upgrade.self_upgrade_execution_context.validate_execution_context`
    (Prompt 382, unchanged) is the *only* consistency check this module
    runs - it is never re-implemented, loosened, or bypassed here, and
    an inconsistent context is never silently repaired (see
    `RESUME_STATUS_INVALID_CONTEXT` below).
  - `self_upgrade.self_upgrade_lifecycle_coordinator
    .SelfUpgradeLifecycleCoordinator.resume` (Prompt 382, unchanged) is
    the *only* place "what is the next valid action" is derived from a
    context. This module never re-derives it from raw stage results,
    never second-guesses the coordinator's decision table, and never
    calls `.decide`/`.advance` (which would require fresh stage
    results this module was never given, and which perform no action
    themselves either - see that module's own safety boundary).

RESUME STATUS (`resume_status`, exactly one of `ALL_RESUME_STATUSES`):
    RESUMED           <- a valid, consistent context was found and the
                         coordinator reports a recorded next action -
                         `decision` carries that action. Every lifecycle
                         status maps straight through to the matching
                         decision the coordinator already reports for
                         it (WAIT_FOR_APPROVAL for PENDING_APPROVAL,
                         BLOCKED for REJECTED/BLOCKED, FAILED/CORRECT
                         for FAILED, ROLLED_BACK for ROLLED_BACK,
                         VERIFY_REGISTRATION for REGISTERED, COMPLETED
                         for VERIFIED, and so on) - this module adds no
                         special-case behavior of its own for any of
                         them; the existing coordinator, unmodified,
                         already reports the right thing.
    NOT_FOUND         <- no persisted context exists for the given
                         `upgrade_request_id`.
    NOT_YET_STARTED   <- a context exists and is consistent, but no
                         lifecycle decision has been recorded on it yet
                         (`current_action` is still `None`) - there is
                         nothing to resume *from*; the caller's next
                         step is an ordinary first `.advance(...)` call
                         with the request's first available input (a
                         `SelfUpgradeRequest` or `CapabilityCreationPlan`),
                         not a resume.
    INVALID_CONTEXT   <- the persisted context failed
                         `validate_execution_context` - `errors` carries
                         every problem found. Never repaired, never
                         partially resumed from.

Never raises: any malformed `upgrade_request_id`, missing context, or
inconsistent context is reported through `resume_status`/`errors`,
never as an exception.
"""

from self_upgrade.self_upgrade_execution_context import validate_execution_context

RESUME_STATUS_RESUMED = "RESUMED"
RESUME_STATUS_NOT_FOUND = "NOT_FOUND"
RESUME_STATUS_NOT_YET_STARTED = "NOT_YET_STARTED"
RESUME_STATUS_INVALID_CONTEXT = "INVALID_CONTEXT"

ALL_RESUME_STATUSES = (
    RESUME_STATUS_RESUMED,
    RESUME_STATUS_NOT_FOUND,
    RESUME_STATUS_NOT_YET_STARTED,
    RESUME_STATUS_INVALID_CONTEXT,
)


def _result(upgrade_request_id, capability_name, resume_status,
            last_completed_action=None, decision=None, errors=None):
    return {
        "upgrade_request_id": upgrade_request_id,
        "capability_name": capability_name,
        "resume_status": resume_status,
        "last_completed_action": last_completed_action,
        "decision": decision,
        "errors": list(errors or []),
    }


def resume_self_upgrade(upgrade_request_id, store, coordinator):
    """Load, validate, and resume the persisted context for
    `upgrade_request_id`. See the module docstring for the full
    `resume_status` vocabulary and the read-only guarantee.

    Arguments:
      upgrade_request_id - the `SelfUpgradeRequest.request_id`/
                            `SelfUpgradeExecutionContext
                            .upgrade_request_id` to resume.
      store               - a `self_upgrade.self_upgrade_execution_context
                            .SelfUpgradeExecutionContextStore` (or
                            anything exposing the same `.load(...)`).
      coordinator         - a `self_upgrade.self_upgrade_lifecycle_coordinator
                            .SelfUpgradeLifecycleCoordinator` (or
                            anything exposing the same `.resume(...)`).

    Always returns a `SelfUpgradeResumeDecision` dict with exactly:
        upgrade_request_id, capability_name, resume_status (one of
        `ALL_RESUME_STATUSES`), last_completed_action, decision (the
        `SelfUpgradeLifecycleDecision` the coordinator reported, or
        `None` when there is nothing to report), errors.

    Never raises; never mutates the store, the coordinator, or
    anything either of them wraps.
    """
    try:
        return _resume(upgrade_request_id, store, coordinator)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(
            upgrade_request_id, None, RESUME_STATUS_INVALID_CONTEXT, errors=[
                f"Unexpected error while resuming: {type(exc).__name__}: {exc}"])


def _resume(upgrade_request_id, store, coordinator):
    context = store.load(upgrade_request_id)
    if context is None:
        return _result(
            upgrade_request_id, None, RESUME_STATUS_NOT_FOUND,
            errors=[f"No persisted execution context found for "
                    f"upgrade_request_id={upgrade_request_id!r}."])

    errors = validate_execution_context(context)
    if errors:
        return _result(
            upgrade_request_id, context.get("capability_name"),
            RESUME_STATUS_INVALID_CONTEXT,
            last_completed_action=context.get("last_completed_action"), errors=errors)

    decision = coordinator.resume(context)
    if decision is None:
        return _result(
            upgrade_request_id, context.get("capability_name"), RESUME_STATUS_NOT_YET_STARTED,
            last_completed_action=context.get("last_completed_action"))

    return _result(
        upgrade_request_id, context.get("capability_name"), RESUME_STATUS_RESUMED,
        last_completed_action=context.get("last_completed_action"), decision=decision)


class SelfUpgradeResumeManager:
    """Thin, stateless-except-for-its-collaborators wrapper around
    `resume_self_upgrade` - the same "small class wired to the
    collaborators it reads from, module function does the real work"
    shape already used by `SelfUpgradeLifecycleCoordinator` itself.

    Holds only the `store`/`coordinator` references it was constructed
    with - never a private context cache, registry, or approval store
    of its own. Read-only: see module docstring for the full safety
    boundary."""

    def __init__(self, store, coordinator):
        self.store = store
        self.coordinator = coordinator

    def resume(self, upgrade_request_id):
        """Resume `upgrade_request_id` from its persisted execution
        context. See `resume_self_upgrade` for the full argument and
        return-value documentation."""
        return resume_self_upgrade(upgrade_request_id, self.store, self.coordinator)
