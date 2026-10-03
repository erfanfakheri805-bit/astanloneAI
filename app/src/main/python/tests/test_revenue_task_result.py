"""
Tests for the RevenueTaskResult model (financial/revenue_task_result.py).

Covers: valid COMPLETED/FAILED results, is_valid() validation
failures (bad result_id/task_id/opportunity_id/status), output/error/
metadata handling, is_successful()/is_failed(), and to_dict() -
including that to_dict() never exposes a mutable reference to this
record's own internal state. This stage is standalone - it is not
wired into RevenueTaskManager, task execution, or the learning system
yet.

Run directly:
    python -m unittest tests.test_revenue_task_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED,
    STATUS_FAILED,
    ALL_STATUSES,
)


def _make_result(**overrides):
    fields = dict(
        result_id="result-test-1",
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        status=STATUS_COMPLETED,
    )
    fields.update(overrides)
    return RevenueTaskResult(**fields)


# ----------------------------------------------------------------------
# 1. Valid COMPLETED result
# ----------------------------------------------------------------------
class TestValidCompletedResult(unittest.TestCase):
    def test_valid_completed_result_has_expected_fields_and_is_valid(self):
        result = _make_result(status=STATUS_COMPLETED, output={"pages": 3})

        self.assertEqual(result.result_id, "result-test-1")
        self.assertEqual(result.task_id, "task-test-1")
        self.assertEqual(result.opportunity_id, "opp-test-1")
        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.output, {"pages": 3})
        self.assertIsNone(result.error)
        self.assertEqual(result.metadata, {})
        self.assertTrue(result.created_at)
        self.assertTrue(result.is_valid())

    def test_completed_result_without_output_is_still_valid(self):
        result = _make_result(status=STATUS_COMPLETED)
        self.assertIsNone(result.output)
        self.assertTrue(result.is_valid())


# ----------------------------------------------------------------------
# 2. Valid FAILED result
# ----------------------------------------------------------------------
class TestValidFailedResult(unittest.TestCase):
    def test_valid_failed_result_has_expected_fields_and_is_valid(self):
        result = _make_result(
            status=STATUS_FAILED,
            error={"type": "TimeoutError", "message": "Upstream call timed out"},
        )

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(
            result.error, {"type": "TimeoutError", "message": "Upstream call timed out"}
        )
        self.assertIsNone(result.output)
        self.assertTrue(result.is_valid())

    def test_failed_result_without_error_is_still_valid(self):
        result = _make_result(status=STATUS_FAILED)
        self.assertIsNone(result.error)
        self.assertTrue(result.is_valid())


# ----------------------------------------------------------------------
# 3. Invalid result_id
# ----------------------------------------------------------------------
class TestInvalidResultId(unittest.TestCase):
    def test_invalid_result_ids_are_rejected(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertFalse(_make_result(result_id=bad_id).is_valid())

    def test_construction_never_raises_for_invalid_result_id(self):
        result = _make_result(result_id="")
        self.assertEqual(result.result_id, "")
        self.assertFalse(result.is_valid())


# ----------------------------------------------------------------------
# 4. Invalid task_id
# ----------------------------------------------------------------------
class TestInvalidTaskId(unittest.TestCase):
    def test_invalid_task_ids_are_rejected(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertFalse(_make_result(task_id=bad_id).is_valid())

    def test_construction_never_raises_for_invalid_task_id(self):
        result = _make_result(task_id=None)
        self.assertIsNone(result.task_id)
        self.assertFalse(result.is_valid())


# ----------------------------------------------------------------------
# 5. Invalid opportunity_id
# ----------------------------------------------------------------------
class TestInvalidOpportunityId(unittest.TestCase):
    def test_invalid_opportunity_ids_are_rejected(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertFalse(_make_result(opportunity_id=bad_id).is_valid())

    def test_construction_never_raises_for_invalid_opportunity_id(self):
        result = _make_result(opportunity_id="")
        self.assertEqual(result.opportunity_id, "")
        self.assertFalse(result.is_valid())


# ----------------------------------------------------------------------
# 6. Invalid status
# ----------------------------------------------------------------------
class TestInvalidStatus(unittest.TestCase):
    def test_all_supported_statuses_are_valid(self):
        for status in ALL_STATUSES:
            self.assertTrue(_make_result(status=status).is_valid())

    def test_unsupported_status_values_are_rejected(self):
        for bad_status in ("PENDING", "IN_PROGRESS", "completed", "", None, 123):
            self.assertFalse(_make_result(status=bad_status).is_valid())

    def test_construction_never_raises_for_invalid_status(self):
        result = _make_result(status="NOT_A_STATUS")
        self.assertEqual(result.status, "NOT_A_STATUS")
        self.assertFalse(result.is_valid())

    def test_only_completed_and_failed_are_supported(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_COMPLETED, STATUS_FAILED})


# ----------------------------------------------------------------------
# 7. Output handling
# ----------------------------------------------------------------------
class TestOutputHandling(unittest.TestCase):
    def test_none_output_is_valid(self):
        self.assertTrue(_make_result(output=None).is_valid())

    def test_structured_output_is_valid(self):
        output = {"summary": "Draft written", "links": ["a", "b"], "count": 2}
        result = _make_result(output=output)
        self.assertEqual(result.output, output)
        self.assertTrue(result.is_valid())

    def test_unsafe_output_is_invalid(self):
        class Unsafe:
            pass

        result = _make_result(output=Unsafe())
        self.assertFalse(result.is_valid())

    def test_output_is_never_executed_or_interpreted(self):
        # A string that looks like code is still just stored data.
        output = "os.system('rm -rf /')"
        result = _make_result(output=output)
        self.assertEqual(result.output, output)
        self.assertTrue(result.is_valid())


# ----------------------------------------------------------------------
# 8. Error handling
# ----------------------------------------------------------------------
class TestErrorHandling(unittest.TestCase):
    def test_none_error_is_valid(self):
        self.assertTrue(_make_result(status=STATUS_FAILED, error=None).is_valid())

    def test_structured_error_is_valid(self):
        error = {"type": "ValueError", "message": "bad input", "retriable": False}
        result = _make_result(status=STATUS_FAILED, error=error)
        self.assertEqual(result.error, error)
        self.assertTrue(result.is_valid())

    def test_unsafe_error_is_invalid(self):
        class Unsafe:
            pass

        result = _make_result(status=STATUS_FAILED, error=Unsafe())
        self.assertFalse(result.is_valid())

    def test_error_is_never_executed_or_interpreted(self):
        error = "__import__('os').system('echo hi')"
        result = _make_result(status=STATUS_FAILED, error=error)
        self.assertEqual(result.error, error)
        self.assertTrue(result.is_valid())


# ----------------------------------------------------------------------
# 9. Metadata handling
# ----------------------------------------------------------------------
class TestMetadataHandling(unittest.TestCase):
    def test_metadata_defaults_to_empty_dict(self):
        result = _make_result(metadata=None)
        self.assertEqual(result.metadata, {})
        self.assertTrue(result.is_valid())

    def test_structured_metadata_is_valid(self):
        metadata = {"reviewer": "auto-check", "score": 9, "tags": ["a", "b"]}
        result = _make_result(metadata=metadata)
        self.assertEqual(result.metadata, metadata)
        self.assertTrue(result.is_valid())

    def test_unsafe_metadata_is_invalid(self):
        class Unsafe:
            pass

        result = _make_result(metadata={"bad": Unsafe()})
        self.assertFalse(result.is_valid())

    def test_metadata_with_non_string_key_is_invalid(self):
        result = _make_result(metadata={1: "value"})
        self.assertFalse(result.is_valid())


# ----------------------------------------------------------------------
# 10. is_successful()
# ----------------------------------------------------------------------
class TestIsSuccessful(unittest.TestCase):
    def test_true_for_completed(self):
        self.assertTrue(_make_result(status=STATUS_COMPLETED).is_successful())

    def test_false_for_failed(self):
        self.assertFalse(_make_result(status=STATUS_FAILED).is_successful())

    def test_false_for_unrecognized_status(self):
        self.assertFalse(_make_result(status="SOMETHING_ELSE").is_successful())


# ----------------------------------------------------------------------
# 11. is_failed()
# ----------------------------------------------------------------------
class TestIsFailed(unittest.TestCase):
    def test_true_for_failed(self):
        self.assertTrue(_make_result(status=STATUS_FAILED).is_failed())

    def test_false_for_completed(self):
        self.assertFalse(_make_result(status=STATUS_COMPLETED).is_failed())

    def test_false_for_unrecognized_status(self):
        self.assertFalse(_make_result(status="SOMETHING_ELSE").is_failed())


# ----------------------------------------------------------------------
# 12. is_valid()
# ----------------------------------------------------------------------
class TestIsValid(unittest.TestCase):
    def test_fully_valid_result(self):
        result = _make_result(
            status=STATUS_COMPLETED,
            output={"done": True},
            metadata={"note": "ok"},
        )
        self.assertTrue(result.is_valid())

    def test_multiple_invalid_fields_still_reports_invalid(self):
        result = _make_result(result_id="", task_id="", status="BAD")
        self.assertFalse(result.is_valid())

    def test_is_valid_never_raises_on_malformed_input(self):
        result = RevenueTaskResult(
            result_id=None,
            task_id=None,
            opportunity_id=None,
            status=None,
            output=object(),
            error=object(),
            metadata={"bad": object()},
        )
        self.assertFalse(result.is_valid())


# ----------------------------------------------------------------------
# 13. to_dict()
# ----------------------------------------------------------------------
class TestToDict(unittest.TestCase):
    def test_to_dict_contains_expected_fields(self):
        result = _make_result(
            status=STATUS_COMPLETED,
            output={"pages": 3},
            metadata={"note": "ok"},
        )
        data = result.to_dict()
        self.assertEqual(
            data,
            {
                "result_id": "result-test-1",
                "task_id": "task-test-1",
                "opportunity_id": "opp-test-1",
                "status": STATUS_COMPLETED,
                "output": {"pages": 3},
                "error": None,
                "metadata": {"note": "ok"},
                "created_at": result.created_at,
            },
        )

    def test_to_dict_returns_a_new_dict_each_time(self):
        result = _make_result()
        self.assertIsNot(result.to_dict(), result.to_dict())


# ----------------------------------------------------------------------
# 14. to_dict() does not expose mutable internal state
# ----------------------------------------------------------------------
class TestToDictDoesNotExposeMutableState(unittest.TestCase):
    def test_mutating_returned_metadata_does_not_affect_result(self):
        result = _make_result(metadata={"note": "original"})
        data = result.to_dict()
        data["metadata"]["note"] = "tampered"
        data["metadata"]["new_key"] = "sneaky"
        self.assertEqual(result.metadata, {"note": "original"})

    def test_mutating_returned_output_does_not_affect_result(self):
        result = _make_result(output={"items": [1, 2, 3]})
        data = result.to_dict()
        data["output"]["items"].append(4)
        data["output"]["new_key"] = "sneaky"
        self.assertEqual(result.output, {"items": [1, 2, 3]})

    def test_mutating_returned_error_does_not_affect_result(self):
        result = _make_result(
            status=STATUS_FAILED, error={"details": ["first"]}
        )
        data = result.to_dict()
        data["error"]["details"].append("tampered")
        self.assertEqual(result.error, {"details": ["first"]})

    def test_mutating_returned_dict_does_not_affect_result(self):
        result = _make_result()
        data = result.to_dict()
        data["status"] = "TAMPERED"
        data["task_id"] = "tampered-task"
        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.task_id, "task-test-1")


if __name__ == "__main__":
    unittest.main()
