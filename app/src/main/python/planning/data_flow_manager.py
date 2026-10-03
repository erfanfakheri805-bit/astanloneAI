"""
Planning - Data Flow Manager
===============================
`DataFlowManager` is the small, plan-wide counterpart to
`PlanManager.propagate_step_output` (planning/plan_manager.py):

    PLAN MANAGER.propagate_step_output(one source, one target)
        -> DATA FLOW MANAGER.propagate_completed_step(one source,
           every *direct* dependent of that source)

Where `propagate_step_output` handles exactly one source/target pair,
`propagate_completed_step` is the convenience a caller reaches for
once a step finishes: "this step just completed - copy its output to
whichever steps are actually waiting on it, and tell me what
happened." It never invents its own propagation rule; every single
copy it might perform is delegated to
`PlanManager.propagate_step_output` (see that method's own docstring
for the full source/target contract - existence, COMPLETED status,
declared dependency, no-overwrite-on-conflict), so there is exactly
one place in the project that decides whether a given source/target
pair is allowed to propagate. This module's only added value is
*finding* the right target steps (a Plan's direct dependents of one
source) and collecting the per-step outcomes into one structured
report.

"Direct dependents" means exactly the steps in the same Plan whose own
`dependencies` list names the source step - never a dependent's own
dependents (no transitive/cascading propagation), and never a step
that merely happens to exist alongside the source. This is what keeps
propagation "controlled" at the plan level, the same way
`propagate_step_output`'s own dependency check keeps it controlled at
the single-pair level (see planning/plan.py's PlanStep.dependencies
and plan_manager.py's `propagate_step_output`).

Like every manager in this project, this one only ever reads/copies
already-produced, already-validated structured data
(execution/... produces it, PlanStep.output_data/input_data - see
planning/plan.py - store it): it never executes a step, never changes
which steps depend on which (a Plan's dependency graph, once created,
is never edited here), and never touches any step outside the
source's own direct dependents. Automatic *execution* of a plan, and
automatic propagation triggered by something other than an explicit
call to `propagate_completed_step`, are both out of scope for this
stage - see plan.py's and plan_manager.py's own module docstrings for
where execution-related responsibilities belong.
"""

from .plan_manager import PlanManager
from .plan import STATUS_COMPLETED


class DataFlowManager:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/GoalManager's own note). Constructed with a reference
    to the PlanManager whose plans/steps it operates on - same
    "wired to the manager it reads from" relationship ExecutionEngine
    already has with PlanManager (see execution/execution_engine.py) -
    so this class never needs, and never keeps, any state of its own
    beyond that one reference."""

    def __init__(self, plan_manager):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("DataFlowManager requires a PlanManager instance.")
        self._plan_manager = plan_manager

    # ------------------------------------------------------------------
    # Plan-wide propagation from one completed step
    # ------------------------------------------------------------------
    def _result(
        self, plan_id, source_step_id, propagated_steps, skipped_steps, conflicts, warnings,
    ):
        """The one place that shapes a propagate_completed_step return
        value, so every early-exit (missing/not-completed source, no
        dependents) and the full-loop path all return exactly the same
        structured, JSON-shaped record (requirement 6)."""
        return {
            "plan_id": plan_id,
            "source_step_id": source_step_id,
            "propagated_steps": propagated_steps,
            "skipped_steps": skipped_steps,
            "conflicts": conflicts,
            "warnings": warnings,
        }

    def propagate_completed_step(self, plan_id, source_step_id):
        """For the COMPLETED step named by `plan_id`/`source_step_id`,
        attempt to propagate its `output_data` to every step in the
        same plan that directly declares it as a dependency - each
        attempt going through `PlanManager.propagate_step_output`
        (requirement 11: no separate copy of that logic here).

        Raises ValueError only for an unknown `plan_id` - same
        convention as `propagate_step_output`/
        `check_plan_readiness`/`check_plan_capabilities`, since a plan
        that doesn't exist has nothing here to operate on at all. A
        missing or not-yet-COMPLETED *source step*, by contrast, is
        reported back as a warning in the structured result below
        (never raised, and never treated as a reason to guess at
        propagating anyway) - the exact same "step-level problems are
        structured explanations, not exceptions" convention
        `propagate_step_output` already follows for its own
        source-side checks.

        Only ever inspects the source step's *direct* dependents (see
        module docstring) - a step's own dependents-of-dependents are
        never touched, and a step that doesn't name `source_step_id`
        in its `dependencies` is never touched either, matching
        `propagate_step_output`'s own "no propagation between
        unrelated steps" rule. Never edits any step's `dependencies`
        (requirement 8), never executes any step (requirement 7), and
        never modifies anything outside those direct dependents
        (requirement 9).

        For each direct dependent, in `plan.steps` order:
          - a successful propagation (dependent had no input_data yet)
            adds that step's `step_id` to `propagated_steps`;
          - a dependent that already has `input_data` is left
            untouched (never overwritten) and recorded, with
            `propagate_step_output`'s own reason, in `conflicts`;
          - any other refusal `propagate_step_output` might report for
            that pair (there normally isn't one, since every step
            iterated here is already confirmed to be a direct
            dependent of an already-COMPLETED source with real
            output) is recorded, with its reason, in `skipped_steps`
            instead - kept as its own bucket so a genuine conflict
            (the one outcome requirement 5 calls out by name) is never
            confused with anything else.
        A source step with no direct dependents at all propagates
        nothing and adds a single explanatory entry to `warnings`,
        rather than treating "nothing to do" as an error.

        Deterministic and side-effect-free beyond the propagation
        itself (requirement 10): no randomness, no clock/network/
        filesystem reads, and, on an early exit (unknown/not-completed
        source), no calls into propagate_step_output at all.

        Returns a dict:
            {
                "plan_id": plan_id,
                "source_step_id": source_step_id,
                "propagated_steps": [step_id, ...],
                "skipped_steps": [{"step_id": ..., "reason": ...}, ...],
                "conflicts": [{"step_id": ..., "reason": ...}, ...],
                "warnings": [str, ...],
            }
        """
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot propagate in unknown plan_id: {plan_id!r}")

        source = self._plan_manager.get_step(plan_id, source_step_id)
        if source is None:
            return self._result(
                plan_id, source_step_id, [], [], [],
                [f"Source step {source_step_id!r} does not exist in plan {plan_id!r}."],
            )

        if source.status != STATUS_COMPLETED:
            return self._result(
                plan_id, source_step_id, [], [], [],
                [
                    f"Source step {source_step_id!r} is not COMPLETED "
                    f"(current status: {source.status!r}); nothing propagated."
                ],
            )

        dependents = [step for step in plan.steps if source_step_id in step.dependencies]

        warnings = []
        if not dependents:
            warnings.append(
                f"No steps in plan {plan_id!r} declare {source_step_id!r} as a dependency."
            )

        propagated_steps = []
        skipped_steps = []
        conflicts = []
        for step in dependents:
            outcome = self._plan_manager.propagate_step_output(
                plan_id, source_step_id, step.step_id
            )
            if outcome["success"]:
                propagated_steps.append(step.step_id)
            elif outcome["reason"] and "already has input_data" in outcome["reason"]:
                conflicts.append({"step_id": step.step_id, "reason": outcome["reason"]})
            else:
                skipped_steps.append({"step_id": step.step_id, "reason": outcome["reason"]})

        return self._result(
            plan_id, source_step_id, propagated_steps, skipped_steps, conflicts, warnings,
        )
