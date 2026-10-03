"""
Tests for self_upgrade.capability_correction_apply
.apply_capability_correction (Prompt 368) - applying exactly ONE
validated source change to a failed capability, through the existing
code_change_apply / text_file_edit infrastructure.

Every test works inside an isolated temp directory; no project file is
ever touched.

Run directly:
    python -m unittest tests.test_capability_correction_apply -v
"""

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import execution.code_change_apply_capability as code_change_apply_module
import self_upgrade.capability_correction_apply as cca_apply
from self_upgrade.capability_correction_apply import (
    apply_capability_correction,
    STATUS_APPLIED, STATUS_INVALID, STATUS_BLOCKED, STATUS_FAILED,
    STATUS_NO_CORRECTION_REQUIRED, ALL_STATUSES,
)
from self_upgrade.capability_correction_analysis import (
    build_capability_correction_analysis,
    STATUS_READY_FOR_CORRECTION,
)
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_test_execution import (
    STATUS_PASSED, STATUS_FAILED as TEST_FAILED, STATUS_BLOCKED as TEST_BLOCKED,
)
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController

SOURCE = "def demo():\n    return missing_name\n\n\ndef other():\n    return 2\n"
FIX = {"old_text": "return missing_name", "new_text": "return 1"}


def _stderr(path):
    return ("Traceback (most recent call last):\n"
            f'  File "{path}", line 2, in demo\n    return missing_name\n'
            "NameError: name 'missing_name' is not defined\n")


