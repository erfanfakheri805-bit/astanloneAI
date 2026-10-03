"""
Execution - Step Execution Preparation
==========================================
`StepExecutionPreparation` is a small, read-only checkpoint that sits
directly in front of actually running a step:

    PLAN (planning/plan.py) -> PlanStep -> StepExecutionPreparation.prepare
        -> {"prepared": bool, ...} -> [only if prepared] a caller decides
        to actually execute the step (execution/execution_engine.py -
        not called from here)

This module answers exactly one question - "is this one specific step,
right now, actually safe and ready to execute?" - and returns a single,
structured, JSON-shaped answer describing why or why not. It never
decides *to* execute anything itself, never calls a capability
handler, never creates an `ExecutionResult`, and never writes a
PlanStep's status or anything else about it. Those responsibilities
stay exactly where they already are: `ExecutionEngine`
(execution/execution_engine.py) owns actually calling a handler, and
`PlanManager.update_step_status` (planning/plan_manager.py) remains
the one and only place a step's status is ever changed.

Deliberately built entirely on this project's existing execution-
readiness logic rather than a second copy of it (requirement 4/10 -
"reuse existing ... logic"):
  - plan/step existence, step status, dependency resolution, and
    capability availability all reuse `PreflightValidator.validate_step`
    (execution/preflight.py) - itself already built on PlanManager's
    own `_unresolved_dependencies`/`_unavailable_capabilities` helpers,
    never re-derived here;
  - required-handler checking reuses
    `CapabilityHandlerRegistry.check_execution_readiness`
    (execution/capability_handlers.py), which itself optionally
    consults `ExecutableCapabilityRegistry.is_available`
    (execution/executable_registry.py) - the exact same handler-
    readiness question `PlanExecutionCoordinator` already asks (see
    execution/plan_execution_coordinator.py);
  - the `PlanExecutionCoordinator` (execution/plan_execution_coordinator.py)
    is constructed internally purely to reuse its existing, already-
    validated wiring between a `PlanManager`, a `CapabilityHandlerRegistry`,
    and an `ExecutableCapabilityRegistry` - `prepare` itself never asks
    the coordinator "what's next" or "what's the whole plan's state";
    it only borrows those three already-wired collaborators.

Nothing in this module:
  - calls a handler, a capability, or anything registered in
    `CapabilityHandlerRegistry`/`ExecutableCapabilityRegistry`;
  - writes a PlanStep's `status`, `input_data`, or `output_data`, or
    modifies the Plan/PlanManager in any way;
  - creates an `ExecutionResult` or reports a RUNNING/any other
    execution status - this module only ever answers "would this be
    safe to run", never "here is what happened while running it";
  - uses `eval()`, `exec()`, a shell command, `subprocess`, or opens
    any network connection anywhere in this file;
  - trusts a PlanStep's stored `input_data` blindly - it is
    re-validated through `planning.plan.ensure_structured_data`
    (the exact same structured-data safety check `PlanStep.set_input`
    already applies at write time), so a step's input is treated as
    plain data, never as code to run.

Same "plain data in, plain data out" convention the rest of this
project already follows (see `PreflightResult.to_dict`/
`CapabilityReadinessResult.to_dict`): `prepare` returns a plain dict
rather than a bare bool or a formatted message.

`build_context`/`get_dependency_outputs`/`prepare_with_context` (added
this stage) connect this same preparation checkpoint to the Plan Data
Flow layer via `ExecutionContextBuilder`
(execution/execution_context_builder.py), so a step that `prepare`
reports as safe to run can also be handed a fully-built
`ExecutionContext` (execution/execution_context.py) carrying its
already-COMPLETED direct dependencies' outputs - without changing
`prepare`'s own long-standing return shape or behavior at all
(existing callers/tests of `prepare` are entirely unaffected;
`ExecutionEngine`'s existing handlers keep working exactly as before -
see execution_context_builder.py's own module docstring for the full
dependency-output contract).
"""

from planning.plan import ensure_structured_data
from planning.plan_manager import PlanManager
from .plan_execution_coordinator import PlanExecutionCoordinator
from .capability_handlers import CapabilityHandlerRegistry
from .executable_registry import ExecutableCapabilityRegistry
from .execution_context_builder import ExecutionContextBuilder

