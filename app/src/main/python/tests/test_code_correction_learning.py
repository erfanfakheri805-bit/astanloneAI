"""
Tests for agent/code_correction_learning.py - connects the existing
code-correction retest/comparison result (agent/code_correction_retest.py,
Prompt 344) to the existing Learning system
(learning/learning_record.py, learning/learning_record_store.py), made
available on the existing AgentLoop via
`AgentLoop.learn_from_code_correction` (agent/agent_loop.py).

Covers the four focused scenarios Prompt 345 asks for:
  - successful correction -> successful learning record
  - failed correction -> failed learning record
  - rejected correction -> no successful learning record
  - original/retest statuses are preserved

...plus a few small, deterministic extras: storing into an actual
`LearningRecordStore`, the record always being a real, valid
`LearningRecord`, and malformed input never raising.

Run directly:
    python -m unittest tests.test_code_correction_learning -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_correction_learning import (
    SOURCE_CODE_CORRECTION_SYSTEM,
    DEFAULT_PATTERN,
    OUTCOME_SUCCESS,
    OUTCOME_FAILURE,
    CONFIDENCE_SUCCESS,
    CONFIDENCE_FAILURE,
    build_code_correction_learning_record,
    learn_from_code_correction,
)
from agent.code_correction_application import STATUS_APPLIED, STATUS_REJECTED, STATUS_NOT_READY
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT
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
    (Prompt 344) result - only the fields
    `build_code_correction_learning_record` itself ever reads."""
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


# ----------------------------------------------------------------------
# 1. successful correction -> successful learning record
# ----------------------------------------------------------------------
class TestSuccessfulCorrectionLearning(unittest.TestCase):
    def test_passed_retest_is_recorded_as_successful(self):
        retest_result = _retest_result(
            retest_status=RESULT_PASSED, improved=True,
        )
        record = build_code_correction_learning_record(retest_result)

        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, OUTCOME_SUCCESS)
        self.assertEqual(record.confidence, CONFIDENCE_SUCCESS)
        self.assertEqual(record.source, SOURCE_CODE_CORRECTION_SYSTEM)
        self.assertTrue(record.is_valid())


# ----------------------------------------------------------------------
# 2. failed correction -> failed learning record
# ----------------------------------------------------------------------
class TestFailedCorrectionLearning(unittest.TestCase):
    def test_still_failing_retest_is_recorded_as_failure(self):
        retest_result = _retest_result(
            retest_status=RESULT_FAILED, improved=False, regressed=False,
        )
        record = build_code_correction_learning_record(retest_result)

        self.assertEqual(record.outcome, OUTCOME_FAILURE)
        self.assertEqual(record.confidence, CONFIDENCE_FAILURE)
        self.assertTrue(record.is_valid())

    def test_timed_out_retest_is_recorded_as_failure(self):
        retest_result = _retest_result(
            original_status=RESULT_FAILED, retest_status=RESULT_TIMEOUT, regressed=True,
        )
        record = build_code_correction_learning_record(retest_result)

        self.assertEqual(record.outcome, OUTCOME_FAILURE)
        self.assertEqual(record.confidence, CONFIDENCE_FAILURE)


# ----------------------------------------------------------------------
# 3. rejected correction -> no successful learning record
# ----------------------------------------------------------------------
class TestRejectedCorrectionLearning(unittest.TestCase):
    def test_rejected_correction_is_recorded_but_never_successful(self):
        retest_result = _retest_result(
            correction_status=STATUS_REJECTED, retest_performed=False, retest_status=None,
        )
        record = build_code_correction_learning_record(retest_result)

        # Still recorded - a rejected correction is knowledge too -
        # but never as success (requirement 4).
        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, OUTCOME_FAILURE)
        self.assertEqual(record.confidence, CONFIDENCE_FAILURE)
        self.assertEqual(record.metadata["correction_status"], STATUS_REJECTED)
        self.assertIsNone(record.metadata["retest_status"])
        self.assertFalse(record.metadata["improved"])
        self.assertFalse(record.metadata["regressed"])

    def test_not_ready_correction_is_recorded_but_never_successful(self):
        retest_result = _retest_result(
            correction_status=STATUS_NOT_READY, retest_performed=False, retest_status=None,
        )
        record = build_code_correction_learning_record(retest_result)

        self.assertEqual(record.outcome, OUTCOME_FAILURE)
        self.assertEqual(record.metadata["correction_status"], STATUS_NOT_READY)


