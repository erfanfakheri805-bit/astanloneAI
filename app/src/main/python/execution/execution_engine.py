"""
Execution - Execution Engine
===============================
`ExecutionEngine` is the first slice of the future Execution Engine,
now connected to PlanStep's own status system:

    PLAN (planning/plan.py) -> READY PlanStep -> ExecutionEngine
        -> caller-supplied handler -> ExecutionResult
        (execution/execution_result.py)
        -> PlanManager.update_step_status (planning/plan_manager.py)

All this stage does is take a PlanStep that PlanManager already says is
READY (see planning/plan_manager.py's dependency-/capability-aware
refresh logic - untouched by this module), hand it to a handler the
*caller* provides, record what happened as a structured
ExecutionResult, and then mirror that same outcome onto the PlanStep
itself so the two records can never disagree. Nothing more:

  - No handler is ever auto-discovered, guessed, or looked up by name -
    see requirement 12 of the previous stage; `execute_step` always
    takes a handler explicitly, and does nothing at all if one isn't
    supplied.
  - No eval(), exec(), subprocess, shell command, network access, or
    filesystem access happens anywhere in this module (or ever will -
    that's out of scope for "safe" the way this project uses the
    word). A handler is just an ordinary Python callable the caller
    already wrote and passed in; this engine never interprets a
    string as code.
  - This engine never invents its own status-changing logic: the one
    and only place a PlanStep's status is written is still
    PlanManager.update_step_status, and the one and only place a
    step's dependents get recomputed is still
    PlanManager.refresh_after_step_change (both untouched by this
    module - see planning/plan_manager.py). This engine only ever
    decides *when* to call them, never how they decide a status.
  - A step is only ever synced when this engine actually attempted to
    run it - i.e. it was READY the moment execute_step was called and
    the three preconditions below all passed. A precondition failure
    (unknown plan, unknown step, or a step that wasn't READY) never
    touches PlanStep status - there's either no real step to update,
    or, per requirement 5, an already-terminal/not-yet-ready step is
    never rewritten just because someone asked to run it.
  - On success, the step moves to COMPLETED and its dependents are
    refreshed (READY/BLOCKED recomputed) via the existing dependency
    logic - a dependent whose only unresolved dependency was this step
    can become READY; one that failed elsewhere stays BLOCKED.
  - On a handler failure, the step moves to FAILED. Dependents are
    *not* recomputed here: a FAILED dependency is never COMPLETED, so
    the existing dependency logic in refresh_step_status would leave
    any dependent BLOCKED anyway - there's nothing to refresh.
  - COMPLETED and FAILED are terminal as far as this engine is
    concerned: they're never written back to any other status
    automatically (requirement 5), and, per the precondition checks
    above, a step already in either state is never re-executed.
  - A handler that raises is always caught here and turned into a
    FAILED ExecutionResult with a safe (type name + message, never a
    full traceback) description - this engine itself never crashes
    because a handler did.
  - This module still never creates, enables, installs, or executes a
    capability; `capability_system` is accepted purely to be forwarded
    read-only into PlanManager.refresh_after_step_change (same
    optional, defaults-to-None, dependency-only-if-omitted contract
    that method already has).

`retry_step` (added this stage) is a thin, controlled wrapper around
`execute_step` for one specific case: a FAILED step whose caller wants
to try again with an explicit handler. It never duplicates the
RUNNING/COMPLETED/FAILED bookkeeping above - it only decides whether a
retry is currently allowed (step exists, not COMPLETED, latest
execution is FAILED, an explicit handler is given, and a configurable
maximum retry count hasn't been exceeded), then delegates the actual
run to `execute_step` and tags the resulting ExecutionResult with
`retry_of`/`retry_number` metadata. Retry numbers are always derived
from `self.history`, never a global counter. Nothing in this module
ever retries a failed step automatically, and a successful retry never
triggers automatic execution of any dependent step - see `retry_step`'s
own docstring for the full contract.

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows - see execution_result.py's
module docstring.

`execute_capability_step` (added in a previous stage) is a second,
parallel execution path alongside `execute_step` above, for the case
where the "handler" isn't supplied by the immediate caller but instead
looked up by capability name from `self.capability_handlers` - a
CapabilityHandlerRegistry (execution/capability_handlers.py). Same
non-negotiables apply: no handler is ever auto-discovered (a
capability name only has a handler because something explicitly called
`self.capability_handlers.register`/`replace`), nothing is executed
that wasn't explicitly registered, and no eval()/exec()/subprocess/
shell/network access happens here or in that registry. This stage adds
a read-only pre-execution readiness check
(`self.capability_handlers.check_execution_readiness`) between
preflight and the actual handler calls: every required capability's
existence, availability, and handler registration are all checked
together before anything runs, and a not-`ready` result refuses the
whole step - no handler at all, not even an already-ready one - the
same way an invalid preflight result already does. See
`execute_capability_step`'s own docstring for the full contract.

`execute_capability_step` now also builds one `ExecutionContext`
(execution/execution_context.py) per required-capability handler call
- a small, safe, structured record of that one execution attempt
(`execution_id`, `plan_id`, `step_id`, `capability_name`, the step's
`input_data`, every capability output already produced earlier in the
same loop, and a free-form `metadata` dict). It is handed to the
handler alongside the existing PlanStep argument through
`call_handler_with_context` (execution/execution_context.py), which
inspects the handler's own declared signature and only ever passes the
context to a handler actually written to accept a second positional
argument - an existing handler that only expects `(step)` keeps
working completely unchanged (requirement 11 of this stage). Building
a context, and handing it to a handler, never changes *whether* or
*how* that handler is called otherwise, never writes a PlanStep's
status/data, and never triggers execution of anything beyond the one
handler call that was already happening - no autonomous or automatic
execution of any other step is added by this.

`execute_registered_capability` is a *third*,
independent execution path, for running one `Capability`
(execution/capability.py) directly by name - out of
`self.executable_capabilities` (an `ExecutableCapabilityRegistry` -
execution/executable_registry.py) - against caller-supplied
`input_data`, with no PlanStep involved at all. It exists alongside
`execute_step`/`execute_capability_step` rather than replacing either:
those two are always about running a READY PlanStep (through a
caller-supplied handler or through required-capability handlers,
respectively); this one is about running one named `Capability` on its
own, for a caller that already knows exactly which capability it wants
and what input to give it - no plan, no step, no `required_capabilities`
list. It deliberately duplicates none of the other two methods' own
logic: existence/enabled/handler-validity checks are `self.
executable_capabilities.is_available` (already implemented once, in
executable_registry.py); input validation and the actual
validate-then-call-the-one-registered-handler-then-safely-catch-its-
exceptions sequence is `Capability.validate_input`/`Capability.execute`
(already implemented once, in capability.py) - this method's own job is
only to translate *those* two objects' outputs into the same
`ExecutionResult` shape (execution_result.py), the same RUNNING ->
COMPLETED/FAILED bookkeeping, and the same `self.history.record` call
every other terminal result in this engine already goes through. See
`execute_registered_capability`'s own docstring for the full contract.
"""

