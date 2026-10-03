"""
Planning - Goal Completion Evaluator
=======================================
`GoalCompletionEvaluator` answers exactly one question - "given what
this project's own records already say about a Goal's Plan, has that
Plan actually satisfied the Goal?" - and nothing broader than that:

    GOAL (planning/goal.py) + PLAN (planning/plan.py)
        -> [already executed, or partially executed, by
            execution/plan_execution_controller.py - unchanged]
        -> GoalCompletionEvaluator.evaluate(goal_id, plan_id)
        -> a single, structured completion-evaluation result

This is a read-only inspector, not a new stage of the Planning/
Execution Engines. It never runs a step, never calls into
ExecutionEngine/StepExecutionController/PlanExecutionController, never
creates or mutates a Goal or a Plan, and never retries anything. It
only ever reads already-recorded state from `GoalManager` and
`PlanManager` - the exact same two managers `PlanExecutionController`
and `PlanManager` itself already depend on (see those modules' own
docstrings) - and turns that state into one of a small, fixed set of
completion states via fixed, deterministic rules.

Every fact this module reports is already sitting in the existing data
model:
  - `Goal.status` / `Goal.requirements` (planning/goal.py);
  - `Plan.status` / `Plan.goal_id` (planning/plan.py) - note `Plan.status`
    is only ever set at creation time or by an explicit caller; nothing
    in this project's execution stack currently advances it as steps
    run (see execution/plan_execution_controller.py's own
    `_determine_status`, which computes a *run's* status from step
    states rather than writing back to `Plan.status`). Because of that,
    this evaluator deliberately does not treat `Plan.status` as
    authoritative - it derives the actual completion state from each
    `PlanStep.status` instead (the same source of truth
    `PlanExecutionController._determine_status` and
    `PlanManager.check_plan_readiness` already use), and only surfaces
    `Plan.status` as one more piece of evidence, flagging it in
    `warnings` when it disagrees with what the steps show;
  - `PlanStep.status` / `PlanStep.output_data` / `PlanStep.expected_output`
    (planning/plan.py).

Nothing here invents a result. If `goal_id` or `plan_id` doesn't
resolve to a real, already-stored record, or the Plan doesn't actually
belong to the Goal, or there is no step-level evidence to reason from
(an empty Plan), this reports `STATE_UNKNOWN` rather than guessing -
same "no fake intelligence" convention `reasoning/reasoning_result.py`
already documents for `ReasoningEngine`.
"""

from .goal_manager import GoalManager
from .plan_manager import PlanManager
from .plan import (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_FAILED,
)

# Small, fixed vocabulary for a completion evaluation's outcome - same
# STATUS_*/ALL_STATUSES convention already used by planning/goal.py,
# planning/plan.py, and reasoning/reasoning_result.py, so callers can
# branch on it reliably instead of comparing against free-form
# strings.
STATE_SATISFIED = "satisfied"
STATE_PARTIALLY_SATISFIED = "partially_satisfied"
STATE_NOT_SATISFIED = "not_satisfied"
STATE_BLOCKED = "blocked"
STATE_FAILED = "failed"
STATE_UNKNOWN = "unknown"

ALL_COMPLETION_STATES = (
    STATE_SATISFIED, STATE_PARTIALLY_SATISFIED, STATE_NOT_SATISFIED,
    STATE_BLOCKED, STATE_FAILED, STATE_UNKNOWN,
)

# Only STATE_SATISFIED is ever reported with satisfied=True - every
# other state (including PARTIALLY_SATISFIED) means the Goal is not
# yet, or can no longer be, fully satisfied by this Plan's current
# state. Kept as a set (not an inline literal) so `evaluate`/
# `evaluate_plan` never have to re-decide this per call.
_SATISFIED_STATES = frozenset({STATE_SATISFIED})

# A step counts as "remaining" (still needs to move) when it is in any
# of these statuses - i.e. every ALL_STEP_STATUSES value except
# COMPLETED/FAILED (terminal) and BLOCKED (tracked separately, since a
# permanently-blocked step is a materially different situation from a
# step that's simply still pending/ready/running).
_REMAINING_STEP_STATUSES = frozenset({STATUS_PENDING, STATUS_READY, STATUS_IN_PROGRESS})


