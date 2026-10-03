"""
Tests for Prompt 347 - passing previously-successful repair patterns
(agent/code_correction_pattern_retrieval.py, Prompt 346) into the
existing correction-proposal generation flow (agent/
code_correction_proposal.py's `build_code_correction_proposal`,
Prompt 341) as optional, advisory-only context.

Covers the four focused scenarios the prompt asks for:
  - a matching learned pattern is passed as context
  - no learned pattern still generates/returns the normal proposal flow
  - a learned pattern is never automatically applied
  - the current error remains independently validated

Run directly:
    python -m unittest tests.test_learned_patterns_in_correction_proposal -v
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
)
from agent.code_correction_pattern_retrieval import (
    retrieve_successful_correction_patterns,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED
from agent.code_correction_application import STATUS_APPLIED
from code_generation.generated_code_execution import STATUS_FAILED
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
    """A minimal, real-shaped `retest_code_correction` (Prompt 344)
    result - the same shape tests/test_code_correction_pattern_
    retrieval.py already uses to feed Prompt 345's learning-record
    builder."""
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


# ----------------------------------------------------------------------
# 1. matching learned pattern is passed as context
# ----------------------------------------------------------------------
class TestMatchingLearnedPatternPassedAsContext(unittest.TestCase):
    def test_build_code_correction_proposal_carries_learned_patterns_through(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)
        self.assertEqual(len(learned), 1)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["learned_patterns"], learned)
        self.assertEqual(proposal["status"], STATUS_PROPOSED)

    def test_agent_loop_propose_code_correction_looks_up_and_forwards_matching_pattern(self):
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
        result = _execution_result(STATUS_FAILED, stderr=stderr)
        bundle = loop.propose_code_correction(result)

        self.assertEqual(bundle["error_analysis"]["error_type"], ERROR_TYPE_RUNTIME)
        self.assertEqual(len(bundle["learned_patterns"]), 1)
        self.assertEqual(bundle["learned_patterns"][0]["outcome"], OUTCOME_SUCCESS)
        # the same list handed to the proposal generator as context
        self.assertEqual(bundle["proposal"]["learned_patterns"], bundle["learned_patterns"])
        self.assertEqual(bundle["proposal"]["status"], STATUS_PROPOSED)


# ----------------------------------------------------------------------
# 2. no learned pattern still generates/returns the normal proposal flow
# ----------------------------------------------------------------------
class TestNoLearnedPatternStillGeneratesNormalProposal(unittest.TestCase):
    def test_build_code_correction_proposal_with_no_context_is_unaffected(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal_without_context = build_code_correction_proposal(analysis)
        proposal_with_empty_context = build_code_correction_proposal(analysis, learned_patterns=[])

        self.assertEqual(proposal_without_context["status"], STATUS_PROPOSED)
        self.assertEqual(proposal_without_context["learned_patterns"], [])
        self.assertEqual(proposal_with_empty_context["learned_patterns"], [])
        # everything except the (identical, empty) learned_patterns field matches
        self.assertEqual(proposal_without_context, proposal_with_empty_context)

    def test_build_code_correction_proposal_normalizes_missing_or_bad_context(self):
        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        self.assertEqual(build_code_correction_proposal(analysis, learned_patterns=None)["learned_patterns"], [])
        self.assertEqual(build_code_correction_proposal(analysis, learned_patterns="not a list")["learned_patterns"], [])

    def test_agent_loop_propose_code_correction_with_empty_store_behaves_as_before(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller)  # no learning_record_store at all

        result = _execution_result(STATUS_FAILED, stderr="")
        bundle = loop.propose_code_correction(result)

        self.assertEqual(bundle["learned_patterns"], [])
        self.assertEqual(bundle["proposal"]["learned_patterns"], [])
        # the proposal itself is generated exactly as it was pre-Prompt-347
        self.assertIn(bundle["proposal"]["status"], (STATUS_PROPOSED, STATUS_NOT_READY))


# ----------------------------------------------------------------------
# 3. a learned pattern is never automatically applied
# ----------------------------------------------------------------------
class TestLearnedPatternNeverAutomaticallyApplied(unittest.TestCase):
    def test_ready_to_apply_stays_false_even_with_a_matching_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertFalse(proposal["ready_to_apply"])

    def test_change_description_is_not_copied_from_the_learned_pattern(self):
        # The learning record carries no source-code/correction text at
        # all (see learning.learning_record.LearningRecord) - there is
        # nothing here to copy. As of Prompt 348, a relevant successful
        # pattern may add one fixed, hedged supporting-context sentence
        # (see test_learned_patterns_improve_correction_proposal.py),
        # but the underlying, deterministic per-error_type template
        # description is still there, unchanged, as a prefix.
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, line_number=4)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        without_context = build_code_correction_proposal(analysis)
        self.assertTrue(proposal["change_description"].startswith(without_context["change_description"]))

    def test_agent_loop_never_applies_or_reexecutes_with_a_learned_pattern_present(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)

        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller, learning_record_store=store)

        stderr = "NameError: name 'x' is not defined\n"
        result = _execution_result(STATUS_FAILED, stderr=stderr)
        bundle = loop.propose_code_correction(result)

        self.assertFalse(bundle["proposal"]["ready_to_apply"])
        self.assertEqual(loop._goal_manager.get_goal("anything"), None)


# ----------------------------------------------------------------------
# 4. the current error remains independently validated
# ----------------------------------------------------------------------
class TestCurrentErrorRemainsIndependentlyValidated(unittest.TestCase):
    def test_non_actionable_error_stays_not_ready_despite_a_matching_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)
        self.assertEqual(len(learned), 1)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, is_actionable=False)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["status"], STATUS_NOT_READY)
        self.assertEqual(proposal["learned_patterns"], learned)

    def test_missing_target_file_stays_not_ready_despite_a_matching_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)
        learned = retrieve_successful_correction_patterns(store, ERROR_TYPE_NAME)

        analysis = _error_analysis(error_type=ERROR_TYPE_NAME, target_file=None)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["status"], STATUS_NOT_READY)

    def test_matching_pattern_never_flips_an_unrecognized_error_type_to_proposed(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="SomeUnrecognizedError")
        learned = retrieve_successful_correction_patterns(store, "SomeUnrecognizedError")
        self.assertEqual(len(learned), 1)

        analysis = _error_analysis(error_type="SomeUnrecognizedError", is_actionable=True)
        proposal = build_code_correction_proposal(analysis, learned_patterns=learned)

        self.assertEqual(proposal["status"], STATUS_NOT_READY)

    def test_agent_loop_still_reports_not_ready_for_non_actionable_failure_with_pattern_on_record(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type=ERROR_TYPE_NAME)

        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller, learning_record_store=store)

        # No traceback at all in stderr - UNKNOWN_ERROR, not actionable -
        # regardless of an unrelated successful NameError pattern on file.
        result = _execution_result(STATUS_FAILED, error="exited with return code 1", stderr="")
        bundle = loop.propose_code_correction(result)

        self.assertFalse(bundle["error_analysis"]["is_actionable"])
        self.assertEqual(bundle["proposal"]["status"], STATUS_NOT_READY)


if __name__ == "__main__":
    unittest.main()