# Fixed vocabulary for the two failed-check names this module adds on
# top of whatever `PreflightValidator` already contributes (see
# `execution.preflight` for `plan_exists`/`step_exists`/`step_ready`/
# `dependencies_satisfied`/`capabilities_available`) - same "a caller
# can branch on *which* check failed reliably" convention preflight.py
# already establishes.
CHECK_HANDLERS_REGISTERED = "handlers_registered"
CHECK_INPUT_DATA_VALID = "input_data_valid"


class StepExecutionPreparation:
    """Not thread-safe (matches the rest of this project - see
    PlanManager/PreflightValidator/PlanExecutionCoordinator's own
    notes). Safe to use one instance per Core / per conversation
    session, wired to that session's own PlanManager and, optionally,
    the same `CapabilityHandlerRegistry`/`ExecutableCapabilityRegistry`
    an existing `ExecutionEngine`/`PlanExecutionCoordinator` already
    uses, rather than maintaining a second, disagreeing set of
    registered handlers - same "share explicitly, or get your own
    private empty one" convention `PlanExecutionCoordinator` already
    follows (see execution/plan_execution_coordinator.py)."""

    def __init__(
        self, plan_manager, capability_handlers=None, executable_capabilities=None,
        context_builder=None,
    ):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("StepExecutionPreparation requires a PlanManager instance.")
        if capability_handlers is not None and not isinstance(
            capability_handlers, CapabilityHandlerRegistry
        ):
            raise TypeError(
                "StepExecutionPreparation's capability_handlers must be a "
                "CapabilityHandlerRegistry instance."
            )
        if executable_capabilities is not None and not isinstance(
            executable_capabilities, ExecutableCapabilityRegistry
        ):
            raise TypeError(
                "StepExecutionPreparation's executable_capabilities must be an "
                "ExecutableCapabilityRegistry instance."
            )
        if context_builder is not None and not isinstance(
            context_builder, ExecutionContextBuilder
        ):
            raise TypeError(
                "StepExecutionPreparation's context_builder must be an "
                "ExecutionContextBuilder instance."
            )
        self._plan_manager = plan_manager
        # Built purely to reuse its existing PreflightValidator +
        # CapabilityHandlerRegistry + ExecutableCapabilityRegistry
        # wiring (see module docstring) - `prepare` never calls this
        # coordinator's own `get_next_ready_step`/`inspect_execution_state`.
        self._coordinator = PlanExecutionCoordinator(
            plan_manager,
            capability_handlers=capability_handlers,
            executable_capabilities=executable_capabilities,
        )
        # Shared, or a private one wired to this same plan_manager -
        # same "share explicitly, or get your own private one"
        # convention as capability_handlers/executable_capabilities
        # above. Only ever used by build_context/get_dependency_outputs/
        # prepare_with_context below - `prepare` itself never touches
        # this (it stays entirely unchanged by this stage).
        self._context_builder = (
            context_builder if context_builder is not None
            else ExecutionContextBuilder(plan_manager)
        )

    @property
    def preflight(self):
        """The `PreflightValidator` this preparation layer reuses -
        exposed so a caller/test can share or inspect the exact same
        instance, never a second copy of it."""
        return self._coordinator.preflight

    @property
    def capability_handlers(self):
        """The `CapabilityHandlerRegistry` this preparation layer
        reuses for required-handler checks."""
        return self._coordinator.capability_handlers

    @property
    def executable_capabilities(self):
        """The `ExecutableCapabilityRegistry` this preparation layer
        reuses (via `capability_handlers.check_execution_readiness`)
        as an additional, optional source of available handlers."""
        return self._coordinator.executable_capabilities

    @property
    def context_builder(self):
        """The `ExecutionContextBuilder` this preparation layer reuses
        for `build_context`/`get_dependency_outputs`/
        `prepare_with_context` below - exposed so a caller/test can
        share or inspect the exact same instance, never a second copy
        of it."""
        return self._context_builder

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _result(self, plan_id, step_id, prepared, status, capabilities,
                input_data, failed_checks, warnings):
        """The one place that shapes a `prepare` return value, so a
        successful and a failed preparation both come back in exactly
        the same structured shape (requirement 6)."""
        return {
            "prepared": bool(prepared),
            "plan_id": plan_id,
            "step_id": step_id,
            "status": status,
            "capabilities": list(capabilities),
            "input_data": input_data,
            "failed_checks": [dict(fc) for fc in failed_checks],
            "warnings": list(warnings),
        }

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------
    def prepare(self, plan_id, step_id, capability_system=None):
        """Validate and prepare the single PlanStep named by
        `plan_id`/`step_id` for execution, without executing it.

        Read-only throughout: never writes a PlanStep's status or
        data, never modifies the Plan, never registers/enables/
        installs/calls a capability or a handler, and never creates an
        `ExecutionResult` - see module docstring. Never raises for an
        unknown `plan_id`/`step_id`; that outcome is reported as
        `prepared=False` with an explanatory failed check instead
        (same "a query that should always have a structured answer"
        convention `PreflightValidator.validate_step` already follows).

        Checks run, all reusing existing logic (requirement 4/5),
        never a second copy of any of it:
          1. `plan_id` names a known plan, and (2) `step_id` names a
             known step within it - both via
             `PreflightValidator.validate_step`. If either is
             missing, preparation stops here: there is no real step
             to report a `status`/`capabilities`/`input_data` for, so
             those come back as `None`/`[]`/`None` and
             `preflight_result.failed_checks` is the complete answer.
          3. Once a real step is in hand, every remaining check is
             evaluated independently (never short-circuited by an
             earlier one), so a single result can report several
             problems at once:
               - the step's current status is READY, and its
                 dependencies are resolved, and its required
                 capabilities are available - all three still via the
                 same `PreflightValidator.validate_step` call above
                 (`step_ready`/`dependencies_satisfied`/
                 `capabilities_available`);
               - a handler is registered/available for every required
                 capability, via
                 `CapabilityHandlerRegistry.check_execution_readiness`
                 (`handlers_registered` - added by this module, since
                 preflight itself never checks handlers);
               - the step's stored `input_data` is still safe,
                 structured data, via `planning.plan.ensure_structured_data`
                 (`input_data_valid` - added by this module, as a
                 defensive re-check; `PlanStep.set_input` already
                 enforces this at write time, so this only ever
                 matters for state that bypassed that safety check).
             A step with no `input_data` recorded is not, on its own,
             a failed check - not every step needs input, and
             `PlanStep.input_data` legitimately defaults to `None`.

        Returns a dict:
            {
                "prepared": bool,          # True only if every check passed
                "plan_id": str,
                "step_id": str,
                "status": str or None,     # the step's current status, or
                                            # None if plan/step unknown
                "capabilities": [str, ...],  # step.required_capabilities,
                                              # or [] if plan/step unknown
                "input_data": ... or None, # the step's (re-validated)
                                            # input_data, or None
                "failed_checks": [{"check": ..., "reason": ...}, ...],
                "warnings": [str, ...],
            }

        `prepared` is True only when `failed_checks` is empty. On
        success, this method still never executes the step, never
        calls a capability handler, and never creates an
        `ExecutionResult` with a RUNNING (or any other) status - it
        only reports that doing so would currently be safe. On
        failure, the plan and step are left completely untouched -
        neither this method nor anything it calls writes a step's
        status or data."""
        preflight_result = self.preflight.validate_step(plan_id, step_id, capability_system)

        step = self._plan_manager.get_step(plan_id, step_id)
        if step is None:
            # Unknown plan and/or step - preflight_result.failed_checks
            # already names exactly which (plan_exists/step_exists);
            # there's no real step to check anything else about.
            return self._result(
                plan_id, step_id, False, None, [], None,
                preflight_result.failed_checks, preflight_result.warnings,
            )

        failed_checks = list(preflight_result.failed_checks)
        warnings = list(preflight_result.warnings)

        # Required handlers - reuses CapabilityHandlerRegistry's own
        # readiness report (and, through it, ExecutableCapabilityRegistry)
        # rather than re-deriving handler-availability logic here.
        readiness = self.capability_handlers.check_execution_readiness(
            step, capability_system, self.executable_capabilities
        )
        warnings.extend(readiness.warnings)
        if readiness.missing_handlers:
            failed_checks.append({
                "check": CHECK_HANDLERS_REGISTERED,
                "reason": (
                    f"Step {step_id!r} has no registered/available handler "
                    f"for required capabilities: {readiness.missing_handlers!r}."
                ),
            })
        # readiness.missing_capabilities/unavailable_capabilities are a
        # more granular, per-capability restatement of exactly the same
        # underlying problem preflight's own capabilities_available
        # check already reported above - surfaced here only as extra
        # warnings (never a second failed check for the same problem).
        if capability_system is not None:
            for name in readiness.missing_capabilities:
                warnings.append(
                    f"Capability {name!r} required by step {step_id!r} is not "
                    "registered in capability_system."
                )
            for name in readiness.unavailable_capabilities:
                warnings.append(
                    f"Capability {name!r} required by step {step_id!r} is "
                    "registered but currently disabled."
                )

        # Step input data - defensively re-validated as safe, structured
        # data (never evaluated as code; no eval()/exec()/shell/network
        # anywhere in this check). PlanStep.set_input already enforces
        # this at write time, so this only ever catches state that
        # bypassed that safety check.
        input_data = step.input_data
        if input_data is not None:
            try:
                input_data = ensure_structured_data(input_data)
            except TypeError as exc:
                failed_checks.append({
                    "check": CHECK_INPUT_DATA_VALID,
                    "reason": (
                        f"Step {step_id!r} input_data is not safe structured "
                        f"data: {exc}"
                    ),
                })

        prepared = not failed_checks

        return self._result(
            plan_id, step_id, prepared, step.status,
            list(step.required_capabilities), input_data,
            failed_checks, warnings,
        )

    # ------------------------------------------------------------------
    # Plan Data Flow <-> ExecutionContext integration (added this stage)
    # ------------------------------------------------------------------
    # Both of the following simply delegate to this preparation layer's
    # own ExecutionContextBuilder (see __init__/context_builder above)
    # - never a second copy of that logic - so a caller already working
    # through StepExecutionPreparation doesn't need to separately
    # import/construct an ExecutionContextBuilder for the common case
    # of a plan_manager it already shares with this instance.
    def get_dependency_outputs(self, plan_id, step_id):
        """See `ExecutionContextBuilder.get_dependency_outputs` - this
        is a direct, unmodified delegation to `self.context_builder`.
        Read-only; never raises for an unknown `plan_id`/`step_id`
        (reported as `success=False` instead)."""
        return self._context_builder.get_dependency_outputs(plan_id, step_id)

    def build_context(self, plan_id, step_id, capability_name=None, execution_id=None):
        """See `ExecutionContextBuilder.build_context` - this is a
        direct, unmodified delegation to `self.context_builder`. Raises
        ValueError for an unknown `plan_id`/`step_id` (same convention
        `ExecutionContextBuilder.build_context` itself documents)."""
        return self._context_builder.build_context(
            plan_id, step_id, capability_name=capability_name, execution_id=execution_id,
        )

    def prepare_with_context(
        self, plan_id, step_id, capability_name=None, execution_id=None,
        capability_system=None,
    ):
        """Exactly `prepare(plan_id, step_id, capability_system)`
        (requirement 14: unchanged - see that method's own docstring
        for the complete check list and return shape), plus one
        additional `"context"` key: a fully-built `ExecutionContext`
        (via `build_context` above) when `prepared` is True, or `None`
        when it isn't - a step this checkpoint didn't consider safe to
        run is never handed a context describing it either.

        `prepare`'s own return value is never mutated in place; this
        returns a fresh dict (`prepare`'s own keys, unchanged, plus
        `"context"`), so a caller relying on `prepare`'s exact,
        long-standing shape - including anything already calling
        `prepare` directly - is completely unaffected by this method
        existing (requirement: "keep ExecutionEngine backward
        compatible; existing handlers must continue working").

        Building the context here never re-runs any check `prepare`
        itself already ran, and never executes the step, a dependency,
        or a capability handler - see `ExecutionContextBuilder.
        build_context`'s own docstring for the full read-only
        contract.

        Returns a dict:
            {
                "prepared": bool,
                "plan_id": str,
                "step_id": str,
                "status": str or None,
                "capabilities": [str, ...],
                "input_data": ... or None,
                "failed_checks": [{"check": ..., "reason": ...}, ...],
                "warnings": [str, ...],
                "context": ExecutionContext or None,
            }
        """
        result = dict(self.prepare(plan_id, step_id, capability_system))
        context = None
        if result["prepared"]:
            context = self._context_builder.build_context(
                plan_id, step_id,
                capability_name=capability_name, execution_id=execution_id,
            )
        result["context"] = context
        return result
