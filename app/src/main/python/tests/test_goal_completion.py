"""
Tests for GoalCompletionEvaluator (planning/goal_completion.py) -
deterministic, read-only evaluation of whether an existing Plan has
satisfied its Goal, built entirely on GoalManager/PlanManager/Plan/
PlanStep.

Covers: fully completed plan, partially completed plan, plan with
remaining (not-yet-started) steps, failed plan, blocked plan, empty
plan, missing goal, missing plan, plan belonging to another goal,
unknown/incomplete information, deterministic confidence, evidence
generation, and read-only behavior (no step/plan/goal is ever
mutated by evaluate()/evaluate_plan()).

Run directly:
    python -m unittest tests.test_goal_completion -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.plan import (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_FAILED,
)
from planning.goal_completion import (
    GoalCompletionEvaluator,
    STATE_SATISFIED, STATE_PARTIALLY_SATISFIED, STATE_NOT_SATISFIED,
    STATE_BLOCKED, STATE_FAILED, STATE_UNKNOWN, ALL_COMPLETION_STATES,
)


class GoalCompletionEvaluatorTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.evaluator = GoalCompletionEvaluator(self.goals, self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class ConstructionTests(unittest.TestCase):
    def test_requires_goal_manager(self):
        plans = PlanManager(GoalManager())
        with self.assertRaises(TypeError):
            GoalCompletionEvaluator("not a goal manager", plans)

    def test_requires_plan_manager(self):
        goals = GoalManager()
        with self.assertRaises(TypeError):
            GoalCompletionEvaluator(goals, "not a plan manager")

    def test_all_completion_states_fixed_vocabulary(self):
        self.assertEqual(
            set(ALL_COMPLETION_STATES),
            {
                STATE_SATISFIED, STATE_PARTIALLY_SATISFIED, STATE_NOT_SATISFIED,
                STATE_BLOCKED, STATE_FAILED, STATE_UNKNOWN,
            },
        )


# --------------------------------------------------------------------
# Fully completed plan -> SATISFIED
# --------------------------------------------------------------------
class FullyCompletedPlanTests(GoalCompletionEvaluatorTestBase):
    def test_all_steps_completed_is_satisfied(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_COMPLETED)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_SATISFIED)
        self.assertTrue(result["satisfied"])
        self.assertEqual(sorted(result["completed_steps"]), sorted([s1.step_id, s2.step_id]))
        self.assertEqual(result["failed_steps"], [])
        self.assertEqual(result["blocked_steps"], [])
        self.assertEqual(result["remaining_steps"], [])
        self.assertEqual(result["confidence"], 1.0)


# --------------------------------------------------------------------
# Partially completed plan -> PARTIALLY_SATISFIED
# --------------------------------------------------------------------
class PartiallyCompletedPlanTests(GoalCompletionEvaluatorTestBase):
    def test_some_completed_some_pending_is_partially_satisfied(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        # s2 stays STATUS_PENDING

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_PARTIALLY_SATISFIED)
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["completed_steps"], [s1.step_id])
        self.assertEqual(result["remaining_steps"], [s2.step_id])
        self.assertEqual(result["confidence"], 0.5)

    def test_some_completed_some_still_active_is_partially_satisfied(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        s3 = self._add_step("Step three")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_BLOCKED)
        # s3 stays STATUS_PENDING (still actively remaining, not stuck)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_PARTIALLY_SATISFIED)
        self.assertEqual(result["blocked_steps"], [s2.step_id])
        self.assertEqual(result["remaining_steps"], [s3.step_id])


# --------------------------------------------------------------------
# Plan with remaining (not-yet-started) steps -> NOT_SATISFIED
# --------------------------------------------------------------------
class RemainingStepsPlanTests(GoalCompletionEvaluatorTestBase):
    def test_all_steps_pending_is_not_satisfied(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two", status=STATUS_READY)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_NOT_SATISFIED)
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["completed_steps"], [])
        self.assertEqual(sorted(result["remaining_steps"]), sorted([s1.step_id, s2.step_id]))
        self.assertEqual(result["confidence"], 0.0)

    def test_in_progress_step_counts_as_remaining(self):
        s1 = self._add_step("Step one", status=STATUS_IN_PROGRESS)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_NOT_SATISFIED)
        self.assertEqual(result["remaining_steps"], [s1.step_id])


# --------------------------------------------------------------------
# Failed plan -> FAILED
# --------------------------------------------------------------------
class FailedPlanTests(GoalCompletionEvaluatorTestBase):
    def test_any_failed_step_makes_plan_failed(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_FAILED)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_FAILED)
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["failed_steps"], [s2.step_id])
        self.assertEqual(result["completed_steps"], [s1.step_id])
        self.assertEqual(result["confidence"], 1.0)

    def test_failed_takes_priority_over_blocked(self):
        s1 = self._add_step("Step one", status=STATUS_BLOCKED)
        s2 = self._add_step("Step two", status=STATUS_FAILED)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_FAILED)


# --------------------------------------------------------------------
# Blocked plan -> BLOCKED
# --------------------------------------------------------------------
class BlockedPlanTests(GoalCompletionEvaluatorTestBase):
    def test_partial_completion_with_nothing_left_but_blocked_steps_is_blocked(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_BLOCKED)

        # Some progress was made (s1 COMPLETED), but nothing failed and
        # nothing is left actively pending/ready/in_progress - the plan
        # cannot currently progress any further on its own, so this is
        # reported as BLOCKED (an actionable, stuck state) rather than
        # merely PARTIALLY_SATISFIED.
        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], STATE_BLOCKED)
        self.assertEqual(result["completed_steps"], [s1.step_id])
        self.assertEqual(result["blocked_steps"], [s2.step_id])

    def test_no_completions_all_blocked_is_blocked(self):
        s1 = self._add_step("Step one", status=STATUS_BLOCKED)
        s2 = self._add_step("Step two", status=STATUS_BLOCKED)

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_BLOCKED)
        self.assertFalse(result["satisfied"])
        self.assertEqual(sorted(result["blocked_steps"]), sorted([s1.step_id, s2.step_id]))
        self.assertEqual(result["remaining_steps"], [])
        self.assertEqual(result["confidence"], 0.0)


# --------------------------------------------------------------------
# Empty plan -> UNKNOWN
# --------------------------------------------------------------------
class EmptyPlanTests(GoalCompletionEvaluatorTestBase):
    def test_empty_plan_is_unknown(self):
        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertIn("Plan has no steps; there is no step-level evidence to evaluate.", result["warnings"])


# --------------------------------------------------------------------
# Missing goal / missing plan / plan belonging to another goal
# --------------------------------------------------------------------
class MissingAndMismatchedTests(GoalCompletionEvaluatorTestBase):
    def test_missing_goal_is_unknown(self):
        result = self.evaluator.evaluate("goal-does-not-exist", self.plan.plan_id)

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["goal_id"], "goal-does-not-exist")
        self.assertEqual(result["plan_id"], self.plan.plan_id)
        self.assertTrue(any("No Goal found" in w for w in result["warnings"]))

    def test_missing_plan_is_unknown(self):
        result = self.evaluator.evaluate(self.goal.goal_id, "plan-does-not-exist")

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertFalse(result["satisfied"])
        self.assertTrue(any("No Plan found" in w for w in result["warnings"]))

    def test_plan_belonging_to_another_goal_is_unknown(self):
        other_goal = self.goals.create_goal("A completely different goal")

        result = self.evaluator.evaluate(other_goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertFalse(result["satisfied"])
        self.assertTrue(any("not the requested goal_id" in w for w in result["warnings"]))

    def test_never_raises_for_missing_or_mismatched_ids(self):
        try:
            self.evaluator.evaluate(None, None)
            self.evaluator.evaluate("", "")
            self.evaluator.evaluate(self.goal.goal_id, None)
        except Exception as exc:  # pragma: no cover - the assertion below is what matters
            self.fail(f"evaluate() raised unexpectedly: {exc!r}")


# --------------------------------------------------------------------
# Unknown / incomplete information
# --------------------------------------------------------------------
class UnknownInformationTests(GoalCompletionEvaluatorTestBase):
    def test_unresolvable_ids_report_unknown_with_zero_confidence(self):
        result = self.evaluator.evaluate("", "")

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["completed_steps"], [])
        self.assertEqual(result["remaining_steps"], [])
        self.assertEqual(result["failed_steps"], [])
        self.assertEqual(result["blocked_steps"], [])

    def test_empty_plan_reports_unknown_not_a_guess(self):
        # An empty plan genuinely has no observable evidence either
        # way - this must never be reported as NOT_SATISFIED (which
        # would imply "we looked and nothing was done").
        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], STATE_UNKNOWN)


# --------------------------------------------------------------------
# Deterministic confidence
# --------------------------------------------------------------------
class DeterministicConfidenceTests(GoalCompletionEvaluatorTestBase):
    def test_same_state_always_yields_same_confidence(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        s3 = self._add_step("Step three")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_COMPLETED)
        # s3 stays pending

        first = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        second = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(first["confidence"], second["confidence"])
        self.assertEqual(first["confidence"], round(2 / 3, 4))

    def test_confidence_reflects_terminal_step_ratio(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two")
        s3 = self._add_step("Step three")
        s4 = self._add_step("Step four")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, s2.step_id, STATUS_FAILED)
        # s3, s4 remain pending -> 2 of 4 steps are terminal

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["confidence"], 0.5)


# --------------------------------------------------------------------
# Evidence generation
# --------------------------------------------------------------------
class EvidenceGenerationTests(GoalCompletionEvaluatorTestBase):
    def test_evidence_references_observable_plan_and_step_facts(self):
        s1 = self._add_step("Step one", expected_output="a report")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)
        self.plans.set_step_input(self.plan.plan_id, s1.step_id, {"x": 1})
        step = self.plans.get_step(self.plan.plan_id, s1.step_id)
        step.set_output({"report": "done"})

        result = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)

        evidence_text = " ".join(result["evidence"])
        self.assertIn(self.plan.plan_id, evidence_text)
        self.assertIn(self.goal.goal_id, evidence_text)
        self.assertIn(s1.step_id, evidence_text)
        self.assertTrue(len(result["evidence"]) > 0)

    def test_evidence_notes_requirements_not_individually_mapped(self):
        goal = self.goals.create_goal(
            "Ship a small feature", requirements=["req-a", "req-b"]
        )
        plan = self.plans.create_plan(goal.goal_id)
        self.plans.add_step(plan.plan_id, "Step one")

        result = self.evaluator.evaluate(goal.goal_id, plan.plan_id)

        self.assertTrue(any("requirement(s)" in w for w in result["warnings"]))


# --------------------------------------------------------------------
# Read-only behavior
# --------------------------------------------------------------------
class ReadOnlyBehaviorTests(GoalCompletionEvaluatorTestBase):
    def test_evaluate_never_mutates_goal_or_plan_or_steps(self):
        s1 = self._add_step("Step one")
        s2 = self._add_step("Step two", dependencies=[s1.step_id])
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)

        before_goal = self.goals.describe_goal(self.goal.goal_id)
        before_plan = self.plans.describe_plan(self.plan.plan_id)

        self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        self.evaluator.evaluate_plan(self.plan.plan_id)

        after_goal = self.goals.describe_goal(self.goal.goal_id)
        after_plan = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before_goal, after_goal)
        self.assertEqual(before_plan, after_plan)

    def test_evaluate_does_not_create_new_goals_or_plans(self):
        goal_count_before = len(self.goals)
        plan_count_before = len(self.plans)

        self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        self.evaluator.evaluate("unknown-goal", "unknown-plan")
        self.evaluator.evaluate_plan("unknown-plan")

        self.assertEqual(len(self.goals), goal_count_before)
        self.assertEqual(len(self.plans), plan_count_before)

    def test_evaluator_module_imports_no_execution_or_shell_machinery(self):
        import planning.goal_completion as module
        with open(module.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        for forbidden in ("subprocess", "os.system", " eval(", " exec(", "socket"):
            self.assertNotIn(forbidden, source)


# --------------------------------------------------------------------
# evaluate_plan() helper
# --------------------------------------------------------------------
class EvaluatePlanHelperTests(GoalCompletionEvaluatorTestBase):
    def test_evaluate_plan_matches_evaluate_for_valid_pair(self):
        s1 = self._add_step("Step one")
        self.plans.update_step_status(self.plan.plan_id, s1.step_id, STATUS_COMPLETED)

        via_goal = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        via_plan_only = self.evaluator.evaluate_plan(self.plan.plan_id)

        self.assertEqual(via_goal["status"], via_plan_only["status"])
        self.assertEqual(via_goal["completed_steps"], via_plan_only["completed_steps"])
        self.assertEqual(via_plan_only["goal_id"], self.goal.goal_id)

    def test_evaluate_plan_missing_plan_is_unknown(self):
        result = self.evaluator.evaluate_plan("plan-does-not-exist")

        self.assertEqual(result["status"], STATE_UNKNOWN)
        self.assertIsNone(result["goal_id"])
        self.assertTrue(any("No Plan found" in w for w in result["warnings"]))

    def test_evaluate_plan_works_without_validating_goal(self):
        # evaluate_plan() never checks a caller-supplied goal_id since
        # it doesn't take one - it just reports the plan's own
        # recorded goal_id.
        s1 = self._add_step("Step one")
        result = self.evaluator.evaluate_plan(self.plan.plan_id)
        self.assertEqual(result["goal_id"], self.goal.goal_id)


# --------------------------------------------------------------------
# Backward compatibility - existing managers still work unmodified
# --------------------------------------------------------------------
class BackwardCompatibilityTests(GoalCompletionEvaluatorTestBase):
    def test_goal_manager_and_plan_manager_unaffected(self):
        goal = self.goals.create_goal("Another goal")
        plan = self.plans.create_plan(goal.goal_id)
        step = self.plans.add_step(plan.plan_id, "A step")
        self.assertEqual(step.status, STATUS_PENDING)
        self.assertEqual(plan.goal_id, goal.goal_id)


if __name__ == "__main__":
    unittest.main()
