"""
Tests for Prompt 348 - improving the existing correction-proposal
generation flow (agent/code_correction_proposal.py's
`build_code_correction_proposal`) so a previously-successful, relevant
repair pattern (agent/code_correction_pattern_retrieval.py, Prompt
346/347) can be referenced as supporting context for a more specific
proposal - never as proof of correctness, and never auto-applied.

Covers the five focused scenarios the prompt asks for:
  - relevant learned pattern used
  - no learned pattern
  - irrelevant learned pattern
  - insufficient information -> "NOT_READY"
  - proposal remains unapplied

Run directly:
    python -m unittest tests.test_learned_patterns_improve_correction_proposal -v
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
    build_code_correction_proposal,
)
from agent.code_error_analysis import (
    ERROR_TYPE_NAME,
    ERROR_TYPE_RUNTIME,
)
from agent.code_correction_learning import (
    learn_from_code_correction,
    OUTCOME_SUCCESS,
    OUTCOME_FAILURE,
)
from agent.code_correction_pattern_retrieval import (
    retrieve_successful_correction_patterns,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED
from agent.code_correction_application import STATUS_APPLIED
from code_generation.generated_code_execution import STATUS_FAILED
from execution.code_change_plan_capability import CAPABILITY_NAME as CODE_CHANGE_PLAN_CAPABILITY_NAME
from learning.learning_record_store import LearningRecordStore

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


def _retest_result(error_type="NameError", retest_status=RESULT_PASSED, improved=True):
    return {
        "correction_result": {
            "proposal": {"error_type": error_type, "status": "PROPOSED"},
            "validation_result": {"status": "VALID"},
            "application": {
                "status": STATUS_APPLIED, "target_file": "/sandbox/generated.py",
                "changed": True, "error": None,
            },
        },
        "original_evaluation": {"classification": RESULT_FAILED, "test_result": {}},
        "retest_performed": True,
        "retest_evaluation": {"classification": retest_status, "test_result": {}},
        "comparison": {
            "original_status": RESULT_FAILED, "retest_status": retest_status,
            "improved": improved, "regressed": False, "unchanged": not improved,
        },
    }


def _record_a_successful_correction(store, error_type="NameError"):
    return learn_from_code_correction(_retest_result(error_type=error_type), store)


def _record_a_failed_correction(store, error_type="NameError"):
    return learn_from_code_correction(
        _retest_result(error_type=error_type, retest_status=RESULT_FAILED, improved=False), store,
    )


# ----------------------------------------------------------------------
# 1. relevant learned pattern used
# ----------------------------------------------------------------------
class TestRelevantLearnedPatternUsed(unittest.TestCase):
    def test_pure_function_marks_pattern_used_and_extends_change_description(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        without_context = build_code_correction_proposal(analysis)
        with_context = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertTrue(with_context["learned_pattern_used"])
        self.assertEqual(with_context["status"], STATUS_PROPOSED)
        self.assertTrue(with_context["change_description"].startswith(without_context["change_description"]))
        self.assertGreater(len(with_context["change_description"]), len(without_context["change_description"]))

    def test_dict_shaped_pattern_from_agent_loop_wrapper_is_also_used(self):
        # AgentLoop.retrieve_successful_correction_patterns returns
        # to_dict()-shaped dicts rather than LearningRecord objects -
        # both shapes must be recognized as relevant.
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_RUNTIME)

        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller, learning_record_store=store)

        stderr = (
            'Traceback (most recent call last):\n'
            '  File "/sandbox/generated.py", line 2, in <module>\n'
            '    raise RuntimeError("boom")\n'
            'RuntimeError: boom\n'
        )
        bundle = loop.propose_code_correction(_execution_result(STATUS_FAILED, stderr=stderr))

        self.assertTrue(bundle["proposal"]["learned_pattern_used"])
        self.assertIn("previously successful correction pattern", bundle["proposal"]["change_description"])

    def test_only_a_relevant_successful_pattern_among_several_is_used(self):
        store = LearningRecordStore()
        _record_a_failed_correction(store, error_type=ERROR_TYPE_NAME)
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)
        self.assertEqual(len(learned), 1)  # the store/retrieval already exclude the failed one

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertTrue(proposal["learned_pattern_used"])


# ----------------------------------------------------------------------
# 2. no learned pattern
# ----------------------------------------------------------------------
class TestNoLearnedPattern(unittest.TestCase):
    def test_no_context_at_all_keeps_normal_proposal_behavior(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis)

        self.assertFalse(proposal["learned_pattern_used"])
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertNotIn("previously successful", proposal["change_description"])

    def test_empty_learned_patterns_list_keeps_normal_proposal_behavior(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=[])

        self.assertFalse(proposal["learned_pattern_used"])
        self.assertEqual(proposal["status"], STATUS_PROPOSED)

    def test_agent_loop_with_no_store_configured_keeps_normal_proposal_behavior(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller)  # no learning_record_store

        bundle = loop.propose_code_correction(_execution_result(STATUS_FAILED, stderr=""))

        self.assertFalse(bundle["proposal"]["learned_pattern_used"])


# ----------------------------------------------------------------------
# 3. irrelevant learned pattern
# ----------------------------------------------------------------------
class TestIrrelevantLearnedPattern(unittest.TestCase):
    def test_pattern_for_a_different_error_type_is_not_used(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_RUNTIME)
        # Deliberately hand the RuntimeError pattern to a NameError proposal -
        # this module must independently recheck relevance, not trust the caller.
        unrelated_pattern = retrieve_successful_correction_patterns(store, ERROR_TYPE_RUNTIME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=unrelated_pattern)

        self.assertFalse(proposal["learned_pattern_used"])
        self.assertEqual(proposal["status"], STATUS_PROPOSED)
        self.assertNotIn("previously successful", proposal["change_description"])

    def test_failed_pattern_for_the_same_error_type_is_not_used(self):
        store = LearningRecordStore()
        _record_a_failed_correction(store, error_type=ERROR_TYPE_NAME)
        all_records = store.find_by_pattern(ERROR_TYPE_NAME)
        self.assertEqual(len(all_records), 1)
        self.assertEqual(all_records[0].outcome, OUTCOME_FAILURE)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        # Pass the failed record directly (bypassing retrieve_successful_
        # correction_patterns' own success filter) to prove this module's
        # own relevance check also requires OUTCOME_SUCCESS.
        proposal = build_code_correction_proposal(analysis, learned_patterns=all_records)

        self.assertFalse(proposal["learned_pattern_used"])

    def test_retrieval_itself_already_excludes_the_irrelevant_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_RUNTIME)
        learned_for_name_error = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)
        self.assertEqual(learned_for_name_error, [])

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned_for_name_error)

        self.assertFalse(proposal["learned_pattern_used"])


# ----------------------------------------------------------------------
# 4. insufficient information -> "NOT_READY"
# ----------------------------------------------------------------------
class TestInsufficientInformationIsNotReady(unittest.TestCase):
    def test_non_actionable_error_is_not_ready_even_with_a_relevant_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, is_actionable=False)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertIsNone(proposal["change_description"])
        self.assertFalse(proposal["learned_pattern_used"])

    def test_missing_target_file_is_not_ready_even_with_a_relevant_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, target_file=None)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertFalse(proposal["learned_pattern_used"])

    def test_non_dict_error_analysis_is_not_ready(self):
        proposal = build_code_correction_proposal("not a real analysis", learned_patterns=[{"pattern": "x"}])
        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertFalse(proposal["learned_pattern_used"])


# ----------------------------------------------------------------------
# 5. proposal remains unapplied
# ----------------------------------------------------------------------
class TestProposalRemainsUnapplied(unittest.TestCase):
    def test_ready_to_apply_is_false_even_when_a_learned_pattern_is_used(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertTrue(proposal["learned_pattern_used"])
        self.assertFalse(proposal["ready_to_apply"])
        self.assertEqual(proposal["apply_capability"], CODE_CHANGE_PLAN_CAPABILITY_NAME)

    def test_agent_loop_never_applies_a_correction_even_with_a_matching_pattern_on_record(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)

        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller, learning_record_store=store)

        bundle = loop.propose_code_correction(
            _execution_result(STATUS_FAILED, stderr="NameError: name 'x' is not defined\n")
        )

        self.assertTrue(bundle["proposal"]["learned_pattern_used"])
        self.assertFalse(bundle["proposal"]["ready_to_apply"])
        # No plan/goal was ever created or touched by proposing a correction.
        self.assertEqual(loop._goal_manager.get_goal("anything"), None)

    def test_validation_step_still_requires_explicit_separate_call_to_ever_apply(self):
        # Even a PROPOSED, learned-pattern-referenced proposal only ever
        # becomes "safe to apply" through the existing, separately
        # invoked validation step - never automatically.
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertTrue(proposal["learned_pattern_used"])
        self.assertFalse(proposal["ready_to_apply"])


if __name__ == "__main__":
    unittest.main()
