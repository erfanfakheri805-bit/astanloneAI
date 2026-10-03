"""
Planning - Plan Manager
=========================
`PlanManager` is deliberately small: it can create a `Plan` for an
existing `Goal`, add a `PlanStep` to a plan, safely update or
dependency-refresh a step's status, retrieve a plan by id, and
describe it for debugging. It is the "future Planning Engine's"
bookkeeping layer, not the Planning Engine itself - no automatic plan
generation, no execution, and no external/network calls happen here
(see planning/plan.py's module docstring for where those belong once
that stage exists). Status management here only ever records or
computes a status (PENDING/READY/BLOCKED, or an explicit
IN_PROGRESS/COMPLETED/FAILED set by a caller) - it never decides to
run a step.

Deliberately separate from, and never a replacement for, the project's
persistent storage (memory/memory_system.py) - same pattern already
used by planning/goal_manager.py and context/conversation_context.py:

    PLAN MANAGER (this module)         PERSISTENT MEMORY/KNOWLEDGE
    ---------------------------------  ---------------------------------
    candidate plans                    learned concepts / facts
    lives only in this process's RAM   lives in the sqlite-backed stores
    cleared on process restart         durable across restarts

A PlanManager is constructed with a reference to the GoalManager whose
goals it plans against (same relationship Core wires up between its
own self.goals and self.plans - see core/core.py) so that
create_plan() can confirm the goal actually exists instead of quietly
creating a plan for nothing.
"""

import itertools

from .goal_manager import GoalManager
from .plan import (
    Plan, PlanStep, STATUS_PENDING, STATUS_READY, STATUS_BLOCKED,
    STATUS_COMPLETED, ALL_STEP_STATUSES, ensure_structured_data,
)

# Deterministic confidence weights, same "never randomized, never
# guessed" convention as goal_manager.py's own confidence scoring.
# These are fixed contributions from actual evidence present at
# plan-creation time - refining how a plan's confidence is judged is
# Planning Engine work, not this stage's.
_CONFIDENCE_BASE = 0.5
_CONFIDENCE_HAS_REQUIRED_CAPABILITIES = 0.2
_CONFIDENCE_HAS_EXPECTED_OUTPUTS = 0.2
_CONFIDENCE_HAS_DEPENDENCIES = 0.1


def _estimate_confidence(required_capabilities, expected_outputs, dependencies):
    """Simple, deterministic confidence estimate for a freshly created
    Plan. Intentionally crude (presence checks only, same as
    goal_manager._estimate_confidence) - a real estimate belongs to
    the Planning Engine, once it exists."""
    confidence = _CONFIDENCE_BASE
    if required_capabilities:
        confidence += _CONFIDENCE_HAS_REQUIRED_CAPABILITIES
    if expected_outputs:
        confidence += _CONFIDENCE_HAS_EXPECTED_OUTPUTS
    if dependencies:
        confidence += _CONFIDENCE_HAS_DEPENDENCIES
    return max(0.0, min(1.0, confidence))


