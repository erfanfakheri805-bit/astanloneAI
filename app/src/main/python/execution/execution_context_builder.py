"""
Execution - Execution Context Builder (Plan Data Flow <-> ExecutionContext)
===============================================================================
`ExecutionContextBuilder` is the small, explicit bridge between the
existing Plan Data Flow layer (planning/plan_manager.py's
`propagate_step_output`, planning/data_flow_manager.py's
`DataFlowManager`) and `ExecutionContext` (execution/execution_context.py):

    PLAN DATA FLOW (already-stored PlanStep.output_data)
        -> ExecutionContextBuilder.get_dependency_outputs (read-only lookup)
        -> ExecutionContextBuilder.build_context (wraps them into one
           ExecutionContext.previous_outputs, alongside the step's own,
           separate input_data)
        -> [only when a caller later explicitly executes that step] a
           handler (execution/execution_engine.py - not called from here)

Before this stage, `ExecutionContext.previous_outputs` could only ever
be populated with outputs produced *earlier in the same
`execute_capability_step` loop* (see execution_engine.py's
`_safe_previous_outputs` - one step's own required-capability handlers
sharing a context with each other). This module extends that same
`previous_outputs` field to also carry a step's *cross-step*
dependency outputs - what its already-COMPLETED direct dependencies
(within the same Plan) already produced - collected the same
structured, read-only way `DataFlowManager.propagate_completed_step`
already collects a source step's direct *dependents*, just walked in
the opposite direction (a step's own `dependencies`, not who depends
on it).

"Direct dependencies" means exactly the step_ids listed in the target
step's own `PlanStep.dependencies` - never a dependency's own
dependencies (no transitive collection), and never a step that merely
happens to exist elsewhere in the same plan. A dependency only ever
contributes an output when all of the following hold (requirement 3):
  - it is looked up within the *same* `plan_id` as the target step
    (this module never looks across plans - `PlanManager.get_step`
    already scopes every lookup to one `plan_id`);
  - it is named in the target step's own `dependencies` list (never a
    step that merely happens to exist alongside it - see
    `get_dependency_outputs` below, which only ever iterates
    `step.dependencies`, the exact same list
    `PlanManager._unresolved_dependencies` already treats as the
    complete, authoritative set for that step);
  - its `status` is exactly `STATUS_COMPLETED` (planning/plan.py) -
    never IN_PROGRESS/FAILED/PENDING/READY/BLOCKED/CANCELLED;
  - it has real, already-validated `output_data` stored on it (never
    `None` - a dependency that completed without recording an output
    contributes nothing; see requirement 10, "never invent an
    output").

Like every module in this project that touches step data, this one
only ever *reads* already-produced, already-validated structured data
(`PlanStep.output_data`/`input_data`, via `PlanStep.get_output`/
`get_input` - see planning/plan.py) and hands it, unmodified, to a
fresh `ExecutionContext` (whose own constructor re-validates everything
through `ensure_structured_data` regardless - see execution_context.py).
It never writes a PlanStep's `status`, `input_data`, or `output_data`,
never calls `PlanManager.propagate_step_output`/
`DataFlowManager.propagate_completed_step` (this is a read path, not a
propagation path - propagation still only ever happens through those
two, entirely unchanged, existing methods), never executes a step or a
capability handler, and never touches any step beyond the target
step's own direct dependencies.

Nothing in this module:
  - uses eval(), exec(), subprocess, a shell command, or opens any
    network connection;
  - calls an AI API, a capability, or a capability handler;
  - automatically executes a dependency, the target step, or any other
    step - `build_context`/`get_dependency_outputs` only ever *read*
    already-recorded state; deciding to actually execute the target
    step remains entirely a caller's job (execution_engine.py/
    step_execution_preparation.py - not called from here);
  - automatically propagates an output to any step other than the one
    `build_context`/`get_dependency_outputs` was explicitly asked
    about - no plan-wide cascade happens here (that remains
    `DataFlowManager.propagate_completed_step`'s own, separate,
    explicitly-invoked job, entirely unchanged by this module).

Deterministic (requirement: "remain deterministic"): given the same
Plan/PlanStep state, `get_dependency_outputs`/`build_context` always
produce the same `outputs`/`source_steps`/`warnings` - no randomness,
no clock/network/filesystem reads (the only place any randomness could
enter is `ExecutionContext`'s own optional fresh `execution_id`
generation, when one isn't supplied - the exact same documented
caveat `ExecutionContext.__init__` itself already carries).
"""

from planning.plan_manager import PlanManager
from planning.data_flow_manager import DataFlowManager
from planning.plan import STATUS_COMPLETED

from .execution_context import ExecutionContext

