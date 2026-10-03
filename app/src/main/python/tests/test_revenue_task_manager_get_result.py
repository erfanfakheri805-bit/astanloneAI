"""
Tests for RevenueTaskManager.get_task_result() and
RevenueTaskManager.has_task_result() (financial/revenue_task_manager.py).

Covers: a task with a COMPLETED result, a task with a FAILED result, a
task with no result, a missing task, invalid task IDs,
has_task_result() true/false cases, result retrieval correctness, and
that neither method ever modifies the task or this manager's own
storage.

Both methods are purely read-only thin wrappers over get_task() plus
RevenueTask's own get_result()/has_result() - this stage never
creates a result, never changes a task's status, and never executes,
retries, or dispatches anything.

Run directly:
    python -m unittest tests.test_revenue_task_manager_get_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task import STATUS_PENDING, STATUS_READY
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
# 1. Existing task with a COMPLETED result
# ----------------------------------------------------------------------
class TestExistingTaskWithCompletedResult(unittest.TestCase):
    def test_get_task_result_returns_the_result(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 3}
        )
        result = manager.get_task_result(task.task_id)
        self.assertIsInstance(result, RevenueTaskResult)
        self.assertEqual(result.status, RESULT_STATUS_COMPLETED)
        self.assertEqual(result.output, {"units": 3})

    def test_result_is_successful(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        result = manager.get_task_result(task.task_id)
        self.assertTrue(result.is_successful())


# ----------------------------------------------------------------------
# 2. Existing task with a FAILED result
# ----------------------------------------------------------------------
class TestExistingTaskWithFailedResult(unittest.TestCase):
    def test_get_task_result_returns_the_result(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_FAILED, error={"reason": "timeout"}
        )
        result = manager.get_task_result(task.task_id)
        self.assertIsInstance(result, RevenueTaskResult)
        self.assertEqual(result.status, RESULT_STATUS_FAILED)
        self.assertEqual(result.error, {"reason": "timeout"})

    def test_result_is_failed(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_FAILED)
        result = manager.get_task_result(task.task_id)
        self.assertTrue(result.is_failed())


# ----------------------------------------------------------------------
# 3. Task without a result
# ----------------------------------------------------------------------
class TestTaskWithoutResult(unittest.TestCase):
    def test_get_task_result_returns_none(self):
        manager, task = _make_manager_with_task()
        self.assertIsNone(manager.get_task_result(task.task_id))

    def test_has_task_result_is_false(self):
        manager, task = _make_manager_with_task()
        self.assertFalse(manager.has_task_result(task.task_id))


# ----------------------------------------------------------------------
# 4. Missing task
# ----------------------------------------------------------------------
class TestMissingTask(unittest.TestCase):
    def test_get_task_result_returns_none_for_unknown_id(self):
        manager = RevenueTaskManager()
        self.assertIsNone(manager.get_task_result("no-such-task"))

    def test_has_task_result_returns_false_for_unknown_id(self):
        manager = RevenueTaskManager()
        self.assertFalse(manager.has_task_result("no-such-task"))

    def test_neither_method_raises_for_missing_task(self):
        manager = RevenueTaskManager()
        try:
            manager.get_task_result("no-such-task")
            manager.has_task_result("no-such-task")
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 5. Invalid task ID
# ----------------------------------------------------------------------
class TestInvalidTaskId(unittest.TestCase):
    def test_none_task_id(self):
        manager = RevenueTaskManager()
        self.assertIsNone(manager.get_task_result(None))
        self.assertFalse(manager.has_task_result(None))

    def test_empty_string_task_id(self):
        manager = RevenueTaskManager()
        self.assertIsNone(manager.get_task_result(""))
        self.assertFalse(manager.has_task_result(""))

    def test_non_string_task_id(self):
        manager = RevenueTaskManager()
        self.assertIsNone(manager.get_task_result(12345))
        self.assertFalse(manager.has_task_result(12345))


# ----------------------------------------------------------------------
# 6. has_task_result() true/false cases
# ----------------------------------------------------------------------
class TestHasTaskResult(unittest.TestCase):
    def test_true_after_recording_completed(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        self.assertTrue(manager.has_task_result(task.task_id))

    def test_true_after_recording_failed(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_FAILED)
        self.assertTrue(manager.has_task_result(task.task_id))

    def test_false_before_recording(self):
        manager, task = _make_manager_with_task()
        self.assertFalse(manager.has_task_result(task.task_id))

    def test_false_after_rejected_recording(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, "BOGUS")
        self.assertFalse(manager.has_task_result(task.task_id))


# ----------------------------------------------------------------------
# 7. Result retrieval correctness
# ----------------------------------------------------------------------
class TestResultRetrievalCorrectness(unittest.TestCase):
    def test_result_task_id_and_opportunity_id_match(self):
        manager, task = _make_manager_with_task(opportunity_id="opp-xyz")
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        result = manager.get_task_result(task.task_id)
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.opportunity_id, "opp-xyz")

    def test_result_id_matches_record_task_result_output(self):
        manager, task = _make_manager_with_task()
        outcome = manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        result = manager.get_task_result(task.task_id)
        self.assertEqual(result.result_id, outcome["result_id"])

    def test_metadata_is_preserved(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, metadata={"source": "manual"}
        )
        result = manager.get_task_result(task.task_id)
        self.assertEqual(result.metadata, {"source": "manual"})

    def test_mutating_returned_result_does_not_affect_manager(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(
            task.task_id, RESULT_STATUS_COMPLETED, output={"units": 3}
        )
        result = manager.get_task_result(task.task_id)
        result.output["units"] = 999
        result.metadata["extra"] = "changed"

        fresh = manager.get_task_result(task.task_id)
        self.assertEqual(fresh.output, {"units": 3})
        self.assertEqual(fresh.metadata, {})

    def test_two_calls_return_independent_objects(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        first = manager.get_task_result(task.task_id)
        second = manager.get_task_result(task.task_id)
        self.assertIsNot(first, second)
        self.assertEqual(first.result_id, second.result_id)


# ----------------------------------------------------------------------
# 8. Task state remains unchanged
# ----------------------------------------------------------------------
class TestTaskStateUnchanged(unittest.TestCase):
    def test_get_task_result_does_not_change_status(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        manager.get_task_result(task.task_id)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_PENDING)

    def test_has_task_result_does_not_change_status(self):
        manager, task = _make_manager_with_task()
        manager.has_task_result(task.task_id)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_PENDING)

    def test_repeated_calls_do_not_change_task_fields(self):
        manager, task = _make_manager_with_task(
            status=STATUS_READY, dependencies=["task-a"], metadata={"k": "v"}
        )
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        manager.get_task_result(task.task_id)
        manager.has_task_result(task.task_id)
        stored = manager.get_task(task.task_id)
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(stored.dependencies, ["task-a"])
        self.assertEqual(stored.metadata, {"k": "v"})

    def test_result_still_attached_after_reads(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        manager.get_task_result(task.task_id)
        manager.has_task_result(task.task_id)
        self.assertTrue(manager.has_task_result(task.task_id))


# ----------------------------------------------------------------------
# 9. Manager state remains unchanged
# ----------------------------------------------------------------------
class TestManagerStateUnchanged(unittest.TestCase):
    def test_task_count_unaffected_by_reads(self):
        manager, task = _make_manager_with_task()
        manager.record_task_result(task.task_id, RESULT_STATUS_COMPLETED)
        before = len(manager.get_all())
        manager.get_task_result(task.task_id)
        manager.has_task_result(task.task_id)
        manager.get_task_result("no-such-task")
        manager.has_task_result("no-such-task")
        after = len(manager.get_all())
        self.assertEqual(before, after)

    def test_no_new_task_created_for_missing_id(self):
        manager = RevenueTaskManager()
        manager.get_task_result("phantom-task")
        manager.has_task_result("phantom-task")
        self.assertIsNone(manager.get_task("phantom-task"))
        self.assertEqual(manager.get_all(), [])

    def test_other_tasks_unaffected(self):
        manager, task_one = _make_manager_with_task(task_id="task-a")
        task_two = manager.create_task(opportunity_id="opp-2", name="Second task")
        manager.record_task_result(task_one.task_id, RESULT_STATUS_COMPLETED)

        manager.get_task_result(task_two.task_id)
        manager.has_task_result(task_two.task_id)

        self.assertFalse(manager.has_task_result(task_two.task_id))
        self.assertTrue(manager.has_task_result(task_one.task_id))


if __name__ == "__main__":
    unittest.main()
