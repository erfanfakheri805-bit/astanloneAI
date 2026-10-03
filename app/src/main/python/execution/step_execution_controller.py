"""
Execution - Step Execution Controller
=========================================
`StepExecutionController` is a small, explicit orchestration layer
that sits directly on top of the execution stack that already exists
in this project:

    PLAN (planning/plan.py) -> PlanStep
        -> StepExecutionPreparation.prepare_with_context
           (execution/step_execution_preparation.py: preflight +
           handler readiness + ExecutionContext, read-only)
        -> [only if prepared] ExecutionEngine.execute_capability_step
           (execution/execution_engine.py: the actual RUNNING ->
           COMPLETED/FAILED run, reusing every existing piece -
           ExecutionResult, ExecutionHistory, ExecutionEventLog,
           CapabilityHandlerRegistry, ExecutableCapabilityRegistry,
           CapabilityOutput, PlanManager.update_step_status,
           PlanManager.refresh_after_step_change)
        -> a single, structured result dict

This module answers exactly one question - "run this one, explicitly
named plan step, right now, and tell me exactly what happened" - and
never anything broader than that. It deliberately does not add any
new execution behavior of its own: every actual decision about
whether a step is safe to run, and everything that happens once it
does run, is still made entirely by `StepExecutionPreparation` and
`ExecutionEngine` respectively (both untouched by this module). This
controller's own job is narrow and mechanical:

  1. gate every run through `StepExecutionPreparation.prepare_with_context`
     first - the single existing place plan/step existence, current
     status, dependency resolution, capability availability, and
     handler registration are all already checked together, and the
     single existing place an `ExecutionContext` for this attempt is
     already built (execution/execution_context.py, via
     execution/execution_context_builder.py) - never a second copy of
     any of that logic;
  2. if that gate fails, record exactly one `PREPARATION_FAILED`
     `ExecutionEvent` (execution/execution_event.py) into the shared
     `ExecutionEventLog`, and return a structured failure - the
     capability handler is never called, the `PlanStep` is never
     touched (it was never safe to touch), and no `ExecutionResult`
     is ever created for a run that never happened;
  3. if that gate passes, delegate the actual run to
     `ExecutionEngine.execute_capability_step` unchanged - the single
     existing place a RUNNING `ExecutionResult` is created, a
     registered capability handler is actually called, every
     lifecycle `ExecutionEvent` for the run itself is recorded, the
     `PlanStep` is moved to COMPLETED/FAILED via
     `PlanManager.update_step_status`, dependents are refreshed via
     `PlanManager.refresh_after_step_change` (COMPLETED only), and the
     terminal `ExecutionResult` is recorded into `ExecutionHistory` -
     never a second copy of any of that logic either;
  4. translate whatever `StepExecutionPreparation`/`ExecutionEngine`
     already reported into the one, fixed, structured result shape
     documented on `execute_step` below.

A step with no `required_capabilities` at all is not a special case
here: `ExecutionEngine.execute_capability_step` already treats that as
trivially ready and completes it immediately with an empty output
(see that method's own docstring) - this controller never needs a
second code path for it.

This controller NEVER, under any circumstance:
  - automatically executes another step, or the rest of the plan -
    `execute_step` only ever touches the single `plan_id`/`step_id`
    it was explicitly called with, once, and returns; nothing here
    loops over `plan.steps`, calls itself again, or consults
    `PlanExecutionCoordinator.get_next_ready_step` at all;
  - creates, installs, enables, or disables a capability - every
    capability/handler this controller can ever run is one some
    caller already explicitly registered ahead of time via
    `CapabilityHandlerRegistry.register`/`replace` or
    `ExecutableCapabilityRegistry.register`;
  - modifies an arbitrary file, or anything outside the in-memory
    `PlanManager`/`ExecutionHistory`/`ExecutionEventLog` state this
    project already keeps;
  - uses `eval()`, `exec()`, `subprocess`, a shell command, or opens
    any network connection - nor does anything it calls into
    (`StepExecutionPreparation`, `ExecutionEngine`, and everything
    beneath them already carry, and continue to carry, that same
    guarantee - see each of those modules' own docstrings);
  - calls an external AI API - this controller only ever coordinates
    already-registered, already-local Python callables.

Retrying a step is deliberately out of scope for this controller: if
`retry_step` already exists on the wired `ExecutionEngine` (see
execution_engine.py), it is never called, bypassed, or reimplemented
here - a caller that wants to retry a FAILED step still calls
`engine.retry_step(...)` directly, exactly as before. This is also
what keeps a `COMPLETED` step protected without inventing any new
retry semantics: a `COMPLETED` step is not `STATUS_READY`, so
`StepExecutionPreparation`'s own preflight check (reused unchanged)
already reports it as not prepared, and `execute_step` returns a
structured failure without ever re-running it - the exact same
protection `ExecutionEngine.execute_step`/`execute_capability_step`
already give an already-terminal step on their own.
"""

