"""
Tests for RevenueTaskManager.record_task_result()
(financial/revenue_task_manager.py).

Covers: a successful COMPLETED result, a successful FAILED result, a
missing task, an invalid result status, duplicate-result protection,
that the recorded result carries the correct task_id/opportunity_id,
output/error/metadata handling, that the result is actually attached
to the stored task (not just echoed back in the return value), and
that the task's own status is never changed by recording a result.

This stage only records an already-finished outcome - it never calls
transition_to(), complete_task(), or fail_task(), and it is not wired
into task execution or the learning system.

Run directly:
    python -m unittest tests.test_revenue_task_manager_record_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task import (
    STATUS_PENDING,
    STATUS_READY,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from financial.revenue_task_manager import RevenueTaskManager
from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED as RESULT_STATUS_COMPLETED,
    STATUS_FAILED as RESULT_STATUS_FAILED,
)


def _make_manager_with_task(**overrides):
    manager = RevenueTaskManager()
    fields = dict(
        opportunity_id="opp-test-1",
        name="Draft the store listing",
        description="Write the app store listing copy for the opportunity.",
    )
    fields.update(overrides)
    task = manager.create_task(**fields)
    return manager, task


# ----------------------------------------------------------------------
# 1. Successful COMPLETED result
# ----------------------------------------------------------------------
class TestSuccessfulCompletedResult(unittest.TestCase):
    def test_records_a_completed_result(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 3}
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["recorded"])
        self.assertEqual(result["status"], RESULT_STATUS_COMPLETED)
        self.assertIsNotNone(result["result_id"])

    def test_returns_a_string_result_id(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        self.assertIsInstance(result["result_id"], str)
        self.assertTrue(result["result_id"].strip())


# ----------------------------------------------------------------------
# 2. Successful FAILED result
# ----------------------------------------------------------------------
class TestSuccessfulFailedResult(unittest.TestCase):
    def test_records_a_failed_result(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(
            task.task_id, RESULT_STATUS_FAILED, error={"reason": "timeout"}
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["recorded"])
        self.assertEqual(result["status"], RESULT_STATUS_FAILED)
        self.assertIsNotNone(result["result_id"])


# ----------------------------------------------------------------------
# 3. Missing task
# ----------------------------------------------------------------------
class TestMissingTask(unittest.TestCase):
    def test_unknown_task_id_is_rejected(self):
        manager = RevenueTaskManager()
        result = manager.record_task_result("no-such-task", RESULT_STATUS_COMPLETED)
        self.assertFalse(result["success"])
        self.assertFalse(result["recorded"])
        self.assertIsNone(result["result_id"])
        self.assertIsNone(result["opportunity_id"])
        self.assertEqual(result["task_id"], "no-such-task")
        self.assertEqual(result["error"], "task_not_found")

    def test_never_raises_for_missing_task(self):
        manager = RevenueTaskManager()
        try:
            manager.record_task_result("no-such-task", RESULT_STATUS_COMPLETED)
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"record_task_result raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 4. Invalid result status
# ----------------------------------------------------------------------
class TestInvalidResultStatus(unittest.TestCase):
    def test_bogus_status_is_rejected(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(task.task_id, "BOGUS")
        self.assertFalse(result["success"])
        self.assertFalse(result["recorded"])
        self.assertIsNone(result["result_id"])
        self.assertEqual(result["error"], "invalid_status")

    def test_task_status_string_is_rejected_as_result_status(self):
        # RevenueTask's own STATUS_PENDING/STATUS_IN_PROGRESS etc. are
        # not valid RevenueTaskResult statuses - only COMPLETED/FAILED
        # are (RevenueTaskResult.ALL_STATUSES).
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(task.task_id, STATUS_PENDING)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_status")

    def test_none_status_is_rejected(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(task.task_id, None)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_status")

    def test_no_result_is_attached_after_invalid_status(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, "BOGUS")
        stored = manager.get_task(task.task_id)
        self.assertFalse(stored.has_result())


# ----------------------------------------------------------------------
# 5. Duplicate result protection
# ----------------------------------------------------------------------
class TestDuplicateResultProtection(unittest.TestCase):
    def test_second_call_is_rejected(self):
        manager, task = _make_manager_with_task()
        first = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        second = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        self.assertTrue(first["success"])
        self.assertFalse(second["success"])
        self.assertFalse(second["recorded"])
        self.assertIsNone(second["result_id"])
        self.assertEqual(second["error"], "result_already_recorded")

    def test_second_call_with_failed_status_is_also_rejected(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        second = manager.record_task_result(task.task_id, RESULT_STATUS_FAILED)
        self.assertFalse(second["success"])
        self.assertEqual(second["error"], "result_already_recorded")

    def test_original_result_is_not_overwritten(self):
        manager, task = _make_manager_with_task()
        first = manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 1}
        )
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 999}
        )
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().result_id, first["result_id"])
        self.assertEqual(stored.get_result().output, {"units": 1})


# ----------------------------------------------------------------------
# 6. Correct task_id
# ----------------------------------------------------------------------
class TestCorrectTaskId(unittest.TestCase):
    def test_result_task_id_matches_the_task(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        self.assertEqual(result["task_id"], task.task_id)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().task_id, task.task_id)


# ----------------------------------------------------------------------
# 7. Correct opportunity_id
# ----------------------------------------------------------------------
class TestCorrectOpportunityId(unittest.TestCase):
    def test_result_opportunity_id_matches_the_task(self):
        manager, task = _make_manager_with_task(opportunity_id="opp-xyz")
        result = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        self.assertEqual(result["opportunity_id"], "opp-xyz")
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().opportunity_id, "opp-xyz")


# ----------------------------------------------------------------------
# 8. Output handling
# ----------------------------------------------------------------------
class TestOutputHandling(unittest.TestCase):
    def test_output_is_stored_on_the_result(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 5}
        )
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().output, {"units": 5})

    def test_output_defaults_to_none(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        self.assertIsNone(stored.get_result().output)

    def test_unsafe_output_is_rejected(self):
        manager, task = _make_manager_with_task()

        class NotStructuredData:
            pass

        result = manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output=NotStructuredData()
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_result_data")
        stored = manager.get_task(task.task_id)
        self.assertFalse(stored.has_result())


# ----------------------------------------------------------------------
# 9. Error handling
# ----------------------------------------------------------------------
class TestErrorHandling(unittest.TestCase):
    def test_error_is_stored_on_the_result(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_FAILED, error={"reason": "timeout"}
        )
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().error, {"reason": "timeout"})

    def test_error_defaults_to_none(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_FAILED)
        stored = manager.get_task(task.task_id)
        self.assertIsNone(stored.get_result().error)

    def test_unsafe_error_is_rejected(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(
            task.task_id, RESULT_STATUS_FAILED, error=lambda: "bad"
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_result_data")
        stored = manager.get_task(task.task_id)
        self.assertFalse(stored.has_result())


# ----------------------------------------------------------------------
# 10. Metadata handling
# ----------------------------------------------------------------------
class TestMetadataHandling(unittest.TestCase):
    def test_metadata_is_stored_on_the_result(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, metadata={"source": "manual"}
        )
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().metadata, {"source": "manual"})

    def test_metadata_defaults_to_empty_dict(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().metadata, {})

    def test_unsafe_metadata_is_rejected(self):
        manager, task = _make_manager_with_task()
        result = manager.record_task_result(
            task.task_id,
            RESULT_STATUS_COMPLETED,
            metadata={"bad": object()},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_result_data")
        stored = manager.get_task(task.task_id)
        self.assertFalse(stored.has_result())


# ----------------------------------------------------------------------
# 11. Result is actually attached to the task
# ----------------------------------------------------------------------
class TestResultActuallyAttached(unittest.TestCase):
    def test_stored_task_has_result_after_recording(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        self.assertTrue(stored.has_result())
        self.assertIsInstance(stored.get_result(), RevenueTaskResult)

    def test_attached_result_matches_returned_result_id(self):
        manager, task = _make_manager_with_task()
        outcome = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.get_result().result_id, outcome["result_id"])

    def test_attachment_persists_across_separate_get_task_calls(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        first_read = manager.get_task(task.task_id)
        second_read = manager.get_task(task.task_id)
        self.assertTrue(first_read.has_result())
        self.assertTrue(second_read.has_result())

    def test_no_result_attached_when_task_missing(self):
        manager = RevenueTaskManager()
        manager.record_task_result("no-such-task", RESULT_STATUS_COMPLETED)
        self.assertIsNone(manager.get_task("no-such-task"))


# ----------------------------------------------------------------------
# 12. Task status remains unchanged
# ----------------------------------------------------------------------
class TestTaskStatusUnchanged(unittest.TestCase):
    def test_pending_task_status_unchanged_after_completed_result(self):
        manager, task = _make_manager_with_task()
        self.assertEqual(task.status, STATUS_PENDING)
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_PENDING)

    def test_in_progress_task_status_unchanged_after_failed_result(self):
        manager, task = _make_manager_with_task(status=STATUS_READY)
        manager.start_task(task.task_id)
        in_progress_task = manager.get_task(task.task_id)
        self.assertEqual(in_progress_task.status, STATUS_IN_PROGRESS)

        manager.record_task_result(task.task_id, RESULT_STATUS_FAILED)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_IN_PROGRESS)

    def test_completed_result_does_not_force_completed_status(self):
        manager, task = _make_manager_with_task(status=STATUS_READY)
        manager.start_task(task.task_id)
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        stored = manager.get_task(task.task_id)
        # record_task_result never calls transition_to(); the task's
        # status stays IN_PROGRESS until a separate, explicit
        # complete_task() call.
        self.assertEqual(stored.status, STATUS_IN_PROGRESS)

    def test_status_unchanged_after_rejected_call(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, "BOGUS")
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_PENDING)

    def test_does_not_call_complete_task_or_fail_task(self):
        manager, task = _make_manager_with_task(status=STATUS_READY)
        manager.start_task(task.task_id)
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        # If this had internally called complete_task(), the status
        # would now be COMPLETED instead of IN_PROGRESS.
        stored = manager.get_task(task.task_id)
        self.assertNotEqual(stored.status, STATUS_COMPLETED)
        self.assertNotEqual(stored.status, STATUS_FAILED)
        self.assertEqual(stored.status, STATUS_IN_PROGRESS)


if __name__ == "__main__":
    unittest.main()