from datetime import datetime, timezone

from .execution_result import ExecutionResult, STATUS_FAILED as EXEC_STATUS_FAILED
from .execution_history import ExecutionHistory
from .preflight import PreflightValidator
from .capability_handlers import CapabilityHandlerRegistry
from .executable_registry import ExecutableCapabilityRegistry
from .execution_context import ExecutionContext, call_handler_with_context
from .capability_output import CapabilityOutput, unwrap_for_previous_output
from .execution_event import (
    ExecutionEvent,
    EVENT_EXECUTION_CREATED,
    EVENT_PREPARATION_STARTED,
    EVENT_PREPARATION_COMPLETED,
    EVENT_PREPARATION_FAILED,
    EVENT_EXECUTION_STARTED,
    EVENT_CAPABILITY_STARTED,
    EVENT_CAPABILITY_COMPLETED,
    EVENT_CAPABILITY_FAILED,
    EVENT_OUTPUT_CREATED,
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    SEVERITY_INFO,
    SEVERITY_ERROR,
)
from .execution_event_log import ExecutionEventLog
from planning.plan import (
    STATUS_READY,
    STATUS_COMPLETED as STEP_STATUS_COMPLETED,
    STATUS_FAILED as STEP_STATUS_FAILED,
    ensure_structured_data,
)
from planning.plan_manager import PlanManager


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_previous_outputs(raw_outputs):
    """A defensive, structured-data-only snapshot of `raw_outputs`
    (the in-progress `{capability_name: return_value}` dict
    `execute_capability_step` is building) for handing to the next
    ExecutionContext (execution/execution_context.py) as
    `previous_outputs`. Any entry whose value isn't safe, JSON-shaped
    structured data (see `ensure_structured_data`) is simply omitted -
    same \"best-effort, never turns an otherwise-fine execution into a
    failure\" tolerance `_sync_step_output` already applies to a
    handler's final output - rather than letting an exotic, non-
    serializable handler return value raise while building the *next*
    handler's context. `raw_outputs` itself is never modified; this
    only ever reads it.

    A value that is a `CapabilityOutput` (execution/capability_output.py)
    is unwrapped to its own already-normalized `get_output()` value
    first (via `unwrap_for_previous_output`), so a standardized
    capability output flows into the next handler's `previous_outputs`
    exactly like any other safe, structured return value (requirement
    9 of capability_output.py: "suitable for use as a previous output
    in later ExecutionContext data flow"). Anything that isn't a
    CapabilityOutput passes through unchanged, so existing handlers'
    plain return values behave exactly as they always have."""
    safe = {}
    for key, value in raw_outputs.items():
        candidate = unwrap_for_previous_output(value)
        try:
            safe[key] = ensure_structured_data(candidate)
        except TypeError:
            continue
    return safe


# Synthetic `plan_id` used for every ExecutionResult
# `execute_registered_capability` produces (see that method's own
# docstring). A registered Capability is never part of a real Plan/
# PlanStep (planning/plan.py) - there is no plan_id to attach a result
# to - but ExecutionResult always requires a non-empty plan_id/step_id
# (execution_result.py's own constructor guarantee), and reusing that
# exact requirement rather than loosening it lets this new execution
# path share ExecutionResult/ExecutionHistory unchanged (requirement
# 10: "avoid duplicating execution logic"). `step_id` for these
# results is always the capability's own name, so
# `self.history.list_for_step(CAPABILITY_EXECUTION_PLAN_ID,
# capability_name)`/`self.history.latest_for_step(...)` already give a
# caller that capability's own execution history for free, with no new
# lookup method needed anywhere.
CAPABILITY_EXECUTION_PLAN_ID = "__capability_execution__"


# Default cap on how many times `retry_step` will re-run the same
# FAILED step before refusing (requirement 8: "a configurable maximum
# retry count") - configurable per ExecutionEngine instance at
# construction time (`max_retries=`) and, if ever needed, per call
# (`retry_step(..., max_retries=...)`). Not a suggestion for how many
# times a step *should* be retried - just a safety ceiling; nothing in
# this module ever retries on its own (requirement 12).
DEFAULT_MAX_RETRIES = 3