from planning.plan_manager import PlanManager

from .execution_engine import ExecutionEngine
from .step_execution_preparation import StepExecutionPreparation
from .capability_handlers import CapabilityHandlerRegistry
from .executable_registry import ExecutableCapabilityRegistry
from .execution_history import ExecutionHistory
from .execution_event_log import ExecutionEventLog
from .execution_context_builder import ExecutionContextBuilder
from .execution_result import STATUS_COMPLETED as EXEC_STATUS_COMPLETED
from .execution_event import (
    ExecutionEvent,
    EVENT_PREPARATION_FAILED,
    SEVERITY_ERROR,
)


class StepExecutionController:
    """Not thread-safe (matches the rest of this project - see
    PlanManager/ExecutionEngine/StepExecutionPreparation's own notes).
    Safe to use one instance per Core / per conversation session.

    Every collaborator this controller needs already exists elsewhere
    in this project (see module docstring); this constructor's only
    job is to accept already-built ones where the caller has them, or
    safely build/wire consistent defaults where it doesn't - never a
    second, disagreeing implementation of anything those collaborators
    already do.

    `plan_manager` is required, same "wired to the manager it reads
    from" relationship every other execution-stack class already has
    (`ExecutionEngine`, `PlanExecutionCoordinator`,
    `StepExecutionPreparation`).

    `execution_engine`, if given, is used exactly as provided - this
    controller never rebuilds or replaces the engine itself, only
    ever calls its existing `execute_capability_step`. When
    `capability_handlers`/`executable_capabilities`/`history`/
    `event_log` are *also* explicitly given alongside an existing
    `execution_engine`, they are wired directly onto that same engine
    (each of those is a plain, reassignable attribute on
    `ExecutionEngine` - see execution_engine.py's own `__init__`) so
    the whole stack shares exactly one of each rather than risking two
    disagreeing registries/histories/logs; when omitted, the engine's
    own already-wired instances are reused unchanged. When
    `execution_engine` itself is omitted, a new one is constructed
    from `plan_manager` plus whichever of those four collaborators
    were given (same defaulting `ExecutionEngine.__init__` already
    applies to any that weren't).

    `preparation`, if given, is used exactly as provided (any
    consistency between its own collaborators and this controller's
    is the caller's responsibility, same trust-the-caller convention
    every other explicit-sharing constructor in this project already
    extends). When omitted, a new `StepExecutionPreparation` is built
    from `plan_manager` and this controller's own (possibly
    just-defaulted) `capability_handlers`/`executable_capabilities`/
    `context_builder`, so preparation and actual execution always
    agree about which handlers/capabilities are registered.
    """

    def __init__(
        self,
        plan_manager,
        execution_engine=None,
        preparation=None,
        capability_handlers=None,
        executable_capabilities=None,
        history=None,
        event_log=None,
        context_builder=None,
    ):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("StepExecutionController requires a PlanManager instance.")
        if execution_engine is not None and not isinstance(execution_engine, ExecutionEngine):
            raise TypeError(
                "StepExecutionController's execution_engine must be an "
                "ExecutionEngine instance."
            )
        if preparation is not None and not isinstance(preparation, StepExecutionPreparation):
            raise TypeError(
                "StepExecutionController's preparation must be a "
                "StepExecutionPreparation instance."
            )
        if capability_handlers is not None and not isinstance(
            capability_handlers, CapabilityHandlerRegistry
        ):
            raise TypeError(
                "StepExecutionController's capability_handlers must be a "
                "CapabilityHandlerRegistry instance."
            )
        if executable_capabilities is not None and not isinstance(
            executable_capabilities, ExecutableCapabilityRegistry
        ):
            raise TypeError(
                "StepExecutionController's executable_capabilities must be an "
                "ExecutableCapabilityRegistry instance."
            )
        if history is not None and not isinstance(history, ExecutionHistory):
            raise TypeError(
                "StepExecutionController's history must be an ExecutionHistory instance."
            )
        if event_log is not None and not isinstance(event_log, ExecutionEventLog):
            raise TypeError(
                "StepExecutionController's event_log must be an ExecutionEventLog instance."
            )
        if context_builder is not None and not isinstance(
            context_builder, ExecutionContextBuilder
        ):
            raise TypeError(
                "StepExecutionController's context_builder must be an "
                "ExecutionContextBuilder instance."
            )

        self._plan_manager = plan_manager

        if execution_engine is not None:
            self._engine = execution_engine
            # Wire any explicitly-supplied shared collaborator directly
            # onto the existing engine - each is a plain, reassignable
            # attribute (see ExecutionEngine.__init__) - so the whole
            # stack agrees on exactly one of each rather than this
            # controller silently consulting a different registry/
            # history/log than the engine actually executes against.
            if capability_handlers is not None:
                self._engine.capability_handlers = capability_handlers
            if executable_capabilities is not None:
                self._engine.executable_capabilities = executable_capabilities
            if history is not None:
                self._engine.history = history
            if event_log is not None:
                self._engine.event_log = event_log
        else:
            self._engine = ExecutionEngine(
                plan_manager,
                history=history,
                capability_handlers=capability_handlers,
                executable_capabilities=executable_capabilities,
                event_log=event_log,
            )

        # Single source of truth from here on: whatever the engine
        # actually holds now (just-defaulted, just-constructed, or
        # just-wired above) - never a second, possibly-disagreeing
        # copy of any of these four.
        self.capability_handlers = self._engine.capability_handlers
        self.executable_capabilities = self._engine.executable_capabilities
        self.history = self._engine.history
        self.event_log = self._engine.event_log

        if preparation is not None:
            self._preparation = preparation
        else:
            self._preparation = StepExecutionPreparation(
                plan_manager,
                capability_handlers=self.capability_handlers,
                executable_capabilities=self.executable_capabilities,
                context_builder=context_builder,
            )

        self.context_builder = self._preparation.context_builder

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _result(
        self, success, plan_id, step_id, execution_id, step_status, output, error,
        warnings, events_recorded, context, data_flow=None,
    ):
        """The one place that shapes an `execute_step` return value, so
        every path below - a preparation failure, a successful run, or
        a failed run - comes back in exactly the same structured shape
        (requirement 9).

        `data_flow` (added alongside Prompt 311's connection to
        `DataFlowManager.propagate_completed_step`) is `None` for every
        path that never reached a successful completion (preparation
        failure, or a run that ended FAILED) - propagation is only ever
        attempted after an actual COMPLETED status, never guessed at -
        and is otherwise the exact, unmodified structured dict
        `propagate_completed_step` itself already returns."""
        return {
            "success": bool(success),
            "plan_id": plan_id,
            "step_id": step_id,
            "execution_id": execution_id,
            "step_status": step_status,
            "output": output,
            "error": error,
            "warnings": list(warnings),
            "events_recorded": list(events_recorded),
            "context": context,
            "data_flow": data_flow,
        }

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------
    def _record_preparation_failed_event(self, plan_id, step_id, message, failed_checks):
        """Best-effort recording of the one `PREPARATION_FAILED` event
        this controller itself is ever responsible for (requirement
        4) - only reached when `StepExecutionPreparation` refused to
        prepare this step, i.e. before `ExecutionEngine` was ever
        consulted, so its own `PREPARATION_FAILED` event never fires
        for this attempt. Same \"event logging must never break an
        execution attempt\" tolerance `ExecutionEngine._record_event`
        already documents - a problem constructing/recording this
        event is swallowed here rather than raised, since the real
        outcome (`prepared=False`) was already fully decided before
        this call."""
        try:
            event = ExecutionEvent(
                event_type=EVENT_PREPARATION_FAILED,
                plan_id=plan_id,
                step_id=step_id,
                message=message,
                data={"failed_checks": [dict(fc) for fc in failed_checks]},
                severity=SEVERITY_ERROR,
            )
            return self.event_log.record(event)
        except Exception:  # noqa: BLE001 - never let event logging break execution
            return None

    def _events_recorded_since(self, before_count, plan_id, step_id):
        """Every event type recorded for this `plan_id`/`step_id`
        during this `execute_step` call - i.e. everything appended to
        `self.event_log` since `before_count` (the log's length right
        before this call started). Read-only; never raises. Using an
        index range rather than `execution_id` correlation means this
        also captures a preparation-failure event, which - by design
        (see module docstring) - has no `execution_id` at all."""
        new_events = self.event_log.list_all()[before_count:]
        return [
            event.event_type for event in new_events
            if event.plan_id == plan_id and event.step_id == step_id
        ]

    # ------------------------------------------------------------------
    # Explicit, single-step execution
    # ------------------------------------------------------------------
    def execute_step(self, plan_id, step_id, capability_system=None):
        """Run exactly the one PlanStep named by `plan_id`/`step_id`,
        once, and return a structured result describing what
        happened. This is always an EXPLICIT request for exactly one
        step: this method never inspects, selects, or executes any
        other step - not the next READY step, not a dependent that
        became READY as a side effect, not the rest of the plan (see
        module docstring's "NEVER" list).

        `capability_system` is optional (defaults to `None`) and is
        forwarded, read-only, into both the preparation gate below
        (`StepExecutionPreparation.prepare_with_context`) and, on a
        successful gate, into `ExecutionEngine.execute_capability_step`
        - never used to create, enable, install, or execute a
        capability itself (same contract every existing method that
        accepts this argument already documents).

        Step 1 - preparation (never skipped, never duplicated):
        `self._preparation.prepare_with_context(plan_id, step_id,
        capability_system=capability_system)` is the single place
        this method asks "is this step known, currently READY, does
        it have every dependency resolved, every required capability
        available, and a registered handler for each - and, if so,
        here is a built `ExecutionContext` for the attempt." Nothing
        above is re-derived here; this method only reads that already-
        structured answer.

        If preparation reports `prepared=False` (requirement 4):
          - no capability handler is ever called;
          - the step's status is never touched - it was never
            confirmed safe to touch, and preparation itself is
            entirely read-only;
          - exactly one `PREPARATION_FAILED` `ExecutionEvent` is
            recorded, joining every failed check's `check`/`reason`
            into one message (same join convention
            `ExecutionEngine._preflight_failure` already uses) and
            preserving the full structured `failed_checks` list in the
            event's own `data`;
          - a structured failure result is returned immediately (see
            return shape below), with `execution_id=None` (no
            `ExecutionResult`/attempt was ever created for a run that
            never happened) and `step_status` taken directly from the
            preparation result (the step's real current status if it
            exists, or `None` if `plan_id`/`step_id` themselves are
            unknown).

        Step 2 - execution (only reached once preparation passed):
        `self._engine.execute_capability_step(plan_id, step_id,
        capability_system=capability_system)` is called exactly once
        - the single existing place a capability handler is actually
        invoked, an `ExecutionContext` is built per required
        capability and hand to it (backward-compatibly - see
        execution_context.py's `call_handler_with_context`), a
        `CapabilityOutput` is attached when a handler returns one, the
        terminal `ExecutionResult` is produced and recorded into
        `self.history`, every `CAPABILITY_*`/`EXECUTION_*`/
        `OUTPUT_CREATED` lifecycle event is recorded into
        `self.event_log`, the `PlanStep` is moved to COMPLETED or
        FAILED via `PlanManager.update_step_status`, and - on success
        only - dependents are refreshed via
        `PlanManager.refresh_after_step_change` (never executed - see
        module docstring). This method never re-implements, shortcuts,
        or second-guesses any part of that; it only reads the
        `ExecutionResult` that comes back.

        Returns a dict (requirement 9):
            {
                "success": bool,               # True only on COMPLETED
                "plan_id": str,
                "step_id": str,
                "execution_id": str or None,   # None only for a
                                                # preparation failure
                "step_status": str or None,    # the step's real,
                                                # current status after
                                                # this call (COMPLETED/
                                                # FAILED on a run that
                                                # happened; unchanged,
                                                # or None if unknown,
                                                # on a preparation
                                                # failure)
                "output": ...,                 # ExecutionResult.output,
                                                # or None
                "error": str or None,          # ExecutionResult.error,
                                                # or the joined
                                                # preparation-failure
                                                # message
                "warnings": [str, ...],        # from preparation
                "events_recorded": [str, ...], # every ExecutionEvent
                                                # type recorded for
                                                # this plan_id/step_id
                                                # during this call, in
                                                # order
                "context": dict or None,       # the built
                                                # ExecutionContext's
                                                # to_dict(), or None on
                                                # a preparation failure
                "data_flow": dict or None,     # the existing,
                                                # unmodified
                                                # DataFlowManager.
                                                # propagate_completed_step
                                                # result for this step
                                                # as source, once it
                                                # actually COMPLETED;
                                                # None for a
                                                # preparation failure
                                                # or a FAILED run -
                                                # propagation is never
                                                # attempted for either
            }
        """
        events_before = len(self.event_log)

        prep_result = self._preparation.prepare_with_context(
            plan_id, step_id, capability_system=capability_system,
        )

        if not prep_result["prepared"]:
            failed_checks = prep_result["failed_checks"]
            message = "; ".join(
                f"{fc['check']}: {fc['reason']}" for fc in failed_checks
            )
            if not message:
                message = (
                    f"Step {step_id!r} in plan {plan_id!r} is not ready for execution."
                )
            self._record_preparation_failed_event(plan_id, step_id, message, failed_checks)
            events_recorded = self._events_recorded_since(events_before, plan_id, step_id)
            return self._result(
                False, plan_id, step_id, None, prep_result["status"], None, message,
                prep_result["warnings"], events_recorded, None,
            )

        context = prep_result["context"]

        result = self._engine.execute_capability_step(
            plan_id, step_id, capability_system=capability_system,
        )

        step = self._plan_manager.get_step(plan_id, step_id)
        step_status = step.status if step is not None else None
        succeeded = result.status == EXEC_STATUS_COMPLETED

        # Prompt 311 - connect this step's own COMPLETED output to its
        # direct dependents' inputs, via the existing DataFlowManager
        # (shared, unchanged, through self.context_builder -
        # never a second, disagreeing DataFlowManager). Only ever
        # attempted after a real COMPLETED status (never for a FAILED
        # run, and never guessed at from anything else); delegates the
        # entire source/target propagation contract - direct-dependents-
        # only, no-overwrite-on-conflict, no new steps, no execution of
        # any dependent - to `propagate_completed_step` itself, never
        # re-derived here.
        data_flow = None
        if succeeded:
            data_flow = self.context_builder.data_flow_manager.propagate_completed_step(
                plan_id, step_id,
            )

        events_recorded = self._events_recorded_since(events_before, plan_id, step_id)

        return self._result(
            succeeded,
            plan_id, step_id, result.execution_id, step_status,
            result.output, result.error, prep_result["warnings"], events_recorded,
            context.to_dict() if context is not None else None,
            data_flow=data_flow,
        )