class Sandboxed(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.path = os.path.join(self.sandbox, "demo_capability.py")
        self.write(self.path, SOURCE)

    @staticmethod
    def write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    @staticmethod
    def read(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def analysis(self, path=None, **test_overrides):
        path = path or self.path
        fields = dict(
            capability_name="demo_capability", file_path=path, status=TEST_FAILED,
            tests_run=1, tests_passed=0, tests_failed=1, execution_time=0.1,
            output="E", errors=[_stderr(path)], timeout_seconds=30)
        fields.update(test_overrides)
        evaluation = evaluate_capability_test_result(fields)
        return build_capability_correction_analysis(evaluation, allowed_dirs=[self.sandbox])

    def apply(self, analysis=None, changes=None, **kwargs):
        kwargs.setdefault("allowed_dirs", [self.sandbox])
        return apply_capability_correction(
            analysis if analysis is not None else self.analysis(),
            [FIX] if changes is None else changes, **kwargs)


class AppliedTests(Sandboxed):
    def test_precondition_analysis_is_ready(self):
        self.assertEqual(self.analysis()["status"], STATUS_READY_FOR_CORRECTION)

    def test_valid_correction_applies_exactly_one_change(self):
        with mock.patch.object(code_change_apply_module, "make_text_file_edit_handler",
                               wraps=code_change_apply_module.make_text_file_edit_handler) as factory:
            result = self.apply()
        self.assertEqual(result["status"], STATUS_APPLIED)
        self.assertTrue(result["correction_applied"])
        self.assertIsNone(result["error"])
        self.assertEqual(factory.call_count, 1)  # existing text_file_edit path, once
        self.assertEqual(self.read(self.path), SOURCE.replace("return missing_name", "return 1"))

    def test_metadata_is_returned(self):
        analysis = self.analysis()
        snapshot = copy.deepcopy(analysis)
        result = self.apply(analysis)
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(os.path.realpath(result["file_path"]), os.path.realpath(self.path))
        self.assertEqual(result["changes_requested"], 1)
        metadata = result["change_metadata"]
        self.assertEqual(metadata["target_fragment"], FIX["old_text"])
        self.assertEqual(metadata["replacement"], FIX["new_text"])
        self.assertEqual(metadata["occurrences_replaced"], 1)
        self.assertEqual(metadata["character_count_before"], len(SOURCE))
        self.assertEqual(result["validation_result"]["status"], "VALID")
        self.assertEqual(result["code_validation"], {"valid": True, "syntax_error": None})
        self.assertEqual(result["correction_analysis"], snapshot)
        self.assertEqual(analysis, snapshot)  # input never mutated
        self.assertEqual(set(ALL_STATUSES),
                         {"APPLIED", "INVALID", "BLOCKED", "FAILED", "NO_CORRECTION_REQUIRED"})


class NoChangeTests(Sandboxed):
    def assert_untouched(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertFalse(result["correction_applied"])
        self.assertEqual(self.read(self.path), SOURCE)

    def test_missing_correction_is_no_correction_required(self):
        passing = self.analysis(status=STATUS_PASSED, tests_run=1, tests_passed=1,
                                tests_failed=0, output=".", errors=["OK"])
        self.assert_untouched(self.apply(passing), STATUS_NO_CORRECTION_REQUIRED)

    def test_correction_not_required_flag(self):
        analysis = self.analysis()
        analysis["correction_required"] = False
        self.assert_untouched(self.apply(analysis), STATUS_NO_CORRECTION_REQUIRED)

    def test_upstream_blocked_invalid_failed_are_preserved(self):
        blocked = self.analysis(status=TEST_BLOCKED, tests_run=None, tests_passed=None,
                                tests_failed=None, output=None, errors=["outside workspace"])
        self.assert_untouched(self.apply(blocked), STATUS_BLOCKED)
        for upstream, expected in (("INVALID", STATUS_INVALID), ("FAILED", STATUS_FAILED)):
            analysis = self.analysis()
            analysis["status"] = upstream
            analysis["blockers"] = ["upstream"]
            self.assert_untouched(self.apply(analysis), expected)

    def test_missing_or_bad_proposal_is_invalid(self):
        analysis = self.analysis()
        analysis["correction_proposal"] = None
        self.assert_untouched(self.apply(analysis), STATUS_INVALID)
        analysis = self.analysis()
        analysis["correction_proposal"]["status"] = "NOT_READY"
        self.assert_untouched(self.apply(analysis), STATUS_INVALID)

    def test_malformed_analysis_is_invalid(self):
        for value in (None, "x", {}, {"status": "READY_FOR_CORRECTION"}):
            result = apply_capability_correction(value, [FIX], allowed_dirs=[self.sandbox])
            self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(self.read(self.path), SOURCE)

    def test_target_mismatch_is_invalid(self):
        analysis = self.analysis()
        analysis["correction_proposal"]["target_file"] = os.path.join(self.sandbox, "other.py")
        self.write(os.path.join(self.sandbox, "other.py"), SOURCE)
        self.assert_untouched(self.apply(analysis), STATUS_INVALID)
        self.assertEqual(self.read(os.path.join(self.sandbox, "other.py")), SOURCE)

    def test_multiple_changes_are_rejected_not_reduced(self):
        second = {"old_text": "return 2", "new_text": "return 3"}
        result = self.apply(changes=[FIX, second])
        self.assert_untouched(result, STATUS_INVALID)
        self.assertEqual(result["changes_requested"], 2)
        for bad in ([], None, FIX):
            result = apply_capability_correction(
                self.analysis(), bad, allowed_dirs=[self.sandbox])
            self.assert_untouched(result, STATUS_INVALID)

    def test_malformed_single_change_is_invalid(self):
        for change in ({}, {"old_text": "", "new_text": "x"}, {"old_text": "a"},
                       {"old_text": "a", "new_text": 5}, {"old_text": "x", "new_text": "x"}, "text"):
            with self.subTest(change=change):
                self.assert_untouched(self.apply(changes=[change]), STATUS_INVALID)

    def test_fragment_not_found_or_ambiguous_is_invalid(self):
        self.assert_untouched(
            self.apply(changes=[{"old_text": "nope()", "new_text": "x"}]), STATUS_INVALID)
        self.write(self.path, SOURCE + "\ndef again():\n    return missing_name\n")
        result = self.apply()
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIn("2 times", result["error"])
        self.assertEqual(self.read(self.path), SOURCE + "\ndef again():\n    return missing_name\n")

    def test_correction_producing_invalid_python_is_rejected(self):
        result = self.apply(changes=[{"old_text": "return missing_name", "new_text": "return (("}])
        self.assert_untouched(result, STATUS_INVALID)
        self.assertFalse(result["code_validation"]["valid"])

    def test_path_outside_allowed_workspace_is_blocked(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        result = self.apply(allowed_dirs=[outside])
        self.assert_untouched(result, STATUS_BLOCKED)
        self.assertIn("outside the allowed directories", result["error"])

    def test_protected_file_is_never_modified(self):
        result = self.apply(protected_paths=[self.path])
        self.assert_untouched(result, STATUS_BLOCKED)
        self.assertIn("protected", result["error"])
        # A symlink/alias to the same file is still protected.
        alias_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(alias_dir, ignore_errors=True))
        alias = os.path.join(alias_dir, "alias.py")
        os.symlink(self.path, alias)
        self.assert_untouched(self.apply(protected_paths=[alias]), STATUS_BLOCKED)

    def test_write_path_never_reached_when_not_allowed(self):
        with mock.patch.object(code_change_apply_module, "make_text_file_edit_handler") as factory:
            self.apply(changes=[FIX, FIX])
            self.apply(protected_paths=[self.path])
            self.apply(allowed_dirs=[tempfile.gettempdir() + "/nowhere-368"])
        factory.assert_not_called()

    def test_non_python_target_is_not_modified(self):
        text_path = os.path.join(self.sandbox, "notes.txt")
        self.write(text_path, "return missing_name")
        analysis = self.analysis(path=text_path)
        result = self.apply(analysis)
        self.assertIn(result["status"], (STATUS_INVALID, STATUS_BLOCKED, STATUS_FAILED))
        self.assertFalse(result["correction_applied"])
        self.assertEqual(self.read(text_path), "return missing_name")


class SafetyAndCompatibilityTests(Sandboxed):
    def test_corrected_code_is_never_executed_or_imported(self):
        def boom(*args, **kwargs):
            raise AssertionError("execution attempted")
        before = set(sys.modules)
        with mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(os, "system", boom):
            result = self.apply()
        self.assertEqual(result["status"], STATUS_APPLIED)
        self.assertNotIn("demo_capability", set(sys.modules) - before)

    def test_no_retry_single_write_per_call(self):
        with mock.patch.object(code_change_apply_module, "make_text_file_edit_handler",
                               wraps=code_change_apply_module.make_text_file_edit_handler) as factory:
            self.apply()
        self.assertEqual(factory.call_count, 1)
        # Second call on the already-corrected file finds nothing to change.
        again = self.apply()
        self.assertEqual(again["status"], STATUS_INVALID)

    def test_agent_loop_exposes_the_same_operation(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        result = loop.apply_capability_correction(
            self.analysis(), [FIX], allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], STATUS_APPLIED)
        self.assertEqual(loop.apply_capability_correction(None, [FIX])["status"], STATUS_INVALID)

    def test_existing_correction_application_unchanged(self):
        from agent.code_correction_application import build_code_correction_application
        validation = {"status": "VALID", "is_safe_to_apply": True, "target_file": self.path}
        result = build_code_correction_application(
            validation, FIX["old_text"], FIX["new_text"], allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(self.read(self.path), SOURCE.replace("return missing_name", "return 1"))


if __name__ == "__main__":
    unittest.main()