class ExecutionEngine:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/GoalManager's own note). Safe to use one instance per
    Core / per conversation session, wired to that session's own
    PlanManager.

    Every terminal ExecutionResult this engine produces - COMPLETED or
    FAILED, including a precondition/preflight failure that never
    reached a handler - is also recorded into `self.history`
    (execution/execution_history.py), in the order it happened. An
    ExecutionHistory can be supplied explicitly (e.g. to share one
    history across several engines/sessions); if omitted, this engine
    creates its own private one. Either way, recording an
    ExecutionResult never executes anything itself - see
    execution_history.py's module docstring.

    Before either `execute_step` or `retry_step` ever creates a
    RUNNING execution or calls a handler, both now route through
    `self.preflight` (execution/preflight.py's PreflightValidator,
    wired to this same PlanManager) - see each method's own docstring
    for exactly where and how."""

    def __init__(
        self, plan_manager, history=None, max_retries=DEFAULT_MAX_RETRIES,
        capability_handlers=None, executable_capabilities=None, event_log=None,
    ):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("ExecutionEngine requires a PlanManager instance.")
        if history is not None and not isinstance(history, ExecutionHistory):
            raise TypeError("ExecutionEngine's history must be an ExecutionHistory instance.")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 1:
            raise ValueError("max_retries must be a positive integer.")
        if capability_handlers is not None and not isinstance(
            capability_handlers, CapabilityHandlerRegistry
        ):
            raise TypeError(
                "ExecutionEngine's capability_handlers must be a "
                "CapabilityHandlerRegistry instance."
            )
        if executable_capabilities is not None and not isinstance(
            executable_capabilities, ExecutableCapabilityRegistry
        ):
            raise TypeError(
                "ExecutionEngine's executable_capabilities must be an "
                "ExecutableCapabilityRegistry instance."
            )
        if event_log is not None and not isinstance(event_log, ExecutionEventLog):
            raise TypeError(
                "ExecutionEngine's event_log must be an ExecutionEventLog instance."
            )
        self._plan_manager = plan_manager
        self.history = history if history is not None else ExecutionHistory()
        # Configurable, per-instance (requirement 8) - a plain
        # attribute, not a private/frozen setting, so a caller can
        # reconfigure it later (e.g. `engine.max_retries = 5`) without
        # needing a new engine. `retry_step` reads this only when its
        # own `max_retries` argument is omitted.
        self.max_retries = max_retries
        # One PreflightValidator per engine, wired to the same
        # PlanManager - both execute_step and retry_step share this
        # single instance rather than each constructing their own, so
        # there's exactly one place preflight checks are implemented
        # (execution/preflight.py) and exactly one object exercising
        # them here.
        self.preflight = PreflightValidator(plan_manager)
        # One CapabilityHandlerRegistry per engine (execution/
        # capability_handlers.py), used only by
        # `execute_capability_step` below. Can be supplied explicitly
        # (e.g. to share one set of approved handlers across several
        # engines/sessions - same "explicit sharing" convention
        # `history` already supports); if omitted, this engine creates
        # its own private, empty one. Either way, nothing is ever
        # registered into it automatically - a caller must explicitly
        # call `engine.capability_handlers.register(...)` before
        # `execute_capability_step` can find anything.
        self.capability_handlers = (
            capability_handlers if capability_handlers is not None
            else CapabilityHandlerRegistry()
        )
        # One ExecutableCapabilityRegistry per engine (execution/
        # executable_registry.py), used only by
        # `execute_registered_capability` below. Same "can be supplied
        # explicitly to share across engines/sessions, otherwise a
        # private empty one is created" convention as
        # `capability_handlers` above - nothing is ever registered
        # into it automatically; a caller must explicitly call
        # `engine.executable_capabilities.register(...)` before
        # `execute_registered_capability` can find anything.
        self.executable_capabilities = (
            executable_capabilities if executable_capabilities is not None
            else ExecutableCapabilityRegistry()
        )
        # One ExecutionEventLog per engine (execution/execution_event_log.py),
        # recording lifecycle events (creation, preparation,
        # start/completion/failure of a whole execution, and of each
        # required capability within it) as they happen. Can be
        # supplied explicitly (e.g. to share one event stream across
        # several engines/sessions - same "explicit sharing"
        # convention `history` already supports); if omitted, this
        # engine creates its own private one. Recording an event never
        # executes anything, never changes a PlanStep's or an
        # ExecutionResult's status, and - see `_record_event` below -
        # can never cause an execution attempt to fail even if
        # something goes wrong while building/recording the event
        # itself.
        self.event_log = event_log if event_log is not None else ExecutionEventLog()
        # A small, bounded, in-memory list of safe (type-name + message
        # only, never a raw traceback) notes about any problem that
        # occurred while trying to record an event - see
        # `_record_event`/`_record_event_logging_failure`. Always a
        # plain list, never `None`, so a caller can inspect it
        # immediately without a None check; normally stays empty.
        self.event_logging_errors = []

    def execute_step(self, plan_id, step_id, handler, capability_system=None, sync_output=True):
        """Run `handler(step)` for the READY PlanStep named by
        `plan_id`/`step_id`, sync the outcome onto that same PlanStep,
        and return a fully-populated ExecutionResult - this method
        never raises for anything the handler itself does (see
        below); it only ever returns.

        `handler` must be an explicit callable - required, no default,
        never auto-discovered (requirement 12 of the previous stage).
        Passing `None` or anything else non-callable raises TypeError
        immediately, before any of the plan/step checks below and
        before anything is recorded - "no execution without an
        explicit handler" means exactly that: nothing happens at all.

        `capability_system` is optional (defaults to None) and is
        forwarded, read-only, in two places: into `self.preflight`'s
        capability-availability check below, and into
        PlanManager.refresh_after_step_change after a successful
        completion. Never used to create, enable, install, or execute
        a capability.

        Before running anything, this step is run through
        `self.preflight.validate_step(plan_id, step_id,
        capability_system)` (execution/preflight.py) - the single
        place plan-existence, step-existence, READY-status,
        dependency-resolution, and capability-availability are all
        checked, reusing PlanManager's own logic rather than a second
        copy of it (see PreflightValidator's own docstring). If that
        preflight result isn't valid, this method returns a FAILED
        ExecutionResult describing every failed check (with
        `started_at`/`finished_at` both stamped, so `duration` is
        always available) - the handler is never called, no
        ExecutionResult ever passes through RUNNING for a preflight
        failure (since nothing was ever actually running), and the
        PlanStep itself is never touched: an already-COMPLETED or
        already-FAILED step is never re-executed or rewritten
        (requirement 5, stage 24), and an unknown plan/step simply has
        no PlanStep to sync.

        Once preflight passes, a RUNNING ExecutionResult is created
        and `handler(step)` is called with the actual PlanStep object:
          - on a normal return, that return value becomes `output`,
            the result is marked COMPLETED, the PlanStep is moved to
            COMPLETED via PlanManager.update_step_status (reusing its
            existing rules rather than writing `step.status`
            directly), and PlanManager.refresh_after_step_change is
            called so any dependent step's READY/BLOCKED status gets
            recomputed from the existing dependency logic;
          - on any exception, a safe description (the exception's type
            name and message - never a raw traceback, which could leak
            internal detail) becomes `error`, the result is marked
            FAILED, and the PlanStep is moved to FAILED the same way.
            Dependents are not refreshed here: a FAILED dependency can
            never satisfy another step's dependency check, so there is
            nothing for the existing logic to change.
        Either way, `execution_id`, `started_at`, `finished_at`, and
        the derived `duration` are always present on the returned
        ExecutionResult (see ExecutionResult.to_dict), and
        `result.status` always agrees with the PlanStep's own
        `status` for any step this call actually ran.

        Every ExecutionResult this method returns - success, handler
        failure, or a precondition failure - is also recorded into
        `self.history` (execution/execution_history.py) exactly once,
        in the order it happened, before it's returned (see
        ExecutionHistory.record's own duplicate-protection note).

        `sync_output` (added this stage, defaults to True) controls
        whether a *successful* completion also copies this
        ExecutionResult's `output` onto the PlanStep's own
        `output_data` (see planning/plan.py's PlanStep.set_output) -
        this is the one, optional (requirement: "optionally
        synchronized") place that happens; nothing here ever pushes
        that output onto any *other* step (no automatic data
        propagation - out of scope for this stage). A handler's return
        value that isn't safe, JSON-shaped structured data (see
        ensure_structured_data) simply isn't synced - a TypeError from
        that check is swallowed here rather than turning an otherwise-
        successful execution into a failure - so `output_data` stays
        whatever it was before. A FAILED execution never touches
        `output_data` at all."""
        if handler is None or not callable(handler):
            raise TypeError("execute_step requires an explicit callable handler.")

        self._record_event(
            EVENT_PREPARATION_STARTED, plan_id, step_id,
            message=f"Preparing step {step_id!r} for execution.",
        )

        preflight_result = self.preflight.validate_step(plan_id, step_id, capability_system)
        if not preflight_result.valid:
            failure = self._preflight_failure(preflight_result)
            self._record_event(
                EVENT_PREPARATION_FAILED, plan_id, step_id,
                execution_id=failure.execution_id,
                message=failure.error or "Preflight checks failed.",
                data={"failed_checks": [dict(fc) for fc in preflight_result.failed_checks]},
                severity=SEVERITY_ERROR,
            )
            return failure

        self._record_event(
            EVENT_PREPARATION_COMPLETED, plan_id, step_id,
            message=f"Preflight checks passed for step {step_id!r}.",
        )

        step = self._plan_manager.get_step(plan_id, step_id)

        result = ExecutionResult(plan_id=plan_id, step_id=step_id)
        self._record_event(
            EVENT_EXECUTION_CREATED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution created for step {step_id!r}.",
        )
        result.mark_running()
        self._record_event(
            EVENT_EXECUTION_STARTED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution started for step {step_id!r}.",
        )

        try:
            output = handler(step)
        except Exception as exc:
            result.mark_failed(f"{type(exc).__name__}: {exc}")
            self._plan_manager.update_step_status(plan_id, step_id, STEP_STATUS_FAILED)
            self.history.record(result)
            self._record_event(
                EVENT_EXECUTION_FAILED, plan_id, step_id,
                execution_id=result.execution_id,
                message=result.error,
                severity=SEVERITY_ERROR,
            )
            return result

        result.mark_completed(output=output)
        self._plan_manager.update_step_status(plan_id, step_id, STEP_STATUS_COMPLETED)
        self._plan_manager.refresh_after_step_change(plan_id, step_id, capability_system)
        if sync_output:
            self._sync_step_output(step, output)
        self.history.record(result)
        self._record_event(
            EVENT_OUTPUT_CREATED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Output produced for step {step_id!r}.",
        )
        self._record_event(
            EVENT_EXECUTION_COMPLETED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution completed for step {step_id!r}.",
        )
        return result

    # ------------------------------------------------------------------
    # Capability-backed execution
    # ------------------------------------------------------------------
    def execute_capability_step(self, plan_id, step_id, capability_system=None, sync_output=True):
        """Run the READY PlanStep named by `plan_id`/`step_id` by
        calling, in order, the registered handler
        (execution/capability_handlers.py's `self.capability_handlers`)
        for each name in that step's own `required_capabilities` list -
        never a caller-supplied handler (that's `execute_step`'s job);
        this method only ever calls handlers that were explicitly
        registered ahead of time via
        `self.capability_handlers.register`/`replace`.

        Exactly like `execute_step`, this method never raises for
        anything a handler itself does; it only ever returns a fully-
        populated ExecutionResult, and every terminal result it
        produces - success, a not-ready step, or a handler failure -
        is recorded into `self.history` exactly once, in the order it
        happened (same convention `execute_step` already follows).

        `capability_system` is optional (defaults to None) and is
        forwarded, read-only, in three places: into `self.preflight`'s
        capability-availability check below, into the readiness check
        below that, and into PlanManager.refresh_after_step_change
        after a successful completion. Never used to create, enable,
        install, or execute a capability.

        Before anything else, this step is run through
        `self.preflight.validate_step(plan_id, step_id,
        capability_system)` (execution/preflight.py) - the exact same
        preflight check `execute_step` uses (requirement: "use the
        existing preflight validation"), covering plan/step existence,
        READY status, and dependency resolution. If that preflight
        result isn't valid, this method returns a FAILED
        ExecutionResult describing every failed check, exactly as
        `execute_step` does for the same case: no handler is ever
        looked up or called, and the PlanStep itself is never touched.

        Once preflight passes, this step is run through
        `self.capability_handlers.check_execution_readiness(step,
        capability_system)` (execution/capability_handlers.py) - the
        one place capability existence, capability availability, and
        handler registration are all checked together for this
        step's own `required_capabilities`, reusing the same
        registry-lookup logic PlanManager/PreflightValidator already
        use rather than a second copy of it. If that readiness result
        isn't `ready` - any required capability is missing from the
        registry, registered but disabled, or has no registered
        handler - this method returns a FAILED ExecutionResult
        describing every capability/handler problem found (with the
        full structured readiness report preserved in
        `metadata["readiness"]`): no handler is called at all in that
        case, not even the ones that *are* ready, and the PlanStep
        itself is never touched - same "a precondition failure never
        rewrites an already-real PlanStep" rule `_preflight_failure`
        already follows.

        A step with an empty `required_capabilities` list is
        trivially ready (nothing to check, nothing to refuse); it
        completes immediately with an empty `output` dict, following
        the exact same RUNNING -> COMPLETED path below as a step with
        capabilities.

        Once readiness confirms every required capability is ready, a
        RUNNING ExecutionResult is created and each handler is called
        in turn, in `required_capabilities` order, as `handler(step)`
        - the actual PlanStep object, same argument `execute_step`
        passes its own handler:
          - each handler's return value is collected into `output`, a
            plain `{capability_name: handler_return_value}` dict (so a
            caller can tell which handler produced which result), and
            the loop moves on to the next required capability;
          - if *any* handler raises, the loop stops immediately - no
            handler later in `required_capabilities` order is ever
            called (requirement: "stop the remaining handlers") - a
            safe description (the exception's type name and message,
            never a raw traceback) becomes `error`, the result is
            marked FAILED, and the PlanStep is moved to FAILED via
            PlanManager.update_step_status (requirement: "synchronize
            the PlanStep using the existing execution logic" - the
            exact same call `execute_step` already uses for a handler
            failure). Dependents are not refreshed in this case, same
            reasoning `execute_step` already documents: a FAILED
            dependency can never satisfy another step's dependency
            check.
        On a full, uninterrupted pass through every required
        capability, the result is marked COMPLETED with the collected
        `output` dict, the PlanStep is moved to COMPLETED via
        PlanManager.update_step_status, and
        PlanManager.refresh_after_step_change is called so any
        dependent step's READY/BLOCKED status gets recomputed - the
        exact same success path `execute_step` already follows.

        Never uses eval(), exec(), subprocess, a shell command, or
        network/filesystem access, and never creates, enables,
        installs, or auto-discovers a capability or a handler - a
        handler here is always exactly the callable some caller
        already registered via `self.capability_handlers`.

        `sync_output` (added this stage, defaults to True) is the
        exact same optional output-syncing behavior `execute_step`
        documents: on success, the collected `output` dict is copied
        onto the PlanStep's own `output_data` (see
        planning/plan.py's PlanStep.set_output), unless it isn't safe,
        JSON-shaped structured data, in which case the sync is simply
        skipped rather than failing the execution. A FAILED execution
        never touches `output_data`."""
        self._record_event(
            EVENT_PREPARATION_STARTED, plan_id, step_id,
            message=f"Preparing step {step_id!r} for capability-based execution.",
        )

        preflight_result = self.preflight.validate_step(plan_id, step_id, capability_system)
        if not preflight_result.valid:
            failure = self._preflight_failure(preflight_result)
            self._record_event(
                EVENT_PREPARATION_FAILED, plan_id, step_id,
                execution_id=failure.execution_id,
                message=failure.error or "Preflight checks failed.",
                data={"failed_checks": [dict(fc) for fc in preflight_result.failed_checks]},
                severity=SEVERITY_ERROR,
            )
            return failure

        step = self._plan_manager.get_step(plan_id, step_id)

        readiness = self.capability_handlers.check_execution_readiness(
            step, capability_system
        )
        if not readiness.ready:
            failure = self._readiness_failure(plan_id, step_id, readiness)
            self._record_event(
                EVENT_PREPARATION_FAILED, plan_id, step_id,
                execution_id=failure.execution_id,
                message=failure.error,
                data={"readiness": readiness.to_dict()},
                severity=SEVERITY_ERROR,
            )
            return failure

        self._record_event(
            EVENT_PREPARATION_COMPLETED, plan_id, step_id,
            message=f"Preflight and readiness checks passed for step {step_id!r}.",
        )

        required = list(step.required_capabilities)

        result = ExecutionResult(plan_id=plan_id, step_id=step_id)
        self._record_event(
            EVENT_EXECUTION_CREATED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution created for step {step_id!r}.",
        )
        result.mark_running()
        self._record_event(
            EVENT_EXECUTION_STARTED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution started for step {step_id!r}.",
        )

        output = {}
        try:
            for capability_name in required:
                handler = self.capability_handlers.get(capability_name)
                self._record_event(
                    EVENT_CAPABILITY_STARTED, plan_id, step_id,
                    execution_id=result.execution_id,
                    message=f"Capability {capability_name!r} started.",
                    data={"capability_name": capability_name},
                )
                # A fresh, lightweight ExecutionContext per required
                # capability (execution/execution_context.py) - shares
                # this same ExecutionResult's execution_id (so the two
                # can be correlated), carries this step's own
                # input_data, and accumulates every capability output
                # already produced earlier in this same loop as
                # previous_outputs. Handed to `handler` in a
                # backward-compatible way via
                # `call_handler_with_context` (requirement 11): a
                # handler that still only expects `(step)` keeps
                # working completely unchanged; only a handler whose
                # own signature actually accepts a second positional
                # argument receives this context at all. Never used to
                # decide *whether* to call a handler, never mutated by
                # anything other than this loop, and never persisted
                # anywhere - purely an informational, read-only
                # accompaniment to a call that was already happening.
                context = ExecutionContext(
                    plan_id=plan_id,
                    step_id=step_id,
                    capability_name=capability_name,
                    input_data=step.input_data,
                    previous_outputs=_safe_previous_outputs(output),
                    execution_id=result.execution_id,
                )
                try:
                    capability_output = call_handler_with_context(handler, step, context)
                except Exception as exc:
                    # Logged here (with the specific capability_name
                    # that failed) before re-raising unchanged, so the
                    # existing outer `except` below still handles the
                    # actual FAILED bookkeeping exactly as it always
                    # has (requirement 15: no behavior change) - this
                    # is purely an additional, non-decision-making
                    # observation of the same failure.
                    self._record_event(
                        EVENT_CAPABILITY_FAILED, plan_id, step_id,
                        execution_id=result.execution_id,
                        message=f"Capability {capability_name!r} failed: "
                                f"{type(exc).__name__}: {exc}",
                        data={"capability_name": capability_name},
                        severity=SEVERITY_ERROR,
                    )
                    raise
                output[capability_name] = capability_output
                self._record_event(
                    EVENT_CAPABILITY_COMPLETED, plan_id, step_id,
                    execution_id=result.execution_id,
                    message=f"Capability {capability_name!r} completed.",
                    data={"capability_name": capability_name},
                )
                # Purely additive (requirement 8 of
                # capability_output.py): a handler written to return a
                # standardized CapabilityOutput has it attached onto
                # this same ExecutionResult, keyed by capability_name,
                # for later retrieval via
                # ExecutionResult.get_capability_output(s). A handler
                # that returns anything else (its own existing output
                # format) is completely unaffected - `output` above
                # still holds exactly what it always held.
                if isinstance(capability_output, CapabilityOutput):
                    result.attach_capability_output(capability_name, capability_output)
        except Exception as exc:
            result.mark_failed(f"{type(exc).__name__}: {exc}")
            self._plan_manager.update_step_status(plan_id, step_id, STEP_STATUS_FAILED)
            self.history.record(result)
            self._record_event(
                EVENT_EXECUTION_FAILED, plan_id, step_id,
                execution_id=result.execution_id,
                message=result.error,
                severity=SEVERITY_ERROR,
            )
            return result

        result.mark_completed(output=output)
        self._plan_manager.update_step_status(plan_id, step_id, STEP_STATUS_COMPLETED)
        self._plan_manager.refresh_after_step_change(plan_id, step_id, capability_system)
        if sync_output:
            self._sync_step_output(step, output)
        self.history.record(result)
        self._record_event(
            EVENT_OUTPUT_CREATED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Output produced for step {step_id!r}.",
        )
        self._record_event(
            EVENT_EXECUTION_COMPLETED, plan_id, step_id,
            execution_id=result.execution_id,
            message=f"Execution completed for step {step_id!r}.",
        )
        return result

    # ------------------------------------------------------------------
    # Registered-capability execution (no PlanStep involved)
    # ------------------------------------------------------------------
    def execute_registered_capability(self, capability_name, input_data):
        """Run the `Capability` (execution/capability.py) registered
        under `capability_name` in `self.executable_capabilities` (an
        `ExecutableCapabilityRegistry` - execution/executable_registry.py)
        against `input_data`, and return a fully-populated
        ExecutionResult - this method never raises for anything the
        capability's own handler does (see below); it only ever
        returns. No PlanStep is involved at all: nothing here reads or
        writes any Plan/PlanStep, and `self.preflight`/
        `self._plan_manager` are never consulted for this path
        (contrast `execute_step`/`execute_capability_step`, which
        always are).

        Checked in order, before anything is called - requirement 2's
        four checks, and requirement 6/7 (disabled/unavailable
        capabilities and invalid input must never reach a handler):
          1. `self.executable_capabilities.has(capability_name)` - the
             capability must actually be registered; a missing
             capability returns a FAILED result immediately.
          2. the registered entry must be enabled (`ExecutableCapabilityRegistry`'s
             own per-entry enabled/disabled state - execution/
             executable_registry.py) - a disabled capability returns a
             FAILED result immediately, exactly like a missing one,
             regardless of whether its handler would otherwise be
             valid.
          3. the `Capability`'s `.handler` must currently be callable -
             checked fresh (not trusted from construction time), same
             "never trust a stale guarantee" reasoning
             `ExecutableCapabilityRegistry.is_available` already
             documents - an invalid handler returns a FAILED result
             immediately.
          4. `capability.validate_input(input_data)` (execution/
             capability.py) - deterministic, schema-based, never calls
             the handler - if invalid, returns a FAILED result
             carrying the validation failure; the handler is never
             called for invalid input (requirement 7).
        All four checks are read-only and share one single source of
        truth each - `ExecutableCapabilityRegistry.is_available`/
        `Capability.validate_input` (already implemented once, in
        their own modules) - never a second, differently-shaped copy
        of either check here (requirement 10).

        Once all four checks pass, `capability.execute(input_data)`
        (execution/capability.py) is called - the *only* thing this
        method ever calls that can call the handler, and it is only
        ever called with the exact `Capability` object retrieved from
        `self.executable_capabilities` in step 1 above (requirement 2:
        "execute only the registered handler"; requirement 9 of the
        previous stage's "no execution without something explicitly
        registered" rule, applied here). `Capability.execute` already
        implements validate-then-call-then-safely-catch-exceptions
        once; this method never duplicates that sequence (requirement
        10) - it only translates the `CapabilityExecutionResult` that
        comes back into this engine's own `ExecutionResult` shape:
          - a RUNNING ExecutionResult is created and marked running
            before `capability.execute` is called, so `started_at` is
            always stamped (requirement 5: "execution timing");
          - on `capability_execution_result.success`, the result is
            marked COMPLETED with that same `output`;
          - otherwise (a validation failure caught inside `execute`,
            or a handler exception caught inside `execute` - either
            way, already reduced to a safe type-name-plus-message
            string by `Capability.execute`, never a raw traceback) the
            result is marked FAILED with that same `error` -
            requirement 8: a handler exception is converted into a
            FAILED ExecutionResult without ever crashing this engine.
        Either way, `result.metadata` always carries
        `capability_name` (requirement 11) and the full structured
        `CapabilityValidationResult` from this attempt (`to_dict()`,
        under `metadata["validation"]`) - requirement 5: "capture
        capability_name" and "input validation result". `execution_id`,
        `started_at`, `finished_at`, and the derived `duration` are
        always present (see ExecutionResult.to_dict), same as every
        other terminal result this engine produces.

        `plan_id`/`step_id` on the returned ExecutionResult are always
        `CAPABILITY_EXECUTION_PLAN_ID`/`capability_name` respectively
        (see that constant's own module-level comment) - a synthetic,
        fixed pairing that exists only so this result can reuse
        ExecutionResult/ExecutionHistory completely unchanged; the
        real, human-meaningful identifier for this execution is always
        `capability_name`, present both as `step_id` and, explicitly,
        in `metadata["capability_name"]`.

        Every ExecutionResult this method returns - success, a missing/
        disabled/invalid-handler capability, an input-validation
        failure, or a handler failure - is also recorded into
        `self.history` (execution/execution_history.py) exactly once,
        in the order it happened, before it's returned (requirement 4
        - same convention `execute_step`/`execute_capability_step`
        already follow).

        Never uses eval(), exec(), subprocess, a shell command, or
        network/filesystem access, and never auto-discovers, creates,
        enables, disables, or installs a capability (requirements 12-
        13) - a capability here is always exactly the `Capability`
        object some caller already explicitly registered via
        `self.executable_capabilities.register`."""
        if not self.executable_capabilities.has(capability_name):
            return self._capability_unavailable_failure(
                capability_name,
                f"No capability is registered under the name {capability_name!r}.",
            )

        capability = self.executable_capabilities.get(capability_name)

        if not self.executable_capabilities.is_available(capability_name):
            description = self.executable_capabilities.describe(capability_name)
            if description is not None and not description["enabled"]:
                reason = f"Capability {capability_name!r} is disabled."
            elif not callable(capability.handler):
                reason = f"Capability {capability_name!r} has no valid callable handler."
            else:  # pragma: no cover - defensive; is_available already covers this
                reason = f"Capability {capability_name!r} is not currently available."
            return self._capability_unavailable_failure(capability_name, reason)

        validation = capability.validate_input(input_data)
        if not validation.valid:
            return self._capability_validation_failure(capability_name, validation)

        result = ExecutionResult(
            plan_id=CAPABILITY_EXECUTION_PLAN_ID, step_id=capability_name,
        )
        result.metadata["capability_name"] = capability_name
        self._record_event(
            EVENT_EXECUTION_CREATED, CAPABILITY_EXECUTION_PLAN_ID, capability_name,
            execution_id=result.execution_id,
            message=f"Execution created for capability {capability_name!r}.",
            data={"capability_name": capability_name},
        )
        result.mark_running()
        self._record_event(
            EVENT_EXECUTION_STARTED, CAPABILITY_EXECUTION_PLAN_ID, capability_name,
            execution_id=result.execution_id,
            message=f"Execution started for capability {capability_name!r}.",
            data={"capability_name": capability_name},
        )

        capability_result = capability.execute(input_data)
        result.metadata["validation"] = capability_result.validation.to_dict()

        if capability_result.success:
            result.mark_completed(output=capability_result.output)
            self.history.record(result)
            self._record_event(
                EVENT_OUTPUT_CREATED, CAPABILITY_EXECUTION_PLAN_ID, capability_name,
                execution_id=result.execution_id,
                message=f"Output produced for capability {capability_name!r}.",
                data={"capability_name": capability_name},
            )
            self._record_event(
                EVENT_EXECUTION_COMPLETED, CAPABILITY_EXECUTION_PLAN_ID, capability_name,
                execution_id=result.execution_id,
                message=f"Execution completed for capability {capability_name!r}.",
                data={"capability_name": capability_name},
            )
        else:
            result.mark_failed(capability_result.error)
            self.history.record(result)
            self._record_event(
                EVENT_EXECUTION_FAILED, CAPABILITY_EXECUTION_PLAN_ID, capability_name,
                execution_id=result.execution_id,
                message=result.error,
                data={"capability_name": capability_name},
                severity=SEVERITY_ERROR,
            )

        return result

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------
    def retry_step(self, plan_id, step_id, handler, max_retries=None, capability_system=None):
        """Re-run a previously FAILED PlanStep's handler, through the
        exact same execution path `execute_step` already uses - this
        method never re-implements any execution logic (requirement
        4); it only decides *whether* a retry is allowed and stamps
        the resulting ExecutionResult with retry metadata.

        `handler` is required and must be an explicit callable - same
        "no execution without an explicit handler" rule `execute_step`
        already enforces. Passing `None` or anything non-callable
        raises TypeError immediately, before any other check and
        before anything is recorded.

        A retry is only allowed when, in order:
          1. the plan exists;
          2. the step exists within that plan;
          3. the step is not already COMPLETED (nothing left to
             retry);
          4. the step's *latest* recorded execution (per
             `self.history.latest_for_step`) is FAILED - a step that
             has never run, or whose latest attempt already
             succeeded, has nothing to retry;
          5. the next `retry_number` (see `_next_retry_number`) does
             not exceed the configured maximum retry count.

        Any of 1-4 failing returns a FAILED ExecutionResult describing
        which check failed (`started_at`/`finished_at` both stamped),
        recorded into `self.history` exactly like any other
        precondition failure from `execute_step` - the handler is
        never called and the PlanStep is never touched.

        `max_retries` is optional; if omitted, this engine's own
        `self.max_retries` (configurable at construction time, or by
        setting `engine.max_retries` directly - see __init__) is used
        instead. If the computed `retry_number` would exceed that
        maximum (requirement 9): nothing is executed, the step is left
        exactly as it was (still FAILED), and a FAILED ExecutionResult
        explaining the limit was reached is returned and recorded -
        still tagged with `retry_of`/`retry_number`/
        `max_retries_reached` in its metadata, so a caller can see
        exactly which retry attempt was refused and why.

        Once a retry is allowed, the FAILED step is moved to READY
        (via `PlanManager.update_step_status` - still the one and only
        place a step's status is written) purely so it can be
        preflight-checked and, if that passes, run the same way any
        other READY step would be. This same `self.preflight`
        (execution/preflight.py) that `execute_step` uses is then run
        directly against the now-READY step (requirement 10 - "retry
        operations must also use the same preflight validation," not
        a second copy of it): if it's invalid - e.g. a dependency or
        required capability stopped being satisfied while this step
        sat FAILED - the READY flip is undone (the step is moved back
        to FAILED, exactly where it was), a FAILED ExecutionResult
        describing every failed check is returned and recorded, and -
        per requirement 9 - nothing is executed and the step ends this
        call in the same state it started in.

        Once that preflight also passes, `self.execute_step(plan_id,
        step_id, handler, capability_system=capability_system)` is
        called to actually run it - reusing every bit of its existing
        behavior (its own preflight check, redundant here but
        harmless since nothing changed in between, RUNNING ->
        COMPLETED/FAILED, syncing the PlanStep via
        PlanManager.update_step_status, refreshing dependents on
        success via PlanManager.refresh_after_step_change - never
        executing them, see requirement 13 - catching handler
        exceptions safely, and recording into `self.history`)
        unchanged; no execution logic is duplicated here (requirement
        4).

        The ExecutionResult `execute_step` returns - already recorded
        into `self.history` by that call - has two extra metadata keys
        added directly onto that same object afterwards (so the copy
        already stored in history reflects them too, per
        ExecutionHistory.record's own "stores the exact object"
        convention):
          - `retry_of`: the `execution_id` of the FAILED execution
            this call retried;
          - `retry_number`: this retry's 1-based position among all
            retries recorded for this step so far (see
            `_next_retry_number` - derived from `self.history`, never
            a global counter, per requirement 7).

        On success, `execute_step` already moves the step to COMPLETED
        (requirement 10) and refreshes dependents' READY/BLOCKED
        status - never executes them (requirement 13). On failure, the
        step is left exactly where it started - FAILED (requirement
        11), ready for another `retry_step` call up to the configured
        maximum. This method never retries on its own on either
        outcome (requirement 12), and never touches any step other
        than the one named."""
        if handler is None or not callable(handler):
            raise TypeError("retry_step requires an explicit callable handler.")

        effective_max_retries = self.max_retries if max_retries is None else max_retries
        if not isinstance(effective_max_retries, int) or isinstance(effective_max_retries, bool) \
                or effective_max_retries < 1:
            raise ValueError("max_retries must be a positive integer.")

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._precondition_failure(
                plan_id, step_id, f"Cannot retry step in unknown plan_id: {plan_id!r}"
            )

        step = self._plan_manager.get_step(plan_id, step_id)
        if step is None:
            return self._precondition_failure(
                plan_id, step_id,
                f"Cannot retry unknown step_id {step_id!r} in plan_id {plan_id!r}",
            )

        if step.status == STEP_STATUS_COMPLETED:
            return self._precondition_failure(
                plan_id, step_id,
                f"Step {step_id!r} is already COMPLETED; nothing to retry.",
            )

        latest = self.history.latest_for_step(plan_id, step_id)
        if latest is None or latest.status != EXEC_STATUS_FAILED:
            return self._precondition_failure(
                plan_id, step_id,
                f"Step {step_id!r} has no prior FAILED execution to retry.",
            )

        next_retry_number = self._next_retry_number(plan_id, step_id)
        if next_retry_number > effective_max_retries:
            failure = self._precondition_failure(
                plan_id, step_id,
                f"Step {step_id!r} has reached the maximum retry count "
                f"({effective_max_retries}); not retrying.",
            )
            failure.metadata["retry_of"] = latest.execution_id
            failure.metadata["retry_number"] = next_retry_number
            failure.metadata["max_retries_reached"] = True
            return failure

        # Allowed: hand the FAILED step back to READY so it can be
        # preflight-checked and, if that passes, run through
        # execute_step's exact same path - no execution logic
        # duplicated here (requirement 4).
        self._plan_manager.update_step_status(plan_id, step_id, STATUS_READY)

        preflight_result = self.preflight.validate_step(plan_id, step_id, capability_system)
        if not preflight_result.valid:
            # Undo the READY flip - this retry never actually ran, so
            # the step must not be left looking runnable (requirement
            # 9: "do not unexpectedly modify the PlanStep").
            self._plan_manager.update_step_status(plan_id, step_id, STEP_STATUS_FAILED)
            failure = self._preflight_failure(preflight_result)
            failure.metadata["retry_of"] = latest.execution_id
            failure.metadata["retry_number"] = next_retry_number
            return failure

        result = self.execute_step(
            plan_id, step_id, handler, capability_system=capability_system
        )
        result.metadata["retry_of"] = latest.execution_id
        result.metadata["retry_number"] = next_retry_number
        return result

    # ------------------------------------------------------------------
    # Event logging (execution_event.py / execution_event_log.py)
    # ------------------------------------------------------------------
    def _record_event(
        self, event_type, plan_id, step_id, execution_id=None,
        message="", data=None, severity=SEVERITY_INFO, metadata=None,
    ):
        """Best-effort recording of one lifecycle ExecutionEvent.
        Building and recording an event can never cause an execution
        attempt to fail (requirement: "event logging must never cause
        the actual execution to fail") - any problem constructing the
        ExecutionEvent itself (an unexpected value that isn't safe
        structured data, an invalid identifier, ...) or recording it
        into `self.event_log` is caught here and represented safely
        (a plain, structured, in-memory note - never a raised
        exception, never a crash, never partial/corrupted execution
        state) rather than ever propagating out of this method. Every
        real execution decision (a PlanStep's status, an
        ExecutionResult's status/output/error) is made entirely
        elsewhere in this class, before or independently of this call,
        so a swallowed event-logging problem never leaves an
        execution attempt in an inconsistent state.

        Returns the recorded ExecutionEvent, or `None` if logging this
        particular event failed - callers never need to check this
        return value; it exists purely for tests/introspection."""
        try:
            event = ExecutionEvent(
                event_type=event_type,
                plan_id=plan_id,
                step_id=step_id,
                execution_id=execution_id,
                message=message,
                data=data,
                severity=severity,
                metadata=metadata,
            )
            return self.event_log.record(event)
        except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
            self._record_event_logging_failure(event_type, plan_id, step_id, exc)
            return None

    def _record_event_logging_failure(self, event_type, plan_id, step_id, exc):
        """A last-resort, itself-never-raising note that event logging
        failed for `event_type`/`plan_id`/`step_id`. Appended to a
        small, in-memory, capped list (`self.event_logging_errors`) as
        a plain, JSON-shaped dict - never a raised exception, never
        the original exception object itself (only its safe type name
        and message, same "never a raw traceback" convention
        `execute_step`'s own handler-failure path already follows).
        If even this bookkeeping fails for some unforeseen reason, it
        is silently swallowed - this method is the true last resort
        and must never be the thing that breaks an execution."""
        try:
            self.event_logging_errors.append(
                {
                    "event_type": str(event_type),
                    "plan_id": str(plan_id) if plan_id is not None else None,
                    "step_id": str(step_id) if step_id is not None else None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            # Keep this list small and bounded - it's a diagnostic
            # aid, never a growing/unbounded log of its own.
            if len(self.event_logging_errors) > 100:
                del self.event_logging_errors[: len(self.event_logging_errors) - 100]
        except Exception:  # noqa: BLE001 - absolute last resort, never propagate
            pass

    def _sync_step_output(self, step, output):
        """Best-effort mirror of a successful ExecutionResult's
        `output` onto `step.output_data` (see planning/plan.py's
        PlanStep.set_output) - the "optionally synchronized" behavior
        `execute_step`/`execute_capability_step` both document. `step`
        is the real PlanStep object already fetched by the caller (may
        be None for a precondition case, though this is only ever
        called from a success path where a real step is guaranteed).
        If `output` isn't safe, JSON-shaped structured data,
        PlanStep.set_output's own TypeError is swallowed here rather
        than turning an already-successful execution into a failure -
        `output_data` is simply left as it was. This never touches any
        *other* step - no automatic data propagation (out of scope for
        this stage)."""
        if step is None:
            return
        try:
            step.set_output(output)
        except TypeError:
            pass

    def _next_retry_number(self, plan_id, step_id):
        """The next 1-based `retry_number` for `plan_id`/`step_id`,
        derived from `self.history` rather than any global/shared
        counter (requirement 7): the highest `retry_number` already
        recorded in this step's history metadata, plus one - or 1 if
        this step has never been retried before. Read-only; records
        nothing itself."""
        previous_numbers = [
            record.metadata.get("retry_number")
            for record in self.history.list_for_step(plan_id, step_id)
            if isinstance(record.metadata.get("retry_number"), int)
        ]
        return (max(previous_numbers) + 1) if previous_numbers else 1

    def _precondition_failure(self, plan_id, step_id, message):
        """A FAILED ExecutionResult for a check that failed before the
        handler was ever called - `started_at` is stamped explicitly
        here (rather than via mark_running, since the result never
        actually runs) so `duration` is still always available. Still
        recorded into `self.history`, same as any other terminal
        result (see execute_step's own docstring note). Used for
        retry-specific eligibility checks (unknown plan/step, already
        COMPLETED, no prior FAILED execution, retry limit reached) -
        see `_preflight_failure` for a PreflightResult's own failed
        checks."""
        result = ExecutionResult(plan_id=plan_id, step_id=step_id, started_at=_now_iso())
        result.mark_failed(message)
        self.history.record(result)
        return result

    def _preflight_failure(self, preflight_result):
        """A FAILED ExecutionResult built from an invalid
        PreflightResult (execution/preflight.py) - same
        `started_at`-stamped-directly, never-RUNNING, always-recorded
        shape as `_precondition_failure`, but for a
        `self.preflight.validate_step` result rather than a
        retry-specific eligibility check. `error` joins every failed
        check's reason (so existing substring-based checks - e.g. a
        step_id or a status name appearing somewhere in the message -
        keep working), and the full structured PreflightResult is
        preserved, unsummarized, in `metadata["preflight"]` for a
        caller that wants to branch on individual `check` names."""
        message = "; ".join(
            f"{fc['check']}: {fc['reason']}" for fc in preflight_result.failed_checks
        )
        result = ExecutionResult(
            plan_id=preflight_result.plan_id,
            step_id=preflight_result.step_id,
            started_at=_now_iso(),
        )
        result.mark_failed(message)
        result.metadata["preflight"] = preflight_result.to_dict()
        self.history.record(result)
        return result

    def _readiness_failure(self, plan_id, step_id, readiness):
        """A FAILED ExecutionResult built from a not-`ready`
        CapabilityReadinessResult (execution/capability_handlers.py) -
        same `started_at`-stamped-directly, never-RUNNING,
        always-recorded shape as `_precondition_failure`/
        `_preflight_failure`, but for
        `execute_capability_step`'s own pre-execution
        capability/handler readiness check rather than a retry
        eligibility check or a plan-level PreflightResult. `error`
        summarizes every missing capability, unavailable capability,
        and missing handler in one message, and the full structured
        readiness report is preserved, unsummarized, in
        `metadata["readiness"]` for a caller that wants the
        per-capability detail (each entry's `capability_name`,
        `available`, `handler_registered`, and `status`)."""
        problems = []
        if readiness.missing_capabilities:
            problems.append(f"missing capabilities: {readiness.missing_capabilities!r}")
        if readiness.unavailable_capabilities:
            problems.append(f"unavailable capabilities: {readiness.unavailable_capabilities!r}")
        if readiness.missing_handlers:
            problems.append(f"missing handlers: {readiness.missing_handlers!r}")
        message = (
            f"Step {step_id!r} is not ready for capability-based execution: "
            + "; ".join(problems)
        )
        result = ExecutionResult(plan_id=plan_id, step_id=step_id, started_at=_now_iso())
        result.mark_failed(message)
        result.metadata["readiness"] = readiness.to_dict()
        self.history.record(result)
        return result

    def _capability_unavailable_failure(self, capability_name, message):
        """A FAILED ExecutionResult for `execute_registered_capability`
        when `capability_name` doesn't exist, is disabled, or has no
        currently-valid handler in `self.executable_capabilities` -
        same `started_at`-stamped-directly, never-RUNNING, always-
        recorded shape as `_precondition_failure`/`_preflight_failure`/
        `_readiness_failure`, but for that method's own pre-execution
        existence/enabled/handler check. `capability_name` is always
        present in `metadata["capability_name"]` (requirement 11), and
        `plan_id`/`step_id` follow the same synthetic
        `CAPABILITY_EXECUTION_PLAN_ID`/`capability_name` pairing
        `execute_registered_capability` itself uses (see that
        constant's own module-level comment)."""
        result = ExecutionResult(
            plan_id=CAPABILITY_EXECUTION_PLAN_ID, step_id=capability_name,
            started_at=_now_iso(),
        )
        result.metadata["capability_name"] = capability_name
        result.mark_failed(message)
        self.history.record(result)
        return result

    def _capability_validation_failure(self, capability_name, validation):
        """A FAILED ExecutionResult for `execute_registered_capability`
        when the supplied `input_data` fails
        `Capability.validate_input` (execution/capability.py) - same
        shape as `_capability_unavailable_failure` above, but for that
        method's own input-validation step rather than its existence/
        enabled/handler check. The handler is never called for this
        case (requirement 7); the full structured
        `CapabilityValidationResult` is preserved, unsummarized, in
        `metadata["validation"]` (requirement 5: "capture ... input
        validation result"), alongside `metadata["capability_name"]`
        (requirement 11)."""
        message = "Input validation failed: " + "; ".join(
            f"{err['field']}: {err['reason']}" for err in validation.errors
        )
        result = ExecutionResult(
            plan_id=CAPABILITY_EXECUTION_PLAN_ID, step_id=capability_name,
            started_at=_now_iso(),
        )
        result.metadata["capability_name"] = capability_name
        result.metadata["validation"] = validation.to_dict()
        result.mark_failed(message)
        self.history.record(result)
        return result
