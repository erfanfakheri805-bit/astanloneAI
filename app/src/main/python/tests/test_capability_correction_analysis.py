"""
Tests for self_upgrade.capability_correction_analysis
.build_capability_correction_analysis (Prompt 367) - routing a
CapabilityEvaluationResult into the EXISTING error-analysis /
correction-proposal / proposal-validation pipeline.

Real failures come from the real sandboxed test-execution stage, run
only inside an isolated temp directory.

Run directly:
    python -m unittest tests.test_capability_correction_analysis -v
"""

import copy
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_upgrade.capability_correction_analysis as cca
from self_upgrade.capability_correction_analysis import (
    build_capability_correction_analysis,
    STATUS_READY_FOR_CORRECTION, STATUS_NO_CORRECTION_REQUIRED,
    STATUS_BLOCKED, STATUS_INVALID, STATUS_FAILED, ALL_STATUSES,
)
from self_upgrade.capability_evaluation import (
    evaluate_capability_test_result,
    EVAL_SUCCESS, EVAL_TIMEOUT, EVAL_BLOCKED, EVAL_INVALID, EVAL_NEEDS_CORRECTION,
)
from self_upgrade.capability_test_execution import (
    run_capability_tests,
    STATUS_PASSED, STATUS_FAILED as TEST_FAILED, STATUS_TIMEOUT as TEST_TIMEOUT,
    STATUS_BLOCKED as TEST_BLOCKED, STATUS_INVALID as TEST_INVALID,
)
from self_upgrade.capability_file_apply import STATUS_APPLIED
from code_generation.generated_code_validator import VALIDATION_VALID
from agent.code_error_analysis import build_code_error_analysis
from agent.code_correction_proposal import STATUS_PROPOSED, STATUS_NOT_READY
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController


def _test_result(**overrides):
    fields = dict(
        capability_name="demo_capability", file_path="/sandbox/demo_capability.py",
        status=STATUS_PASSED, tests_run=3, tests_passed=3, tests_failed=0,
        execution_time=0.1, output="...", errors=["Ran 3 tests\n\nOK"], timeout_seconds=30,
    )
    fields.update(overrides)
    return fields


def _evaluate(**overrides):
    return evaluate_capability_test_result(_test_result(**overrides))


NAME_ERROR_STDERR = (
    "E\n======\nERROR: test_x (test_demo.T)\n------\nTraceback (most recent call last):\n"
    '  File "/sandbox/test_demo.py", line 5, in test_x\n    demo()\n'
    '  File "/sandbox/demo_capability.py", line 2, in demo\n    return missing\n'
    "NameError: name 'missing' is not defined\n\n------\nRan 1 test in 0.001s\n\nFAILED (errors=1)\n"
)


def _needs_correction(file_path="/sandbox/demo_capability.py", stderr=NAME_ERROR_STDERR):
    evaluation = _evaluate(
        file_path=file_path, status=TEST_FAILED, tests_run=1, tests_passed=0,
        tests_failed=1, output="E", errors=[stderr])
    assert evaluation["evaluation_status"] == EVAL_NEEDS_CORRECTION
    return evaluation


ALLOWED = ["/sandbox"]


