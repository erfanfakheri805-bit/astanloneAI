"""
Tests for agent/code_correction_proposal.py - connects the existing
`CodeErrorAnalysis` (agent/code_error_analysis.py) to one small,
structured, inert correction proposal, made available on the existing
AgentLoop via `AgentLoop.propose_code_correction` (agent/agent_loop.py).

Covers: an actionable error producing a PROPOSED proposal (for each of
the five named exception families), a non-actionable error producing
NOT_READY, a timeout producing either a proposal (target_file present)
or NOT_READY (target_file missing), missing target/source information
producing NOT_READY, no input ever raising, the proposal never
containing invented source code, and AgentLoop.propose_code_correction
preserving the original execution/evaluation/error-analysis results
alongside the proposal.

Run directly:
    python -m unittest tests.test_code_correction_proposal -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_proposal import (
    STATUS_PROPOSED,
    STATUS_NOT_READY,
    ALL_CODE_CORRECTION_PROPOSAL_STATUSES,
    build_code_correction_proposal,
)
from agent.code_error_analysis import (
    ERROR_TYPE_SYNTAX,
    ERROR_TYPE_NAME,
    ERROR_TYPE_TYPE,
    ERROR_TYPE_IMPORT,
    ERROR_TYPE_RUNTIME,
    ERROR_TYPE_TIMEOUT,
    ERROR_TYPE_UNKNOWN,
    build_code_error_analysis,
)
from execution.code_change_plan_capability import CAPABILITY_NAME as CODE_CHANGE_PLAN_CAPABILITY_NAME
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


def _error_analysis(target_file="/sandbox/generated.py", error_type=ERROR_TYPE_NAME,
                     error_message="name 'x' is not defined", stderr="Traceback...",
                     line_number=4, is_actionable=True):
    return {
        "target_file": target_file,
        "error_type": error_type,
        "error_message": error_message,
        "stderr": stderr,
        "line_number": line_number,
        "is_actionable": is_actionable,
    }


def _execution_result(status, target_file="/sandbox/generated.py", error=None, stderr=None):
    return {"status": status, "target_file": target_file, "stdout": None, "stderr": stderr, "error": error}


class TestBuildCodeCorrectionProposalActionable(unittest.TestCase):
    def test_syntax_error_produces_proposal(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_SYNTAX, line_number=1)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertEqual(proposal["target_file"], "/sandbox/generated.py")
        self.assertEqual(proposal["error_type"], ERROR_TYPE_SYNTAX)
        self.assertIn("syntax error", proposal["change_description"])
        self.assertIn("/sandbox/generated.py", proposal["change_description"])
        self.assertIn("line 1", proposal["change_description"])
        self.assertFalse(proposal["ready_to_apply"])
        self.assertEqual(proposal["apply_capability"], CODE_CHANGE_PLAN_CAPABILITY_NAME)

    def test_name_error_produces_proposal(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, line_number=4)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertIn("missing name", proposal["change_description"])
        self.assertIn("line 4", proposal["change_description"])

    def test_type_error_produces_proposal(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_TYPE, line_number=2)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertIn("type mismatch", proposal["change_description"])

    def test_import_error_produces_proposal(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_IMPORT, line_number=1)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertIn("import", proposal["change_description"])

    def test_runtime_error_produces_proposal(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_RUNTIME, line_number=7)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertIn("runtime error", proposal["change_description"])

    def test_reason_includes_error_message_when_present(self):
        analysis = _error_analysis(error_message="name 'undefined_var' is not defined")
        proposal = build_code_correction_proposal(analysis)
        self.assertIn("name 'undefined_var' is not defined", proposal["reason"])

    def test_never_contains_invented_source_code(self):
        # requirement 7: never invent a source-code fragment.
        analysis = _error_analysis(error_type=ERROR_TYPE_SYNTAX)
        proposal = build_code_correction_proposal(analysis)
        self.assertNotIn("old_text", proposal)
        self.assertNotIn("new_text", proposal)
        self.assertNotIn("source_code", proposal)


class TestBuildCodeCorrectionProposalNonActionable(unittest.TestCase):
    def test_non_actionable_error_is_not_ready(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_UNKNOWN, is_actionable=False)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertIsNone(proposal["change_description"])
        self.assertFalse(proposal["ready_to_apply"])
        self.assertIsNone(proposal["apply_capability"])

    def test_successful_execution_is_not_ready(self):
        analysis = build_code_error_analysis(_execution_result(STATUS_EXECUTED, stderr=""))
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)

    def test_rejected_execution_is_not_ready(self):
        analysis = build_code_error_analysis(
            _execution_result(STATUS_REJECTED, error="refused before running")
        )
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)


class TestBuildCodeCorrectionProposalTimeout(unittest.TestCase):
    def test_timeout_with_target_file_produces_proposal(self):
        analysis = _error_analysis(
            error_type=ERROR_TYPE_TIMEOUT, line_number=None,
            error_message="Execution of '/sandbox/generated.py' timed out after 5 seconds.",
        )
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertIn("infinite loop", proposal["change_description"])

    def test_timeout_without_target_file_is_not_ready(self):
        analysis = _error_analysis(target_file=None, error_type=ERROR_TYPE_TIMEOUT, line_number=None)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertIsNone(proposal["change_description"])


class TestBuildCodeCorrectionProposalMissingInformation(unittest.TestCase):
    def test_missing_target_file_is_not_ready(self):
        analysis = _error_analysis(target_file=None)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertIsNone(proposal["change_description"])

    def test_non_dict_input_never_raises_and_is_not_ready(self):
        proposal = build_code_correction_proposal("not an analysis")
        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertIsNone(proposal["target_file"])
        self.assertIsNone(proposal["error_type"])
        self.assertIsNone(proposal["change_description"])
        self.assertFalse(proposal["ready_to_apply"])
        self.assertIsNone(proposal["apply_capability"])

    def test_none_input_never_raises(self):
        proposal = build_code_correction_proposal(None)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)

    def test_unrecognized_error_type_marked_actionable_is_not_ready(self):
        # Defensive: even if is_actionable/target_file were both
        # present, an error_type outside the fixed template lookup is
        # never guessed at - still NOT_READY.
        analysis = _error_analysis(error_type="SomeUnsupportedError", is_actionable=True)
        proposal = build_code_correction_proposal(analysis)
        self.assertEqual(proposal["status"], STATUS_NOT_READY)


class TestAllCodeCorrectionProposalStatuses(unittest.TestCase):
    def test_fixed_two_way_vocabulary(self):
        self.assertEqual(ALL_CODE_CORRECTION_PROPOSAL_STATUSES, (STATUS_PROPOSED, STATUS_NOT_READY))


class TestAgentLoopProposeCodeCorrection(unittest.TestCase):
    """Requirement: make the proposal available to the existing
    AgentLoop without creating a duplicate correction system, and
    preserve the original execution/evaluation/error-analysis
    results."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_actionable_failure_via_agent_loop_produces_proposal(self):
        stderr = (
            'Traceback (most recent call last):\n'
            '  File "/sandbox/generated.py", line 2, in <module>\n'
            '    raise RuntimeError("boom")\n'
            'RuntimeError: boom\n'
        )
        result = _execution_result(STATUS_FAILED, stderr=stderr)
        bundle = self.loop.propose_code_correction(result)
        self.assertIs(bundle["execution_result"], result)
        self.assertEqual(bundle["error_analysis"]["error_type"], ERROR_TYPE_RUNTIME)
        self.assertEqual(bundle["proposal"]["status"], STATUS_PROPOSED)
        self.assertEqual(bundle["proposal"]["apply_capability"], CODE_CHANGE_PLAN_CAPABILITY_NAME)

    def test_non_actionable_failure_via_agent_loop_is_not_ready(self):
        # No traceback at all in stderr - UNKNOWN_ERROR, not actionable.
        result = _execution_result(STATUS_FAILED, error="exited with return code 1", stderr="")
        bundle = self.loop.propose_code_correction(result)
        self.assertFalse(bundle["error_analysis"]["is_actionable"])
        self.assertEqual(bundle["proposal"]["status"], STATUS_NOT_READY)

    def test_timeout_via_agent_loop_produces_proposal(self):
        result = _execution_result(
            STATUS_TIMEOUT, error="timed out after 5 seconds.", stderr="",
        )
        bundle = self.loop.propose_code_correction(result)
        self.assertEqual(bundle["proposal"]["status"], STATUS_PROPOSED)
        self.assertEqual(bundle["proposal"]["error_type"], ERROR_TYPE_TIMEOUT)

    def test_preserves_original_execution_evaluation_and_error_analysis(self):
        result = _execution_result(STATUS_FAILED, stderr="")
        bundle = self.loop.propose_code_correction(result)
        self.assertEqual(
            bundle["evaluation"], self.loop.evaluate_generated_code_execution_result(result)
        )
        self.assertEqual(
            bundle["error_analysis"], self.loop.analyze_generated_code_error(result)
        )

    def test_never_applies_or_reexecutes(self):
        # Proposing a correction only reports a structured, inert
        # proposal - it never touches the Plan/Goal (no plan/goal was
        # even created in this test's setUp) and returns no applied
        # change of its own.
        result = _execution_result(STATUS_FAILED, stderr="")
        bundle = self.loop.propose_code_correction(result)
        self.assertFalse(bundle["proposal"]["ready_to_apply"])
        self.assertEqual(self.loop._goal_manager.get_goal("anything"), None)

    def test_invalid_input_via_agent_loop_never_raises(self):
        bundle = self.loop.propose_code_correction("not a result")
        self.assertEqual(bundle["proposal"]["status"], STATUS_NOT_READY)


if __name__ == "__main__":
    unittest.main()
