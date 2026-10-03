"""
Execution - Plan Execution Coordinator
==========================================
`PlanExecutionCoordinator` is a small, read-only inspection layer that
sits *above* `PreflightValidator` (execution/preflight.py) and
`CapabilityHandlerRegistry` (execution/capability_handlers.py):

    PLAN (planning/plan.py) -> PlanExecutionCoordinator
        -> PreflightValidator (per READY step)
        -> CapabilityHandlerRegistry.check_execution_readiness (per
           READY step that requires capabilities)
        -> "here is the next step that could actually run, or here is
           why none can right now"

This module answers exactly one question - "which step, if any, is
both READY and actually executable right now?" - and a second,
aggregate version of it - "what does this whole plan's execution state
look like?" It never answers *how* to run that step, and it never runs
anything itself. Every rule this module applies (is a step's status
READY, are its dependencies resolved, are its required capabilities
available, is a handler registered for each of them) already exists
somewhere else in this project - PlanManager's dependency/capability
logic (planning/plan_manager.py), PreflightValidator's per-step check
(execution/preflight.py), and CapabilityHandlerRegistry's own
readiness report (execution/capability_handlers.py) - so this module
never re-derives any of them; it only calls into those three and
reads their already-structured results.

Nothing in this module:
  - calls a handler, a capability, or anything registered in
    CapabilityHandlerRegistry/ExecutableCapabilityRegistry;
  - modifies a file, imports/execs/evals a string as code, or shells
    out to anything;
  - opens a network connection;
  - registers, enables, disables, or installs a capability;
  - writes a PlanStep's `status` (or anything else about it) -
    PlanManager.update_step_status (planning/plan_manager.py) remains
    the one and only place a step's status is ever changed, and this
    module never calls it.
This is strictly a read-only "which step is next, and is it actually
runnable" query - deciding *to* run it, and actually running it, stay
exactly where they already are: a caller (eventually the Execution
Engine's own orchestration, not built yet) that receives this
coordinator's answer and chooses what to do with it.
"""

from planning.plan import (
    STATUS_READY, STATUS_BLOCKED, STATUS_COMPLETED, STATUS_FAILED,
)
from planning.plan_manager import PlanManager
from .preflight import PreflightValidator
from .capability_handlers import CapabilityHandlerRegistry
from .executable_registry import ExecutableCapabilityRegistry


