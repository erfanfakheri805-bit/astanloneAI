"""
Tests for self_upgrade.capability_correction_verification
.verify_capability_correction (Prompt 369) - retesting a capability
once after an APPLIED correction and comparing with the previous
failure.

The real chain (test -> evaluate -> analyze -> apply one correction ->
retest) runs only inside isolated temp directories.

Run directly:
    python -m unittest tests.test_capability_correction_verification -v
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import execution.code_change_apply_capability as code_change_apply_module
import self_upgrade.capability_correction_verification as ccv
from self_upgrade.capability_correction_verification import (
    verify_capability_correction,
    STATUS_VERIFIED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID,
    ALL_STATUSES,
)
from self_upgrade.capability_correction_apply import apply_capability_correction
from self_upgrade.capability_correction_analysis import build_capability_correction_analysis
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_test_execution import run_capability_tests
from self_upgrade.capability_file_apply import STATUS_APPLIED
from code_generation.generated_code_validator import VALIDATION_VALID
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController

BROKEN = "def demo():\n    return missing_name\n"
TEST = ("import unittest\nfrom demo_capability import demo\n\n"
        "class T(unittest.TestCase):\n    def test_demo(self):\n"
        "        self.assertEqual(demo(), 1)\n")
TARGET = "test_demo_capability"


class Chain(unittest.TestCase):
    """Builds the real chain up to an APPLIED correction."""

    def setUp(self):
        self.sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.path = os.path.join(self.sandbox, "demo_capability.py")
        self.write(self.path, BROKEN)
        self.write(os.path.join(self.sandbox, TARGET + ".py"), TEST)
        apply_result = dict(
            capability_name="demo_capability", target_module="generated.demo_capability",
            status=STATUS_APPLIED, file_path=self.path, bytes_written=1,
            validation_result={"status": VALIDATION_VALID}, error=None)
        self.previous = run_capability_tests(apply_result, self.sandbox, TARGET)

    @staticmethod
    def write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def correct(self, new_text="return 1"):
        analysis = build_capability_correction_analysis(
            evaluate_capability_test_result(self.previous), allowed_dirs=[self.sandbox])
        return apply_capability_correction(
            analysis, [{"old_text": "return missing_name", "new_text": new_text}],
            allowed_dirs=[self.sandbox])

    def verify(self, correction=None, previous=None, **kwargs):
        kwargs.setdefault("allowed_dirs", [self.sandbox])
        return verify_capability_correction(
            previous if previous is not None else self.previous,
            correction if correction is not None else self.correct(),
            self.sandbox, TARGET, **kwargs)


class VerifiedAndFailedTests(Chain):
    def test_previous_failure_precondition(self):
        self.assertEqual(self.previous["status"], "FAILED")

    def test_passing_retest_is_verified(self):
        result = self.verify()
        self.assertEqual(result["status"], STATUS_VERIFIED)
        self.assertTrue(result["correction_verified"])
        self.assertTrue(result["improved"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["previous_status"], "FAILED")
        self.assertEqual(result["retest_status"], "PASSED")
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(result["previous_evaluation"]["evaluation_status"], "NEEDS_CORRECTION")
        self.assertEqual(result["retest_evaluation"]["evaluation_status"], "SUCCESS")
        self.assertEqual(set(ALL_STATUSES),
                         {"VERIFIED", "FAILED", "TIMEOUT", "BLOCKED", "INVALID"})

    def test_failing_retest_is_failed(self):
        correction = self.correct("return 2")  # valid Python, still wrong
        result = self.verify(correction)
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertFalse(result["correction_verified"])
        self.assertFalse(result["improved"])  # same failure count as before
        self.assertEqual(result["retest_status"], "FAILED")
        self.assertTrue(result["errors"])

    def test_original_and_retest_results_are_both_preserved(self):
        previous_snapshot = copy.deepcopy(self.previous)
        correction = self.correct()
        correction_snapshot = copy.deepcopy(correction)
        result = self.verify(correction)
        self.assertEqual(result["previous_test_result"], previous_snapshot)
        self.assertEqual(result["retest_result"]["status"], "PASSED")
        self.assertEqual(result["correction_apply_result"], correction_snapshot)
        self.assertEqual(self.previous, previous_snapshot)  # inputs untouched
        self.assertEqual(correction, correction_snapshot)
        # original failure details survive alongside the new result
        self.assertTrue(any("NameError" in e for e in result["previous_test_result"]["errors"]))

    def test_retest_runs_once_with_the_same_target(self):
        correction = self.correct()
        with mock.patch.object(ccv, "run_capability_tests",
                               wraps=ccv.run_capability_tests) as runner:
            self.verify(correction)
        runner.assert_called_once()
        args, kwargs = runner.call_args
        self.assertEqual(args[1:3], (self.sandbox, TARGET))
        self.assertEqual(kwargs["timeout_seconds"], self.previous["timeout_seconds"])


class ControlledStatusTests(Chain):
    """Retest outcomes that are impractical to trigger for real are
    injected through the (single) reused test-execution function."""

    def _with_retest(self, retest):
        correction = self.correct()
        with mock.patch.object(ccv, "run_capability_tests", return_value=retest):
            return self.verify(correction)

    def _retest(self, **overrides):
        fields = dict(
            capability_name="demo_capability", file_path=self.path, status="PASSED",
            tests_run=1, tests_passed=1, tests_failed=0, execution_time=0.1,
            output=".", errors=["OK"], timeout_seconds=30)
        fields.update(overrides)
        return fields

    def test_timeout(self):
        result = self._with_retest(self._retest(
            status="TIMEOUT", tests_run=None, tests_passed=None, tests_failed=None,
            output=None, errors=[], timeout_seconds=3))
        self.assertEqual(result["status"], STATUS_TIMEOUT)
        self.assertFalse(result["correction_verified"])
        self.assertIn("3", result["errors"][0])

    def test_blocked(self):
        result = self._with_retest(self._retest(
            status="BLOCKED", tests_run=None, tests_passed=None, tests_failed=None,
            output=None, errors=["outside the allowed workspace"]))
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertFalse(result["correction_verified"])

    def test_invalid_retest_result(self):
        result = self._with_retest(self._retest(
            status="INVALID", tests_run=None, tests_passed=None, tests_failed=None,
            output=None, errors=["test_target is required."]))
        self.assertEqual(result["status"], STATUS_INVALID)

    def test_inconsistent_passed_retest_is_invalid_not_verified(self):
        result = self._with_retest(self._retest(tests_failed=1, tests_passed=0))
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertFalse(result["correction_verified"])

    def test_fewer_failures_counts_as_improved_but_not_verified(self):
        self.previous["tests_run"], self.previous["tests_failed"] = 3, 2
        self.previous["tests_passed"] = 1
        result = self._with_retest(self._retest(
            status="FAILED", tests_run=3, tests_passed=2, tests_failed=1,
            errors=["AssertionError"]))
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertTrue(result["improved"])
        self.assertFalse(result["correction_verified"])

    def test_real_blocked_when_file_outside_allowed_dirs(self):
        other = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(other, ignore_errors=True))
        result = self.verify(self.correct(), allowed_dirs=[other])
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(self.read(), BROKEN.replace("return missing_name", "return 1"))


class InvalidInputTests(Chain):
    def assert_invalid_and_not_run(self, result):
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertFalse(result["correction_verified"])
        self.assertTrue(result["errors"])

    def test_garbage_inputs(self):
        with mock.patch.object(ccv, "run_capability_tests") as runner:
            for previous, correction in ((None, None), ("x", {}), (self.previous, None),
                                         (self.previous, "x"), ({}, {})):
                with self.subTest(previous=previous, correction=correction):
                    self.assert_invalid_and_not_run(verify_capability_correction(
                        previous, correction, self.sandbox, TARGET))
        runner.assert_not_called()

    def test_correction_not_applied_is_never_retested(self):
        correction = self.correct()
        for status, flag in (("INVALID", False), ("BLOCKED", False),
                             ("NO_CORRECTION_REQUIRED", False), ("APPLIED", False)):
            broken = dict(correction, status=status, correction_applied=flag)
            with mock.patch.object(ccv, "run_capability_tests") as runner:
                self.assert_invalid_and_not_run(self.verify(broken))
            runner.assert_not_called()

    def test_previous_must_be_a_failure(self):
        passing = dict(self.previous, status="PASSED", tests_run=1, tests_passed=1,
                       tests_failed=0, errors=["OK"])
        correction = self.correct()
        with mock.patch.object(ccv, "run_capability_tests") as runner:
            self.assert_invalid_and_not_run(self.verify(correction, previous=passing))
            timeout = dict(self.previous, status="TIMEOUT", tests_run=None, tests_passed=None,
                           tests_failed=None, errors=[])
            self.assert_invalid_and_not_run(self.verify(correction, previous=timeout))
        runner.assert_not_called()

    def test_capability_mismatch_is_rejected(self):
        correction = dict(self.correct(), capability_name="other_capability")
        with mock.patch.object(ccv, "run_capability_tests") as runner:
            result = self.verify(correction)
        self.assert_invalid_and_not_run(result)
        self.assertIn("name", result["errors"][0])
        runner.assert_not_called()

    def test_path_mismatch_is_rejected(self):
        other = os.path.join(self.sandbox, "other.py")
        self.write(other, BROKEN)
        correction = dict(self.correct(), file_path=other)
        with mock.patch.object(ccv, "run_capability_tests") as runner:
            result = self.verify(correction)
        self.assert_invalid_and_not_run(result)
        self.assertIn("path", result["errors"][0])
        runner.assert_not_called()

    def test_correction_without_valid_source_check_is_rejected(self):
        correction = dict(self.correct(), code_validation=None)
        with mock.patch.object(ccv, "run_capability_tests") as runner:
            self.assert_invalid_and_not_run(self.verify(correction))
        runner.assert_not_called()

    def test_missing_test_target_is_invalid_via_existing_runner(self):
        result = verify_capability_correction(
            self.previous, self.correct(), self.sandbox, "", allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], STATUS_INVALID)


class SafetyAndCompatibilityTests(Chain):
    def test_no_additional_correction_is_applied(self):
        correction = self.correct("return 2")
        after_correction = self.read()
        with mock.patch.object(code_change_apply_module, "make_text_file_edit_handler") as edit, \
                mock.patch.object(code_change_apply_module, "make_code_change_apply_handler") as apply_:
            result = self.verify(correction)
        self.assertEqual(result["status"], STATUS_FAILED)  # still failing, left as is
        edit.assert_not_called()
        apply_.assert_not_called()
        self.assertEqual(self.read(), after_correction)

    def test_only_the_corrected_file_differs_afterwards(self):
        correction = self.correct()
        def files():
            state = {}
            for name in os.listdir(self.sandbox):
                if name.endswith(".py"):
                    with open(os.path.join(self.sandbox, name), "rb") as handle:
                        state[name] = handle.read()
            return state
        before = files()
        self.verify(correction)
        self.assertEqual(files(), before)

    def test_agent_loop_exposes_the_same_operation(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        result = loop.verify_capability_correction(
            self.previous, self.correct(), self.sandbox, TARGET, allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], STATUS_VERIFIED)
        self.assertEqual(loop.verify_capability_correction(
            None, None, self.sandbox, TARGET)["status"], STATUS_INVALID)

    def test_existing_test_execution_behavior_unchanged(self):
        apply_result = dict(
            capability_name="demo_capability", target_module="m", status=STATUS_APPLIED,
            file_path=self.path, bytes_written=1,
            validation_result={"status": VALIDATION_VALID}, error=None)
        again = run_capability_tests(apply_result, self.sandbox, TARGET)
        self.assertEqual(again["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
