"""
Execution - Plan Execution Controller
=========================================
`PlanExecutionController` is the next, small layer directly on top of
the execution stack that already exists in this project:

    PLAN (planning/plan.py)
        -> PlanExecutionCoordinator.get_next_ready_step
           (execution/plan_execution_coordinator.py: "which READY step,
           if any, is actually executable right now?", read-only)
        -> [only if one was found] StepExecutionController.execute_step
           (execution/step_execution_controller.py: gate through
           StepExecutionPreparation, then run it through
           ExecutionEngine.execute_capability_step - unchanged)
        -> PlanManager.refresh_after_step_change (on success only)
        -> repeat, until nothing more can safely be done
        -> a single, structured whole-plan result dict

This module answers exactly one question - "run as much of this one,
already-existing Plan as can safely run right now, one step at a
time, and tell me exactly what happened" - and nothing broader than
that. It does not decide *how* to run a single step (that is already
`StepExecutionController`/`ExecutionEngine`'s job, reused unchanged),
does not decide *which* step is next-eligible (that is already
`PlanExecutionCoordinator`'s job, reused unchanged), and does not
create goals, plans, or capabilities of its own.

Every rule this module applies already exists somewhere else in this
project; this module never re-derives any of them, it only calls into
them, in order, and reads their already-structured results:

  - "does this plan exist at all" / "is it worth attempting" reuses
    `PlanManager.get_plan` and `PlanManager.check_plan_readiness`
    (planning/plan_manager.py);
  - "which READY step, if any, is actually executable right now"
    reuses `PlanExecutionCoordinator.get_next_ready_step`
    (execution/plan_execution_coordinator.py) - itself already built
    on `PreflightValidator`/`CapabilityHandlerRegistry`;
  - "prepare and run exactly this one step" reuses
    `StepExecutionController.execute_step`
    (execution/step_execution_controller.py) unchanged - preparation,
    the actual capability call, `ExecutionResult`/`ExecutionHistory`/
    `ExecutionEventLog` recording, and the step's own COMPLETED/FAILED
    status transition all continue to happen exactly where they
    already did;
  - "let dependents become READY after a successful step" reuses
    `PlanManager.refresh_after_step_change`.

Nothing in this module:
  - creates, installs, enables, or discovers a capability, or invents
    a handler for one - only capabilities/handlers a caller already
    registered ahead of time (via `CapabilityHandlerRegistry`/
    `ExecutableCapabilityRegistry`, the exact same objects
    `StepExecutionController`/`ExecutionEngine` already use) can ever
    run here;
  - creates a new `Plan`, a new `PlanStep`, or a new `Goal` - it only
    ever operates on a `plan_id` a caller already created via
    `PlanManager.create_plan`/`add_step`;
  - modifies an arbitrary file, imports/execs/evals a string as code,
    or shells out to anything;
  - opens a network connection, or calls an external AI API;
  - implements automatic retry - a FAILED step is left FAILED; a
    caller that wants to retry it still calls
    `ExecutionEngine.retry_step` directly, exactly as before this
    module existed;
  - executes a step whose current status is BLOCKED, FAILED,
    CANCELLED, or COMPLETED - `PlanExecutionCoordinator.
    get_next_ready_step` (reused, unmodified) only ever considers a
    step whose status is currently STATUS_READY.

Two safety limits this module itself is responsible for enforcing,
since neither `PlanExecutionCoordinator` nor `StepExecutionController`
has any notion of "a whole plan's execution run":
  - `max_steps_per_run` - a conservative, finite cap on how many steps
    one `execute_plan` call will ever execute, so a caller can never
    accidentally trigger an unbounded run;
  - cycle detection over the plan's own step-dependency graph, run
    once, before a single step is ever executed, so a cyclic plan is
    reported as a structured error rather than silently never
    terminating (a cycle could never actually cause an infinite loop
    here, since `get_next_ready_step` only ever returns a step whose
    dependencies are already resolved to COMPLETED - but this module
    checks and refuses up front regardless, so a cyclic plan is never
    even attempted).
"""

