"""
Tests for the ExecutionLearning model (learning/execution_learning.py).

Covers: a successful execution producing a record, a failed execution
producing a record, invalid input returning None, that the original
ExecutionResult is never modified, and the learn_from_execution()
convenience wrapper that stores a created record into an existing
LearningRecordStore. This stage only builds/stores a LearningRecord
from an already-produced ExecutionResult - it never touches
plans/capabilities/skills/code.

Run directly:
    python -m unittest tests.test_execution_learning -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.execution_result import ExecutionResult
from execution.capability_output import CapabilityOutput
from learning.learning_record import LearningRecord
from learning.learning_record_store import LearningRecordStore
from learning.execution_learning import ExecutionLearning


class TestSuccessfulExecution(unittest.TestCase):
    def test_successful_execution_creates_a_record(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        result.mark_completed(output="done")
        learner = ExecutionLearning()

        record = learner.create_record(result)

        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, "success")
        self.assertTrue(record.is_valid())

    def test_capability_name_used_as_pattern_when_available(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        result.mark_completed()
        result.attach_capability_output(
            "send_notification", CapabilityOutput(success=True, capability_name="send_notification")
        )
        learner = ExecutionLearning()

        record = learner.create_record(result)

        self.assertEqual(record.pattern, "send_notification")


class TestFailedExecution(unittest.TestCase):
    def test_failed_execution_creates_a_record(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-2")
        result.mark_failed("boom")
        learner = ExecutionLearning()

        record = learner.create_record(result)

        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, "failure")
        self.assertTrue(record.is_valid())
        self.assertEqual(record.metadata.get("error"), "boom")

    def test_failed_execution_falls_back_to_step_pattern(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-2")
        result.mark_failed("boom")
        learner = ExecutionLearning()

        record = learner.create_record(result)

        self.assertEqual(record.pattern, "step:step-2")


class TestInvalidInput(unittest.TestCase):
    def test_non_execution_result_returns_none(self):
        learner = ExecutionLearning()

        self.assertIsNone(learner.create_record({"status": "completed"}))
        self.assertIsNone(learner.create_record(None))

    def test_pending_execution_result_returns_none(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        learner = ExecutionLearning()

        self.assertIsNone(learner.create_record(result))


class TestExecutionResultUnchanged(unittest.TestCase):
    def test_create_record_does_not_modify_the_execution_result(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        result.mark_completed(output="done")
        before = result.to_dict()
        learner = ExecutionLearning()

        learner.create_record(result)

        self.assertEqual(result.to_dict(), before)


class TestLearnFromExecution(unittest.TestCase):
    def test_successful_execution_creates_and_stores_a_record(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        result.mark_completed(output="done")
        store = LearningRecordStore()
        learner = ExecutionLearning()

        record = learner.learn_from_execution(result, store)

        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, "success")
        self.assertEqual(len(store), 1)
        self.assertEqual(store.get(record.record_id).outcome, "success")

    def test_failed_execution_creates_and_stores_a_record(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-2")
        result.mark_failed("boom")
        store = LearningRecordStore()
        learner = ExecutionLearning()

        record = learner.learn_from_execution(result, store)

        self.assertIsInstance(record, LearningRecord)
        self.assertEqual(record.outcome, "failure")
        self.assertEqual(len(store), 1)
        self.assertEqual(store.get(record.record_id).metadata.get("error"), "boom")

    def test_invalid_execution_does_not_create_or_store_a_record(self):
        store = LearningRecordStore()
        learner = ExecutionLearning()

        record = learner.learn_from_execution({"status": "completed"}, store)

        self.assertIsNone(record)
        self.assertEqual(len(store), 0)

    def test_pending_execution_does_not_create_or_store_a_record(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        store = LearningRecordStore()
        learner = ExecutionLearning()

        record = learner.learn_from_execution(result, store)

        self.assertIsNone(record)
        self.assertEqual(len(store), 0)

    def test_original_execution_result_remains_unchanged(self):
        result = ExecutionResult(plan_id="plan-1", step_id="step-1")
        result.mark_completed(output="done")
        before = result.to_dict()
        store = LearningRecordStore()
        learner = ExecutionLearning()

        learner.learn_from_execution(result, store)

        self.assertEqual(result.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