# Metadata key `build_context` uses to surface any warnings collected
# while gathering dependency outputs (e.g. a dependency with no
# output, or one that isn't COMPLETED yet) on the ExecutionContext
# itself, without ever mixing them into `previous_outputs` (which must
# only ever hold real, structured step outputs - never diagnostic
# text). Only ever set when there is at least one warning to report -
# see `build_context` below.
DEPENDENCY_WARNINGS_METADATA_KEY = "dependency_warnings"


class ExecutionContextBuilder:
    """Not thread-safe (matches the rest of this project - see
    PlanManager/DataFlowManager/StepExecutionPreparation's own notes).
    Constructed with a reference to the PlanManager whose plans/steps
    it reads from - same "wired to the manager it reads from"
    relationship DataFlowManager already has with PlanManager - plus,
    optionally, an existing `DataFlowManager` to share (e.g. the same
    instance a caller's `ExecutionEngine`/session already uses) rather
    than silently constructing a second, disagreeing one. This class
    keeps no state of its own beyond those two references; every
    lookup re-reads current Plan/PlanStep state fresh each call."""

    def __init__(self, plan_manager, data_flow_manager=None):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError(
                "ExecutionContextBuilder requires a PlanManager instance."
            )
        if data_flow_manager is not None and not isinstance(
            data_flow_manager, DataFlowManager
        ):
            raise TypeError(
                "ExecutionContextBuilder's data_flow_manager must be a "
                "DataFlowManager instance."
            )
        self._plan_manager = plan_manager
        # Not currently used to *derive* dependency outputs (dependency
        # collection below only ever needs plan_manager.get_step - see
        # get_dependency_outputs), but shared/exposed so a caller never
        # ends up with two disagreeing DataFlowManager instances over
        # the same PlanManager - same "share explicitly, or get your
        # own private one" convention StepExecutionPreparation already
        # follows for its own PlanExecutionCoordinator (see
        # step_execution_preparation.py).
        self._data_flow_manager = (
            data_flow_manager if data_flow_manager is not None
            else DataFlowManager(plan_manager)
        )

    @property
    def plan_manager(self):
        return self._plan_manager

    @property
    def data_flow_manager(self):
        return self._data_flow_manager

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _dependency_result(self, success, outputs, source_steps, warnings):
        """The one place that shapes a `get_dependency_outputs` return
        value, so a missing-plan/missing-step early exit and the full
        collection loop both return exactly the same structured,
        JSON-shaped record (requirement 9)."""
        return {
            "success": bool(success),
            "outputs": dict(outputs),
            "source_steps": list(source_steps),
            "warnings": list(warnings),
        }

    # ------------------------------------------------------------------
    # Read-only dependency-output collection (requirements 2/3/10/11)
    # ------------------------------------------------------------------
    def get_dependency_outputs(self, plan_id, step_id):
        """Collect the already-produced `output_data` of every step in
        `plan_id` that `step_id` directly depends on and that is
        actually eligible to contribute one (requirement 3): the same
        plan, an actual entry in `step_id`'s own `dependencies` list,
        `STATUS_COMPLETED`, and real stored `output_data`.

        Never raises for an unknown `plan_id`/`step_id` - reported
        back as `success=False` with an explanatory warning instead
        (same "a read-only query always has a structured answer"
        convention `PreflightValidator.validate_step` and
        `StepExecutionPreparation.prepare` already follow), since a
        caller may reasonably probe an id before knowing whether it
        exists.

        For each of `step_id`'s declared dependencies, in
        `step.dependencies` order (requirement: "correct
        source_steps"):
          - a dependency that doesn't exist as a step in this plan is
            skipped and recorded, with a reason, in `warnings`
            (requirement 11: a dependency that isn't COMPLETED - which
            includes one that doesn't exist at all - is never treated
            as available);
          - a dependency that exists but isn't `STATUS_COMPLETED` is
            skipped and recorded, with a reason, in `warnings`
            (requirement 11);
          - a dependency that is `STATUS_COMPLETED` but has no stored
            `output_data` (`get_output()` returns `None`) is skipped
            and recorded, with a reason, in `warnings` - its output is
            never invented (requirement 10);
          - only a dependency that is `STATUS_COMPLETED` *and* has
            real stored output contributes an entry: `outputs[dep_id]`
            is set to that dependency's own `get_output()`
            (unmodified - never merged, summarized, or otherwise
            transformed), and `dep_id` is appended to `source_steps`.

        A step with no dependencies at all (`step.dependencies == []`)
        simply produces `success=True`, empty `outputs`/`source_steps`,
        and no warnings - not an error, and not, on its own, a reason
        to warn.

        Never touches any step that isn't actually named in
        `step_id`'s own `dependencies` (requirement 7: no propagation
        to/collection from unrelated steps) - a step that happens to
        be COMPLETED elsewhere in the same plan, but that `step_id`
        never declared a dependency on, is never inspected at all.

        Returns a dict:
            {
                "success": bool,       # False only for an unknown plan/step
                "outputs": {step_id: output_data, ...},
                "source_steps": [step_id, ...],  # keys of `outputs`, in
                                                  # step.dependencies order
                "warnings": [str, ...],
            }
        """
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._dependency_result(
                False, {}, [],
                [f"Cannot collect dependency outputs for unknown plan_id: {plan_id!r}."],
            )

        step = self._plan_manager.get_step(plan_id, step_id)
        if step is None:
            return self._dependency_result(
                False, {}, [],
                [
                    f"Cannot collect dependency outputs for unknown step_id "
                    f"{step_id!r} in plan_id {plan_id!r}."
                ],
            )

        outputs = {}
        source_steps = []
        warnings = []

        for dep_id in step.dependencies:
            # Scoped to this same plan_id only - PlanManager.get_step
            # never looks outside the plan it's given (requirement 3:
            # "belong to the same plan").
            dep_step = self._plan_manager.get_step(plan_id, dep_id)
            if dep_step is None:
                warnings.append(
                    f"Dependency {dep_id!r} of step {step_id!r} does not "
                    f"exist in plan {plan_id!r}; no output available."
                )
                continue
            if dep_step.status != STATUS_COMPLETED:
                warnings.append(
                    f"Dependency {dep_id!r} of step {step_id!r} is not "
                    f"COMPLETED (current status: {dep_step.status!r}); its "
                    "output is not available."
                )
                continue
            output = dep_step.get_output()
            if output is None:
                warnings.append(
                    f"Dependency {dep_id!r} of step {step_id!r} is COMPLETED "
                    "but has no stored output_data; nothing to include."
                )
                continue
            outputs[dep_id] = output
            source_steps.append(dep_id)

        return self._dependency_result(True, outputs, source_steps, warnings)

    # ------------------------------------------------------------------
    # ExecutionContext construction (requirements 4/8/12)
    # ------------------------------------------------------------------
    def build_context(
        self, plan_id, step_id, capability_name=None, execution_id=None,
    ):
        """Validate `plan_id`/`step_id` name a real plan/step, collect
        that step's valid dependency outputs (via
        `get_dependency_outputs` above - never a second copy of that
        logic), and return one fresh `ExecutionContext`
        (execution/execution_context.py) describing an execution
        attempt for that step.

        Raises ValueError - and builds nothing - if `plan_id`/
        `step_id` don't resolve to a real step (same convention
        `PlanManager.set_step_input`/`update_step_status` already use
        for an explicit, caller-driven action that requires a real
        step to act on - unlike `get_dependency_outputs`'s own
        read-only-probe convention above, building a context is a
        request for a real object describing a real step, not a
        query that might reasonably be answered "not found").

        The returned context's `input_data` is `step_id`'s own,
        unmodified explicit `input_data` (`step.get_input()`) -
        completely separate from `previous_outputs`, which only ever
        holds the collected dependency outputs (requirement 12: never
        overwritten, never merged together). `capability_name` and
        `execution_id` are passed straight through to
        `ExecutionContext.__init__` (optional; a fresh `execution_id`
        is generated there when omitted).

        Any warnings collected while gathering dependency outputs
        (e.g. a dependency that isn't COMPLETED, or has no output) are
        attached to the returned context as
        `metadata["dependency_warnings"]` - informational only, and
        only ever set when there is at least one - so a caller can see
        *why* a given dependency's output is missing without that
        information ever being mistaken for a real previous output.

        Never executes `step_id`, never executes any of its
        dependencies, never writes any step's status/input_data/
        output_data, and never calls a capability handler - building a
        context is entirely read-only (requirements 6/7).

        Deterministic given the same Plan/PlanStep state (see module
        docstring) - the only caveat being the same fresh-`execution_id`
        randomness `ExecutionContext.__init__` already documents when
        `execution_id` isn't supplied here.

        Returns:
            ExecutionContext
        """
        if self._plan_manager.get_plan(plan_id) is None:
            raise ValueError(
                f"Cannot build ExecutionContext for unknown plan_id: {plan_id!r}."
            )
        step = self._plan_manager.get_step(plan_id, step_id)
        if step is None:
            raise ValueError(
                f"Cannot build ExecutionContext for unknown step_id "
                f"{step_id!r} in plan_id {plan_id!r}."
            )

        dependency_result = self.get_dependency_outputs(plan_id, step_id)

        context = ExecutionContext(
            plan_id=plan_id,
            step_id=step_id,
            capability_name=capability_name,
            input_data=step.get_input(),
            previous_outputs=dependency_result["outputs"],
            execution_id=execution_id,
        )
        if dependency_result["warnings"]:
            context.set_metadata(
                DEPENDENCY_WARNINGS_METADATA_KEY, dependency_result["warnings"]
            )
        return context
