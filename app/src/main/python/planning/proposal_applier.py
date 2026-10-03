"""
Planning - Proposal Applier
==============================
`ProposalApplier` answers the question directly downstream of
`AdaptivePlanProposal` (planning/adaptive_plan_proposal.py) - "given
one already-validated `ProposedChange`, how is it safely written onto
the `Plan` it targets?":

    PLAN + PROPOSED CHANGE
        -> AdaptivePlanProposal.validate_proposal  (read-only: is this
           change well-formed and does it target a real step?)
        -> ProposalApplier.apply_change  (this module: mutate exactly
           the one field the change describes - nothing else)

This is deliberately the smallest possible applier, not a general
proposal-execution engine: it supports exactly seven change types -
`ADD_CAPABILITY_REQUIREMENT`, `REMOVE_CAPABILITY_REQUIREMENT`,
`PROVIDE_INPUT`, `PROVIDE_OUTPUT`, `REORDER_STEP`, `ADD_DEPENDENCY`,
and `REMOVE_DEPENDENCY` - and each one does exactly one thing. The
first two add or remove a single capability name from one PlanStep's
`required_capabilities` list; `PROVIDE_INPUT`/`PROVIDE_OUTPUT` set a
PlanStep's `input_data`/`output_data` respectively (via
`PlanStep.set_input`/`set_output`, so the exact same
`ensure_structured_data` safety check already used everywhere else in
`planning/plan.py` applies here too) - but only when the step has no
`input_data`/`output_data` yet, so an already-recorded value is never
silently overwritten; `REORDER_STEP` moves the target `PlanStep` to a
different index within `plan.steps`, touching only that list's order
- the step object itself, and every other step's own fields, are left
exactly as they were; `ADD_DEPENDENCY` appends one step_id to the
target `PlanStep`'s own `dependencies` list (the same list
`plan_manager.py`'s dependency resolution already reads - no second
dependency system), after rejecting a self-dependency, a duplicate,
or anything that would create a cycle; `REMOVE_DEPENDENCY` removes one
already-present step_id from that same list, rejecting anything not
currently in it, and (matching `AdaptivePlanProposal`'s own use of
this change type to clear a dangling reference) never requires the
removed id to still match a real step. None of these ever creates or
removes a step, never changes `status` (a step's own or the plan's),
never executes anything, and never talks to the network or an
external AI API - same "inert, structural-only" boundary
`AdaptivePlanProposal` itself already draws around proposing a change
in the first place. Only `ADD_DEPENDENCY`/`REMOVE_DEPENDENCY` touch
`dependencies`, and even then only ever the single target step's own
list.

The caller is expected to have already run the change through
`AdaptivePlanProposal.validate_proposal` (or otherwise confirmed it is
well-formed) before calling `apply_change` - this module trusts that
upstream check for judgment calls like "is this confidence a
reasonable number", but still performs its own small, defensive
checks on the handful of fields it actually needs (a supported
`change_type`, a `target_step_id` that exists on `plan`, and either a
non-empty `capability` string, safe `input_data`/`output_data`, or a
valid `new_position` integer, depending on `change_type`) so a
malformed or unsupported change is safely rejected - reported back,
never raised - rather than silently corrupting plan state.
"""

from .plan import Plan
from .adaptive_plan_proposal import (
    CHANGE_ADD_CAPABILITY_REQUIREMENT,
    CHANGE_REMOVE_CAPABILITY_REQUIREMENT,
    CHANGE_PROVIDE_INPUT,
    CHANGE_PROVIDE_OUTPUT,
    CHANGE_REORDER_STEP,
    CHANGE_ADD_DEPENDENCY,
    CHANGE_REMOVE_DEPENDENCY,
)

# The only change types this applier knows how to apply (requirement:
# "support ONLY these change types"). Anything else - including every
# other member of adaptive_plan_proposal.ALL_CHANGE_TYPES - is safely
# rejected by apply_change below.
SUPPORTED_CHANGE_TYPES = (
    CHANGE_ADD_CAPABILITY_REQUIREMENT,
    CHANGE_REMOVE_CAPABILITY_REQUIREMENT,
    CHANGE_PROVIDE_INPUT,
    CHANGE_PROVIDE_OUTPUT,
    CHANGE_REORDER_STEP,
    CHANGE_ADD_DEPENDENCY,
    CHANGE_REMOVE_DEPENDENCY,
)