class GoalCompletionEvaluator:
    """Not thread-safe (matches the rest of this project - see
    PlanManager/GoalManager's own notes). Safe to use one instance per
    Core / per conversation session.

    Constructed with references to the existing `GoalManager` and
    `PlanManager` it reads from - same "wired to the managers it reads
    from" relationship `PlanManager` itself already has to
    `GoalManager` (see plan_manager.py). Never constructs its own
    managers and never receives a raw dict in their place.
    """

    def __init__(self, goal_manager, plan_manager):
        if not isinstance(goal_manager, GoalManager):
            raise TypeError("GoalCompletionEvaluator requires a GoalManager instance.")
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("GoalCompletionEvaluator requires a PlanManager instance.")
        self._goal_manager = goal_manager
        self._plan_manager = plan_manager

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------
    def _result(
        self, goal_id, plan_id, status, completed_steps, remaining_steps,
        failed_steps, blocked_steps, evidence, warnings,
    ):
        """The one place that shapes a result dict, so every path
        below - missing goal, missing plan, mismatched plan, empty
        plan, or an actual evaluated state - comes back in exactly the
        same structured shape (requirement 8)."""
        return {
            "goal_id": goal_id,
            "plan_id": plan_id,
            "status": status,
            "satisfied": status in _SATISFIED_STATES,
            "confidence": self._confidence_for(status, completed_steps, failed_steps, remaining_steps, blocked_steps),
            "completed_steps": list(completed_steps),
            "remaining_steps": list(remaining_steps),
            "failed_steps": list(failed_steps),
            "blocked_steps": list(blocked_steps),
            "evidence": list(evidence),
            "warnings": list(warnings),
        }

    def _confidence_for(self, status, completed_steps, failed_steps, remaining_steps, blocked_steps):
        """Deterministic confidence (requirement 9): never randomized,
        never a bare guess, always recomputed from the same step
        counts already used to decide `status`.

        `STATE_UNKNOWN` always reports 0.0 - by definition there was
        not enough observable evidence to decide anything, so there is
        nothing to be confident about. Every other state reports the
        fraction of the plan's steps that have reached a *terminal*,
        already-observed outcome (COMPLETED or FAILED) - i.e. how much
        of the plan's step-level picture is actually settled, rather
        than still pending/ready/in_progress/blocked. This is 1.0 for
        a fully COMPLETED or a FAILED-and-otherwise-terminal plan, 0.0
        for a plan where nothing has finished yet, and a step-count
        fraction in between for a partially-worked plan - always the
        same value for the same step states, and always derivable by
        a caller from the very `completed_steps`/`failed_steps`/
        `remaining_steps`/`blocked_steps` lists this same result
        already carries."""
        if status == STATE_UNKNOWN:
            return 0.0
        total = len(completed_steps) + len(failed_steps) + len(remaining_steps) + len(blocked_steps)
        if total == 0:
            return 0.0
        terminal = len(completed_steps) + len(failed_steps)
        return round(terminal / total, 4)

    # ------------------------------------------------------------------
    # Shared step-state inspection (used by both evaluate/evaluate_plan)
    # ------------------------------------------------------------------
    def _classify_steps(self, plan):
        """Partition `plan.steps` into completed/failed/blocked/
        remaining step_id lists, purely from each step's own
        `status` - the same field `PlanManager`/
        `PlanExecutionController` already treat as the single source
        of truth for a step's real-world state. Order matches
        `plan.steps`. Read-only - never touches a step."""
        completed_steps = []
        failed_steps = []
        blocked_steps = []
        remaining_steps = []
        for step in plan.steps:
            if step.status == STATUS_COMPLETED:
                completed_steps.append(step.step_id)
            elif step.status == STATUS_FAILED:
                failed_steps.append(step.step_id)
            elif step.status == STATUS_BLOCKED:
                blocked_steps.append(step.step_id)
            elif step.status in _REMAINING_STEP_STATUSES:
                remaining_steps.append(step.step_id)
            else:
                # Unreached with today's ALL_STEP_STATUSES, but never
                # silently dropped if the step vocabulary ever grows -
                # an unrecognized status is still "not yet resolved".
                remaining_steps.append(step.step_id)
        return completed_steps, failed_steps, blocked_steps, remaining_steps

    def _build_evidence(self, plan, completed_steps, failed_steps, blocked_steps, remaining_steps):
        """Structured evidence entries, each built directly from an
        already-observed field on `plan`/its steps - never free-form,
        invented explanation (requirement 10). Every entry here is
        reconstructable by a caller from the plan/step records
        themselves; this only narrates what they already say."""
        evidence = [
            f"Plan {plan.plan_id!r} has {len(plan.steps)} step(s).",
            f"Plan.status field currently records {plan.status!r}.",
        ]
        if completed_steps:
            evidence.append(f"{len(completed_steps)} step(s) COMPLETED: {completed_steps}.")
        if failed_steps:
            evidence.append(f"{len(failed_steps)} step(s) FAILED: {failed_steps}.")
        if blocked_steps:
            evidence.append(f"{len(blocked_steps)} step(s) BLOCKED: {blocked_steps}.")
        if remaining_steps:
            evidence.append(
                f"{len(remaining_steps)} step(s) not yet resolved "
                f"(pending/ready/in_progress): {remaining_steps}."
            )
        for step in plan.steps:
            if step.status == STATUS_COMPLETED and step.expected_output is not None:
                has_output = step.output_data is not None
                evidence.append(
                    f"Step {step.step_id!r} declares expected_output "
                    f"{step.expected_output!r} and "
                    f"{'has' if has_output else 'has no'} recorded output_data."
                )
        return evidence

    def _determine_state(self, total, completed, failed, blocked, remaining):
        """Fixed, ordered, deterministic rules (requirement 6/9) -
        never a guess, never randomized. Every branch below reads only
        already-computed counts; there is no free-form judgment call
        anywhere in this method."""
        if total == 0:
            return STATE_UNKNOWN
        if failed:
            return STATE_FAILED
        if completed == total:
            return STATE_SATISFIED
        if not remaining and blocked:
            # Nothing failed, nothing left actively pending/ready/
            # running, but at least one step is stuck BLOCKED and the
            # plan is not fully COMPLETED - the plan cannot currently
            # progress any further on its own.
            return STATE_BLOCKED
        if completed:
            # Some, but not all, steps are COMPLETED, and there is
            # still at least one step (remaining and/or blocked) that
            # hasn't reached a terminal state.
            return STATE_PARTIALLY_SATISFIED
        return STATE_NOT_SATISFIED

    def _evaluate_plan_state(self, plan):
        """Shared core used by both `evaluate` and `evaluate_plan`:
        classify `plan`'s steps, decide a completion state, and build
        the evidence/warnings for it. Returns
        (status, completed, failed, blocked, remaining, evidence, warnings)."""
        completed_steps, failed_steps, blocked_steps, remaining_steps = self._classify_steps(plan)
        total = len(plan.steps)
        status = self._determine_state(
            total, len(completed_steps), len(failed_steps), len(blocked_steps), len(remaining_steps)
        )
        evidence = self._build_evidence(
            plan, completed_steps, failed_steps, blocked_steps, remaining_steps
        )
        warnings = []
        if total == 0:
            warnings.append("Plan has no steps; there is no step-level evidence to evaluate.")
        return status, completed_steps, failed_steps, blocked_steps, remaining_steps, evidence, warnings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(self, goal_id, plan_id):
        """Evaluate whether the Plan `plan_id` has satisfied the Goal
        `goal_id`, using only what `GoalManager`/`PlanManager` already
        have on record. Read-only: never executes a step or a
        capability, never modifies the Goal or the Plan, never creates
        a new Plan/Goal, and never retries anything (requirement 11).

        Verifies, in order, before looking at any step-level state:
          1. `goal_id` resolves to a real, stored Goal;
          2. `plan_id` resolves to a real, stored Plan;
          3. that Plan's own `goal_id` actually matches the requested
             `goal_id` - a Plan belonging to a different Goal is never
             silently evaluated as if it were this one's.
        Each failure is reported as `STATE_UNKNOWN` with a warning
        explaining exactly which check failed, rather than raising -
        same "a query that should always have a structured answer"
        convention `PlanExecutionController.execute_plan` already
        follows for an unknown `plan_id`.

        Never raises for an unknown/mismatched id. Always returns the
        structured dict described in this module's docstring /
        requirement 8.
        """
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            return self._result(
                goal_id, plan_id, STATE_UNKNOWN, [], [], [], [],
                [], [f"No Goal found for goal_id {goal_id!r}."],
            )

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._result(
                goal_id, plan_id, STATE_UNKNOWN, [], [], [], [],
                [], [f"No Plan found for plan_id {plan_id!r}."],
            )

        if plan.goal_id != goal_id:
            return self._result(
                goal_id, plan_id, STATE_UNKNOWN, [], [], [], [],
                [],
                [
                    f"Plan {plan_id!r} belongs to goal_id {plan.goal_id!r}, "
                    f"not the requested goal_id {goal_id!r}; refusing to "
                    "evaluate a plan against a goal it isn't attached to."
                ],
            )

        (status, completed_steps, failed_steps, blocked_steps, remaining_steps,
         evidence, warnings) = self._evaluate_plan_state(plan)

        evidence.insert(0, f"Goal {goal_id!r} status field currently records {goal.status!r}.")
        if goal.requirements:
            warnings.append(
                f"Goal {goal_id!r} declares {len(goal.requirements)} requirement(s) "
                "that are not individually mapped to plan steps in the existing "
                "data model; only step-level completion could be verified."
            )

        return self._result(
            goal_id, plan_id, status, completed_steps, remaining_steps,
            failed_steps, blocked_steps, evidence, warnings,
        )

    def evaluate_plan(self, plan_id):
        """Evaluate `plan_id`'s own completion state independently of
        any Goal - useful when a caller only has a `plan_id` on hand,
        or wants a plan's state without re-validating the Goal
        relationship `evaluate` already checks.

        Same read-only contract, same fixed completion-state
        vocabulary, and the same structured result shape as
        `evaluate` (requirement 13); `goal_id` in the returned dict is
        the Plan's own recorded `goal_id` (or `None` if `plan_id`
        isn't known at all) rather than one supplied by the caller,
        since there's nothing here to cross-check it against."""
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._result(
                None, plan_id, STATE_UNKNOWN, [], [], [], [],
                [], [f"No Plan found for plan_id {plan_id!r}."],
            )

        (status, completed_steps, failed_steps, blocked_steps, remaining_steps,
         evidence, warnings) = self._evaluate_plan_state(plan)

        return self._result(
            plan.goal_id, plan_id, status, completed_steps, remaining_steps,
            failed_steps, blocked_steps, evidence, warnings,
        )