class NoCorrectionAndControlledStatesTests(unittest.TestCase):
    def test_success_is_no_correction_required(self):
        with mock.patch.object(cca, "build_code_error_analysis") as analysis:
            result = build_capability_correction_analysis(_evaluate())
        self.assertEqual(result["status"], STATUS_NO_CORRECTION_REQUIRED)
        self.assertEqual(result["evaluation_status"], EVAL_SUCCESS)
        self.assertFalse(result["correction_required"])
        self.assertIsNone(result["correction_proposal"])
        self.assertEqual(result["blockers"], [])
        analysis.assert_not_called()

    def test_blocked_is_preserved(self):
        evaluation = _evaluate(status=TEST_BLOCKED, tests_run=None, tests_passed=None,
                               tests_failed=None, output=None, errors=["outside the allowed workspace"])
        with mock.patch.object(cca, "build_code_error_analysis") as analysis:
            result = build_capability_correction_analysis(evaluation)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["evaluation_status"], EVAL_BLOCKED)
        self.assertFalse(result["correction_required"])
        self.assertIsNone(result["error_analysis"])
        self.assertIn("outside the allowed workspace", result["blockers"][0])
        analysis.assert_not_called()

    def test_timeout_is_preserved_and_not_treated_as_code_error(self):
        evaluation = _evaluate(status=TEST_TIMEOUT, tests_run=None, tests_passed=None,
                               tests_failed=None, output=None, errors=[], timeout_seconds=7)
        with mock.patch.object(cca, "build_code_error_analysis") as analysis:
            result = build_capability_correction_analysis(evaluation)
        self.assertEqual(result["evaluation_status"], EVAL_TIMEOUT)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertFalse(result["correction_required"])
        self.assertIsNone(result["correction_proposal"])
        self.assertIn("7", result["blockers"][0])
        analysis.assert_not_called()

    def test_invalid_is_preserved(self):
        evaluation = _evaluate(capability_name=None, file_path=None, status=TEST_INVALID,
                               tests_run=None, tests_passed=None, tests_failed=None,
                               output=None, errors=["test_target is required."])
        with mock.patch.object(cca, "build_code_error_analysis") as analysis:
            result = build_capability_correction_analysis(evaluation)
        self.assertEqual(result["evaluation_status"], EVAL_INVALID)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertFalse(result["correction_required"])
        analysis.assert_not_called()

    def test_plain_failed_evaluation_is_failed_status(self):
        evaluation = _evaluate(status=TEST_FAILED, tests_failed=0, tests_passed=3,
                               errors=[], output=None)
        result = build_capability_correction_analysis(evaluation)
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertFalse(result["correction_required"])

    def test_malformed_inputs_are_invalid(self):
        for value in (None, "x", 5, {}, {"evaluation_status": "SUCCESS"},
                      {**_evaluate(), "evaluation_status": "MAYBE"}):
            with self.subTest(value=value):
                result = build_capability_correction_analysis(value)
                self.assertEqual(result["status"], STATUS_INVALID)
                self.assertTrue(result["blockers"])

    def test_needs_correction_missing_file_path_is_invalid(self):
        evaluation = _needs_correction()
        evaluation["file_path"] = None
        self.assertEqual(build_capability_correction_analysis(evaluation)["status"], STATUS_INVALID)

    def test_status_vocabulary(self):
        self.assertEqual(set(ALL_STATUSES), {
            "READY_FOR_CORRECTION", "NO_CORRECTION_REQUIRED", "BLOCKED", "INVALID", "FAILED"})