from planning.plan import (
    STATUS_READY, STATUS_BLOCKED, STATUS_COMPLETED, STATUS_FAILED,
)
from planning.plan_manager import PlanManager

from .plan_execution_coordinator import PlanExecutionCoordinator
from .step_execution_controller import StepExecutionController
from .capability_handlers import CapabilityHandlerRegistry
from .executable_registry import ExecutableCapabilityRegistry
from .execution_history import ExecutionHistory
from .execution_event_log import ExecutionEventLog
from .execution_engine import ExecutionEngine
from .step_execution_preparation import StepExecutionPreparation

# Conservative, finite default - see module docstring's "Two safety
# limits" section. Never unbounded; a caller can always pass an
# explicit, smaller-or-larger `max_steps_per_run` to `execute_plan`
# itself, or to this class's constructor as the instance-wide default.
DEFAULT_MAX_STEPS_PER_RUN = 25

# Fixed vocabulary for the whole-plan status `execute_plan` reports -
# same controlled-vocabulary convention as planning/plan.py's own
# STATUS_*/ALL_STATUSES and execution/execution_event.py's own
# EVENT_*/ALL_EVENT_TYPES.
PLAN_RUN_COMPLETED = "completed"
PLAN_RUN_BLOCKED = "blocked"
PLAN_RUN_FAILED = "failed"
PLAN_RUN_WAITING = "waiting"

ALL_PLAN_RUN_STATUSES = (
    PLAN_RUN_COMPLETED, PLAN_RUN_BLOCKED, PLAN_RUN_FAILED, PLAN_RUN_WAITING,
)


