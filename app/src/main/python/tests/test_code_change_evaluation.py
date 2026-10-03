"""
Tests for agent/code_change_evaluation.py - connects the existing
`code_change_apply_and_test` capability's own structured result to
AgentLoop via `AgentLoop.evaluate_code_change_result`
(agent/agent_loop.py).

Covers the five distinguishable states (change succeeded + test
passed, change succeeded + test failed, change failed, test timed
out, invalid operation), correction_required being true only for a
final FAILED/TIMEOUT test status, the original change_result/
test_result always being preserved separately and unmodified, no
input ever raising, and AgentLoop.evaluate_code_change_result
delegating to this module unchanged.

Run directly:
    python -m unittest tests.test_code_change_evaluation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_evaluation import (
    ALL_CODE_CHANGE_STATES,
    STATE_CHANGE_SUCCEEDED_TEST_PASSED,
    STATE_CHANGE_SUCCEEDED_TEST_FAILED,
    STATE_CHANGE_FAILED,
    STATE_TEST_TIMEOUT,
    STATE_INVALID,
    classify_code_change_result,
    build_code_change_evaluation,
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


class TestClassifyCodeChangeResult(unittest.TestCase):
    def test_change_succeeded_test_passed(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        self.assertEqual(classify_code_change_result(result), STATE_CHANGE_SUCCEEDED_TEST_PASSED)

    def test_change_succeeded_test_failed(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        self.assertEqual(classify_code_change_result(result), STATE_CHANGE_SUCCEEDED_TEST_FAILED)

    def test_change_failed(self):
        result = _result(CHANGE_STATUS_NOT_APPLIED)
        self.assertEqual(classify_code_change_result(result), STATE_CHANGE_FAILED)

    def test_change_failed_even_if_test_status_somehow_present(self):
        # change_status NOT_APPLIED always means the test was never
        # started (see code_change_apply_and_test_capability.py) - a
        # caller-constructed dict with a stray test_status is still
        # classified purely off change_status.
        result = _result(CHANGE_STATUS_NOT_APPLIED, RESULT_PASSED)
        self.assertEqual(classify_code_change_result(result), STATE_CHANGE_FAILED)

    def test_test_timed_out(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)
        self.assertEqual(classify_code_change_result(result), STATE_TEST_TIMEOUT)

    def test_invalid_when_not_a_dict(self):
        for bad_input in (None, "oops", 42, [], object()):
            with self.subTest(bad_input=bad_input):
                self.assertEqual(classify_code_change_result(bad_input), STATE_INVALID)

    def test_invalid_when_change_status_missing(self):
        self.assertEqual(classify_code_change_result({}), STATE_INVALID)

    def test_invalid_when_change_status_unrecognised(self):
        result = _result("SOMETHING_ELSE")
        self.assertEqual(classify_code_change_result(result), STATE_INVALID)

    def test_invalid_when_applied_but_test_status_is_result_invalid(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_INVALID)
        self.assertEqual(classify_code_change_result(result), STATE_INVALID)

    def test_invalid_when_applied_but_test_never_ran(self):
        # e.g. python_test_runner itself raised - test_status is None,
        # error is set, per code_change_apply_and_test_capability.py's
        # own exception-handling branch.
        result = _result(CHANGE_STATUS_APPLIED, None, error="RuntimeError: boom")
        self.assertEqual(classify_code_change_result(result), STATE_INVALID)

    def test_all_states_is_the_fixed_five_way_vocabulary(self):
        self.assertEqual(
            set(ALL_CODE_CHANGE_STATES),
            {
                STATE_CHANGE_SUCCEEDED_TEST_PASSED,
                STATE_CHANGE_SUCCEEDED_TEST_FAILED,
                STATE_CHANGE_FAILED,
                STATE_TEST_TIMEOUT,
                STATE_INVALID,
            },
        )


class TestBuildCodeChangeEvaluation(unittest.TestCase):
    def test_correction_required_true_only_for_failed_or_timeout(self):
        cases = [
            (_result(CHANGE_STATUS_APPLIED, RESULT_PASSED), False),
            (_result(CHANGE_STATUS_APPLIED, RESULT_FAILED), True),
            (_result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT), True),
            (_result(CHANGE_STATUS_APPLIED, RESULT_INVALID), False),
            (_result(CHANGE_STATUS_NOT_APPLIED), False),
            (None, False),
        ]
        for result, expected in cases:
            with self.subTest(result=result):
                evaluation = build_code_change_evaluation(result)
                self.assertEqual(evaluation["correction_required"], expected)

    def test_change_result_and_test_result_stored_separately_and_unmodified(self):
        change_result = {"change_applied": True, "path": "thing.py"}
        test_result = {"success": True, "timed_out": False}
        result = _result(
            CHANGE_STATUS_APPLIED, RESULT_PASSED,
            change_result=change_result, test_result=test_result,
        )
        evaluation = build_code_change_evaluation(result)
        self.assertIs(evaluation["change_result"], change_result)
        self.assertIs(evaluation["test_result"], test_result)

    def test_exposes_small_structured_state_shape(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        evaluation = build_code_change_evaluation(result)
        self.assertEqual(
            set(evaluation.keys()),
            {
                "state", "change_status", "test_status",
                "correction_required", "error", "change_result", "test_result",
            },
        )

    def test_change_failed_case_reports_error_and_no_test_status(self):
        change_result = {"change_applied": False, "error": "fragment not found"}
        result = _result(
            CHANGE_STATUS_NOT_APPLIED,
            error="Code change was not applied; test was not started.",
            change_result=change_result,
        )
        evaluation = build_code_change_evaluation(result)
        self.assertEqual(evaluation["state"], STATE_CHANGE_FAILED)
        self.assertIsNone(evaluation["test_status"])
        self.assertFalse(evaluation["correction_required"])
        self.assertEqual(evaluation["error"], "Code change was not applied; test was not started.")
        self.assertIs(evaluation["change_result"], change_result)

    def test_never_raises_on_malformed_input(self):
        for bad_input in (None, "oops", 42, [], object(), {}):
            with self.subTest(bad_input=bad_input):
                evaluation = build_code_change_evaluation(bad_input)
                self.assertEqual(evaluation["state"], STATE_INVALID)
                self.assertFalse(evaluation["correction_required"])
                self.assertIsNone(evaluation["change_result"])
                self.assertIsNone(evaluation["test_result"])


class TestAgentLoopEvaluateCodeChangeResult(unittest.TestCase):
    """Requirement: connect this evaluation to the existing AgentLoop
    without creating a duplicate evaluation/agent system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_delegates_to_build_code_change_evaluation_unchanged(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        self.assertEqual(
            self.loop.evaluate_code_change_result(result),
            build_code_change_evaluation(result),
        )

    def test_change_succeeded_test_failed_via_agent_loop(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        evaluation = self.loop.evaluate_code_change_result(result)
        self.assertEqual(evaluation["state"], STATE_CHANGE_SUCCEEDED_TEST_FAILED)
        self.assertTrue(evaluation["correction_required"])

    def test_test_timeout_via_agent_loop(self):
        result = _result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)
        evaluation = self.loop.evaluate_code_change_result(result)
        self.assertEqual(evaluation["state"], STATE_TEST_TIMEOUT)
        self.assertTrue(evaluation["correction_required"])

    def test_invalid_operation_via_agent_loop_never_raises(self):
        evaluation = self.loop.evaluate_code_change_result("not a result")
        self.assertEqual(evaluation["state"], STATE_INVALID)
        self.assertFalse(evaluation["correction_required"])

    def test_never_automatically_performs_another_correction(self):
        # A FAILED/TIMEOUT evaluation only reports correction_required
        # - it never itself calls apply_correction_proposal or any
        # other Plan-modifying method; the Plan is untouched by this
        # call (no plan/goal was even created in this test's setUp).
        result = _result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)
        self.loop.evaluate_code_change_result(result)
        self.assertEqual(self.loop._plan_manager._plans, {})


if __name__ == "__main__":
    unittest.main()
