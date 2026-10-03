"""
Tests for `AgentLoop.request_code_change_correction_analysis`
(agent/agent_loop.py) - Prompt 333: connects the existing code-change
correction decision (Prompt 332: `evaluate_code_change_correction_decision`,
built on agent/code_change_evaluation.py's
`build_code_change_correction_decision`) to the existing
`AdaptivePlanAnalyzer` (planning/adaptive_plan_analyzer.py), reused
exactly as `request_analysis`/`request_correction_analysis` already
reuse it - never a second, duplicate analyzer.

Covers: FAILED/TIMEOUT code-change results triggering plan analysis,
PASSED/INVALID/CHANGE_FAILED results never triggering it, the original
change_result/test_result/correction decision/plan analysis result all
being preserved unmodified, no Plan mutation, and safe handling of an
unknown goal_id/plan_id.

Run directly:
    python -m unittest tests.test_code_change_correction_analysis -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from agent.code_change_evaluation import build_code_change_correction_decision
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID
from execution.code_change_apply_and_test_capability import (
    CHANGE_STATUS_APPLIED,
    CHANGE_STATUS_NOT_APPLIED,
)

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.goal_completion import GoalCompletionEvaluator
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer, ANALYSIS_INCOMPLETE, ANALYSIS_UNKNOWN
from execution.plan_execution_controller import PlanExecutionController


def _code_change_result(change_status, test_status=None, change_result=None, test_result=None):
    return {
        "change_status": change_status,
        "test_status": test_status,
        "test_output": None,
        "error": None,
        "change_result": change_result,
        "test_result": test_result,
    }


class AgentLoopCodeChangeCorrectionAnalysisTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)


class TestRequestCodeChangeCorrectionAnalysis(AgentLoopCodeChangeCorrectionAnalysisTestBase):
    # ------------------------------------------------------------------
    # FAILED / TIMEOUT -> analysis is requested.
    # ------------------------------------------------------------------
    def test_failed_test_status_performs_analysis(self):
        self._add_step()  # left pending -> plan incomplete, a real blocker
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertTrue(result["correction"]["correction_required"])
        self.assertTrue(result["analysis_performed"])
        self.assertIsNotNone(result["analysis"])
        self.assertEqual(result["analysis"], loop.request_analysis(self.goal.goal_id, self.plan.plan_id))

    def test_timeout_test_status_performs_analysis(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertTrue(result["correction"]["correction_required"])
        self.assertTrue(result["analysis_performed"])
        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_INCOMPLETE)

    # ------------------------------------------------------------------
    # PASSED -> analysis is not requested.
    # ------------------------------------------------------------------
    def test_passed_test_status_skips_analysis(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertFalse(result["correction"]["correction_required"])
        self.assertFalse(result["analysis_performed"])
        self.assertIsNone(result["analysis"])

    def test_passed_test_status_needs_no_analyzer(self):
        # No analyzer supplied at all - a PASSED result must never even
        # attempt to reach it, so this must not raise.
        loop = AgentLoop(self.goals, self.plans, self.controller)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        try:
            result = loop.request_code_change_correction_analysis(
                self.goal.goal_id, self.plan.plan_id, code_change_result
            )
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"request_code_change_correction_analysis required an "
                      f"analyzer for a passed result: {exc!r}")
        self.assertFalse(result["analysis_performed"])

    # ------------------------------------------------------------------
    # INVALID result -> analysis is not requested.
    # ------------------------------------------------------------------
    def test_invalid_result_skips_analysis(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, "not a result"
        )

        self.assertEqual(result["correction"]["reason"], "INVALID")
        self.assertFalse(result["correction"]["correction_required"])
        self.assertFalse(result["analysis_performed"])
        self.assertIsNone(result["analysis"])

    def test_invalid_test_status_within_applied_change_skips_analysis(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_INVALID)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertFalse(result["correction"]["correction_required"])
        self.assertFalse(result["analysis_performed"])
        self.assertIsNone(result["analysis"])

    def test_change_failed_skips_analysis(self):
        # The change itself never applied - no test ever ran, so this
        # is CHANGE_FAILED, not a FAILED/TIMEOUT test status; no
        # analysis is required.
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_NOT_APPLIED)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(result["correction"]["reason"], "CHANGE_FAILED")
        self.assertFalse(result["correction"]["correction_required"])
        self.assertFalse(result["analysis_performed"])
        self.assertIsNone(result["analysis"])

    # ------------------------------------------------------------------
    # The correction decision itself is reused unchanged.
    # ------------------------------------------------------------------
    def test_correction_matches_evaluate_code_change_correction_decision(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(
            result["correction"], loop.evaluate_code_change_correction_decision(code_change_result)
        )
        self.assertEqual(
            result["correction"], build_code_change_correction_decision(code_change_result)
        )

    # ------------------------------------------------------------------
    # Original results are preserved (requirement 7).
    # ------------------------------------------------------------------
    def test_original_change_result_and_test_result_preserved(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        change_result_marker = {"file": "app.py", "applied": True}
        test_result_marker = {"success": False, "timed_out": False, "failures": 2}
        code_change_result = _code_change_result(
            CHANGE_STATUS_APPLIED, RESULT_FAILED,
            change_result=change_result_marker, test_result=test_result_marker,
        )

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(result["change_result"], change_result_marker)
        self.assertEqual(result["test_result"], test_result_marker)

    def test_preserved_results_present_even_when_no_analysis_performed(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        change_result_marker = {"file": "app.py", "applied": True}
        test_result_marker = {"success": True, "timed_out": False}
        code_change_result = _code_change_result(
            CHANGE_STATUS_APPLIED, RESULT_PASSED,
            change_result=change_result_marker, test_result=test_result_marker,
        )

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(result["change_result"], change_result_marker)
        self.assertEqual(result["test_result"], test_result_marker)
        self.assertIsNone(result["analysis"])

    def test_malformed_input_preserves_none_for_both_results(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, "not a result"
        )

        self.assertIsNone(result["change_result"])
        self.assertIsNone(result["test_result"])

    # ------------------------------------------------------------------
    # No analyzer supplied, but analysis is actually needed -> raises.
    # ------------------------------------------------------------------
    def test_failed_without_analyzer_raises(self):
        loop = AgentLoop(self.goals, self.plans, self.controller)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        with self.assertRaises(ValueError):
            loop.request_code_change_correction_analysis(
                self.goal.goal_id, self.plan.plan_id, code_change_result
            )

    # ------------------------------------------------------------------
    # Missing Plan/Goal data is handled safely.
    # ------------------------------------------------------------------
    def test_unknown_plan_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        try:
            result = loop.request_code_change_correction_analysis(
                self.goal.goal_id, "no-such-plan", code_change_result
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"request_code_change_correction_analysis raised for an "
                      f"unknown plan_id: {exc!r}")

        self.assertTrue(result["analysis_performed"])
        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_UNKNOWN)

    def test_unknown_goal_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)

        result = loop.request_code_change_correction_analysis(
            "no-such-goal", self.plan.plan_id, code_change_result
        )

        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_UNKNOWN)

    # ------------------------------------------------------------------
    # No Plan/step mutation, and no capability/step execution, occurs.
    # ------------------------------------------------------------------
    def test_no_plan_modification_when_correction_required(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_plan_modification_when_correction_not_required(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_step_is_executed(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        loop.request_code_change_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertEqual(evaluation["completed_steps"], [])

    # ------------------------------------------------------------------
    # Never auto-invoked by run(), never generates/applies a proposal.
    # ------------------------------------------------------------------
    def test_run_never_calls_this_automatically(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertNotIn("correction", result)
        self.assertNotIn("analysis_performed", result)
        self.assertNotIn("analysis", result)
        self.assertNotIn("change_result", result)

    def test_existing_request_correction_analysis_unaffected(self):
        # The pre-existing, bare-test_result correction-analysis
        # connection (Prompt 322) must keep working unchanged.
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, {"success": False, "timed_out": False}
        )
        self.assertTrue(result["analysis_performed"])


if __name__ == "__main__":
    unittest.main()
