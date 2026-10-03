"""
Tests for RevenueTask's result attachment
(financial/revenue_task.py: set_result()/get_result()/has_result()/
clear_result(), plus the resulting "result" key in to_dict()).

Covers: a task with no result attached, attaching a valid COMPLETED
result, attaching a valid FAILED result, rejecting a result with a
mismatched task_id, rejecting a result with a mismatched
opportunity_id, rejecting a non-RevenueTaskResult object,
get_result(), has_result(), clear_result(), serialization via
to_dict(), that a task's status is never changed by any of this, and
that the attached result object itself is never modified.

This stage is standalone - set_result() never creates a result, never
attaches one automatically on completion/failure, and is not wired
into RevenueTaskManager, an execution stage, or the learning system.

Run directly:
    python -m unittest tests.test_revenue_task_result_attachment -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task import (
    RevenueTask,
    STATUS_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED as RESULT_STATUS_COMPLETED,
    STATUS_FAILED as RESULT_STATUS_FAILED,
)


def _make_task(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        name="Draft the store listing",
        description="Write the app store listing copy for the opportunity.",
    )
    fields.update(overrides)
    return RevenueTask(**fields)


def _make_result(**overrides):
    fields = dict(
        result_id="result-test-1",
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        status=RESULT_STATUS_COMPLETED,
    )
    fields.update(overrides)
    return RevenueTaskResult(**fields)


# ----------------------------------------------------------------------
# 1. Task without a result
# ----------------------------------------------------------------------
class TestTaskWithoutResult(unittest.TestCase):
    def test_new_task_has_no_result(self):
        task = _make_task()
        self.assertIsNone(task.get_result())
        self.assertFalse(task.has_result())

    def test_to_dict_result_is_none_when_unattached(self):
        task = _make_task()
        self.assertIsNone(task.to_dict()["result"])


# ----------------------------------------------------------------------
# 2. Valid COMPLETED result
# ----------------------------------------------------------------------
class TestValidCompletedResult(unittest.TestCase):
    def test_attaching_a_valid_completed_result_succeeds(self):
        task = _make_task()
        result = _make_result(status=RESULT_STATUS_COMPLETED, output={"ok": True})
        self.assertTrue(task.set_result(result))
        self.assertTrue(task.has_result())
        self.assertIs(task.get_result(), result)

    def test_completed_result_reports_successful(self):
        task = _make_task()
        result = _make_result(status=RESULT_STATUS_COMPLETED)
        task.set_result(result)
        self.assertTrue(task.get_result().is_successful())


# ----------------------------------------------------------------------
# 3. Valid FAILED result
# ----------------------------------------------------------------------
class TestValidFailedResult(unittest.TestCase):
    def test_attaching_a_valid_failed_result_succeeds(self):
        task = _make_task()
        result = _make_result(
            result_id="result-test-2",
            status=RESULT_STATUS_FAILED,
            error={"reason": "timeout"},
        )
        self.assertTrue(task.set_result(result))
        self.assertTrue(task.has_result())
        self.assertIs(task.get_result(), result)

    def test_failed_result_reports_failed(self):
        task = _make_task()
        result = _make_result(status=RESULT_STATUS_FAILED)
        task.set_result(result)
        self.assertTrue(task.get_result().is_failed())


# ----------------------------------------------------------------------
# 4. Mismatched task_id
# ----------------------------------------------------------------------
class TestMismatchedTaskId(unittest.TestCase):
    def test_mismatched_task_id_is_rejected(self):
        task = _make_task(task_id="task-test-1")
        result = _make_result(task_id="task-other")
        self.assertFalse(task.set_result(result))
        self.assertFalse(task.has_result())
        self.assertIsNone(task.get_result())

    def test_mismatched_task_id_does_not_replace_existing_result(self):
        task = _make_task()
        good_result = _make_result()
        task.set_result(good_result)
        bad_result = _make_result(result_id="result-bad", task_id="task-other")
        self.assertFalse(task.set_result(bad_result))
        self.assertIs(task.get_result(), good_result)


# ----------------------------------------------------------------------
# 5. Mismatched opportunity_id
# ----------------------------------------------------------------------
class TestMismatchedOpportunityId(unittest.TestCase):
    def test_mismatched_opportunity_id_is_rejected(self):
        task = _make_task(opportunity_id="opp-test-1")
        result = _make_result(opportunity_id="opp-other")
        self.assertFalse(task.set_result(result))
        self.assertFalse(task.has_result())
        self.assertIsNone(task.get_result())

    def test_mismatched_opportunity_id_does_not_replace_existing_result(self):
        task = _make_task()
        good_result = _make_result()
        task.set_result(good_result)
        bad_result = _make_result(result_id="result-bad", opportunity_id="opp-other")
        self.assertFalse(task.set_result(bad_result))
        self.assertIs(task.get_result(), good_result)


# ----------------------------------------------------------------------
# 6. Invalid result object
# ----------------------------------------------------------------------
class TestInvalidResultObject(unittest.TestCase):
    def test_none_is_rejected(self):
        task = _make_task()
        self.assertFalse(task.set_result(None))
        self.assertFalse(task.has_result())

    def test_plain_dict_is_rejected(self):
        task = _make_task()
        fake = {
            "task_id": task.task_id,
            "opportunity_id": task.opportunity_id,
            "status": RESULT_STATUS_COMPLETED,
        }
        self.assertFalse(task.set_result(fake))
        self.assertFalse(task.has_result())

    def test_string_is_rejected(self):
        task = _make_task()
        self.assertFalse(task.set_result("not a result"))
        self.assertFalse(task.has_result())

    def test_revenue_task_instance_is_rejected(self):
        # Another RevenueTask is not a RevenueTaskResult, even though
        # it shares task_id/opportunity_id-shaped attributes.
        task = _make_task()
        other_task = _make_task(task_id="task-test-1")
        self.assertFalse(task.set_result(other_task))
        self.assertFalse(task.has_result())


# ----------------------------------------------------------------------
# 7. get_result()
# ----------------------------------------------------------------------
class TestGetResult(unittest.TestCase):
    def test_returns_none_before_attachment(self):
        task = _make_task()
        self.assertIsNone(task.get_result())

    def test_returns_the_exact_attached_object(self):
        task = _make_task()
        result = _make_result()
        task.set_result(result)
        self.assertIs(task.get_result(), result)

    def test_returns_none_after_clear(self):
        task = _make_task()
        task.set_result(_make_result())
        task.clear_result()
        self.assertIsNone(task.get_result())


# ----------------------------------------------------------------------
# 8. has_result()
# ----------------------------------------------------------------------
class TestHasResult(unittest.TestCase):
    def test_false_before_attachment(self):
        task = _make_task()
        self.assertFalse(task.has_result())

    def test_true_after_valid_attachment(self):
        task = _make_task()
        task.set_result(_make_result())
        self.assertTrue(task.has_result())

    def test_false_after_rejected_attachment(self):
        task = _make_task()
        task.set_result(_make_result(task_id="task-other"))
        self.assertFalse(task.has_result())

    def test_false_after_clear(self):
        task = _make_task()
        task.set_result(_make_result())
        task.clear_result()
        self.assertFalse(task.has_result())


# ----------------------------------------------------------------------
# 9. clear_result()
# ----------------------------------------------------------------------
class TestClearResult(unittest.TestCase):
    def test_clears_an_attached_result(self):
        task = _make_task()
        task.set_result(_make_result())
        task.clear_result()
        self.assertIsNone(task.get_result())
        self.assertFalse(task.has_result())

    def test_safe_to_call_when_no_result_attached(self):
        task = _make_task()
        # Should not raise.
        task.clear_result()
        self.assertIsNone(task.get_result())

    def test_clear_does_not_change_status(self):
        task = _make_task(status=STATUS_COMPLETED)
        task.set_result(_make_result())
        task.clear_result()
        self.assertEqual(task.status, STATUS_COMPLETED)

    def test_clear_does_not_affect_other_fields(self):
        task = _make_task(
            status=STATUS_IN_PROGRESS,
            priority="HIGH",
            dependencies=["task-a"],
            metadata={"k": "v"},
        )
        task.set_result(_make_result())
        task.clear_result()
        self.assertEqual(task.status, STATUS_IN_PROGRESS)
        self.assertEqual(task.priority, "HIGH")
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"k": "v"})


# ----------------------------------------------------------------------
# 10. Serialization (to_dict())
# ----------------------------------------------------------------------
class TestSerialization(unittest.TestCase):
    def test_to_dict_includes_result_as_dict_when_attached(self):
        task = _make_task()
        result = _make_result(output={"units": 3})
        task.set_result(result)
        data = task.to_dict()
        self.assertEqual(data["result"], result.to_dict())

    def test_to_dict_result_is_none_when_not_attached(self):
        task = _make_task()
        self.assertIsNone(task.to_dict()["result"])

    def test_to_dict_result_is_a_safe_copy(self):
        task = _make_task()
        result = _make_result(output={"units": 3})
        task.set_result(result)
        data = task.to_dict()
        data["result"]["output"]["units"] = 999
        # Mutating the returned dict must never affect the attached
        # result's own internal state.
        self.assertEqual(task.get_result().output, {"units": 3})

    def test_to_dict_other_fields_unaffected_by_result(self):
        task = _make_task(status=STATUS_COMPLETED)
        task.set_result(_make_result())
        data = task.to_dict()
        self.assertEqual(data["task_id"], task.task_id)
        self.assertEqual(data["opportunity_id"], task.opportunity_id)
        self.assertEqual(data["status"], STATUS_COMPLETED)


# ----------------------------------------------------------------------
# 11. Task status is unaffected by result attachment
# ----------------------------------------------------------------------
class TestStatusUnchangedByResultAttachment(unittest.TestCase):
    def test_set_result_does_not_change_pending_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.set_result(_make_result())
        self.assertEqual(task.status, STATUS_PENDING)

    def test_set_result_does_not_change_in_progress_status(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        task.set_result(_make_result(status=RESULT_STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_IN_PROGRESS)

    def test_failed_result_does_not_force_failed_status(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        task.set_result(_make_result(status=RESULT_STATUS_FAILED))
        self.assertEqual(task.status, STATUS_IN_PROGRESS)

    def test_rejected_result_does_not_change_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.set_result(_make_result(task_id="task-other"))
        self.assertEqual(task.status, STATUS_PENDING)


# ----------------------------------------------------------------------
# 12. The attached result object is never modified
# ----------------------------------------------------------------------
class TestResultObjectNotModified(unittest.TestCase):
    def test_set_result_does_not_modify_the_result(self):
        task = _make_task()
        result = _make_result(output={"units": 3}, metadata={"note": "ok"})
        before = result.to_dict()
        task.set_result(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_get_result_does_not_modify_the_result(self):
        task = _make_task()
        result = _make_result()
        task.set_result(result)
        before = result.to_dict()
        task.get_result()
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_rejected_result_is_left_untouched(self):
        task = _make_task()
        result = _make_result(task_id="task-other")
        before = result.to_dict()
        task.set_result(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_clear_result_does_not_modify_the_detached_result(self):
        task = _make_task()
        result = _make_result()
        task.set_result(result)
        before = result.to_dict()
        task.clear_result()
        after = result.to_dict()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