class NeedsCorrectionPipelineTests(unittest.TestCase):
    def test_error_analysis_is_invoked_with_failure_information(self):
        evaluation = _needs_correction()
        with mock.patch.object(cca, "build_code_error_analysis",
                               wraps=build_code_error_analysis) as analysis:
            build_capability_correction_analysis(evaluation, allowed_dirs=ALLOWED)
        analysis.assert_called_once()
        (execution_result,), _ = analysis.call_args
        self.assertEqual(execution_result["target_file"], "/sandbox/demo_capability.py")
        self.assertEqual(execution_result["status"], "FAILED")
        self.assertIn("NameError: name 'missing' is not defined", execution_result["stderr"])
        self.assertEqual(execution_result["stdout"], "E")
        self.assertEqual(execution_result["error"], evaluation["failure_reason"])

    def test_output_is_used_when_there_are_no_errors(self):
        evaluation = _needs_correction()
        evaluation["errors"] = []
        evaluation["output"] = "Traceback...\nNameError: name 'x' is not defined\n"
        with mock.patch.object(cca, "build_code_error_analysis",
                               wraps=build_code_error_analysis) as analysis:
            build_capability_correction_analysis(evaluation, allowed_dirs=ALLOWED)
        self.assertIn("NameError", analysis.call_args[0][0]["stderr"])

    def test_ready_for_correction_with_proposal_from_existing_infrastructure(self):
        with mock.patch.object(cca, "build_code_correction_proposal",
                               wraps=cca.build_code_correction_proposal) as builder:
            result = build_capability_correction_analysis(_needs_correction(), allowed_dirs=ALLOWED)
        builder.assert_called_once()
        self.assertEqual(result["status"], STATUS_READY_FOR_CORRECTION)
        self.assertEqual(result["evaluation_status"], EVAL_NEEDS_CORRECTION)
        self.assertTrue(result["correction_required"])
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["error_analysis"]["error_type"], "NameError")
        self.assertEqual(result["error_analysis"]["line_number"], 2)
        proposal = result["correction_proposal"]
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertEqual(proposal["target_file"], "/sandbox/demo_capability.py")
        self.assertFalse(proposal["ready_to_apply"])
        self.assertIn("line 2", proposal["change_description"])
        self.assertEqual(result["validation"]["status"], "VALID")

    def test_failure_info_and_original_evaluation_preserved(self):
        evaluation = _needs_correction()
        snapshot = copy.deepcopy(evaluation)
        result = build_capability_correction_analysis(evaluation, allowed_dirs=ALLOWED)
        info = result["failure_info"]
        self.assertEqual(info["capability_name"], "demo_capability")
        self.assertEqual(info["file_path"], "/sandbox/demo_capability.py")
        self.assertEqual(info["tests_failed"], 1)
        self.assertEqual(info["errors"], evaluation["errors"])
        self.assertEqual(info["output"], "E")
        self.assertEqual(info["failure_reason"], evaluation["failure_reason"])
        self.assertIsNone(info["source_info"]["source_text"])
        self.assertEqual(result["evaluation_result"], snapshot)
        self.assertEqual(evaluation, snapshot)  # input not mutated

    def test_line_number_in_test_file_is_not_attributed_to_capability(self):
        stderr = ("Traceback (most recent call last):\n"
                  '  File "/sandbox/test_demo.py", line 9, in test_x\n    self.fail()\n'
                  "NameError: name 'x' is not defined\n")
        result = build_capability_correction_analysis(
            _needs_correction(stderr=stderr), allowed_dirs=ALLOWED)
        self.assertEqual(result["status"], STATUS_READY_FOR_CORRECTION)
        self.assertIsNone(result["error_analysis"]["line_number"])
        self.assertNotIn("line 9", result["correction_proposal"]["change_description"])

    def test_unrecognized_error_is_blocked_by_existing_analysis(self):
        # The existing analysis does not name AssertionError as an
        # actionable type - this integration must not override that.
        stderr = "Traceback (most recent call last):\nAssertionError: 42 != 43\n"
        result = build_capability_correction_analysis(
            _needs_correction(stderr=stderr), allowed_dirs=ALLOWED)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["correction_proposal"]["status"], STATUS_NOT_READY)
        self.assertTrue(result["correction_required"])
        self.assertTrue(result["blockers"])

    def test_existing_validation_is_not_bypassed(self):
        with mock.patch.object(cca, "build_code_correction_proposal_validation",
                               wraps=cca.build_code_correction_proposal_validation) as validator:
            outside = build_capability_correction_analysis(
                _needs_correction(), allowed_dirs=["/somewhere/else"])
        validator.assert_called_once()
        self.assertEqual(outside["status"], STATUS_BLOCKED)
        self.assertIn("outside the allowed directories", outside["blockers"][0])
        self.assertEqual(outside["validation"]["status"], "INVALID")

    def test_learned_patterns_provider_is_advisory_only(self):
        seen = []
        provider = lambda error_type: seen.append(error_type) or []
        result = build_capability_correction_analysis(
            _needs_correction(), allowed_dirs=ALLOWED, learned_patterns_provider=provider)
        self.assertEqual(seen, ["NameError"])
        self.assertEqual(result["status"], STATUS_READY_FOR_CORRECTION)


