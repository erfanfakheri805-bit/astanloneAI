"""
Tests for agent/code_correction_pattern_retrieval.py - lets the
existing AgentLoop retrieve previously-recorded, successful
code-correction learning records (agent/code_correction_learning.py,
Prompt 345) for a given error_type, before generating a new correction
proposal. Made available on the existing AgentLoop via
`AgentLoop.retrieve_successful_correction_patterns` (agent/agent_loop.py).

Covers the four focused scenarios Prompt 346 asks for:
  - matching successful pattern
  - different error type -> no match
  - no learned patterns -> empty result
  - failed correction is not returned as a successful pattern

...plus a few small, deterministic extras: reuse of the existing
LearningRecordStore (never a second store), a missing/None store never
raising, and the AgentLoop wiring matching the pure function.

Run directly:
    python -m unittest tests.test_code_correction_pattern_retrieval -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_pattern_retrieval import retrieve_successful_correction_patterns
from agent.code_correction_learning import (
    learn_from_code_correction,
    SOURCE_CODE_CORRECTION_SYSTEM,
    OUTCOME_SUCCESS,
)
from agent.code_correction_application import STATUS_APPLIED, STATUS_REJECTED
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED
from learning.learning_record import LearningRecord
from learning.learning_record_store import LearningRecordStore
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController


def _retest_result(
    error_type="NameError", correction_status=STATUS_APPLIED,
    original_status=RESULT_FAILED, retest_status=None,
    retest_performed=True, improved=False, regressed=False,
):
    """A minimal, real-shaped `retest_code_correction`
    (Prompt 344) result - the exact same shape
    tests/test_code_correction_learning.py already uses to exercise
    Prompt 345's own learning-record builder."""
    return {
        "correction_result": {
            "proposal": {"error_type": error_type, "status": "PROPOSED"},
            "validation_result": {"status": "VALID"},
            "application": {
                "status": correction_status, "target_file": "/x/thing.py",
                "changed": correction_status == STATUS_APPLIED, "error": None,
            },
        },
        "original_evaluation": {"classification": original_status, "test_result": {}},
        "retest_performed": retest_performed,
        "retest_evaluation": (
            {"classification": retest_status, "test_result": {}}
            if retest_performed else None
        ),
        "comparison": (
            {
                "original_status": original_status, "retest_status": retest_status,
                "improved": improved, "regressed": regressed, "unchanged": not (improved or regressed),
            }
            if retest_performed else None
        ),
    }


def _record_a_successful_correction(store, error_type="NameError"):
    return learn_from_code_correction(
        _retest_result(error_type=error_type, retest_status=RESULT_PASSED, improved=True),
        store,
    )


def _record_a_failed_correction(store, error_type="NameError"):
    return learn_from_code_correction(
        _retest_result(error_type=error_type, retest_status=RESULT_FAILED),
        store,
    )


# ----------------------------------------------------------------------
# 1. matching successful pattern
# ----------------------------------------------------------------------
class TestMatchingSuccessfulPattern(unittest.TestCase):
    def test_returns_the_successful_record_for_its_own_error_type(self):
        store = LearningRecordStore()
        stored = _record_a_successful_correction(store, error_type="NameError")

        results = retrieve_successful_correction_patterns(store, "NameError")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].record_id, stored.record_id)
        self.assertEqual(results[0].outcome, OUTCOME_SUCCESS)
        self.assertEqual(results[0].source, SOURCE_CODE_CORRECTION_SYSTEM)

    def test_multiple_successful_records_for_the_same_error_type_are_all_returned(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="TypeError")
        _record_a_successful_correction(store, error_type="TypeError")

        results = retrieve_successful_correction_patterns(store, "TypeError")

        self.assertEqual(len(results), 2)


# ----------------------------------------------------------------------
# 2. different error type -> no match
# ----------------------------------------------------------------------
class TestDifferentErrorTypeNoMatch(unittest.TestCase):
    def test_unrelated_error_type_returns_nothing(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="NameError")

        results = retrieve_successful_correction_patterns(store, "AttributeError")

        self.assertEqual(results, [])


