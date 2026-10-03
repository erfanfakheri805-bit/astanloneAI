"""
Tests for agent/code_correction_proposal_validation.py - connects the
existing code-correction proposal (agent/code_correction_proposal.py,
Prompt 341) to one small, structured validation result, made available
on the existing AgentLoop via
`AgentLoop.validate_code_correction_proposal` (agent/agent_loop.py).

Covers: a fully valid proposal, a proposal missing its target file, a
proposal missing error information, a proposal missing a correction
description, a proposal whose target path is outside the allowed
directories, a proposal that was itself NOT_READY (Prompt 341) passing
through as NOT_READY here too, no input ever raising, the original
proposal never being mutated, and AgentLoop.validate_code_correction_proposal
delegating to this module unchanged.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_correction_proposal_validation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_NOT_READY,
    ALL_CODE_CORRECTION_PROPOSAL_VALIDATION_STATUSES,
    build_code_correction_proposal_validation,
)
from agent.code_correction_proposal import (
    STATUS_PROPOSED,
    STATUS_NOT_READY,
    build_code_correction_proposal,
)
from agent.code_error_analysis import ERROR_TYPE_NAME

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _proposal(target_file="generated.py", error_type=ERROR_TYPE_NAME,
              reason="NameError detected", change_description="Define the missing name.",
              status=STATUS_PROPOSED):
    return {
        "target_file": target_file,
        "error_type": error_type,
        "reason": reason,
        "change_description": change_description,
        "status": status,
        "ready_to_apply": False,
        "apply_capability": "code_change_plan",
    }


class TestBuildCodeCorrectionProposalValidation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.allowed_dir = self._tmp.name
        self.target_file = os.path.join(self.allowed_dir, "generated.py")
        with open(self.target_file, "w") as f:
            f.write("x = undefined_name\n")

    def test_valid_proposal(self):
        proposal = _proposal(target_file=self.target_file)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_VALID)
        self.assertEqual(result["target_file"], self.target_file)
        self.assertTrue(result["is_safe_to_apply"])
        self.assertIn(self.target_file, result["reason"])

    def test_missing_target_file_is_invalid(self):
        proposal = _proposal(target_file=None)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_INVALID)
        self.assertFalse(result["is_safe_to_apply"])
        self.assertIn("target file", result["reason"])

    def test_missing_error_information_is_invalid(self):
        proposal = _proposal(target_file=self.target_file, error_type=None)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_INVALID)
        self.assertFalse(result["is_safe_to_apply"])
        self.assertIn("error information", result["reason"])

    def test_missing_correction_description_is_invalid(self):
        proposal = _proposal(target_file=self.target_file, change_description=None)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_INVALID)
        self.assertFalse(result["is_safe_to_apply"])
        self.assertIn("correction description", result["reason"])

    def test_unsafe_target_path_is_invalid(self):
        outside_file = "/definitely/outside/generated.py"
        proposal = _proposal(target_file=outside_file)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_INVALID)
        self.assertFalse(result["is_safe_to_apply"])
        self.assertIn("outside the allowed directories", result["reason"])

    def test_not_ready_proposal_stays_not_ready(self):
        proposal = _proposal(status=STATUS_NOT_READY, change_description=None)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_NOT_READY)
        self.assertFalse(result["is_safe_to_apply"])

    def test_non_dict_input_never_raises(self):
        result = build_code_correction_proposal_validation("not a proposal", allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_NOT_READY)
        self.assertIsNone(result["target_file"])
        self.assertFalse(result["is_safe_to_apply"])

    def test_none_input_never_raises(self):
        result = build_code_correction_proposal_validation(None, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_NOT_READY)
        self.assertFalse(result["is_safe_to_apply"])

    def test_does_not_mutate_original_proposal(self):
        proposal = _proposal(target_file=self.target_file)
        original = dict(proposal)
        build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(proposal, original)

    def test_never_reads_or_writes_target_file_contents(self):
        # A real actionable proposal, path allowed - VALID - but the
        # file's own content is never inspected: prove this by
        # deleting the file after building the proposal and before
        # validating; validation must still succeed the same way.
        proposal = _proposal(target_file=self.target_file)
        os.remove(self.target_file)
        result = build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_VALID)
        self.assertTrue(result["is_safe_to_apply"])


class TestAllCodeCorrectionProposalValidationStatuses(unittest.TestCase):
    def test_fixed_three_way_vocabulary(self):
        self.assertEqual(
            ALL_CODE_CORRECTION_PROPOSAL_VALIDATION_STATUSES,
            (VALIDATION_STATUS_VALID, VALIDATION_STATUS_INVALID, VALIDATION_STATUS_NOT_READY),
        )

    def test_not_ready_is_the_same_token_as_proposal_not_ready(self):
        # requirement: reuse the existing proposal vocabulary, never a
        # second, differently-spelled one.
        self.assertEqual(VALIDATION_STATUS_NOT_READY, STATUS_NOT_READY)


class TestAgentLoopValidateCodeCorrectionProposal(unittest.TestCase):
    """Requirement: connect the validation result to the existing
    AgentLoop, without creating a duplicate validation system."""

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

    def test_delegates_to_build_function_unchanged(self):
        proposal = _proposal(target_file=self.target_file)
        self.assertEqual(
            self.loop.validate_code_correction_proposal(proposal, allowed_dirs=[self.allowed_dir]),
            build_code_correction_proposal_validation(proposal, allowed_dirs=[self.allowed_dir]),
        )

    def test_valid_proposal_via_agent_loop(self):
        proposal = _proposal(target_file=self.target_file)
        result = self.loop.validate_code_correction_proposal(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_VALID)
        self.assertTrue(result["is_safe_to_apply"])

    def test_unsafe_path_via_agent_loop_is_invalid(self):
        proposal = _proposal(target_file="/outside/generated.py")
        result = self.loop.validate_code_correction_proposal(proposal, allowed_dirs=[self.allowed_dir])
        self.assertEqual(result["status"], VALIDATION_STATUS_INVALID)
        self.assertFalse(result["is_safe_to_apply"])

    def test_invalid_input_via_agent_loop_never_raises(self):
        result = self.loop.validate_code_correction_proposal("not a proposal")
        self.assertEqual(result["status"], VALIDATION_STATUS_NOT_READY)
        self.assertFalse(result["is_safe_to_apply"])

    def test_never_applies_or_modifies_anything(self):
        # Validating only reports a verdict - it never touches the
        # Plan/Goal (no plan/goal was even created in this test's
        # setUp) and never writes to the target file.
        proposal = _proposal(target_file=self.target_file)
        with open(self.target_file) as f:
            before = f.read()
        self.loop.validate_code_correction_proposal(proposal, allowed_dirs=[self.allowed_dir])
        with open(self.target_file) as f:
            after = f.read()
        self.assertEqual(before, after)
        self.assertEqual(self.loop._goal_manager.get_goal("anything"), None)


if __name__ == "__main__":
    unittest.main()
