"""
Tests for self_upgrade.capability_evaluation.evaluate_capability_test_result
(Prompt 366) - structured evaluation of a CapabilityTestResult.

Most tests feed hand-built CapabilityTestResult dicts (the exact shape
`run_capability_tests` returns); one class also feeds genuine results
from the real, sandboxed test-execution stage (isolated temp dir only).

Run directly:
    python -m unittest tests.test_capability_evaluation -v
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.capability_evaluation import (
    evaluate_capability_test_result,
    EVAL_SUCCESS, EVAL_FAILED, EVAL_TIMEOUT, EVAL_BLOCKED, EVAL_INVALID,
    EVAL_NEEDS_CORRECTION, ALL_EVALUATION_STATUSES,
)
from self_upgrade.capability_test_execution import (
    run_capability_tests,
    STATUS_PASSED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID,
)
from self_upgrade.capability_file_apply import STATUS_APPLIED
from code_generation.generated_code_validator import VALIDATION_VALID
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController


def _test_result(**overrides):
    fields = dict(
        capability_name="demo_capability",
        file_path="/sandbox/demo_capability.py",
        status=STATUS_PASSED,
        tests_run=3, tests_passed=3, tests_failed=0,
        execution_time=0.12, output="...", errors=["Ran 3 tests\n\nOK"],
        timeout_seconds=30,
    )
    fields.update(overrides)
    return fields


def _failed(**overrides):
    fields = dict(
        status=STATUS_FAILED, tests_run=3, tests_passed=2, tests_failed=1,
        output="F..", errors=["AssertionError: 42 != 43"],
    )
    fields.update(overrides)
    return _test_result(**fields)


class OutcomeTests(unittest.TestCase):
    def test_passed_is_success(self):
        result = evaluate_capability_test_result(_test_result())
        self.assertEqual(result["evaluation_status"], EVAL_SUCCESS)
        self.assertTrue(result["success"])
        self.assertIsNone(result["failure_reason"])
        self.assertFalse(result["correction_required"])
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual((result["tests_run"], result["tests_passed"], result["tests_failed"]), (3, 3, 0))

    def test_failed_with_useful_error_needs_correction(self):
        result = evaluate_capability_test_result(_failed())
        self.assertEqual(result["evaluation_status"], EVAL_NEEDS_CORRECTION)
        self.assertFalse(result["success"])
        self.assertTrue(result["correction_required"])
        self.assertIn("1", result["failure_reason"])

    def test_failed_with_only_failed_count_needs_correction(self):
        result = evaluate_capability_test_result(_failed(errors=[], output=None))
        self.assertEqual(result["evaluation_status"], EVAL_NEEDS_CORRECTION)

    def test_failed_without_useful_information_is_failed(self):
        result = evaluate_capability_test_result(
            _failed(tests_failed=0, tests_passed=3, errors=[""], output="  "))
        self.assertEqual(result["evaluation_status"], EVAL_FAILED)
        self.assertFalse(result["success"])
        self.assertFalse(result["correction_required"])

    def test_timeout(self):
        result = evaluate_capability_test_result(_test_result(
            status=STATUS_TIMEOUT, tests_run=None, tests_passed=None, tests_failed=None,
            errors=[], output=None, timeout_seconds=7))
        self.assertEqual(result["evaluation_status"], EVAL_TIMEOUT)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_seconds"], 7)
        self.assertIn("7", result["failure_reason"])
        self.assertTrue(result["correction_required"])
        self.assertFalse(result["success"])

    def test_blocked(self):
        result = evaluate_capability_test_result(_test_result(
            status=STATUS_BLOCKED, tests_run=None, tests_passed=None, tests_failed=None,
            output=None, errors=["file_path is outside the allowed workspace."]))
        self.assertEqual(result["evaluation_status"], EVAL_BLOCKED)
        self.assertIn("outside the allowed workspace", result["failure_reason"])
        self.assertFalse(result["correction_required"])
        self.assertFalse(result["success"])

    def test_invalid_passes_through(self):
        result = evaluate_capability_test_result(_test_result(
            capability_name=None, file_path=None,
            status=STATUS_INVALID, tests_run=None, tests_passed=None, tests_failed=None,
            output=None, errors=["test_target is required."]))
        self.assertEqual(result["evaluation_status"], EVAL_INVALID)
        self.assertEqual(result["errors"], ["test_target is required."])
        self.assertFalse(result["correction_required"])

    def test_all_statuses_are_declared(self):
        self.assertEqual(set(ALL_EVALUATION_STATUSES), {
            "SUCCESS", "FAILED", "TIMEOUT", "BLOCKED", "INVALID", "NEEDS_CORRECTION"})


class IncompleteOrInconsistentTests(unittest.TestCase):
    def _assert_invalid(self, value):
        result = evaluate_capability_test_result(value)
        self.assertEqual(result["evaluation_status"], EVAL_INVALID)
        self.assertFalse(result["success"])
        self.assertFalse(result["correction_required"])
        self.assertTrue(result["failure_reason"])
        return result

    def test_non_dict_inputs(self):
        for value in (None, "PASSED", 42, [], ()):
            self._assert_invalid(value)

    def test_missing_keys(self):
        broken = _test_result()
        del broken["tests_run"]
        self._assert_invalid(broken)
        self._assert_invalid({})

    def test_unrecognized_status(self):
        self._assert_invalid(_test_result(status="MAYBE"))

    def test_passed_with_failed_tests(self):
        self._assert_invalid(_test_result(tests_failed=1, tests_passed=2))

    def test_passed_with_no_tests_run(self):
        self._assert_invalid(_test_result(tests_run=0, tests_passed=0, tests_failed=0))

    def test_passed_with_missing_counts(self):
        self._assert_invalid(_test_result(tests_run=None))

    def test_counts_exceed_tests_run(self):
        self._assert_invalid(_failed(tests_run=2, tests_passed=2, tests_failed=1))

    def test_negative_or_wrong_type_counts(self):
        self._assert_invalid(_failed(tests_failed=-1))
        self._assert_invalid(_failed(tests_run="3"))
        self._assert_invalid(_failed(tests_run=True))

    def test_executed_result_missing_identity(self):
        self._assert_invalid(_test_result(capability_name=""))
        self._assert_invalid(_failed(file_path=None))

    def test_errors_not_a_list(self):
        self._assert_invalid(_test_result(errors="oops"))


class PreservationTests(unittest.TestCase):
    def test_failure_information_preserved(self):
        source = _failed(execution_time=1.5, output="F..", errors=["Traceback...", "AssertionError"])
        result = evaluate_capability_test_result(source)
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(result["file_path"], "/sandbox/demo_capability.py")
        self.assertEqual((result["tests_run"], result["tests_passed"], result["tests_failed"]), (3, 2, 1))
        self.assertEqual(result["output"], "F..")
        self.assertEqual(result["errors"], ["Traceback...", "AssertionError"])
        self.assertEqual(result["execution_time"], 1.5)
        self.assertEqual(result["timeout_seconds"], 30)
        self.assertEqual(result["test_result_status"], STATUS_FAILED)
        self.assertEqual(result["original_test_result"], source)

    def test_timeout_information_preserved(self):
        source = _test_result(status=STATUS_TIMEOUT, tests_run=1, tests_passed=0,
                              tests_failed=0, output="partial", errors=[], timeout_seconds=5,
                              execution_time=5.0)
        result = evaluate_capability_test_result(source)
        self.assertEqual(result["timeout_seconds"], 5)
        self.assertEqual(result["execution_time"], 5.0)
        self.assertEqual(result["output"], "partial")

    def test_input_not_mutated_and_original_is_a_copy(self):
        source = _failed()
        snapshot = copy.deepcopy(source)
        result = evaluate_capability_test_result(source)
        self.assertEqual(source, snapshot)
        result["original_test_result"]["errors"].append("x")
        result["errors"].append("y")
        self.assertEqual(source, snapshot)

    def test_correction_required_determination(self):
        expectations = {
            "passed": (_test_result(), False),
            "failed_useful": (_failed(), True),
            "failed_empty": (_failed(tests_failed=0, tests_passed=3, errors=[], output=None), False),
            "timeout": (_test_result(status=STATUS_TIMEOUT, tests_run=None, tests_passed=None,
                                     tests_failed=None, errors=[], output=None), True),
            "blocked": (_test_result(status=STATUS_BLOCKED, tests_run=None, tests_passed=None,
                                     tests_failed=None, errors=["x"], output=None), False),
            "invalid": (_test_result(status=STATUS_INVALID, tests_run=None, tests_passed=None,
                                     tests_failed=None, errors=["x"], output=None), False),
        }
        for name, (source, expected) in expectations.items():
            with self.subTest(name):
                self.assertEqual(
                    evaluate_capability_test_result(source)["correction_required"], expected)


class RealTestExecutionIntegrationTests(unittest.TestCase):
    """Feed genuine `run_capability_tests` results through the evaluator."""

    MODULE = "def demo_capability():\n    return 42\n"
    TEST = ("import unittest\nfrom demo_capability import demo_capability\n\n"
            "class T(unittest.TestCase):\n    def test_value(self):\n"
            "        self.assertEqual(demo_capability(), {expected})\n")

    def _run(self, expected):
        with tempfile.TemporaryDirectory() as sandbox:
            path = os.path.join(sandbox, "demo_capability.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.MODULE)
            with open(os.path.join(sandbox, "test_demo_capability.py"), "w", encoding="utf-8") as handle:
                handle.write(self.TEST.format(expected=expected))
            apply_result = dict(
                capability_name="demo_capability", target_module="generated.demo_capability",
                status=STATUS_APPLIED, file_path=path, bytes_written=10,
                validation_result={"status": VALIDATION_VALID}, error=None)
            return run_capability_tests(apply_result, sandbox, "test_demo_capability")

    def test_real_passing_run_is_success(self):
        result = evaluate_capability_test_result(self._run(42))
        self.assertEqual(result["evaluation_status"], EVAL_SUCCESS)

    def test_real_failing_run_needs_correction(self):
        result = evaluate_capability_test_result(self._run(43))
        self.assertEqual(result["evaluation_status"], EVAL_NEEDS_CORRECTION)
        self.assertTrue(result["correction_required"])
        self.assertEqual(result["tests_failed"], 1)
        self.assertTrue(any("AssertionError" in e for e in result["errors"]))

    def test_real_malformed_apply_result_is_invalid(self):
        result = evaluate_capability_test_result(run_capability_tests({}, "/tmp", "x"))
        self.assertEqual(result["evaluation_status"], EVAL_INVALID)


class AgentLoopAndCompatibilityTests(unittest.TestCase):
    def test_agent_loop_exposes_evaluator_unchanged(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        source = _failed()
        self.assertEqual(loop.evaluate_capability_test_result(source),
                         evaluate_capability_test_result(source))
        self.assertEqual(loop.evaluate_capability_test_result(None)["evaluation_status"], EVAL_INVALID)

    def test_test_execution_vocabulary_unchanged(self):
        self.assertEqual(
            (STATUS_PASSED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID),
            ("PASSED", "FAILED", "TIMEOUT", "BLOCKED", "INVALID"))


if __name__ == "__main__":
    unittest.main()
