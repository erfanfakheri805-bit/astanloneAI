"""
Tests for agent/code_change_evaluation.py's
`build_code_change_correction_decision` and its AgentLoop connection,
`AgentLoop.evaluate_code_change_correction_decision`
(agent/agent_loop.py).

Covers the small, structured `{correction_required, reason,
source_test_status}` decision for every reachable code-change/test
outcome (PASSED, FAILED, TIMEOUT, INVALID, and a failed change),
malformed input never raising, and AgentLoop delegating to this
module's function unchanged.

Run directly:
    python -m unittest tests.test_code_change_correction_decision -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_evaluation import (
    build_code_change_correction_decision,
)
from execution.code_change_apply_and_test_capability import (
    CHANGE_STATUS_APPLIED,
    CHANGE_STATUS_NOT_APPLIED,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _result(change_status, test_status=None, error=None, change_result=None, test_result=None):
    return {
        "change_status": change_status,
        "test_status": test_status,
        "test_output": None,
        "error": error,
        "change_result": change_result,
        "test_result": test_result,
    }


class TestBuildCodeChangeCorrectionDecision(unittest.TestCase):
    def test_passed(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_APPLIED, RESULT_PASSED))
        self.assertEqual(
            decision,
            {"correction_required": False, "reason": "PASSED", "source_test_status": RESULT_PASSED},
        )

    def test_failed(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_APPLIED, RESULT_FAILED))
        self.assertEqual(
            decision,
            {"correction_required": True, "reason": "FAILED", "source_test_status": RESULT_FAILED},
        )

    def test_timeout(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT))
        self.assertEqual(
            decision,
            {"correction_required": True, "reason": "TIMEOUT", "source_test_status": RESULT_TIMEOUT},
        )

    def test_invalid_test_status(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_APPLIED, RESULT_INVALID))
        self.assertEqual(
            decision,
            {"correction_required": False, "reason": "INVALID", "source_test_status": RESULT_INVALID},
        )

    def test_invalid_malformed_input_never_raises(self):
        for bad_input in (None, "oops", 42, [], object(), {}):
            with self.subTest(bad_input=bad_input):
                decision = build_code_change_correction_decision(bad_input)
                self.assertEqual(
                    decision,
                    {"correction_required": False, "reason": "INVALID", "source_test_status": None},
                )

    def test_change_failure(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_NOT_APPLIED))
        self.assertEqual(
            decision,
            {"correction_required": False, "reason": "CHANGE_FAILED", "source_test_status": None},
        )

    def test_result_contains_only_the_three_required_keys(self):
        decision = build_code_change_correction_decision(_result(CHANGE_STATUS_APPLIED, RESULT_PASSED))
        self.assertEqual(set(decision.keys()), {"correction_required", "reason", "source_test_status"})


class TestAgentLoopEvaluateCodeChangeCorrectionDecision(unittest.TestCase):
    """Requirement: make the decision available to the existing
    AgentLoop state without creating a duplicate evaluation/correction
    system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_delegates_to_build_code_change_correction_decision_unchanged(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        self.assertEqual(
            self.loop.evaluate_code_change_correction_decision(result),
            build_code_change_correction_decision(result),
        )

    def test_passed_via_agent_loop(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        decision = self.loop.evaluate_code_change_correction_decision(result)
        self.assertFalse(decision["correction_required"])
        self.assertEqual(decision["reason"], "PASSED")

    def test_failed_via_agent_loop(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        decision = self.loop.evaluate_code_change_correction_decision(result)
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], "FAILED")

    def test_timeout_via_agent_loop(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)
        decision = self.loop.evaluate_code_change_correction_decision(result)
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], "TIMEOUT")

    def test_invalid_via_agent_loop_never_raises(self):
        decision = self.loop.evaluate_code_change_correction_decision("not a result")
        self.assertFalse(decision["correction_required"])
        self.assertEqual(decision["reason"], "INVALID")
        self.assertIsNone(decision["source_test_status"])

    def test_change_failure_via_agent_loop(self):
        result = _result(CHANGE_STATUS_NOT_APPLIED)
        decision = self.loop.evaluate_code_change_correction_decision(result)
        self.assertFalse(decision["correction_required"])
        self.assertEqual(decision["reason"], "CHANGE_FAILED")

    def test_never_automatically_performs_another_correction(self):
        # A FAILED/TIMEOUT decision only reports correction_required -
        # it never itself calls apply_correction_proposal or any other
        # Plan-modifying method; the Plan is untouched by this call (no
        # plan/goal was even created in this test's setUp).
        result = _result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)
        self.loop.evaluate_code_change_correction_decision(result)
        self.assertEqual(self.loop._plan_manager._plans, {})


if __name__ == "__main__":
    unittest.main()