# ----------------------------------------------------------------------
# 4. original/retest statuses are preserved
# ----------------------------------------------------------------------
class TestStatusesArePreserved(unittest.TestCase):
    def test_original_and_retest_status_preserved_in_metadata(self):
        retest_result = _retest_result(
            error_type="TypeError", original_status=RESULT_TIMEOUT,
            retest_status=RESULT_PASSED, improved=True,
        )
        record = build_code_correction_learning_record(retest_result)

        self.assertEqual(record.metadata["error_type"], "TypeError")
        self.assertEqual(record.metadata["original_status"], RESULT_TIMEOUT)
        self.assertEqual(record.metadata["retest_status"], RESULT_PASSED)
        self.assertEqual(record.metadata["correction_status"], STATUS_APPLIED)
        self.assertTrue(record.metadata["improved"])
        self.assertFalse(record.metadata["regressed"])

    def test_retest_result_itself_is_not_mutated(self):
        retest_result = _retest_result(retest_status=RESULT_PASSED, improved=True)
        import copy
        before = copy.deepcopy(retest_result)

        build_code_correction_learning_record(retest_result)

        self.assertEqual(retest_result, before)

    def test_pattern_uses_error_type(self):
        retest_result = _retest_result(error_type="AttributeError", retest_status=RESULT_FAILED)
        record = build_code_correction_learning_record(retest_result)
        self.assertEqual(record.pattern, "AttributeError")

    def test_missing_error_type_falls_back_to_default_pattern(self):
        retest_result = _retest_result(error_type=None, retest_status=RESULT_FAILED)
        record = build_code_correction_learning_record(retest_result)
        self.assertEqual(record.pattern, DEFAULT_PATTERN)


# ----------------------------------------------------------------------
# Extra: storage reuses the existing LearningRecordStore/pattern
# infrastructure unchanged.
# ----------------------------------------------------------------------
class TestLearnFromCodeCorrectionStoresIntoExistingStore(unittest.TestCase):
    def test_successful_record_is_stored_and_findable_by_pattern(self):
        store = LearningRecordStore()
        retest_result = _retest_result(
            error_type="NameError", retest_status=RESULT_PASSED, improved=True,
        )

        stored = learn_from_code_correction(retest_result, store)

        self.assertIsNotNone(stored)
        self.assertEqual([r.record_id for r in store.find_by_pattern("NameError")], [stored.record_id])
        self.assertEqual([r.record_id for r in store.find_by_source(SOURCE_CODE_CORRECTION_SYSTEM)], [stored.record_id])
        self.assertEqual([r.record_id for r in store.find_by_outcome(OUTCOME_SUCCESS)], [stored.record_id])

    def test_rejected_record_is_stored_but_not_under_success_outcome(self):
        store = LearningRecordStore()
        retest_result = _retest_result(
            correction_status=STATUS_REJECTED, retest_performed=False, retest_status=None,
        )

        stored = learn_from_code_correction(retest_result, store)

        self.assertIsNotNone(stored)
        self.assertEqual(store.find_by_outcome(OUTCOME_SUCCESS), [])
        self.assertEqual([r.record_id for r in store.find_by_outcome(OUTCOME_FAILURE)], [stored.record_id])


class TestNeverRaises(unittest.TestCase):
    def test_non_dict_retest_result_never_raises(self):
        record = build_code_correction_learning_record("not a retest result")
        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, OUTCOME_FAILURE)

    def test_none_retest_result_never_raises(self):
        record = build_code_correction_learning_record(None)
        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, OUTCOME_FAILURE)
        self.assertEqual(record.pattern, DEFAULT_PATTERN)
        self.assertTrue(record.is_valid())


# ----------------------------------------------------------------------
# AgentLoop wiring: `learn_from_code_correction` reuses
# `build_code_correction_learning_record` unchanged and stores through
# the existing, already-wired `learning_record_store`.
# ----------------------------------------------------------------------
class TestAgentLoopLearnFromCodeCorrection(unittest.TestCase):
    def _agent_loop(self, learning_record_store=None):
        goal_manager = GoalManager()
        plan_manager = PlanManager(goal_manager)
        controller = PlanExecutionController(plan_manager)
        return AgentLoop(
            goal_manager, plan_manager, controller,
            learning_record_store=learning_record_store,
        )

    def test_stores_into_configured_learning_record_store(self):
        store = LearningRecordStore()
        loop = self._agent_loop(learning_record_store=store)
        retest_result = _retest_result(retest_status=RESULT_PASSED, improved=True)

        result = loop.learn_from_code_correction(retest_result)

        self.assertTrue(result["stored"])
        self.assertEqual(result["record"]["outcome"], OUTCOME_SUCCESS)
        self.assertEqual(len(store.get_all()), 1)

    def test_reports_not_stored_with_no_configured_store(self):
        loop = self._agent_loop(learning_record_store=None)
        retest_result = _retest_result(retest_status=RESULT_PASSED, improved=True)

        result = loop.learn_from_code_correction(retest_result)

        self.assertFalse(result["stored"])
        self.assertEqual(result["record"]["outcome"], OUTCOME_SUCCESS)

    def test_rejected_correction_never_stored_as_success(self):
        store = LearningRecordStore()
        loop = self._agent_loop(learning_record_store=store)
        retest_result = _retest_result(
            correction_status=STATUS_REJECTED, retest_performed=False, retest_status=None,
        )

        result = loop.learn_from_code_correction(retest_result)

        self.assertTrue(result["stored"])
        self.assertEqual(result["record"]["outcome"], OUTCOME_FAILURE)


if __name__ == "__main__":
    unittest.main()