# Controlled reason codes for the structured result apply_change
# returns - same "each outcome names exactly which case it is"
# convention execution/preflight.py's CHECK_* names and
# adaptive_plan_proposal.py's CHECK_* names already use.
RESULT_APPLIED = "applied"
RESULT_ALREADY_PRESENT = "already_present"
RESULT_NOT_PRESENT = "not_present"
RESULT_UNSUPPORTED_CHANGE_TYPE = "unsupported_change_type"
RESULT_UNKNOWN_TARGET_STEP = "unknown_target_step"
RESULT_INVALID_CAPABILITY = "invalid_capability"
RESULT_INVALID_PLAN = "invalid_plan"
RESULT_INVALID_CHANGE = "invalid_change"
RESULT_INPUT_ALREADY_PRESENT = "input_already_present"
RESULT_INVALID_INPUT_DATA = "invalid_input_data"
RESULT_OUTPUT_ALREADY_PRESENT = "output_already_present"
RESULT_INVALID_OUTPUT_DATA = "invalid_output_data"
RESULT_INVALID_POSITION = "invalid_position"
RESULT_INVALID_DEPENDENCY = "invalid_dependency"
RESULT_UNKNOWN_DEPENDENCY_STEP = "unknown_dependency_step"
RESULT_SELF_DEPENDENCY = "self_dependency"
RESULT_DEPENDENCY_ALREADY_PRESENT = "dependency_already_present"
RESULT_DEPENDENCY_CYCLE = "dependency_cycle"
RESULT_DEPENDENCY_NOT_PRESENT = "dependency_not_present"