class PlanExecutionController:
    """Not thread-safe (matches the rest of this project - see
    PlanManager/ExecutionEngine/StepExecutionController's own notes).
    Safe to use one instance per Core / per conversation session.

    Every collaborator this controller needs already exists elsewhere
    in this project. `plan_manager` is required, same "wired to the
    manager it reads from" relationship every other execution-stack
    class already has.

    `step_controller`, if given, is used exactly as provided - this
    controller never rebuilds or replaces it, only ever calls its
    existing `execute_step`, and reuses its already-wired
    `capability_handlers`/`executable_capabilities`/`history`/
    `event_log` for everything below (so the whole stack agrees on
    exactly one of each). When `step_controller` is omitted, a new one
    is built from `plan_manager` plus whichever of
    `execution_engine`/`preparation`/`capability_handlers`/
    `executable_capabilities`/`history`/`event_log` were given (same
    defaulting `StepExecutionController.__init__` already applies to
    any that weren't) - never a second, disagreeing implementation of
    anything `StepExecutionController` already does.

    `coordinator`, if given, is used exactly as provided. When
    omitted, a new `PlanExecutionCoordinator` is built, wired to this
    same `plan_manager` and sharing this same
    `capability_handlers`/`executable_capabilities` - so "which step
    is next-eligible" and "does this step have a registered handler"
    are always asked against the exact same registries `execute_step`
    itself runs against.

    `max_steps_per_run`, if given, becomes this instance's own
    default safety cap (see `DEFAULT_MAX_STEPS_PER_RUN`); `execute_plan`
    can still be called with its own explicit override for one run.
    Must be a positive integer.
    """

    def __init__(
        self,
        plan_manager,
        coordinator=None,
        step_controller=None,
        execution_engine=None,
        preparation=None,
        capability_handlers=None,
        executable_capabilities=None,
        history=None,
        event_log=None,
        max_steps_per_run=DEFAULT_MAX_STEPS_PER_RUN,
    ):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("PlanExecutionController requires a PlanManager instance.")
        if coordinator is not None and not isinstance(coordinator, PlanExecutionCoordinator):
            raise TypeError(
                "PlanExecutionController's coordinator must be a "
                "PlanExecutionCoordinator instance."
            )
        if step_controller is not None and not isinstance(step_controller, StepExecutionController):
            raise TypeError(
                "PlanExecutionController's step_controller must be a "
                "StepExecutionController instance."
            )
        if execution_engine is not None and not isinstance(execution_engine, ExecutionEngine):
            raise TypeError(
                "PlanExecutionController's execution_engine must be an "
                "ExecutionEngine instance."
            )
        if preparation is not None and not isinstance(preparation, StepExecutionPreparation):
            raise TypeError(
                "PlanExecutionController's preparation must be a "
                "StepExecutionPreparation instance."
            )
        if capability_handlers is not None and not isinstance(
            capability_handlers, CapabilityHandlerRegistry
        ):
            raise TypeError(
                "PlanExecutionController's capability_handlers must be a "
                "CapabilityHandlerRegistry instance."
            )
        if executable_capabilities is not None and not isinstance(
            executable_capabilities, ExecutableCapabilityRegistry
        ):
            raise TypeError(
                "PlanExecutionController's executable_capabilities must be an "
                "ExecutableCapabilityRegistry instance."
            )
        if history is not None and not isinstance(history, ExecutionHistory):
            raise TypeError(
                "PlanExecutionController's history must be an ExecutionHistory instance."
            )
        if event_log is not None and not isinstance(event_log, ExecutionEventLog):
            raise TypeError(
                "PlanExecutionController's event_log must be an ExecutionEventLog instance."
            )
        if not isinstance(max_steps_per_run, int) or isinstance(max_steps_per_run, bool) \
                or max_steps_per_run < 1:
            raise ValueError("max_steps_per_run must be a positive integer.")

        self._plan_manager = plan_manager
        self.max_steps_per_run = max_steps_per_run

        if step_controller is not None:
            self._step_controller = step_controller
        else:
            self._step_controller = StepExecutionController(
                plan_manager,
                execution_engine=execution_engine,
                preparation=preparation,
                capability_handlers=capability_handlers,
                executable_capabilities=executable_capabilities,
                history=history,
                event_log=event_log,
            )

        # Single source of truth from here on - whatever the step
        # controller actually holds now - never a second, possibly
        # disagreeing copy of any of these.
        self.capability_handlers = self._step_controller.capability_handlers
        self.executable_capabilities = self._step_controller.executable_capabilities
        self.history = self._step_controller.history
        self.event_log = self._step_controller.event_log

        if coordinator is not None:
            self._coordinator = coordinator
        else:
            self._coordinator = PlanExecutionCoordinator(
                plan_manager,
                capability_handlers=self.capability_handlers,
                executable_capabilities=self.executable_capabilities,
            )

    # ------------------------------------------------------------------
    # Read-only access to the shared coordinator (added alongside
    # agent/agent_loop.py's "identify the next READY step without
    # executing it" lookahead) - exposes the exact same
    # `PlanExecutionCoordinator` instance `execute_plan` itself already
    # calls into above, never a second, disagreeing one built with
    # different registries. Public (unlike `_coordinator`) so a caller
    # such as `AgentLoop` can ask "what would run next" - purely
    # read-only, via `get_next_ready_step`/`inspect_execution_state` -
    # without executing anything and without reaching into this
    # controller's private state.
    # ------------------------------------------------------------------
    @property
    def coordinator(self):
        return self._coordinator

    # ------------------------------------------------------------------
    # Read-only access to the shared step controller (added alongside
    # agent/agent_loop.py's "execute the identified next step, one at a
    # time" connection - Prompt 310). Exposes the exact same
    # `StepExecutionController` instance `execute_plan` itself already
    # calls `execute_step` on above, never a second, disagreeing one
    # built with different registries/history/event log. Public (unlike
    # `_step_controller`) so a caller such as `AgentLoop` can run a
    # single, explicitly-identified step through the existing
    # preparation -> capability-execution -> result-recording flow,
    # without reaching into this controller's private state and without
    # this controller (or `AgentLoop`) ever re-implementing any part of
    # `StepExecutionController.execute_step` itself.
    # ------------------------------------------------------------------
    @property
    def step_controller(self):
        return self._step_controller

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _result(
        self, success, plan_id, status, executed_steps, completed_steps,
        failed_steps, blocked_steps, skipped_steps, execution_ids, outputs,
        warnings, error,
    ):
        """The one place that shapes an `execute_plan` return value, so
        every path below - a missing plan, a cycle, a clean run, a
        failure, a safety-limit stop - comes back in exactly the same
        structured shape (requirement 12)."""
        return {
            "success": bool(success),
            "plan_id": plan_id,
            "status": status,
            "executed_steps": list(executed_steps),
            "completed_steps": list(completed_steps),
            "failed_steps": list(failed_steps),
            "blocked_steps": list(blocked_steps),
            "skipped_steps": list(skipped_steps),
            "execution_ids": list(execution_ids),
            "outputs": dict(outputs),
            "warnings": list(warnings),
            "error": error,
        }

    # ------------------------------------------------------------------
    # Cycle detection (requirement 11)
    # ------------------------------------------------------------------
    def _detect_cycle(self, plan):
        """Read-only DFS over `plan`'s own step-dependency graph
        (edges: step -> each of its own `dependencies` that names
        another step actually in this same plan; a dependency on an
        id that doesn't match any step in the plan is left out, since
        it can never be part of a cycle - it is an unresolved
        dependency, not a cyclic one, and is already reported
        elsewhere via `PlanManager.check_plan_readiness`).

        Returns the cyclic path (a list of step_ids, first id repeated
        at the end) the first time one is found, or `None` if the
        graph is acyclic. Never mutates anything - no step's status,
        no plan state - this only inspects `step.dependencies`, which
        `PlanStep` already stores as a plain list.
        """
        steps_by_id = {step.step_id: step for step in plan.steps}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {step_id: WHITE for step_id in steps_by_id}
        path = []
        found = []

        def visit(step_id):
            if found:
                return
            color[step_id] = GRAY
            path.append(step_id)
            for dep_id in steps_by_id[step_id].dependencies:
                if found:
                    return
                if dep_id not in steps_by_id:
                    continue
                if color[dep_id] == GRAY:
                    start = path.index(dep_id)
                    found.append(path[start:] + [dep_id])
                    return
                if color[dep_id] == WHITE:
                    visit(dep_id)
            if not found:
                path.pop()
                color[step_id] = BLACK

        for step_id in steps_by_id:
            if color[step_id] == WHITE and not found:
                visit(step_id)

        return found[0] if found else None

    # ------------------------------------------------------------------
    # Whole-plan status determination (requirement 9 - "do not guess")
    # ------------------------------------------------------------------
    def _determine_status(self, plan, plan_id, capability_system, stopped_for_limit):
        """Determine COMPLETED/FAILED/WAITING/BLOCKED for `plan` once
        `execute_plan`'s own loop has stopped, entirely from
        already-computed, already-existing facts - never a guess:

          - a plan with no steps at all has nothing left to do, so it
            is trivially COMPLETED;
          - any step currently FAILED makes the whole plan FAILED
            (`execute_plan` itself already stops the instant a step
            fails - see requirement 8 - so this is simply reporting
            that stop, never re-deciding it);
          - every step COMPLETED makes the whole plan COMPLETED;
          - if this run stopped specifically because
            `max_steps_per_run` was reached (requirement 10), the plan
            is WAITING - more steps may still be eligible, this run
            simply chose not to find out, so a future call can
            continue exactly where this one left off;
          - otherwise, this run's own loop already stopped because
            `PlanExecutionCoordinator.get_next_ready_step` (the exact
            same, single existing "what's next" check `execute_plan`
            itself just used) reported nothing currently executable.
            Asking it again here - read-only, no side effects - is the
            single source of truth for "is there truly nothing more
            possible right now": if it still reports nothing
            executable, the plan is BLOCKED; if it now reports
            something executable (a capability_system passed in with
            different availability than earlier in the same call,
            for instance), the plan is WAITING rather than silently
            treated as permanently stuck.
        """
        if not plan.steps:
            return PLAN_RUN_COMPLETED
        if any(step.status == STATUS_FAILED for step in plan.steps):
            return PLAN_RUN_FAILED
        if all(step.status == STATUS_COMPLETED for step in plan.steps):
            return PLAN_RUN_COMPLETED
        if stopped_for_limit:
            return PLAN_RUN_WAITING
        next_result = self._coordinator.get_next_ready_step(plan_id, capability_system)
        if next_result["executable"]:
            return PLAN_RUN_WAITING
        return PLAN_RUN_BLOCKED

    # ------------------------------------------------------------------
    # Controlled, sequential plan execution
    # ------------------------------------------------------------------
    def execute_plan(self, plan_id, capability_system=None, max_steps_per_run=None):
        """Execute as many of `plan_id`'s steps as can safely run right
        now, one at a time, stopping the instant a step fails, and
        never executing more than `max_steps_per_run` steps in this
        one call.

        `capability_system` is optional (defaults to `None`) and is
        forwarded, read-only, into every existing check this method
        calls (`PlanExecutionCoordinator.get_next_ready_step`,
        `StepExecutionController.execute_step`,
        `PlanManager.refresh_*`) - never used here to create, enable,
        install, or execute a capability itself.

        `max_steps_per_run`, if given, overrides this instance's own
        `self.max_steps_per_run` for this one call only. Must be a
        positive integer.

        Never raises for an unknown `plan_id` - reported as a
        structured failure instead (same "a query that should always
        have a structured answer" convention the rest of this
        project's execution-stack classes already follow).

        Step 0 - guards, before a single step is ever touched
        (requirements 1, 2, 11):
          1. `plan_id` must name a known plan (via
             `PlanManager.get_plan`) - if not, this returns
             immediately with `status="failed"` and a structured
             `error`, having executed nothing.
          2. the plan's own dependency graph must be acyclic (see
             `_detect_cycle` above) - if a cycle is found, this
             returns immediately with `status="blocked"` and a
             structured `error` naming the cyclic step_ids, having
             executed nothing.

        Step 1 - an initial, one-time dependency/capability refresh
        (`PlanManager.refresh_plan_step_statuses`) so any step still
        sitting at PENDING (never explicitly moved to READY/BLOCKED by
        a caller) is correctly classified before this method's own
        loop starts looking for READY, executable steps - the exact
        same refresh a caller would otherwise have to remember to run
        themselves.

        Step 2 - the controlled loop (requirements 3, 4, 5, 6, 7, 8,
        10, 14, 16), executed at most `max_steps_per_run` times:
          a. ask `PlanExecutionCoordinator.get_next_ready_step` - the
             single existing "which step, if any, is both READY and
             actually executable right now" check (already covers:
             refreshed dependency/status information, step is READY,
             required capabilities are available, required handlers
             are registered) - never re-derived here;
          b. if none is found, stop the loop (there is nothing more
             this run can safely do right now);
          c. otherwise, run that one step, exactly once, through
             `StepExecutionController.execute_step` - the single
             existing place a step is actually prepared
             (`StepExecutionPreparation`) and executed
             (`ExecutionEngine.execute_capability_step`), never a
             second copy of either;
          d. on success: record the step as executed and completed,
             preserve its output, and call
             `PlanManager.refresh_after_step_change` so any dependent
             step's READY/BLOCKED status is recomputed from the
             plan's current state - allowing the next eligible step to
             become READY, purely through the plan's own existing
             dependency graph;
          e. on failure: record the step as executed and failed,
             preserve the failure's error, and stop the loop
             immediately - no dependent step's status is refreshed and
             no further step is ever attempted in this call (this is
             the one and only place `execute_plan` deliberately does
             *not* call `refresh_after_step_change`, so a step that
             was BLOCKED on the now-FAILED step is correctly left
             exactly as blocked as it already was, never silently
             promoted).

        Step 3 - once the loop stops (nothing more executable, a
        failure, or the safety limit), determine the whole-plan status
        (`_determine_status` above - COMPLETED/BLOCKED/FAILED/WAITING,
        never guessed) and assemble the final `blocked_steps` (every
        step currently STATUS_BLOCKED) and `skipped_steps` (every step
        currently STATUS_READY that this call did not itself execute -
        i.e. a step that could still run in a future call) lists
        directly from the plan's own, current step statuses.

        Returns a dict (requirement 12):
            {
                "success": bool,            # True unless the plan was
                                             # unknown, contained a
                                             # cycle, or a step failed
                                             # during this run
                "plan_id": str,
                "status": str,               # "completed" | "blocked"
                                              # | "failed" | "waiting"
                "executed_steps": [step_id, ...],   # in the order run
                "completed_steps": [step_id, ...],  # subset, in order
                "failed_steps": [step_id, ...],     # subset, in order
                                                     # (at most one,
                                                     # since execution
                                                     # stops on the
                                                     # first failure)
                "blocked_steps": [step_id, ...],
                "skipped_steps": [step_id, ...],
                "execution_ids": [execution_id or None, ...],  # one
                                                     # per executed
                                                     # step, same order
                                                     # as executed_steps
                "outputs": {step_id: output, ...},  # completed steps
                                                     # only, and only
                                                     # when the step
                                                     # actually
                                                     # produced one
                "warnings": [str, ...],
                "error": str or None,
            }
        """
        limit = max_steps_per_run if max_steps_per_run is not None else self.max_steps_per_run
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("max_steps_per_run must be a positive integer.")

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._result(
                False, plan_id, PLAN_RUN_FAILED, [], [], [], [], [], [], {},
                [], f"Unknown plan_id: {plan_id!r}.",
            )

        cycle = self._detect_cycle(plan)
        if cycle is not None:
            return self._result(
                False, plan_id, PLAN_RUN_BLOCKED, [], [], [], [], [], [], {},
                [], (
                    "Plan dependency graph contains a cycle: "
                    + " -> ".join(cycle)
                ),
            )

        warnings = []

        # Step 1 - one-time refresh so PENDING steps are correctly
        # classified before the loop below starts looking for READY,
        # executable ones.
        self._plan_manager.refresh_plan_step_statuses(plan_id, capability_system)

        executed_steps = []
        completed_steps = []
        failed_steps = []
        execution_ids = []
        outputs = {}
        error = None
        success = True
        stopped_for_limit = False

        steps_run = 0
        while steps_run < limit:
            next_result = self._coordinator.get_next_ready_step(plan_id, capability_system)
            for w in next_result["warnings"]:
                if w not in warnings:
                    warnings.append(w)

            if not next_result["executable"]:
                break

            step = next_result["step"]
            step_id = step.step_id

            exec_result = self._step_controller.execute_step(
                plan_id, step_id, capability_system=capability_system,
            )
            executed_steps.append(step_id)
            execution_ids.append(exec_result["execution_id"])
            steps_run += 1

            if exec_result["success"]:
                completed_steps.append(step_id)
                if exec_result["output"] is not None:
                    outputs[step_id] = exec_result["output"]
                # Requirement 7 - allow the next eligible step to
                # become READY, purely through the plan's own existing
                # dependency graph. Never executes anything itself.
                self._plan_manager.refresh_after_step_change(
                    plan_id, step_id, capability_system,
                )
            else:
                # Requirement 8 - stop, preserve the failure, do not
                # touch any dependent step's status.
                failed_steps.append(step_id)
                error = exec_result["error"]
                success = False
                break
        else:
            # The loop exhausted `limit` iterations without a `break`
            # above - i.e. it stopped only because the safety cap was
            # reached, not because nothing more was executable and not
            # because of a failure (requirement 10).
            stopped_for_limit = True
            warnings.append(
                f"max_steps_per_run limit ({limit}) reached; stopping "
                "this run safely. Call execute_plan again to continue."
            )

        blocked_steps = [
            step.step_id for step in plan.steps if step.status == STATUS_BLOCKED
        ]
        skipped_steps = [
            step.step_id for step in plan.steps
            if step.status == STATUS_READY and step.step_id not in executed_steps
        ]

        status = self._determine_status(plan, plan_id, capability_system, stopped_for_limit)

        return self._result(
            success, plan_id, status, executed_steps, completed_steps,
            failed_steps, blocked_steps, skipped_steps, execution_ids, outputs,
            warnings, error,
        )