# ----------------------------------------------------------------------
# 3. no learned patterns -> empty result
# ----------------------------------------------------------------------
class TestNoLearnedPatternsEmptyResult(unittest.TestCase):
    def test_empty_store_returns_empty_list(self):
        store = LearningRecordStore()

        results = retrieve_successful_correction_patterns(store, "NameError")

        self.assertEqual(results, [])

    def test_none_store_returns_empty_list(self):
        results = retrieve_successful_correction_patterns(None, "NameError")
        self.assertEqual(results, [])

    def test_blank_error_type_returns_empty_list(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="NameError")

        self.assertEqual(retrieve_successful_correction_patterns(store, ""), [])
        self.assertEqual(retrieve_successful_correction_patterns(store, None), [])


# ----------------------------------------------------------------------
# 4. failed correction is not returned as a successful pattern
# ----------------------------------------------------------------------
class TestFailedCorrectionNeverReturned(unittest.TestCase):
    def test_failed_record_for_same_error_type_is_excluded(self):
        store = LearningRecordStore()
        _record_a_failed_correction(store, error_type="NameError")

        results = retrieve_successful_correction_patterns(store, "NameError")

        self.assertEqual(results, [])

    def test_only_the_successful_record_is_returned_among_mixed_records(self):
        store = LearningRecordStore()
        _record_a_failed_correction(store, error_type="NameError")
        successful = _record_a_successful_correction(store, error_type="NameError")
        _record_a_failed_correction(store, error_type="NameError")

        results = retrieve_successful_correction_patterns(store, "NameError")

        self.assertEqual([r.record_id for r in results], [successful.record_id])

    def test_rejected_correction_is_never_returned(self):
        store = LearningRecordStore()
        learn_from_code_correction(
            _retest_result(
                error_type="NameError", correction_status=STATUS_REJECTED,
                retest_performed=False, retest_status=None,
            ),
            store,
        )

        results = retrieve_successful_correction_patterns(store, "NameError")
        self.assertEqual(results, [])


# ----------------------------------------------------------------------
# Extra: reuses the existing store's own filtering methods, never a
# second learning system; records from a different source under the
# same pattern string are never mistaken for this pipeline's own.
# ----------------------------------------------------------------------
class TestReusesExistingStoreOnly(unittest.TestCase):
    def test_unrelated_source_under_same_pattern_is_ignored(self):
        store = LearningRecordStore()
        other = LearningRecord(
            source="some_other_system", pattern="NameError",
            outcome=OUTCOME_SUCCESS, confidence=1.0,
        )
        store.add(other)

        results = retrieve_successful_correction_patterns(store, "NameError")

        self.assertEqual(results, [])

    def test_returned_records_are_safe_copies(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="NameError")

        results = retrieve_successful_correction_patterns(store, "NameError")
        results[0].outcome = "tampered"

        results_again = retrieve_successful_correction_patterns(store, "NameError")
        self.assertEqual(results_again[0].outcome, OUTCOME_SUCCESS)


# ----------------------------------------------------------------------
# AgentLoop wiring: `retrieve_successful_correction_patterns` reuses
# the pure function unchanged and this loop's own configured store.
# ----------------------------------------------------------------------
class TestAgentLoopRetrieveSuccessfulCorrectionPatterns(unittest.TestCase):
    def _agent_loop(self, learning_record_store=None):
        goal_manager = GoalManager()
        plan_manager = PlanManager(goal_manager)
        controller = PlanExecutionController(plan_manager)
        return AgentLoop(
            goal_manager, plan_manager, controller,
            learning_record_store=learning_record_store,
        )

    def test_wired_method_returns_matching_successful_pattern(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="NameError")
        loop = self._agent_loop(learning_record_store=store)

        results = loop.retrieve_successful_correction_patterns("NameError")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["outcome"], OUTCOME_SUCCESS)
        self.assertEqual(results[0]["metadata"]["error_type"], "NameError")

    def test_wired_method_returns_empty_for_no_store(self):
        loop = self._agent_loop(learning_record_store=None)
        self.assertEqual(loop.retrieve_successful_correction_patterns("NameError"), [])

    def test_wired_method_returns_empty_for_different_error_type(self):
        store = LearningRecordStore()
        _record_a_successful_correction(store, error_type="NameError")
        loop = self._agent_loop(learning_record_store=store)

        self.assertEqual(loop.retrieve_successful_correction_patterns("TypeError"), [])

    def test_wired_method_excludes_failed_corrections(self):
        store = LearningRecordStore()
        _record_a_failed_correction(store, error_type="NameError")
        loop = self._agent_loop(learning_record_store=store)

        self.assertEqual(loop.retrieve_successful_correction_patterns("NameError"), [])


if __name__ == "__main__":
    unittest.main()