class ProposalApplier:
    """Applies exactly one already-validated `ProposedChange`
    (planning/adaptive_plan_proposal.py) to a `Plan` - see
    `SUPPORTED_CHANGE_TYPES` for which. Stateless - holds no
    collaborators and no instance state - so a single instance (or a
    fresh one per call) both work identically."""

    def _result(self, success, reason_code, message, plan_id=None, change_id=None,
                change_type=None, target_step_id=None, capability=None,
                input_data=None, output_data=None, new_position=None,
                dependency=None):
        """The one place that shapes apply_change's return value, so
        every outcome (success or rejection) comes back in the same
        small, structured, JSON-safe shape - same convention
        AdaptivePlanProposal.validate_proposal's own single return
        shape follows. `capability`/`input_data`/`output_data`/
        `new_position`/`dependency` are simply whichever one is
        relevant to `change_type` - the others stay None."""
        return {
            "success": success,
            "reason_code": reason_code,
            "reason": message,
            "plan_id": plan_id,
            "change_id": change_id,
            "change_type": change_type,
            "target_step_id": target_step_id,
            "capability": capability,
            "input_data": input_data,
            "output_data": output_data,
            "new_position": new_position,
            "dependency": dependency,
        }

    def apply_change(self, plan, change):
        """Apply one `change` (a `ProposedChange` instance, or a plain
        dict shaped like `ProposedChange.to_dict()`) to `plan` (a
        `Plan` instance), in place.

        Only `ADD_CAPABILITY_REQUIREMENT`, `REMOVE_CAPABILITY_REQUIREMENT`,
        `PROVIDE_INPUT`, `PROVIDE_OUTPUT`, `REORDER_STEP`,
        `ADD_DEPENDENCY`, and `REMOVE_DEPENDENCY` are supported; every
        other `change_type` is rejected. For the
        capability changes, `proposed_data` must contain a non-empty
        string under the `"capability"` key naming the capability to
        add/remove. For `PROVIDE_INPUT`/`PROVIDE_OUTPUT`,
        `proposed_data` must contain a non-None value under the
        `"input_data"`/`"output_data"` key that is safe structured data
        (checked via `PlanStep.set_input`/`set_output`/
        `ensure_structured_data` - see planning/plan.py); if the target
        step already has that value set, this is rejected rather than
        overwriting it. For `REORDER_STEP`, `proposed_data` must
        contain an integer `"new_position"` that is a valid index
        (`0 <= new_position < len(plan.steps)`); the target step is
        moved there within `plan.steps`, and every step object -
        including the one moved - is left otherwise unchanged. For
        `ADD_DEPENDENCY`, `proposed_data` must contain a non-empty
        string under the `"dependency_step_id"` key naming a step
        already in `plan`, distinct from the target step, not already
        in the target step's `dependencies`, and not creating a cycle
        with it; if any of those hold, the change is rejected as a
        safe failure and `dependencies` is left untouched. For
        `REMOVE_DEPENDENCY`, `proposed_data` must contain a non-empty
        string under the `"remove_dependency"` key that is currently
        in the target step's `dependencies`; if it isn't, the change
        is rejected as a safe failure and `dependencies` is left
        untouched, otherwise only that one entry is removed.

        Never raises for a malformed or unsupported `change` or an
        unknown `target_step_id` - each such case is reported back as
        `success: False` with a `reason_code`/`reason` explaining why,
        same "never raises for bad input, always reports" convention
        `AdaptivePlanProposal.validate_proposal` already follows.

        Returns a small structured dict (see `_result` above)."""
        if not isinstance(plan, Plan):
            return self._result(
                False, RESULT_INVALID_PLAN,
                f"plan must be a Plan instance, got {type(plan).__name__}.",
            )

        if hasattr(change, "to_dict"):
            change = change.to_dict()
        if not isinstance(change, dict):
            return self._result(
                False, RESULT_INVALID_CHANGE,
                f"change must be a dict (or expose to_dict()), got {type(change).__name__}.",
                plan_id=plan.plan_id,
            )

        change_id = change.get("change_id")
        change_type = change.get("change_type")
        target_step_id = change.get("target_step_id")

        if change_type not in SUPPORTED_CHANGE_TYPES:
            return self._result(
                False, RESULT_UNSUPPORTED_CHANGE_TYPE,
                f"Unsupported change_type: {change_type!r}; ProposalApplier only "
                f"applies {SUPPORTED_CHANGE_TYPES!r}.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        step = next((s for s in plan.steps if s.step_id == target_step_id), None)
        if step is None:
            return self._result(
                False, RESULT_UNKNOWN_TARGET_STEP,
                f"target_step_id {target_step_id!r} does not exist in plan {plan.plan_id!r}.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        proposed_data = change.get("proposed_data") or {}
        if not isinstance(proposed_data, dict):
            proposed_data = {}

        if change_type == CHANGE_PROVIDE_INPUT:
            return self._apply_provide_input(
                plan, step, proposed_data,
                change_id=change_id, change_type=change_type, target_step_id=target_step_id,
            )

        if change_type == CHANGE_PROVIDE_OUTPUT:
            return self._apply_provide_output(
                plan, step, proposed_data,
                change_id=change_id, change_type=change_type, target_step_id=target_step_id,
            )

        if change_type == CHANGE_REORDER_STEP:
            return self._apply_reorder_step(
                plan, step, proposed_data,
                change_id=change_id, change_type=change_type, target_step_id=target_step_id,
            )

        if change_type == CHANGE_ADD_DEPENDENCY:
            return self._apply_add_dependency(
                plan, step, proposed_data,
                change_id=change_id, change_type=change_type, target_step_id=target_step_id,
            )

        if change_type == CHANGE_REMOVE_DEPENDENCY:
            return self._apply_remove_dependency(
                plan, step, proposed_data,
                change_id=change_id, change_type=change_type, target_step_id=target_step_id,
            )

        capability = proposed_data.get("capability")
        if not isinstance(capability, str) or not capability.strip():
            return self._result(
                False, RESULT_INVALID_CAPABILITY,
                "change.proposed_data must include a non-empty 'capability' string.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )
        capability = capability.strip()

        if change_type == CHANGE_ADD_CAPABILITY_REQUIREMENT:
            if capability in step.required_capabilities:
                return self._result(
                    True, RESULT_ALREADY_PRESENT,
                    f"Capability {capability!r} is already required by step "
                    f"{target_step_id!r}; no duplicate was added.",
                    plan_id=plan.plan_id, change_id=change_id,
                    change_type=change_type, target_step_id=target_step_id,
                    capability=capability,
                )
            step.required_capabilities.append(capability)
            return self._result(
                True, RESULT_APPLIED,
                f"Added capability {capability!r} to step {target_step_id!r}.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                capability=capability,
            )

        # change_type == CHANGE_REMOVE_CAPABILITY_REQUIREMENT
        if capability not in step.required_capabilities:
            return self._result(
                True, RESULT_NOT_PRESENT,
                f"Capability {capability!r} was not required by step "
                f"{target_step_id!r}; nothing to remove.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                capability=capability,
            )
        step.required_capabilities.remove(capability)
        return self._result(
            True, RESULT_APPLIED,
            f"Removed capability {capability!r} from step {target_step_id!r}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            capability=capability,
        )

    def _apply_provide_input(self, plan, step, proposed_data, change_id, change_type, target_step_id):
        """Set `step.input_data` from `proposed_data["input_data"]`,
        but only when the step has no `input_data` recorded yet.
        Delegates the actual safety check to `PlanStep.set_input`
        (planning/plan.py's `ensure_structured_data`) rather than
        re-implementing "primitives, lists, and dicts only" here -
        same "one place decides what's safe" convention that check
        already follows for every other caller."""
        if step.get_input() is not None:
            return self._result(
                False, RESULT_INPUT_ALREADY_PRESENT,
                f"Step {target_step_id!r} already has input_data set; refusing to "
                "overwrite it.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        if "input_data" not in proposed_data or proposed_data["input_data"] is None:
            return self._result(
                False, RESULT_INVALID_INPUT_DATA,
                "change.proposed_data must include a non-None 'input_data' value.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        try:
            step.set_input(proposed_data["input_data"])
        except TypeError as exc:
            return self._result(
                False, RESULT_INVALID_INPUT_DATA,
                f"change.proposed_data['input_data'] is not safe structured data: {exc}",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        return self._result(
            True, RESULT_APPLIED,
            f"Set input_data for step {target_step_id!r}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            input_data=step.get_input(),
        )

    def _apply_provide_output(self, plan, step, proposed_data, change_id, change_type, target_step_id):
        """Set `step.output_data` from `proposed_data["output_data"]`,
        but only when the step has no `output_data` recorded yet.
        Delegates the actual safety check to `PlanStep.set_output`
        (planning/plan.py's `ensure_structured_data`) rather than
        re-implementing "primitives, lists, and dicts only" here -
        same "one place decides what's safe" convention that check
        already follows for every other caller. Mirrors
        `_apply_provide_input` exactly, for the output side."""
        if step.get_output() is not None:
            return self._result(
                False, RESULT_OUTPUT_ALREADY_PRESENT,
                f"Step {target_step_id!r} already has output_data set; refusing to "
                "overwrite it.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        if "output_data" not in proposed_data or proposed_data["output_data"] is None:
            return self._result(
                False, RESULT_INVALID_OUTPUT_DATA,
                "change.proposed_data must include a non-None 'output_data' value.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        try:
            step.set_output(proposed_data["output_data"])
        except TypeError as exc:
            return self._result(
                False, RESULT_INVALID_OUTPUT_DATA,
                f"change.proposed_data['output_data'] is not safe structured data: {exc}",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        return self._result(
            True, RESULT_APPLIED,
            f"Set output_data for step {target_step_id!r}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            output_data=step.get_output(),
        )

    def _apply_reorder_step(self, plan, step, proposed_data, change_id, change_type, target_step_id):
        """Move `step` to `proposed_data["new_position"]` within
        `plan.steps`. Only the *order* of `plan.steps` changes - the
        same `PlanStep` objects remain (`step` itself is neither
        replaced nor mutated beyond its position in the list; every
        other step keeps its own position relative to the others,
        shifting only to make room), so dependencies, capabilities,
        input/output data, and status are all completely untouched by
        this."""
        if "new_position" not in proposed_data:
            return self._result(
                False, RESULT_INVALID_POSITION,
                "change.proposed_data must include a 'new_position' integer.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        new_position = proposed_data["new_position"]
        if isinstance(new_position, bool) or not isinstance(new_position, int):
            return self._result(
                False, RESULT_INVALID_POSITION,
                f"'new_position' must be an integer, got {type(new_position).__name__}.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        if not (0 <= new_position < len(plan.steps)):
            return self._result(
                False, RESULT_INVALID_POSITION,
                f"'new_position' {new_position} is out of range for a plan with "
                f"{len(plan.steps)} step(s).",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )

        plan.steps.remove(step)
        plan.steps.insert(new_position, step)

        return self._result(
            True, RESULT_APPLIED,
            f"Moved step {target_step_id!r} to position {new_position}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            new_position=new_position,
        )

    def _creates_cycle(self, plan, from_step_id, to_step_id):
        """Would adding `from_step_id -> depends on -> to_step_id`
        create a cycle in the plan's dependency graph? True if
        `from_step_id` is reachable from `to_step_id` by following
        existing `dependencies` edges (i.e. `to_step_id` already,
        directly or transitively, depends on `from_step_id`) - adding
        the new edge on top of that would close a loop. Reuses the
        same `PlanStep.dependencies` lists everything else in this
        module and `plan_manager.py` already reads; does not build a
        second/parallel dependency representation."""
        steps_by_id = {s.step_id: s for s in plan.steps}
        visited = set()
        stack = [to_step_id]
        while stack:
            current = stack.pop()
            if current == from_step_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            current_step = steps_by_id.get(current)
            if current_step is None:
                continue
            stack.extend(current_step.dependencies)
        return False

    def _apply_add_dependency(self, plan, step, proposed_data, change_id, change_type, target_step_id):
        """Add `proposed_data["dependency_step_id"]` to
        `step.dependencies` (reusing the existing `PlanStep.dependencies`
        list - the same representation `plan_manager.py`'s dependency
        resolution already reads - rather than a second dependency
        system). Rejected, never raised, when: the dependency field is
        missing/empty; the dependency step doesn't exist in `plan`; the
        dependency equals `target_step_id` itself (a step cannot depend
        on itself); the dependency is already present (reported as a
        safe failure, not silently re-added); or adding it would create
        a cycle in the dependency graph (checked via `_creates_cycle`
        before the list is ever touched). Never changes step status,
        inputs, outputs, or capabilities, and never touches any step
        other than `step`'s own `dependencies` list."""
        dependency_step_id = proposed_data.get("dependency_step_id")
        if not isinstance(dependency_step_id, str) or not dependency_step_id.strip():
            return self._result(
                False, RESULT_INVALID_DEPENDENCY,
                "change.proposed_data must include a non-empty 'dependency_step_id' string.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )
        dependency_step_id = dependency_step_id.strip()

        if dependency_step_id == target_step_id:
            return self._result(
                False, RESULT_SELF_DEPENDENCY,
                f"Step {target_step_id!r} cannot depend on itself.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                dependency=dependency_step_id,
            )

        dependency_step = next((s for s in plan.steps if s.step_id == dependency_step_id), None)
        if dependency_step is None:
            return self._result(
                False, RESULT_UNKNOWN_DEPENDENCY_STEP,
                f"dependency_step_id {dependency_step_id!r} does not exist in plan "
                f"{plan.plan_id!r}.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                dependency=dependency_step_id,
            )

        if dependency_step_id in step.dependencies:
            return self._result(
                False, RESULT_DEPENDENCY_ALREADY_PRESENT,
                f"Step {target_step_id!r} already depends on {dependency_step_id!r}; "
                "no duplicate was added.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                dependency=dependency_step_id,
            )

        if self._creates_cycle(plan, target_step_id, dependency_step_id):
            return self._result(
                False, RESULT_DEPENDENCY_CYCLE,
                f"Adding {dependency_step_id!r} as a dependency of {target_step_id!r} "
                "would create a dependency cycle; rejected.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                dependency=dependency_step_id,
            )

        step.dependencies.append(dependency_step_id)
        return self._result(
            True, RESULT_APPLIED,
            f"Added {dependency_step_id!r} as a dependency of step {target_step_id!r}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            dependency=dependency_step_id,
        )

    def _apply_remove_dependency(self, plan, step, proposed_data, change_id, change_type, target_step_id):
        """Remove `proposed_data["remove_dependency"]` from
        `step.dependencies` (same key name `AdaptivePlanProposal`'s
        own `CHANGE_REMOVE_DEPENDENCY` proposals already use - see
        `_propose_for_blocker`'s `BLOCKER_MISSING_STEP` case - and the
        same `PlanStep.dependencies` list `ADD_DEPENDENCY`/
        `plan_manager.py` already read, so this removes from the one
        existing dependency representation rather than creating a
        second). Deliberately does not require `remove_dependency` to
        match another step currently in `plan`: `AdaptivePlanProposal`
        proposes exactly this change to clear a *dangling* dependency
        reference (one pointing at a step_id no longer in the plan),
        so requiring the referenced step to exist would make that use
        case impossible to apply. Rejected, never raised, when: the
        `remove_dependency` field is missing/empty, or it isn't
        currently in `step`'s `dependencies` (a safe failure, not
        silently ignored). Only the one matching entry is removed -
        every other dependency `step` has stays exactly as it was, in
        the same order - and status, inputs, outputs, and capabilities
        are all left untouched."""
        dependency_step_id = proposed_data.get("remove_dependency")
        if not isinstance(dependency_step_id, str) or not dependency_step_id.strip():
            return self._result(
                False, RESULT_INVALID_DEPENDENCY,
                "change.proposed_data must include a non-empty 'remove_dependency' string.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
            )
        dependency_step_id = dependency_step_id.strip()

        if dependency_step_id not in step.dependencies:
            return self._result(
                False, RESULT_DEPENDENCY_NOT_PRESENT,
                f"Step {target_step_id!r} does not depend on {dependency_step_id!r}; "
                "nothing to remove.",
                plan_id=plan.plan_id, change_id=change_id,
                change_type=change_type, target_step_id=target_step_id,
                dependency=dependency_step_id,
            )

        step.dependencies.remove(dependency_step_id)
        return self._result(
            True, RESULT_APPLIED,
            f"Removed {dependency_step_id!r} as a dependency of step {target_step_id!r}.",
            plan_id=plan.plan_id, change_id=change_id,
            change_type=change_type, target_step_id=target_step_id,
            dependency=dependency_step_id,
        )
