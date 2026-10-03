"""
Tests for agent/generated_code_execution_evaluation.py - connects the
existing `execute_generated_code` result
(code_generation/generated_code_execution.py) to AgentLoop via
`AgentLoop.evaluate_generated_code_execution_result`
(agent/agent_loop.py).

Covers all four mapped statuses (PASSED/FAILED/TIMEOUT/INVALID),
correction_required being true only for a final FAILED/TIMEOUT status,
the original target_file/error always being preserved unmodified, no
input ever raising, and
AgentLoop.evaluate_generated_code_execution_result delegating to this
module unchanged.

Run directly:
    python -m unittest tests.test_generated_code_execution_evaluation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.generated_code_execution_evaluation import (
    classify_generated_code_execution_result,
    build_generated_code_execution_evaluation,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID
from code_generation.generated_code_execution import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_REJECTED,
)

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _execution_result(status, target_file="/sandbox/generated.py", error=None,
                       stdout=None, stderr=None):
    return {
        "status": status,
        "target_file": target_file,
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
    }


class TestClassifyGeneratedCodeExecutionResult(unittest.TestCase):
    def test_executed_maps_to_passed(self):
        result = _execution_result(STATUS_EXECUTED, stdout="ok")
        self.assertEqual(classify_generated_code_execution_result(result), RESULT_PASSED)

    def test_failed_maps_to_failed(self):
        result = _execution_result(STATUS_FAILED, error="exited with return code 1")
        self.assertEqual(classify_generated_code_execution_result(result), RESULT_FAILED)

    def test_timeout_maps_to_timeout(self):
        result = _execution_result(STATUS_TIMEOUT, error="timed out after 5 seconds")
        self.assertEqual(classify_generated_code_execution_result(result), RESULT_TIMEOUT)

    def test_rejected_maps_to_invalid(self):
        result = _execution_result(STATUS_REJECTED, error="path outside allowed directories")
        self.assertEqual(classify_generated_code_execution_result(result), RESULT_INVALID)

    def test_non_dict_is_invalid(self):
        self.assertEqual(classify_generated_code_execution_result("not a result"), RESULT_INVALID)
        self.assertEqual(classify_generated_code_execution_result(None), RESULT_INVALID)

    def test_unrecognised_status_is_invalid(self):
        result = _execution_result("SOMETHING_ELSE")
        self.assertEqual(classify_generated_code_execution_result(result), RESULT_INVALID)


class TestBuildGeneratedCodeExecutionEvaluation(unittest.TestCase):
    def test_passed_shape_and_no_correction_required(self):
        result = _execution_result(STATUS_EXECUTED, target_file="/sandbox/foo.py")
        evaluation = build_generated_code_execution_evaluation(result)
        self.assertEqual(
            evaluation,
            {
                "status": RESULT_PASSED,
                "target_file": "/sandbox/foo.py",
                "execution_status": STATUS_EXECUTED,
                "error": None,
                "correction_required": False,
            },
        )

    def test_failed_requires_correction(self):
        result = _execution_result(
            STATUS_FAILED, target_file="/sandbox/foo.py",
            error="Execution of '/sandbox/foo.py' exited with return code 1.",
        )
        evaluation = build_generated_code_execution_evaluation(result)
        self.assertEqual(evaluation["status"], RESULT_FAILED)
        self.assertEqual(evaluation["execution_status"], STATUS_FAILED)
        self.assertEqual(evaluation["target_file"], "/sandbox/foo.py")
        self.assertEqual(
            evaluation["error"], "Execution of '/sandbox/foo.py' exited with return code 1."
        )
        self.assertTrue(evaluation["correction_required"])

    def test_timeout_requires_correction(self):
        result = _execution_result(
            STATUS_TIMEOUT, target_file="/sandbox/foo.py",
            error="Execution of '/sandbox/foo.py' timed out after 5 seconds.",
        )
        evaluation = build_generated_code_execution_evaluation(result)
        self.assertEqual(evaluation["status"], RESULT_TIMEOUT)
        self.assertEqual(evaluation["execution_status"], STATUS_TIMEOUT)
        self.assertTrue(evaluation["correction_required"])

    def test_rejected_invalid_does_not_require_correction(self):
        # Requirement: correction_required is true only for FAILED or
        # TIMEOUT - a rejected/never-run execution is INVALID, not
        # flagged for correction here.
        result = _execution_result(
            STATUS_REJECTED, target_file="/sandbox/foo.py",
            error="Code generation did not succeed; refusing to execute it.",
        )
        evaluation = build_generated_code_execution_evaluation(result)
        self.assertEqual(evaluation["status"], RESULT_INVALID)
        self.assertFalse(evaluation["correction_required"])

    def test_non_dict_input_never_raises_and_is_invalid(self):
        evaluation = build_generated_code_execution_evaluation("not a result")
        self.assertEqual(
            evaluation,
            {
                "status": RESULT_INVALID,
                "target_file": None,
                "execution_status": None,
                "error": None,
                "correction_required": False,
            },
        )

    def test_none_input_never_raises(self):
        evaluation = build_generated_code_execution_evaluation(None)
        self.assertEqual(evaluation["status"], RESULT_INVALID)
        self.assertFalse(evaluation["correction_required"])

    def test_original_target_file_and_error_preserved_unmodified(self):
        result = _execution_result(
            STATUS_FAILED, target_file="/sandbox/exact/path.py", error="exact error text",
        )
        evaluation = build_generated_code_execution_evaluation(result)
        self.assertIs(evaluation["target_file"], result["target_file"])
        self.assertIs(evaluation["error"], result["error"])


class TestAgentLoopEvaluateGeneratedCodeExecutionResult(unittest.TestCase):
    """Requirement: make the evaluation result available to the
    existing AgentLoop without creating a duplicate evaluation/agent
    system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_delegates_to_build_function_unchanged(self):
        result = _execution_result(STATUS_EXECUTED)
        self.assertEqual(
            self.loop.evaluate_generated_code_execution_result(result),
            build_generated_code_execution_evaluation(result),
        )

    def test_passed_via_agent_loop(self):
        result = _execution_result(STATUS_EXECUTED, target_file="/sandbox/foo.py")
        evaluation = self.loop.evaluate_generated_code_execution_result(result)
        self.assertEqual(evaluation["status"], RESULT_PASSED)
        self.assertFalse(evaluation["correction_required"])

    def test_failed_via_agent_loop(self):
        result = _execution_result(STATUS_FAILED, error="exited with return code 1")
        evaluation = self.loop.evaluate_generated_code_execution_result(result)
        self.assertEqual(evaluation["status"], RESULT_FAILED)
        self.assertTrue(evaluation["correction_required"])

    def test_timeout_via_agent_loop(self):
        result = _execution_result(STATUS_TIMEOUT, error="timed out")
        evaluation = self.loop.evaluate_generated_code_execution_result(result)
        self.assertEqual(evaluation["status"], RESULT_TIMEOUT)
        self.assertTrue(evaluation["correction_required"])

    def test_invalid_via_agent_loop_never_raises(self):
        evaluation = self.loop.evaluate_generated_code_execution_result("not a result")
        self.assertEqual(evaluation["status"], RESULT_INVALID)
        self.assertFalse(evaluation["correction_required"])

    def test_rejected_via_agent_loop_is_invalid_not_correction_required(self):
        result = _execution_result(STATUS_REJECTED, error="refused before running")
        evaluation = self.loop.evaluate_generated_code_execution_result(result)
        self.assertEqual(evaluation["status"], RESULT_INVALID)
        self.assertFalse(evaluation["correction_required"])

    def test_never_automatically_retries_or_modifies_anything(self):
        # Evaluating a FAILED/TIMEOUT result only reports
        # correction_required - it never itself re-executes the
        # generated code or modifies the Plan (no plan/goal was even
        # created in this test's setUp).
        result = _execution_result(STATUS_TIMEOUT, error="timed out")
        self.loop.evaluate_generated_code_execution_result(result)
        self.assertEqual(self.loop._goal_manager.get_goal("anything"), None)


if __name__ == "__main__":
    unittest.main()