class SafetyTests(unittest.TestCase):
    def test_no_code_is_executed(self):
        def boom(*args, **kwargs):
            raise AssertionError("code execution attempted")
        with mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(os, "system", boom):
            for evaluation in (_evaluate(), _needs_correction()):
                result = build_capability_correction_analysis(evaluation, allowed_dirs=ALLOWED)
                self.assertNotEqual(result["status"], STATUS_FAILED)

    def test_no_files_are_modified(self):
        def snapshot(root):
            state = {}
            for base, _, names in os.walk(root):
                for name in names:
                    path = os.path.join(base, name)
                    with open(path, "rb") as handle:
                        state[path] = (hashlib.sha256(handle.read()).hexdigest(),
                                       os.stat(path).st_mtime_ns)
            return state

        with tempfile.TemporaryDirectory() as sandbox:
            path = os.path.join(sandbox, "demo_capability.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("def demo():\n    return missing\n")
            before = snapshot(sandbox)
            evaluation = _needs_correction(file_path=path)
            result = build_capability_correction_analysis(evaluation, allowed_dirs=[sandbox])
            self.assertEqual(result["status"], STATUS_READY_FOR_CORRECTION)
            self.assertEqual(snapshot(sandbox), before)
            self.assertFalse(result["correction_proposal"]["ready_to_apply"])


class RealPipelineIntegrationTests(unittest.TestCase):
    """capability file -> real sandboxed test run -> evaluation -> analysis."""

    def _run(self, module_text, test_text):
        sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(sandbox, ignore_errors=True))
        path = os.path.join(sandbox, "demo_capability.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(module_text)
        with open(os.path.join(sandbox, "test_demo_capability.py"), "w", encoding="utf-8") as handle:
            handle.write(test_text)
        apply_result = dict(
            capability_name="demo_capability", target_module="generated.demo_capability",
            status=STATUS_APPLIED, file_path=path, bytes_written=1,
            validation_result={"status": VALIDATION_VALID}, error=None)
        test_result = run_capability_tests(apply_result, sandbox, "test_demo_capability")
        return sandbox, path, evaluate_capability_test_result(test_result)

    TEST = ("import unittest\nfrom demo_capability import demo\n\n"
            "class T(unittest.TestCase):\n    def test_demo(self):\n"
            "        self.assertEqual(demo(), 1)\n")

    def test_real_name_error_reaches_a_proposal(self):
        sandbox, path, evaluation = self._run("def demo():\n    return missing_name\n", self.TEST)
        self.assertEqual(evaluation["evaluation_status"], EVAL_NEEDS_CORRECTION)
        result = build_capability_correction_analysis(evaluation, allowed_dirs=[sandbox])
        self.assertEqual(result["status"], STATUS_READY_FOR_CORRECTION)
        self.assertEqual(result["error_analysis"]["error_type"], "NameError")
        self.assertEqual(result["error_analysis"]["line_number"], 2)
        self.assertEqual(result["correction_proposal"]["target_file"], path)

    def test_real_success_needs_no_correction(self):
        _, _, evaluation = self._run("def demo():\n    return 1\n", self.TEST)
        self.assertEqual(build_capability_correction_analysis(evaluation)["status"],
                         STATUS_NO_CORRECTION_REQUIRED)


class AgentLoopIntegrationTests(unittest.TestCase):
    def _loop(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        return AgentLoop(goals, plans, PlanExecutionController(plans))

    def test_agent_loop_exposes_the_same_analysis(self):
        loop = self._loop()
        evaluation = _needs_correction()
        via_loop = loop.analyze_capability_correction(evaluation, allowed_dirs=ALLOWED)
        direct = build_capability_correction_analysis(evaluation, allowed_dirs=ALLOWED)
        self.assertEqual(via_loop["status"], STATUS_READY_FOR_CORRECTION)
        self.assertEqual(via_loop["correction_proposal"], direct["correction_proposal"])
        self.assertEqual(loop.analyze_capability_correction(None)["status"], STATUS_INVALID)

    def test_existing_agent_loop_correction_path_unchanged(self):
        loop = self._loop()
        execution = {"status": "FAILED", "target_file": "/sandbox/a.py", "stdout": "",
                     "stderr": "NameError: name 'x' is not defined\n", "error": "exit 1"}
        proposal = loop.propose_code_correction(execution)["proposal"]
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertEqual(proposal["error_type"], "NameError")


if __name__ == "__main__":
    unittest.main()
