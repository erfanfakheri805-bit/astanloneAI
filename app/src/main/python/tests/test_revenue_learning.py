"""
Tests for RevenueLearningRecord (financial/revenue_learning.py).

Covers: building a record from a successful/failed RevenueTaskResult
via from_task_result(), exact task_id/opportunity_id preservation, the
success flag, output/error copying (independence from the original
result), is_valid()/is_successful()/is_failed(), to_dict()
serialization, and that the original RevenueTaskResult is never
modified by from_task_result().

This stage only defines the record's shape and how one is built from
an already-existing RevenueTaskResult - it does not learn anything,
does not execute anything, and is not wired into any learning system
yet.

Run directly:
    python -m unittest tests.test_revenue_learning -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_learning import RevenueLearningRecord
from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


def _make_task_result(**overrides):
    fields = dict(
        result_id="result-test-1",
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        status=STATUS_COMPLETED,
    )
    fields.update(overrides)
    return RevenueTaskResult(**fields)


def _make_learning_record(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        result_status=STATUS_COMPLETED,
        success=True,
    )
    fields.update(overrides)
    return RevenueLearningRecord(**fields)


# ----------------------------------------------------------------------
# 1. Successful RevenueTaskResult -> learning record
# ----------------------------------------------------------------------
class TestSuccessfulResultToLearningRecord(unittest.TestCase):
    def test_from_task_result_builds_a_successful_record(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"pages": 3})
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.result_status, STATUS_COMPLETED)
        self.assertTrue(record.success)
        self.assertTrue(record.is_successful())
        self.assertFalse(record.is_failed())

    def test_from_task_result_generates_a_learning_id(self):
        result = _make_task_result(status=STATUS_COMPLETED)
        record = RevenueLearningRecord.from_task_result(result)
        self.assertIsInstance(record.learning_id, str)
        self.assertTrue(record.learning_id.strip())

    def test_from_task_result_sets_a_created_at_timestamp(self):
        result = _make_task_result(status=STATUS_COMPLETED)
        record = RevenueLearningRecord.from_task_result(result)
        self.assertIsInstance(record.created_at, str)
        self.assertTrue(record.created_at.strip())


# ----------------------------------------------------------------------
# 2. Failed RevenueTaskResult -> learning record
# ----------------------------------------------------------------------
class TestFailedResultToLearningRecord(unittest.TestCase):
    def test_from_task_result_builds_a_failed_record(self):
        result = _make_task_result(status=STATUS_FAILED, error="timeout")
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.result_status, STATUS_FAILED)
        self.assertFalse(record.success)
        self.assertTrue(record.is_failed())
        self.assertFalse(record.is_successful())


# ----------------------------------------------------------------------
# 3. Exact task/opportunity ID preservation
# ----------------------------------------------------------------------
class TestIdPreservation(unittest.TestCase):
    def test_task_id_is_preserved_exactly(self):
        result = _make_task_result(task_id="task-xyz-42")
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.task_id, "task-xyz-42")

    def test_opportunity_id_is_preserved_exactly(self):
        result = _make_task_result(opportunity_id="opp-xyz-42")
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.opportunity_id, "opp-xyz-42")

    def test_learning_id_is_not_the_result_id(self):
        result = _make_task_result(result_id="result-abc")
        record = RevenueLearningRecord.from_task_result(result)
        self.assertNotEqual(record.learning_id, "result-abc")


# ----------------------------------------------------------------------
# 4. Success flag
# ----------------------------------------------------------------------
class TestSuccessFlag(unittest.TestCase):
    def test_success_true_only_for_completed(self):
        completed = _make_task_result(status=STATUS_COMPLETED)
        record = RevenueLearningRecord.from_task_result(completed)
        self.assertIs(record.success, True)

    def test_success_false_for_failed(self):
        failed = _make_task_result(status=STATUS_FAILED)
        record = RevenueLearningRecord.from_task_result(failed)
        self.assertIs(record.success, False)


# ----------------------------------------------------------------------
# 5. Output and error copying
# ----------------------------------------------------------------------
class TestOutputAndErrorCopying(unittest.TestCase):
    def test_output_is_copied_with_equal_value(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 5, "tags": ["a", "b"]})
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.output, {"units": 5, "tags": ["a", "b"]})

    def test_output_is_independent_from_the_original_result(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 5})
        record = RevenueLearningRecord.from_task_result(result)
        record.output["units"] = 999
        self.assertEqual(result.output, {"units": 5})

    def test_error_is_copied_with_equal_value(self):
        result = _make_task_result(status=STATUS_FAILED, error="connection lost")
        record = RevenueLearningRecord.from_task_result(result)
        self.assertEqual(record.error, "connection lost")

    def test_none_output_and_error_are_preserved(self):
        result = _make_task_result(status=STATUS_COMPLETED, output=None, error=None)
        record = RevenueLearningRecord.from_task_result(result)
        self.assertIsNone(record.output)
        self.assertIsNone(record.error)


# ----------------------------------------------------------------------
# 6. Validation
# ----------------------------------------------------------------------
class TestValidation(unittest.TestCase):
    def test_valid_record_from_task_result_passes_is_valid(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"a": 1})
        record = RevenueLearningRecord.from_task_result(result)
        self.assertTrue(record.is_valid())

    def test_empty_learning_id_is_invalid(self):
        record = _make_learning_record(learning_id="")
        self.assertFalse(record.is_valid())

    def test_empty_task_id_is_invalid(self):
        record = _make_learning_record(task_id="")
        self.assertFalse(record.is_valid())

    def test_empty_opportunity_id_is_invalid(self):
        record = _make_learning_record(opportunity_id="")
        self.assertFalse(record.is_valid())

    def test_invalid_result_status_is_invalid(self):
        record = _make_learning_record(result_status="BOGUS")
        self.assertFalse(record.is_valid())

    def test_non_bool_success_is_invalid(self):
        record = _make_learning_record(success="yes")
        self.assertFalse(record.is_valid())

    def test_non_string_non_none_error_is_invalid(self):
        record = _make_learning_record(error=12345)
        self.assertFalse(record.is_valid())

    def test_unsafe_output_is_invalid(self):
        class NotStructuredData:
            pass

        record = _make_learning_record(output=NotStructuredData())
        self.assertFalse(record.is_valid())

    def test_unsafe_metadata_is_invalid(self):
        class NotStructuredData:
            pass

        record = _make_learning_record(metadata={"bad": NotStructuredData()})
        self.assertFalse(record.is_valid())

    def test_from_task_result_rejects_non_result_input(self):
        with self.assertRaises(TypeError):
            RevenueLearningRecord.from_task_result({"not": "a result"})

    def test_construction_never_raises_on_bad_input(self):
        try:
            RevenueLearningRecord(
                task_id=None,
                opportunity_id=None,
                result_status="BOGUS",
                success="not-a-bool",
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"RevenueLearningRecord() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 7. Safe serialization
# ----------------------------------------------------------------------
class TestSafeSerialization(unittest.TestCase):
    def test_to_dict_shape(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 1})
        record = RevenueLearningRecord.from_task_result(result)
        data = record.to_dict()
        self.assertEqual(set(data.keys()), {
            "learning_id", "task_id", "opportunity_id", "result_status",
            "success", "output", "error", "created_at", "metadata",
        })

    def test_to_dict_values_match_record(self):
        result = _make_task_result(status=STATUS_FAILED, error="boom")
        record = RevenueLearningRecord.from_task_result(result)
        data = record.to_dict()
        self.assertEqual(data["task_id"], record.task_id)
        self.assertEqual(data["opportunity_id"], record.opportunity_id)
        self.assertEqual(data["result_status"], STATUS_FAILED)
        self.assertEqual(data["success"], False)
        self.assertEqual(data["error"], "boom")

    def test_to_dict_output_is_an_independent_copy(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 1})
        record = RevenueLearningRecord.from_task_result(result)
        data = record.to_dict()
        data["output"]["units"] = 999
        self.assertEqual(record.output, {"units": 1})

    def test_to_dict_metadata_is_an_independent_copy(self):
        record = _make_learning_record(metadata={"note": "ok"})
        data = record.to_dict()
        data["metadata"]["note"] = "changed"
        self.assertEqual(record.metadata, {"note": "ok"})


# ----------------------------------------------------------------------
# 8. Original RevenueTaskResult remains unchanged
# ----------------------------------------------------------------------
class TestOriginalResultUnchanged(unittest.TestCase):
    def test_from_task_result_does_not_modify_the_result(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 3}, metadata={"note": "ok"})
        before = result.to_dict()
        RevenueLearningRecord.from_task_result(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_from_task_result_does_not_modify_a_failed_result(self):
        result = _make_task_result(status=STATUS_FAILED, error="disk full")
        before = result.to_dict()
        RevenueLearningRecord.from_task_result(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_mutating_the_returned_record_does_not_affect_the_result(self):
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 3})
        record = RevenueLearningRecord.from_task_result(result)
        record.output["units"] = 42
        record.metadata["extra"] = "changed"
        self.assertEqual(result.output, {"units": 3})
        self.assertEqual(result.metadata, {})


if __name__ == "__main__":
    unittest.main()
