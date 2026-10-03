"""
Tests for agent/code_correction_retest.py - connects the existing
correction-application result (agent/code_correction_application.py,
Prompt 343) to the existing `python_test_runner` capability
(execution/python_test_runner_capability.py) and the existing
`agent.test_result_evaluation` classifier, made available on the
existing AgentLoop via `AgentLoop.retest_code_correction`
(agent/agent_loop.py).

Covers the four focused scenarios Prompt 344 asks for:
  - failed -> passed (improved)
  - failed -> failed (unchanged)
  - timeout -> passed (improved)
  - a rejected correction never triggers a retest

...plus a few small, deterministic extras: an unapplied (NOT_READY)
correction also skipping the retest, an already-passing original
result never entering the retest path (requirement 7), and a
timeout-after-failure being reported as a regression.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_correction_retest -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_retest import (
    build_code_correction_retest,
    compare_test_outcomes,
)
from agent.code_correction_application import (
    STATUS_APPLIED,
    STATUS_NOT_READY,
    STATUS_REJECTED,
)
from agent.test_result_evaluation import (
    RESULT_PASSED,
    RESULT_FAILED,
    RESULT_TIMEOUT,
    RESULT_INVALID,
)
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController

PASSING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestOk(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertEqual(1 + 1, 2)\n"
)

FAILING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestNotOk(unittest.TestCase):\n"
    "    def test_not_ok(self):\n"
    "        self.assertEqual(1 + 1, 3)\n"
)

HANGING_TEST_SOURCE = (
    "import time\n"
    "import unittest\n\n"
    "class TestHanging(unittest.TestCase):\n"
    "    def test_hangs(self):\n"
    "        time.sleep(60)\n"
)


def _test_result(success, timed_out=False):
    """A minimal, real-shaped `python_test_runner` result - only the
    two fields `classify_test_result` itself ever reads."""
    return {
        "success": success, "timed_out": timed_out, "return_code": 0 if success else 1,
        "stdout": "", "stderr": "", "tests_run": 1, "failures": 0, "errors": 0,
        "skipped": 0, "duration_seconds": 0.01, "path": "/x", "requested_path": "/x",
        "target": None,
    }


ORIGINAL_FAILED = _test_result(success=False)
ORIGINAL_TIMEOUT = _test_result(success=False, timed_out=True)
ORIGINAL_PASSED = _test_result(success=True)


class CodeCorrectionRetestTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.allowed_dir = self._tmp.name

    def _write(self, name, content):
        path = os.path.join(self.allowed_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _application(self, status, target_file=None):
        if target_file is None:
            target_file = os.path.join(self.allowed_dir, "generated.py")
        return {
            "status": status,
            "target_file": target_file,
            "changed": status == STATUS_APPLIED,
            "error": None if status == STATUS_APPLIED else "some reason",
        }

    def _correction_result(self, status, target_file=None):
        return {
            "proposal": {"status": "PROPOSED"},
            "validation_result": {"status": "VALID"},
            "application": self._application(status, target_file=target_file),
        }


# ----------------------------------------------------------------------
# 1. failed -> passed
# ----------------------------------------------------------------------
class TestFailedThenPassed(CodeCorrectionRetestTestBase):
    def test_retest_runs_and_reports_improved(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertTrue(result["retest_performed"])
        self.assertEqual(result["original_evaluation"]["classification"], RESULT_FAILED)
        self.assertEqual(result["retest_evaluation"]["classification"], RESULT_PASSED)
        comparison = result["comparison"]
        self.assertEqual(comparison["original_status"], RESULT_FAILED)
        self.assertEqual(comparison["retest_status"], RESULT_PASSED)
        self.assertTrue(comparison["improved"])
        self.assertFalse(comparison["regressed"])
        self.assertFalse(comparison["unchanged"])

    def test_correction_result_preserved_unchanged(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertIs(result["correction_result"], correction_result)


# ----------------------------------------------------------------------
# 2. failed -> failed
# ----------------------------------------------------------------------
class TestFailedThenFailed(CodeCorrectionRetestTestBase):
    def test_retest_runs_and_reports_unchanged(self):
        self._write("test_bad.py", FAILING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertTrue(result["retest_performed"])
        self.assertEqual(result["retest_evaluation"]["classification"], RESULT_FAILED)
        comparison = result["comparison"]
        self.assertFalse(comparison["improved"])
        self.assertFalse(comparison["regressed"])
        self.assertTrue(comparison["unchanged"])


# ----------------------------------------------------------------------
# 3. timeout -> passed
# ----------------------------------------------------------------------
class TestTimeoutThenPassed(CodeCorrectionRetestTestBase):
    def test_retest_runs_and_reports_improved(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_TIMEOUT, allowed_dirs=[self.allowed_dir],
        )

        self.assertTrue(result["retest_performed"])
        self.assertEqual(result["original_evaluation"]["classification"], RESULT_TIMEOUT)
        self.assertEqual(result["retest_evaluation"]["classification"], RESULT_PASSED)
        comparison = result["comparison"]
        self.assertTrue(comparison["improved"])
        self.assertFalse(comparison["regressed"])
        self.assertFalse(comparison["unchanged"])


# ----------------------------------------------------------------------
# 4. rejected correction -> no retest
# ----------------------------------------------------------------------
class TestRejectedCorrectionNeverRetests(CodeCorrectionRetestTestBase):
    def test_rejected_application_skips_retest(self):
        # Even with a passing test file sitting right there, a
        # REJECTED application must never trigger the reused test
        # runner at all.
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_REJECTED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertFalse(result["retest_performed"])
        self.assertIsNone(result["retest_evaluation"])
        self.assertIsNone(result["comparison"])
        # The original result is still evaluated and preserved -
        # only the retest itself is skipped.
        self.assertEqual(result["original_evaluation"]["classification"], RESULT_FAILED)

    def test_not_ready_application_also_skips_retest(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_NOT_READY)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertFalse(result["retest_performed"])
        self.assertIsNone(result["retest_evaluation"])
        self.assertIsNone(result["comparison"])


# ----------------------------------------------------------------------
# Extra: a successful original result must never enter this path
# (requirement 7), even if, for whatever reason, an application was
# marked APPLIED.
# ----------------------------------------------------------------------
class TestSuccessfulOriginalNeverRetests(CodeCorrectionRetestTestBase):
    def test_passed_original_skips_retest(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_PASSED, allowed_dirs=[self.allowed_dir],
        )

        self.assertFalse(result["retest_performed"])
        self.assertIsNone(result["retest_evaluation"])
        self.assertIsNone(result["comparison"])
        self.assertEqual(result["original_evaluation"]["classification"], RESULT_PASSED)


# ----------------------------------------------------------------------
# Extra: a retest that is worse than the original failure is a
# regression, not "unchanged".
# ----------------------------------------------------------------------
class TestRegression(CodeCorrectionRetestTestBase):
    def test_failed_then_timeout_is_a_regression(self):
        self._write("test_hangs.py", HANGING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)

        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
            timeout_seconds=1,
        )

        self.assertTrue(result["retest_performed"])
        self.assertEqual(result["retest_evaluation"]["classification"], RESULT_TIMEOUT)
        comparison = result["comparison"]
        self.assertFalse(comparison["improved"])
        self.assertTrue(comparison["regressed"])
        self.assertFalse(comparison["unchanged"])


class TestCompareTestOutcomesPureFunction(unittest.TestCase):
    def test_passed_is_always_improved(self):
        for original in (RESULT_FAILED, RESULT_TIMEOUT):
            comparison = compare_test_outcomes(original, RESULT_PASSED)
            self.assertTrue(comparison["improved"])
            self.assertFalse(comparison["regressed"])
            self.assertFalse(comparison["unchanged"])

    def test_same_or_less_severe_failure_is_unchanged(self):
        comparison = compare_test_outcomes(RESULT_TIMEOUT, RESULT_FAILED)
        self.assertFalse(comparison["improved"])
        self.assertFalse(comparison["regressed"])
        self.assertTrue(comparison["unchanged"])

    def test_more_severe_failure_is_regressed(self):
        comparison = compare_test_outcomes(RESULT_FAILED, RESULT_TIMEOUT)
        self.assertFalse(comparison["improved"])
        self.assertTrue(comparison["regressed"])
        self.assertFalse(comparison["unchanged"])

    def test_invalid_retest_is_treated_as_severely_as_timeout(self):
        comparison = compare_test_outcomes(RESULT_FAILED, RESULT_INVALID)
        self.assertTrue(comparison["regressed"])


class TestNeverRaises(CodeCorrectionRetestTestBase):
    def test_non_dict_correction_result_never_raises(self):
        result = build_code_correction_retest(
            "not a correction result", ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )
        self.assertFalse(result["retest_performed"])
        self.assertIsNone(result["retest_evaluation"])
        self.assertIsNone(result["comparison"])

    def test_none_correction_result_never_raises(self):
        result = build_code_correction_retest(
            None, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )
        self.assertFalse(result["retest_performed"])

    def test_unsafe_target_file_is_reported_not_raised(self):
        correction_result = self._correction_result(
            STATUS_APPLIED, target_file="/definitely/outside/project",
        )
        result = build_code_correction_retest(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )
        self.assertTrue(result["retest_performed"])
        self.assertEqual(result["retest_evaluation"]["classification"], RESULT_INVALID)
        self.assertTrue(result["comparison"]["regressed"])


# ----------------------------------------------------------------------
# AgentLoop wiring: `retest_code_correction` reuses
# `build_code_correction_retest` unchanged.
# ----------------------------------------------------------------------
class TestAgentLoopRetestCodeCorrection(CodeCorrectionRetestTestBase):
    def _agent_loop(self):
        goal_manager = GoalManager()
        plan_manager = PlanManager(goal_manager)
        controller = PlanExecutionController(plan_manager)
        return AgentLoop(goal_manager, plan_manager, controller)

    def test_wired_method_matches_pure_function(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_APPLIED)
        loop = self._agent_loop()

        result = loop.retest_code_correction(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertTrue(result["retest_performed"])
        self.assertTrue(result["comparison"]["improved"])

    def test_wired_method_skips_retest_for_rejected_correction(self):
        self._write("test_ok.py", PASSING_TEST_SOURCE)
        correction_result = self._correction_result(STATUS_REJECTED)
        loop = self._agent_loop()

        result = loop.retest_code_correction(
            correction_result, ORIGINAL_FAILED, allowed_dirs=[self.allowed_dir],
        )

        self.assertFalse(result["retest_performed"])


if __name__ == "__main__":
    unittest.main()