class PlanExecutionCoordinator:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/ExecutionEngine's own notes). Constructed with a
    reference to the PlanManager whose plans/steps it inspects - same
    "wired to the manager it reads from" relationship ExecutionEngine
    already has (see execution/execution_engine.py) - plus, exactly
    like ExecutionEngine, an optional CapabilityHandlerRegistry and
    ExecutableCapabilityRegistry it can share with an existing engine
    rather than maintaining a second, disagreeing set of registered
    handlers. If either is omitted, this coordinator creates its own
    private, empty one (same default ExecutionEngine already applies)
    - a step requiring capabilities is then correctly reported as
    having a missing handler, since nothing has been registered
    anywhere for it to find.

    Owns a single `PreflightValidator`, wired to the same PlanManager,
    for exactly the same reason ExecutionEngine owns one: one object
    exercising the one existing implementation of preflight checks,
    never a second copy of that logic here."""

    def __init__(self, plan_manager, capability_handlers=None, executable_capabilities=None):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("PlanExecutionCoordinator requires a PlanManager instance.")
        if capability_handlers is not None and not isinstance(
            capability_handlers, CapabilityHandlerRegistry
        ):
            raise TypeError(
                "PlanExecutionCoordinator's capability_handlers must be a "
                "CapabilityHandlerRegistry instance."
            )
        if executable_capabilities is not None and not isinstance(
            executable_capabilities, ExecutableCapabilityRegistry
        ):
            raise TypeError(
                "PlanExecutionCoordinator's executable_capabilities must be an "
                "ExecutableCapabilityRegistry instance."
            )
        self._plan_manager = plan_manager
        self.preflight = PreflightValidator(plan_manager)
        self.capability_handlers = (
            capability_handlers if capability_handlers is not None
            else CapabilityHandlerRegistry()
        )
        self.executable_capabilities = (
            executable_capabilities if executable_capabilities is not None
            else ExecutableCapabilityRegistry()
        )

    # ------------------------------------------------------------------
    # Shared single-step executability check
    # ------------------------------------------------------------------
    def _step_executability(self, plan_id, step, capability_system):
        """Is this one, already-READY `step` actually executable right
        now? Returns `(executable: bool, reason: str)`. The single
        place both `get_next_ready_step` and `inspect_execution_state`
        ask this question, so the two methods can never disagree about
        what "executable" means.

        Reuses, never re-derives:
          - `self.preflight.validate_step` (execution/preflight.py)
            for status/dependency/capability-availability checks -
            the exact same check ExecutionEngine.execute_step already
            runs before calling a handler;
          - `self.capability_handlers.check_execution_readiness`
            (execution/capability_handlers.py), only when `step`
            actually has `required_capabilities`, for whether every
            one of them has both an available capability *and* a
            registered handler - the exact same check
            ExecutionEngine.execute_capability_step already runs.
        A step with no required capabilities never needs the second
        check at all - preflight alone (status READY, dependencies
        resolved, and, when `capability_system` is given, no *other*
        step-level capability problem) is sufficient, since
        `execute_step`'s own caller-supplied handler is a per-call
        argument this coordinator never receives or predicts."""
        preflight_result = self.preflight.validate_step(plan_id, step.step_id, capability_system)
        if not preflight_result.valid:
            failed = "; ".join(
                f"{fc['check']}: {fc['reason']}" for fc in preflight_result.failed_checks
            )
            return False, f"Preflight failed for step {step.step_id!r}: {failed}"

        if step.required_capabilities:
            readiness = self.capability_handlers.check_execution_readiness(
                step, capability_system, self.executable_capabilities
            )
            if not readiness.ready:
                problems = []
                if readiness.missing_capabilities:
                    problems.append(f"missing capabilities: {readiness.missing_capabilities!r}")
                if readiness.unavailable_capabilities:
                    problems.append(
                        f"unavailable capabilities: {readiness.unavailable_capabilities!r}"
                    )
                if readiness.missing_handlers:
                    problems.append(f"missing handlers: {readiness.missing_handlers!r}")
                return False, (
                    f"Capability readiness failed for step {step.step_id!r}: "
                    + "; ".join(problems)
                )

        return True, f"Step {step.step_id!r} is READY and executable."

    # ------------------------------------------------------------------
    # Next-step selection
    # ------------------------------------------------------------------
    def _next_step_result(self, plan_id, step, executable, reason, warnings):
        """The one place that shapes a get_next_ready_step return
        value, so a found step and a "nothing executable" outcome both
        come back in exactly the same structured shape."""
        return {
            "plan_id": plan_id,
            "step_id": step.step_id if step is not None else None,
            "step": step,
            "executable": bool(executable),
            "reason": reason,
            "warnings": list(warnings),
        }

    def get_next_ready_step(self, plan_id, capability_system=None):
        """Inspect `plan_id`'s steps, in their existing `plan.steps`
        order, and return the *first* one that is both currently
        STATUS_READY and actually executable (see
        `_step_executability` above) right now.

        Never raises for an unknown `plan_id` - same "a query that
        should always have a structured answer" convention
        `PreflightValidator.validate_step` already follows for an
        unknown plan/step - since a caller may reasonably poll this
        repeatedly without first confirming the plan still exists.

        Considers only steps whose *current* status (as PlanManager
        already tracks it - never recomputed or second-guessed here)
        is STATUS_READY; PENDING, BLOCKED, IN_PROGRESS, COMPLETED, and
        FAILED steps are always skipped, in that they're never even
        passed to `_step_executability`. Among READY steps, one that
        fails preflight or capability readiness is skipped too (its
        reason recorded in `warnings`) and the search continues to the
        next READY step in order - the first one that passes both
        checks is returned immediately, so a later READY step's own
        problems (if any) are never even evaluated.

        Read-only throughout: never calls a handler or a capability,
        never writes a PlanStep's status, never registers/enables/
        installs anything, and never uses eval()/exec()/subprocess/
        shell/network access - see module docstring.

        Returns a dict:
            {
                "plan_id": plan_id,
                "step_id": step_id or None,   # the chosen step, if any
                "step": PlanStep or None,     # the actual object, for
                                               # a caller that wants it
                                               # directly rather than
                                               # looking it up again
                "executable": bool,           # True only when a step
                                               # was actually found
                "reason": str,                # why this step was
                                               # chosen, or why none was
                "warnings": [str, ...],       # one entry per READY
                                               # step that was skipped
                                               # before this result,
                                               # explaining why
            }
        """
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._next_step_result(
                plan_id, None, False, f"Unknown plan_id: {plan_id!r}.", [],
            )

        warnings = []
        for step in plan.steps:
            if step.status != STATUS_READY:
                continue
            executable, reason = self._step_executability(plan_id, step, capability_system)
            if executable:
                return self._next_step_result(plan_id, step, True, reason, warnings)
            warnings.append(reason)

        if warnings:
            reason = "One or more steps are READY, but none is currently executable."
        else:
            reason = f"No READY steps found in plan {plan_id!r}."
        return self._next_step_result(plan_id, None, False, reason, warnings)

    # ------------------------------------------------------------------
    # Whole-plan execution state
    # ------------------------------------------------------------------
    def inspect_execution_state(self, plan_id, capability_system=None):
        """A structured, whole-plan snapshot of where every step
        currently stands, plus which one (if any) `get_next_ready_step`
        would pick right now. Raises ValueError for an unknown
        `plan_id` - same convention as PlanManager's own whole-plan
        aggregations (`check_plan_readiness`/`check_plan_capabilities`
        - planning/plan_manager.py), since this, like those, computes
        something about a specific real plan rather than answering a
        single step-level query.

        Every count below is a simple, deterministic tally over
        `plan.steps` - no ordering/priority logic, no randomness, and
        no step is ever double-counted (each step has exactly one
        `status` at any moment, so it contributes to exactly one of
        `ready_steps`/`blocked_steps`/`completed_steps`/`failed_steps`,
        or to none of them if it's PENDING or IN_PROGRESS - this
        method reports only the statuses requirement 4 names).
        `executable_steps` is a *subset* of `ready_steps`: every READY
        step is checked with the exact same `_step_executability` used
        by `get_next_ready_step`, so the two methods can never
        disagree about which READY steps actually qualify.

        Returns a dict:
            {
                "plan_id": plan_id,
                "total_steps": int,
                "ready_steps": int,        # status == READY
                "executable_steps": int,   # READY *and* executable
                "blocked_steps": int,      # status == BLOCKED
                "completed_steps": int,    # status == COMPLETED
                "failed_steps": int,       # status == FAILED
                "next_step_id": step_id or None,  # from
                                                   # get_next_ready_step
                "warnings": [str, ...],
            }
        """
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            raise ValueError(
                f"Cannot inspect execution state for unknown plan_id: {plan_id!r}"
            )

        total_steps = len(plan.steps)
        ready_steps = 0
        executable_steps = 0
        blocked_steps = 0
        completed_steps = 0
        failed_steps = 0
        warnings = []

        for step in plan.steps:
            if step.status == STATUS_READY:
                ready_steps += 1
                executable, reason = self._step_executability(plan_id, step, capability_system)
                if executable:
                    executable_steps += 1
                else:
                    warnings.append(reason)
            elif step.status == STATUS_BLOCKED:
                blocked_steps += 1
            elif step.status == STATUS_COMPLETED:
                completed_steps += 1
            elif step.status == STATUS_FAILED:
                failed_steps += 1

        if total_steps == 0:
            warnings.append(f"Plan {plan_id!r} has no steps.")
        elif ready_steps > 0 and executable_steps == 0:
            warnings.append("One or more steps are READY, but none is currently executable.")

        next_result = self.get_next_ready_step(plan_id, capability_system)

        return {
            "plan_id": plan_id,
            "total_steps": total_steps,
            "ready_steps": ready_steps,
            "executable_steps": executable_steps,
            "blocked_steps": blocked_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "next_step_id": next_result["step_id"],
            "warnings": warnings,
        }