class PlanManager:
    """Not thread-safe (matches the rest of the project - see
    goal_manager.GoalManager's own note). Safe to use one instance per
    Core / per conversation session."""

    def __init__(self, goal_manager):
        if not isinstance(goal_manager, GoalManager):
            raise TypeError("PlanManager requires a GoalManager instance.")
        self._goal_manager = goal_manager
        self._plans = {}
        self._id_counter = itertools.count(1)

    # ------------------------------------------------------------------
    # Creation / storage
    # ------------------------------------------------------------------
    def create_plan(
        self,
        goal_id,
        dependencies=None,
        required_capabilities=None,
        expected_outputs=None,
        metadata=None,
    ):
        """Create a Plan for an existing Goal, store it, and return it.

        Raises ValueError if `goal_id` doesn't match a Goal the
        GoalManager actually knows about - a Plan always attaches to
        something real, never a dangling reference."""
        if not goal_id or not self._goal_manager.get_goal(goal_id):
            raise ValueError(f"Cannot create a plan for unknown goal_id: {goal_id!r}")

        plan_id = f"plan-{next(self._id_counter)}"
        confidence = _estimate_confidence(required_capabilities, expected_outputs, dependencies)

        plan = Plan(
            plan_id=plan_id,
            goal_id=goal_id,
            dependencies=dependencies,
            required_capabilities=required_capabilities,
            expected_outputs=expected_outputs,
            confidence=confidence,
            metadata=metadata,
        )
        self._plans[plan_id] = plan
        return plan

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def add_step(
        self,
        plan_id,
        description,
        dependencies=None,
        required_capabilities=None,
        expected_output=None,
        status=STATUS_PENDING,
        input_data=None,
        output_data=None,
    ):
        """Append a new PlanStep to an existing Plan and return the
        step. Raises ValueError if `plan_id` is unknown or
        `description` is empty/whitespace-only - a step always
        represents something actually asked for, same as
        GoalManager.create_goal's own guard on empty input.
        `input_data`/`output_data` are optional and default to None
        (no data yet) - same PlanStep.set_input/set_output safety
        check applies here, via PlanStep's own constructor."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot add a step to unknown plan_id: {plan_id!r}")
        if not description or not str(description).strip():
            raise ValueError("Cannot add a step with empty description.")

        step_id = f"{plan_id}-step-{len(plan.steps) + 1}"
        step = PlanStep(
            step_id=step_id,
            description=str(description).strip(),
            dependencies=dependencies,
            required_capabilities=required_capabilities,
            expected_output=expected_output,
            status=status,
            input_data=input_data,
            output_data=output_data,
        )
        plan.steps.append(step)
        return step

    def get_step(self, plan_id, step_id):
        """Return the PlanStep for `step_id` within `plan_id`, or None
        if the plan or the step within it isn't known (never raises
        for an unknown id - same convention as get_plan)."""
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        for step in plan.steps:
            if step.step_id == step_id:
                return step
        return None

    # ------------------------------------------------------------------
    # Structured input/output (data-flow layer)
    # ------------------------------------------------------------------
    # Small, focused helpers so a caller can store/retrieve one step's
    # structured input/output without reaching into PlanStep directly.
    # Neither of these passes data to any other step, decides when a
    # step should run, or executes anything - see plan.py's
    # PlanStep.set_input/set_output/get_input/get_output, which these
    # simply delegate to once the plan_id/step_id are confirmed real.
    def set_step_input(self, plan_id, step_id, data):
        """Safely set `step_id`'s `input_data` within `plan_id`.
        Raises ValueError - same convention as update_step_status -
        if `plan_id`/`step_id` don't resolve to a real step, and
        TypeError (via PlanStep.set_input) if `data` isn't safe,
        JSON-shaped structured data. Returns the updated step."""
        step = self.get_step(plan_id, step_id)
        if step is None:
            raise ValueError(
                f"Cannot set input for unknown step_id {step_id!r} in plan_id {plan_id!r}"
            )
        step.set_input(data)
        return step

    def get_step_output(self, plan_id, step_id):
        """Return `step_id`'s currently stored `output_data` within
        `plan_id`, or None if the plan/step isn't known *or* the step
        simply has no output recorded yet - same "never raises for an
        unknown id" convention as get_step/get_plan, since this is a
        read-only lookup rather than a mutation."""
        step = self.get_step(plan_id, step_id)
        if step is None:
            return None
        return step.get_output()

    # ------------------------------------------------------------------
    # Controlled propagation between dependent steps
    # ------------------------------------------------------------------
    def _propagation_result(
        self, plan_id, source_step_id, target_step_id, success, propagated, reason,
        output_summary,
    ):
        """The one place that shapes a propagate_step_output return
        value, so every success/failure/conflict path returns exactly
        the same structured, JSON-shaped record (requirement 8) rather
        than each check building its own dict."""
        return {
            "success": bool(success),
            "plan_id": plan_id,
            "source_step_id": source_step_id,
            "target_step_id": target_step_id,
            "propagated": bool(propagated),
            "reason": reason,
            "output_summary": output_summary,
        }

    def _summarize_output(self, output_data):
        """A small, deterministic summary of a step's `output_data` -
        never the raw structure itself in a spot meant to be read at a
        glance (a UI, a log). None (no output) summarizes as None; a
        dict summarizes as its own (already-string) keys, in the order
        they were stored; a list summarizes as its length; any other
        JSON-safe scalar (str/int/float/bool) is short enough to show
        as-is. Only ever reads `output_data` - never mutates it."""
        if output_data is None:
            return None
        if isinstance(output_data, dict):
            return {"type": "dict", "keys": list(output_data.keys())}
        if isinstance(output_data, list):
            return {"type": "list", "length": len(output_data)}
        return {"type": type(output_data).__name__, "value": output_data}

    def propagate_step_output(self, plan_id, source_step_id, target_step_id):
        """Copy `source_step_id`'s `output_data` into
        `target_step_id`'s `input_data`, within the same `plan_id` -
        the one, explicit, caller-invoked way structured data ever
        moves from one step to another (see planning/plan.py's
        PlanStep.set_input/set_output and this class's own
        set_step_input/get_step_output, which this builds on rather
        than duplicating). This never runs automatically for a whole
        plan and never executes `target_step_id` (or anything else) -
        it only ever copies already-produced, already-validated
        structured data from one step's record to another's, when a
        caller explicitly asks for exactly that pair.

        Every one of the following must hold, checked in order, or
        propagation is refused with a structured explanation
        (requirement 8) rather than an exception - unlike
        update_step_status/set_step_input, an unknown *step* id here
        is an ordinary "nothing to propagate" outcome, not a
        programmer error, since a caller may reasonably probe an
        arbitrary source/target pair before knowing whether either
        side is ready:
          - `plan_id` must be a real, known Plan (raises ValueError -
            same convention as check_plan_readiness/
            check_plan_capabilities - since an unknown plan_id itself
            is the same "nothing real to operate on" case those
            already treat as a hard error);
          - the source step must exist in that plan;
          - the source step's status must be COMPLETED;
          - the source step must actually have output_data (not None);
          - the target step must exist in that same plan;
          - the target step must declare `source_step_id` in its own
            `dependencies` - this is what makes propagation
            "controlled": data only ever flows along an edge the plan
            itself already declared, never between steps that just
            happen to be passed in together (requirement 6);
          - the target step's `input_data` must still be None - an
            existing input is never silently overwritten (requirement
            7); this is reported back as a conflict, not a crash.

        On success, the target's `input_data` becomes a defensively-
        copied, re-validated copy of the source's `output_data` (via
        PlanStep.set_input -> ensure_structured_data - the same single
        safety check every other structured-data entry point in this
        project funnels through), so a later mutation of one step's
        stored data can never reach into the other's, and nothing that
        isn't safe, JSON-shaped structured data could ever have gotten
        into either field to begin with (requirement 10). The source
        step's own `output_data` is never touched (requirement 4).

        Deterministic (requirement 9): given the same plan/step state,
        this always returns the same result - no randomness, no
        clock/network/filesystem reads, and no partial writes on a
        refused propagation.

        Returns a dict:
            {
                "success": bool,           # True only when propagated
                "plan_id": plan_id,
                "source_step_id": source_step_id,
                "target_step_id": target_step_id,
                "propagated": bool,        # same value as "success" -
                                            # kept as its own key since
                                            # it's the specific fact
                                            # requirement 8 asks for
                "reason": str,             # human-readable explanation,
                                            # for both success and every
                                            # refusal/conflict case
                "output_summary": dict | scalar | None,
                    # see _summarize_output - always computed from the
                    # source step's *current* output_data when the
                    # source step was found at all, even on a later
                    # refusal (e.g. target already has input), so a
                    # caller can see what *would* have propagated;
                    # None when there's no source step/output to
                    # summarize yet.
            }
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot propagate output in unknown plan_id: {plan_id!r}")

        source = self.get_step(plan_id, source_step_id)
        if source is None:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Source step {source_step_id!r} does not exist in plan {plan_id!r}.",
                None,
            )

        target = self.get_step(plan_id, target_step_id)
        if target is None:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Target step {target_step_id!r} does not exist in plan {plan_id!r}.",
                self._summarize_output(source.output_data),
            )

        if source.status != STATUS_COMPLETED:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Source step {source_step_id!r} is not COMPLETED "
                f"(current status: {source.status!r}).",
                self._summarize_output(source.output_data),
            )

        if source.output_data is None:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Source step {source_step_id!r} has no output_data to propagate.",
                None,
            )

        if source_step_id not in target.dependencies:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Target step {target_step_id!r} does not declare "
                f"{source_step_id!r} as a dependency; refusing to propagate "
                "between unrelated steps.",
                self._summarize_output(source.output_data),
            )

        if target.input_data is not None:
            return self._propagation_result(
                plan_id, source_step_id, target_step_id, False, False,
                f"Target step {target_step_id!r} already has input_data; "
                "refusing to overwrite it.",
                self._summarize_output(source.output_data),
            )

        target.set_input(source.output_data)
        return self._propagation_result(
            plan_id, source_step_id, target_step_id, True, True,
            f"Propagated output_data from {source_step_id!r} to {target_step_id!r}.",
            self._summarize_output(source.output_data),
        )

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------
    # Deliberately small: a safe way to change one step's status, plus
    # a dependency-aware helper that can tell a step apart as READY vs
    # BLOCKED. Neither of these executes anything or decides *when* a
    # step should run - that decision, and any automatic transition
    # into IN_PROGRESS/COMPLETED/FAILED, belongs to the future
    # Execution Engine (see plan.py's module docstring), not here.
    def update_step_status(self, plan_id, step_id, new_status):
        """Safely set one step's status. Raises ValueError - and
        leaves the step untouched - if `plan_id`/`step_id` don't
        resolve to a real step, or if `new_status` isn't one of
        PlanStep's recognized statuses (see plan.ALL_STEP_STATUSES).
        Only ever touches the one step named; never cascades to any
        other step in the plan (see refresh_step_status for that)."""
        step = self.get_step(plan_id, step_id)
        if step is None:
            raise ValueError(
                f"Cannot update unknown step_id {step_id!r} in plan_id {plan_id!r}"
            )
        step.set_status(new_status)
        return step

    def _unresolved_dependencies(self, plan, step):
        """step_ids `step` depends on that aren't yet COMPLETED,
        including dependencies that don't match any step in `plan` -
        those can never resolve on their own, so they count as
        unresolved too."""
        steps_by_id = {s.step_id: s for s in plan.steps}
        unresolved = []
        for dep_id in step.dependencies:
            dep_step = steps_by_id.get(dep_id)
            if dep_step is None or dep_step.status != STATUS_COMPLETED:
                unresolved.append(dep_id)
        return unresolved

    def _capability_registry_lookup(self, capability_system):
        """The one place that reads capability_system.all() and indexes
        it by name - the "existing capability registry lookup logic"
        both _unavailable_capabilities and check_plan_capabilities
        build on, so there's a single read-only lookup rather than two
        copies of it. Never registers/enables/disables anything."""
        return {row["name"]: row for row in capability_system.all()}

    def _unavailable_capabilities(self, step, capability_system):
        """`step.required_capabilities` names that aren't currently
        available (registered-and-enabled means available;
        unregistered, or registered-but-disabled, does not).

        No `capability_system` passed means this check is opted out
        of entirely (returns [] regardless of `required_capabilities`)
        - this is what keeps refresh_step_status and friends backward
        compatible for callers that don't pass one."""
        if not step.required_capabilities or capability_system is None:
            return []
        registered = self._capability_registry_lookup(capability_system)
        unavailable = []
        for cap_name in step.required_capabilities:
            row = registered.get(cap_name)
            if row is None or not bool(row["enabled"]):
                unavailable.append(cap_name)
        return unavailable

    def refresh_step_status(self, plan_id, step_id, capability_system=None):
        """Recompute BLOCKED/READY for one step from its dependencies'
        *current* status and, when `capability_system` is given, its
        required capabilities' *current* availability: READY only if
        every dependency is COMPLETED (or it has none) AND every
        required capability is available (or it has none); BLOCKED
        otherwise. `capability_system` is optional and defaults to
        None, which skips the capability check entirely (dependency-
        only behavior, unchanged from before this capability-aware
        check existed) - same "existing capability registry lookup
        logic" used by check_plan_capabilities, never a new one.

        Only touches a step that's currently PENDING, READY, or
        BLOCKED - a step already IN_PROGRESS, COMPLETED, or FAILED
        reflects real work that happened elsewhere and is never
        silently overwritten by this. This only ever computes/records
        a status; it never creates, enables, installs, or executes a
        capability, and never runs a step."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot refresh a step in unknown plan_id: {plan_id!r}")
        step = self.get_step(plan_id, step_id)
        if step is None:
            raise ValueError(
                f"Cannot refresh unknown step_id {step_id!r} in plan_id {plan_id!r}"
            )

        if step.status not in (STATUS_PENDING, STATUS_READY, STATUS_BLOCKED):
            return step

        blocked = bool(self._unresolved_dependencies(plan, step)) or bool(
            self._unavailable_capabilities(step, capability_system)
        )
        new_status = STATUS_BLOCKED if blocked else STATUS_READY
        return self.update_step_status(plan_id, step_id, new_status)

    def refresh_plan_step_statuses(self, plan_id, capability_system=None):
        """Refresh READY/BLOCKED (see refresh_step_status, including
        its optional capability check) for every eligible step in a
        plan at once - a convenience for callers that just
        added/changed steps and want the whole dependency graph
        re-evaluated, rather than calling refresh_step_status once per
        step_id."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot refresh unknown plan_id: {plan_id!r}")
        return [
            self.refresh_step_status(plan_id, step.step_id, capability_system)
            for step in plan.steps
        ]

    def refresh_after_step_change(self, plan_id, changed_step_id, capability_system=None):
        """Cascade a status change on one step into the rest of the
        plan: after `changed_step_id`'s status has been set (typically
        via update_step_status, e.g. moved to COMPLETED or FAILED),
        call this so every *other* step that might depend on it gets
        its READY/BLOCKED recomputed too - a step that was BLOCKED on
        `changed_step_id` becomes READY once that dependency (and all
        its others) are COMPLETED *and* (when `capability_system` is
        given) all its required capabilities are available, and stays
        BLOCKED otherwise.

        This does not special-case which status `changed_step_id`
        moved to (COMPLETED, FAILED, IN_PROGRESS, ...) - it simply
        re-evaluates the whole plan's dependency graph from its
        current state (see refresh_plan_step_statuses), which already
        guarantees:
          - only PENDING/READY/BLOCKED steps are ever touched;
          - a touched step becomes READY only when *all* of its
            dependencies are COMPLETED (so a FAILED or still-pending
            dependency correctly leaves/keeps it BLOCKED, and a
            dependency that doesn't match any step in the plan is
            treated the same way - see _unresolved_dependencies) *and*
            all of its required capabilities are available when
            `capability_system` is given (see
            _unavailable_capabilities; omitting `capability_system`
            skips this check entirely, same dependency-only behavior
            as before);
          - COMPLETED, FAILED, and IN_PROGRESS steps are never
            overwritten automatically.
        Raises ValueError if `plan_id` or `changed_step_id` isn't
        known - same convention as refresh_step_status. Never creates,
        enables, installs, or executes a capability, and never
        executes a step; those decisions belong to the future
        Execution Engine (see plan.py's module docstring)."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot refresh unknown plan_id: {plan_id!r}")
        if self.get_step(plan_id, changed_step_id) is None:
            raise ValueError(
                f"Cannot refresh after unknown step_id {changed_step_id!r} "
                f"in plan_id {plan_id!r}"
            )
        return self.refresh_plan_step_statuses(plan_id, capability_system)

    def get_ready_step_ids(self, plan_id):
        """Read-only dependency check: return the step_ids of every
        currently PENDING step in `plan_id` whose dependencies are all
        COMPLETED (or that has none) - i.e. the steps that could start
        right now. A PENDING step with at least one dependency that
        isn't COMPLETED (including a dependency that doesn't match any
        step in the plan, via _unresolved_dependencies) is left out.

        Unlike refresh_step_status/refresh_plan_step_statuses, this
        never writes a step's `status` - it only reports readiness.
        Steps not currently PENDING (already READY/BLOCKED/IN_PROGRESS/
        COMPLETED/FAILED) are left out too, since only a PENDING step
        is waiting to be judged ready. Order matches `plan.steps`.
        Never executes a step - that decision belongs to the future
        Execution Engine (see plan.py's module docstring)."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot compute ready steps for unknown plan_id: {plan_id!r}")
        return [
            step.step_id
            for step in plan.steps
            if step.status == STATUS_PENDING and not self._unresolved_dependencies(plan, step)
        ]

    # ------------------------------------------------------------------
    # Capability aggregation
    # ------------------------------------------------------------------
    def check_plan_capabilities(self, plan_id, capability_system):
        """Aggregate every PlanStep's `required_capabilities` across a
        whole Plan and report, for each unique capability name, whether
        it's currently available in `capability_system` and which
        step_ids require it.

        `capability_system` is the project's existing
        capabilities.capability_system.CapabilitySystem (or anything
        exposing the same `.all()` registry lookup) - this method only
        ever reads from it via that lookup; it never registers,
        enables, disables, or otherwise changes a capability, and never
        executes anything (same "read-only reporting" convention as
        get_ready_step_ids).

        Returns a list of dicts, one per unique required capability
        name (first-seen order across steps, then within a step, with
        duplicate requirements across steps collapsed into one entry):
            {
                "capability_name": str,
                "available": bool,   # False for an unregistered capability
                "status": str,       # the registry's status, or
                                      # "unregistered" if not found there
                "required_by_steps": [step_id, ...],
            }
        A plan with no required capabilities anywhere returns [].

        Raises ValueError for an unknown plan_id - same convention as
        get_ready_step_ids/refresh_plan_step_statuses, since this is a
        plan-wide computation rather than a single-record retrieval."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot check capabilities for unknown plan_id: {plan_id!r}")

        # capability_name -> [step_id, ...], first-seen order, no
        # duplicate step_ids and no duplicate capability entries even
        # when several steps (or one step, redundantly) require it.
        required_by_steps = {}
        for step in plan.steps:
            for cap_name in step.required_capabilities:
                step_ids = required_by_steps.setdefault(cap_name, [])
                if step.step_id not in step_ids:
                    step_ids.append(step.step_id)

        # Existing capability registry lookup logic - same shared,
        # read-only lookup _unavailable_capabilities (used by
        # refresh_step_status) also builds on. No writes.
        registered = self._capability_registry_lookup(capability_system)

        results = []
        for cap_name, step_ids in required_by_steps.items():
            row = registered.get(cap_name)
            if row is None:
                available = False
                status = "unregistered"
            else:
                available = bool(row["enabled"])
                status = row["status"]
            results.append({
                "capability_name": cap_name,
                "available": available,
                "status": status,
                "required_by_steps": step_ids,
            })
        return results

    def check_plan_readiness(self, plan_id, capability_system):
        """Read-only readiness check for a whole Plan: is every step in
        it currently unblocked - dependencies resolved *and* required
        capabilities available - so the plan as a whole could proceed?

        Deliberately built entirely on the same, already-existing
        logic rather than a new copy of it:
          - per-step dependency resolution reuses
            _unresolved_dependencies (also used by refresh_step_status);
          - per-step capability availability reuses
            _unavailable_capabilities (also used by refresh_step_status);
          - the capability summary reuses check_plan_capabilities itself.
        Like those, this only ever reads - it never calls
        update_step_status or touches a step's stored `status`, never
        registers/enables/disables a capability, and never executes
        anything. Requirement 3's "A Plan is READY only when..." is
        exactly what `ready` reports below; nothing here changes the
        Plan's own `status` field to match it.

        Returns:
            {
                "plan_id": plan_id,
                "ready": bool,
                "total_steps": int,
                "ready_steps": int,     # steps with no unresolved
                                         # dependencies and no
                                         # unavailable capabilities
                "blocked_steps": int,   # every other step
                "unavailable_capabilities": [   # check_plan_capabilities
                    {"capability_name", "available", "status",          # entries
                     "required_by_steps"}, ...                          # with
                ],                                                      # available=False
                "unresolved_dependencies": {step_id: [dep_id, ...], ...},
                "warnings": [str, ...],
            }
        A plan with zero steps is never ready (requirement 3) and gets
        a warning saying so.

        Raises ValueError for an unknown plan_id - same convention as
        check_plan_capabilities/get_ready_step_ids."""
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Cannot check readiness for unknown plan_id: {plan_id!r}")

        unresolved_dependencies = {}
        ready_count = 0
        blocked_count = 0
        for step in plan.steps:
            unresolved = self._unresolved_dependencies(plan, step)
            missing_caps = self._unavailable_capabilities(step, capability_system)
            if unresolved:
                unresolved_dependencies[step.step_id] = list(unresolved)
            if unresolved or missing_caps:
                blocked_count += 1
            else:
                ready_count += 1

        capability_report = self.check_plan_capabilities(plan_id, capability_system)
        unavailable_capabilities = [
            entry for entry in capability_report if not entry["available"]
        ]

        total_steps = len(plan.steps)
        warnings = []
        if total_steps == 0:
            warnings.append("Plan has no steps.")

        ready = total_steps > 0 and blocked_count == 0

        return {
            "plan_id": plan_id,
            "ready": ready,
            "total_steps": total_steps,
            "ready_steps": ready_count,
            "blocked_steps": blocked_count,
            "unavailable_capabilities": unavailable_capabilities,
            "unresolved_dependencies": unresolved_dependencies,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_plan(self, plan_id):
        """Return the Plan for `plan_id`, or None if no such plan
        exists (never raises for an unknown id)."""
        return self._plans.get(plan_id)

    def all_plans(self):
        """All stored Plans, oldest-first (insertion order)."""
        return list(self._plans.values())

    def __len__(self):
        return len(self._plans)

    # ------------------------------------------------------------------
    # Debugging
    # ------------------------------------------------------------------
    def describe_plan(self, plan_id):
        """Structured (JSON-shaped) representation of one plan for
        debugging/inspection, or None if `plan_id` isn't known. Safe
        to hand to a UI, a test, or a log - see Plan.to_dict()."""
        plan = self.get_plan(plan_id)
        return plan.to_dict() if plan else None

    def debug_state(self):
        """Structured snapshot of every plan currently held, for
        debugging/inspection (a developer panel, a test)."""
        return {
            "plan_count": len(self._plans),
            "plans": [p.to_dict() for p in self.all_plans()],
        }
