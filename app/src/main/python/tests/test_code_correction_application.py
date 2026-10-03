"""
Tests for agent/code_correction_application.py - connects the existing
proposal-validation result (agent/code_correction_proposal_validation.py,
Prompt 342) to the existing `code_change_apply` capability
(execution/code_change_apply_capability.py, itself built on
`code_change_plan` + `text_file_edit`), made available on the existing
AgentLoop via `AgentLoop.apply_code_correction` (agent/agent_loop.py).

Covers: a valid proposal producing exactly one applied correction
(changed=True), an invalid proposal producing no modification, an
unsafe target path being rejected, an ambiguous (non-unique) source
fragment leaving the file untouched and reporting NOT_READY, no input
ever raising, and AgentLoop.apply_code_correction preserving the
original proposal/validation_result alongside the application result.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_correction_application -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_application import (
    STATUS_APPLIED,
    STATUS_NOT_READY,
    STATUS_REJECTED,
    STATUS_ERROR,
    ALL_CODE_CORRECTION_APPLICATION_STATUSES,
    build_code_correction_application,
)
from agent.code_correction_proposal_validation import build_code_correction_proposal_validation
from agent.code_correction_proposal import STATUS_PROPOSED, STATUS_NOT_READY as PROPOSAL_NOT_READY
from agent.code_error_analysis import ERROR_TYPE_NAME

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _validation_result(target_file, status="VALID", is_safe_to_apply=True, reason="valid"):
    return {
        "status": status,
        "target_file": target_file,
        "reason": reason,
        "is_safe_to_apply": is_safe_to_apply,
    }


def _proposal(target_file, status=STATUS_PROPOSED):
    return {
        "target_file": target_file,
        "error_type": ERROR_TYPE_NAME,
        "reason": "NameError detected",
        "change_description": "Define the missing name.",
        "status": status,
        "ready_to_apply": False,
        "apply_capability": "code_change_plan",
    }


class TestBuildCodeCorrectionApplication(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.allowed_dir = self._tmp.name
        self.target_file = os.path.join(self.allowed_dir, "generated.py")
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\n")

    def _read(self):
        with open(self.target_file) as f:
            return f.read()

    def test_valid_proposal_applies_one_correction(self):
        validation = _validation_result(self.target_file)
        result = build_code_correction_application(
            validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_APPLIED)
        self.assertTrue(result["changed"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["target_file"], self.target_file)
        self.assertEqual(self._read(), "x = 42\n")

    def test_successful_correction_reports_changed_true(self):
        validation = _validation_result(self.target_file)
        result = build_code_correction_application(
            validation, "undefined_name", "0", allowed_dirs=[self.allowed_dir],
        )
        self.assertTrue(result["changed"])

    def test_invalid_proposal_makes_no_modification(self):
        validation = _validation_result(
            self.target_file, status="INVALID", is_safe_to_apply=False,
            reason="The proposal does not include error information.",
        )
        before = self._read()
        result = build_code_correction_application(
            validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertFalse(result["changed"])
        self.assertEqual(result["error"], "The proposal does not include error information.")
        self.assertEqual(self._read(), before)

    def test_not_ready_validation_makes_no_modification(self):
        validation = _validation_result(
            self.target_file, status="NOT_READY", is_safe_to_apply=False,
        )
        before = self._read()
        result = build_code_correction_application(
            validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertFalse(result["changed"])
        self.assertEqual(self._read(), before)

    def test_unsafe_path_is_rejected(self):
        # A validation_result claiming VALID for a path outside the
        # allowed directories - the reused code_change_plan/
        # text_file_edit safety checks still catch it and this is
        # reported as ERROR, never applied.
        outside_file = "/definitely/outside/generated.py"
        validation = _validation_result(outside_file)
        result = build_code_correction_application(
            validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertIn(result["status"], (STATUS_ERROR, STATUS_NOT_READY, STATUS_REJECTED))
        self.assertFalse(result["changed"])

    def test_ambiguous_fragment_makes_no_modification(self):
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\ny = undefined_name\n")
        before = self._read()
        validation = _validation_result(self.target_file)
        result = build_code_correction_application(
            validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_NOT_READY)
        self.assertFalse(result["changed"])
        self.assertIn("occur", result["error"].lower())
        self.assertEqual(self._read(), before)

    def test_missing_fragment_makes_no_modification(self):
        before = self._read()
        validation = _validation_result(self.target_file)
        result = build_code_correction_application(
            validation, "this_text_is_not_present", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_NOT_READY)
        self.assertFalse(result["changed"])
        self.assertEqual(self._read(), before)

    def test_missing_old_text_is_not_ready(self):
        validation = _validation_result(self.target_file)
        result = build_code_correction_application(
            validation, "", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_NOT_READY)
        self.assertFalse(result["changed"])

    def test_non_dict_validation_result_never_raises(self):
        result = build_code_correction_application(
            "not a validation result", "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertFalse(result["changed"])

    def test_none_input_never_raises(self):
        result = build_code_correction_application(None, "x", "y", allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertFalse(result["changed"])

    def test_never_overwrites_an_unrelated_file(self):
        other_file = os.path.join(self.allowed_dir, "other.py")
        with open(other_file, "w") as f:
            f.write("z = undefined_name\n")
        validation = _validation_result(self.target_file)
        build_code_correction_application(
            validation, "undefined_name", "1", allowed_dirs=[self.allowed_dir],
        )
        with open(other_file) as f:
            self.assertEqual(f.read(), "z = undefined_name\n")


class TestAllCodeCorrectionApplicationStatuses(unittest.TestCase):
    def test_fixed_four_way_vocabulary(self):
        self.assertEqual(
            ALL_CODE_CORRECTION_APPLICATION_STATUSES,
            (STATUS_APPLIED, STATUS_NOT_READY, STATUS_REJECTED, STATUS_ERROR),
        )


class TestAgentLoopApplyCodeCorrection(unittest.TestCase):
    """Requirement: connect a validated proposal to the existing safe
    code-editing system through AgentLoop, preserving the original
    proposal/validation_result, without creating a duplicate editing
    or proposal system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.allowed_dir = self._tmp.name
        self.target_file = os.path.join(self.allowed_dir, "generated.py")
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\n")

    def _read(self):
        with open(self.target_file) as f:
            return f.read()

    def test_valid_proposal_applies_one_correction_via_agent_loop(self):
        proposal = _proposal(self.target_file)
        validation = self.loop.validate_code_correction_proposal(
            proposal, allowed_dirs=[self.allowed_dir],
        )
        bundle = self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(bundle["application"]["status"], STATUS_APPLIED)
        self.assertTrue(bundle["application"]["changed"])
        self.assertIs(bundle["proposal"], proposal)
        self.assertIs(bundle["validation_result"], validation)
        with open(self.target_file) as f:
            self.assertEqual(f.read(), "x = 42\n")

    def test_invalid_proposal_makes_no_modification_via_agent_loop(self):
        proposal = _proposal(self.target_file, status=PROPOSAL_NOT_READY)
        validation = self.loop.validate_code_correction_proposal(
            proposal, allowed_dirs=[self.allowed_dir],
        )
        before = self._read()
        bundle = self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(bundle["application"]["status"], STATUS_REJECTED)
        self.assertFalse(bundle["application"]["changed"])
        self.assertEqual(self._read(), before)

    def test_ambiguous_fragment_via_agent_loop_is_not_ready(self):
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\ny = undefined_name\n")
        proposal = _proposal(self.target_file)
        validation = self.loop.validate_code_correction_proposal(
            proposal, allowed_dirs=[self.allowed_dir],
        )
        bundle = self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(bundle["application"]["status"], STATUS_NOT_READY)
        self.assertFalse(bundle["application"]["changed"])

    def test_delegates_to_build_function_unchanged(self):
        proposal = _proposal(self.target_file)
        validation = self.loop.validate_code_correction_proposal(
            proposal, allowed_dirs=[self.allowed_dir],
        )
        expected = build_code_correction_application(
            validation, "undefined_name", "1", allowed_dirs=[self.allowed_dir],
        )
        # Re-fetch with a fresh copy of the file so both calls see the
        # same starting state (the first call above already applied
        # the change).
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\n")
        actual = self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "1", allowed_dirs=[self.allowed_dir],
        )["application"]
        self.assertEqual(actual, expected)

    def test_never_applies_a_second_correction_automatically(self):
        proposal = _proposal(self.target_file)
        validation = self.loop.validate_code_correction_proposal(
            proposal, allowed_dirs=[self.allowed_dir],
        )
        self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "42", allowed_dirs=[self.allowed_dir],
        )
        with open(self.target_file) as f:
            once_applied = f.read()
        # Calling again with the exact same (now stale) validation_result
        # only ever performs the one call's worth of work - it is not
        # itself an automatic retry loop, and the fragment no longer
        # matches, so nothing further changes.
        second = self.loop.apply_code_correction(
            proposal, validation, "undefined_name", "99", allowed_dirs=[self.allowed_dir],
        )
        self.assertEqual(second["application"]["status"], STATUS_NOT_READY)
        with open(self.target_file) as f:
            self.assertEqual(f.read(), once_applied)
        self.assertEqual(self.loop._goal_manager.get_goal("anything"), None)

    def test_invalid_input_via_agent_loop_never_raises(self):
        bundle = self.loop.apply_code_correction(
            "not a proposal", "not a validation result", "x", "y",
        )
        self.assertEqual(bundle["application"]["status"], STATUS_REJECTED)
        self.assertFalse(bundle["application"]["changed"])


if __name__ == "__main__":
    unittest.main()
