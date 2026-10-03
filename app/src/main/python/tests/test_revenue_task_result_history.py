"""
Tests for RevenueTaskResultHistory
(financial/revenue_task_result_history.py).

Covers: valid result recording, duplicate result IDs, get_all(),
get_for_task(), get_for_opportunity(), get_latest_for_task(),
count_for_task(), clear(), multiple results for one task, multiple
tasks in one opportunity, insertion order, invalid inputs, that
returned lists/results are independent from this history's own
internal state, and that the original RevenueTaskResult objects
handed to record() are never modified.

This stage only stores and retrieves already-built RevenueTaskResult
objects - it does not build a result itself, does not touch a
RevenueTask's status or its own attached result, and does not
execute, retry, or persist anything.

Run directly:
    python -m unittest tests.test_revenue_task_result_history -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task_result_history import RevenueTaskResultHistory
from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED,
    STATUS_FAILED,
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
# 1. Valid result recording
# ----------------------------------------------------------------------
class TestValidResultRecording(unittest.TestCase):
    def test_record_returns_the_same_result_on_success(self):
        history = RevenueTaskResultHistory()
        result = _make_result()
        self.assertIs(history.record(result), result)

    def test_record_increases_history_length(self):
        history = RevenueTaskResultHistory()
        self.assertEqual(len(history), 0)
        history.record(_make_result())
        self.assertEqual(len(history), 1)

    def test_completed_and_failed_results_both_accepted(self):
        history = RevenueTaskResultHistory()
        completed = _make_result(result_id="r-1", status=STATUS_COMPLETED)
        failed = _make_result(result_id="r-2", status=STATUS_FAILED)
        self.assertIs(history.record(completed), completed)
        self.assertIs(history.record(failed), failed)
        self.assertEqual(len(history), 2)


# ----------------------------------------------------------------------
# 2. Duplicate result IDs
# ----------------------------------------------------------------------
class TestDuplicateResultIds(unittest.TestCase):
    def test_second_record_with_same_id_is_rejected(self):
        history = RevenueTaskResultHistory()
        first = _make_result(result_id="dup-1")
        second = _make_result(result_id="dup-1", output={"different": True})
        self.assertIs(history.record(first), first)
        self.assertIsNone(history.record(second))
        self.assertEqual(len(history), 1)

    def test_original_result_is_kept_on_duplicate(self):
        history = RevenueTaskResultHistory()
        first = _make_result(result_id="dup-2", output={"units": 1})
        second = _make_result(result_id="dup-2", output={"units": 999})
        history.record(first)
        history.record(second)
        stored = history.get_all()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].output, {"units": 1})

    def test_recording_the_exact_same_object_twice_is_rejected(self):
        history = RevenueTaskResultHistory()
        result = _make_result()
        history.record(result)
        self.assertIsNone(history.record(result))
        self.assertEqual(len(history), 1)


# ----------------------------------------------------------------------
# 3. get_all()
# ----------------------------------------------------------------------
class TestGetAll(unittest.TestCase):
    def test_empty_history_returns_empty_list(self):
        history = RevenueTaskResultHistory()
        self.assertEqual(history.get_all(), [])

    def test_returns_every_recorded_result(self):
        history = RevenueTaskResultHistory()
        r1 = _make_result(result_id="r-1")
        r2 = _make_result(result_id="r-2")
        history.record(r1)
        history.record(r2)
        all_results = history.get_all()
        self.assertEqual(len(all_results), 2)
        self.assertEqual([r.result_id for r in all_results], ["r-1", "r-2"])


# ----------------------------------------------------------------------
# 4. get_for_task()
# ----------------------------------------------------------------------
class TestGetForTask(unittest.TestCase):
    def test_returns_only_matching_task(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-b"))
        history.record(_make_result(result_id="r-3", task_id="task-a"))
        results = history.get_for_task("task-a")
        self.assertEqual([r.result_id for r in results], ["r-1", "r-3"])

    def test_unknown_task_id_returns_empty_list(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result())
        self.assertEqual(history.get_for_task("no-such-task"), [])

    def test_empty_history_returns_empty_list(self):
        history = RevenueTaskResultHistory()
        self.assertEqual(history.get_for_task("task-test-1"), [])


# ----------------------------------------------------------------------
# 5. get_for_opportunity()
# ----------------------------------------------------------------------
class TestGetForOpportunity(unittest.TestCase):
    def test_returns_only_matching_opportunity(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a"))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-b"))
        history.record(_make_result(result_id="r-3", opportunity_id="opp-a"))
        results = history.get_for_opportunity("opp-a")
        self.assertEqual([r.result_id for r in results], ["r-1", "r-3"])

    def test_unknown_opportunity_id_returns_empty_list(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result())
        self.assertEqual(history.get_for_opportunity("no-such-opp"), [])


# ----------------------------------------------------------------------
# 6. get_latest_for_task()
# ----------------------------------------------------------------------
class TestGetLatestForTask(unittest.TestCase):
    def test_returns_none_for_unknown_task(self):
        history = RevenueTaskResultHistory()
        self.assertIsNone(history.get_latest_for_task("no-such-task"))

    def test_returns_the_only_result(self):
        history = RevenueTaskResultHistory()
        result = _make_result()
        history.record(result)
        latest = history.get_latest_for_task("task-test-1")
        self.assertEqual(latest.result_id, result.result_id)

    def test_returns_the_most_recently_recorded_result(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-a"))
        history.record(_make_result(result_id="r-3", task_id="task-a"))
        latest = history.get_latest_for_task("task-a")
        self.assertEqual(latest.result_id, "r-3")

    def test_ignores_other_tasks(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-b"))
        latest = history.get_latest_for_task("task-a")
        self.assertEqual(latest.result_id, "r-1")


# ----------------------------------------------------------------------
# 7. count_for_task()
# ----------------------------------------------------------------------
class TestCountForTask(unittest.TestCase):
    def test_zero_for_unknown_task(self):
        history = RevenueTaskResultHistory()
        self.assertEqual(history.count_for_task("no-such-task"), 0)

    def test_counts_only_matching_task(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-b"))
        history.record(_make_result(result_id="r-3", task_id="task-a"))
        self.assertEqual(history.count_for_task("task-a"), 2)
        self.assertEqual(history.count_for_task("task-b"), 1)

    def test_count_matches_get_for_task_length(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-a"))
        self.assertEqual(
            history.count_for_task("task-a"), len(history.get_for_task("task-a"))
        )


# ----------------------------------------------------------------------
# 8. clear()
# ----------------------------------------------------------------------
class TestClear(unittest.TestCase):
    def test_removes_all_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1"))
        history.record(_make_result(result_id="r-2"))
        history.clear()
        self.assertEqual(history.get_all(), [])
        self.assertEqual(len(history), 0)

    def test_safe_to_call_on_empty_history(self):
        history = RevenueTaskResultHistory()
        history.clear()
        self.assertEqual(len(history), 0)

    def test_can_record_again_after_clear(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1"))
        history.clear()
        result = _make_result(result_id="r-1")
        self.assertIs(history.record(result), result)
        self.assertEqual(len(history), 1)


# ----------------------------------------------------------------------
# 9. Multiple results for one task
# ----------------------------------------------------------------------
class TestMultipleResultsForOneTask(unittest.TestCase):
    def test_all_results_are_kept(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", status=STATUS_COMPLETED))
        self.assertEqual(history.count_for_task("task-a"), 3)
        self.assertEqual(
            [r.result_id for r in history.get_for_task("task-a")],
            ["r-1", "r-2", "r-3"],
        )


# ----------------------------------------------------------------------
# 10. Multiple tasks in one opportunity
# ----------------------------------------------------------------------
class TestMultipleTasksInOneOpportunity(unittest.TestCase):
    def test_results_from_multiple_tasks_are_grouped_by_opportunity(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1"))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1"))
        history.record(_make_result(result_id="r-3", task_id="task-c", opportunity_id="opp-2"))
        opp1_results = history.get_for_opportunity("opp-1")
        self.assertEqual([r.result_id for r in opp1_results], ["r-1", "r-2"])
        self.assertEqual(len(history.get_for_opportunity("opp-2")), 1)


# ----------------------------------------------------------------------
# 11. Insertion order
# ----------------------------------------------------------------------
class TestInsertionOrder(unittest.TestCase):
    def test_get_all_preserves_insertion_order(self):
        history = RevenueTaskResultHistory()
        ids = ["r-3", "r-1", "r-2"]
        for result_id in ids:
            history.record(_make_result(result_id=result_id))
        self.assertEqual([r.result_id for r in history.get_all()], ids)

    def test_get_for_task_preserves_insertion_order(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-c", task_id="task-a"))
        history.record(_make_result(result_id="r-a", task_id="task-a"))
        history.record(_make_result(result_id="r-b", task_id="task-a"))
        self.assertEqual(
            [r.result_id for r in history.get_for_task("task-a")],
            ["r-c", "r-a", "r-b"],
        )

    def test_rejected_duplicate_does_not_disturb_order(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1"))
        history.record(_make_result(result_id="r-2"))
        history.record(_make_result(result_id="r-1"))  # duplicate, rejected
        self.assertEqual([r.result_id for r in history.get_all()], ["r-1", "r-2"])


# ----------------------------------------------------------------------
# 12. Invalid inputs
# ----------------------------------------------------------------------
class TestInvalidInputs(unittest.TestCase):
    def test_none_is_rejected(self):
        history = RevenueTaskResultHistory()
        self.assertIsNone(history.record(None))
        self.assertEqual(len(history), 0)

    def test_plain_dict_is_rejected(self):
        history = RevenueTaskResultHistory()
        fake = {"result_id": "r-1", "task_id": "task-a", "status": STATUS_COMPLETED}
        self.assertIsNone(history.record(fake))
        self.assertEqual(len(history), 0)

    def test_string_is_rejected(self):
        history = RevenueTaskResultHistory()
        self.assertIsNone(history.record("not a result"))
        self.assertEqual(len(history), 0)

    def test_empty_result_id_is_rejected(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="")
        self.assertIsNone(history.record(result))
        self.assertEqual(len(history), 0)

    def test_invalid_status_is_rejected(self):
        history = RevenueTaskResultHistory()
        result = _make_result(status="BOGUS")
        self.assertIsNone(history.record(result))
        self.assertEqual(len(history), 0)

    def test_unsafe_output_is_rejected(self):
        history = RevenueTaskResultHistory()

        class NotStructuredData:
            pass

        result = _make_result(output=NotStructuredData())
        self.assertIsNone(history.record(result))
        self.assertEqual(len(history), 0)

    def test_never_raises_on_invalid_input(self):
        history = RevenueTaskResultHistory()
        try:
            history.record(None)
            history.record(123)
            history.record({"not": "a result"})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"record() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 13. Returned lists are independent
# ----------------------------------------------------------------------
class TestReturnedListsAreIndependent(unittest.TestCase):
    def test_mutating_get_all_list_does_not_affect_history(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1"))
        results = history.get_all()
        results.append(_make_result(result_id="fake"))
        results.clear()
        self.assertEqual(len(history), 1)
        self.assertEqual(len(history.get_all()), 1)

    def test_mutating_returned_result_does_not_affect_history(self):
        history = RevenueTaskResultHistory()
        result = _make_result(output={"units": 3})
        history.record(result)
        fetched = history.get_all()[0]
        fetched.output["units"] = 999
        fetched.metadata["extra"] = "changed"

        fresh = history.get_all()[0]
        self.assertEqual(fresh.output, {"units": 3})
        self.assertEqual(fresh.metadata, {})

    def test_two_calls_return_independent_objects(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result())
        first = history.get_all()[0]
        second = history.get_all()[0]
        self.assertIsNot(first, second)
        self.assertEqual(first.result_id, second.result_id)

    def test_get_for_task_returns_independent_list(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        results = history.get_for_task("task-a")
        results.append("garbage")
        self.assertEqual(len(history.get_for_task("task-a")), 1)


# ----------------------------------------------------------------------
# 14. Original result objects remain unchanged
# ----------------------------------------------------------------------
class TestOriginalResultObjectsRemainUnchanged(unittest.TestCase):
    def test_record_does_not_modify_the_result(self):
        history = RevenueTaskResultHistory()
        result = _make_result(output={"units": 3}, metadata={"note": "ok"})
        before = result.to_dict()
        history.record(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_rejected_duplicate_does_not_modify_either_result(self):
        history = RevenueTaskResultHistory()
        first = _make_result(result_id="dup-1", output={"units": 1})
        second = _make_result(result_id="dup-1", output={"units": 2})
        history.record(first)
        before_first = first.to_dict()
        before_second = second.to_dict()
        history.record(second)
        self.assertEqual(first.to_dict(), before_first)
        self.assertEqual(second.to_dict(), before_second)

    def test_get_all_does_not_modify_stored_results(self):
        history = RevenueTaskResultHistory()
        result = _make_result()
        history.record(result)
        before = result.to_dict()
        history.get_all()
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_clear_does_not_modify_the_result_object(self):
        history = RevenueTaskResultHistory()
        result = _make_result()
        history.record(result)
        before = result.to_dict()
        history.clear()
        after = result.to_dict()
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# 15. get_task_success_rate()
# ----------------------------------------------------------------------
class TestGetTaskSuccessRate(unittest.TestCase):
    def test_no_results_returns_zero_report(self):
        history = RevenueTaskResultHistory()
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report, {
            "task_id": "task-a",
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
        })

    def test_one_completed_result(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["success_rate"], 1.0)

    def test_one_failed_result(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_FAILED))
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 0)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.0)

    def test_mixed_completed_and_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report["total_results"], 2)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.5)

    def test_multiple_results_exact_success_rate(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", task_id="task-a", status=status))
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report["total_results"], 4)
        self.assertEqual(report["completed_count"], 3)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.75)

    def test_success_rate_is_always_within_zero_and_one(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_FAILED, STATUS_FAILED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", task_id="task-a", status=status))
        report = history.get_task_success_rate("task-a")
        self.assertGreaterEqual(report["success_rate"], 0.0)
        self.assertLessEqual(report["success_rate"], 1.0)
        self.assertIsInstance(report["success_rate"], float)

    def test_success_rate_is_float_type_even_when_zero_or_one(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        report = history.get_task_success_rate("task-a")
        self.assertIsInstance(report["success_rate"], float)

        empty_report = history.get_task_success_rate("no-such-task")
        self.assertIsInstance(empty_report["success_rate"], float)

    def test_invalid_task_id_returns_zero_report(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-task"):
            report = history.get_task_success_rate(bogus_id)
            self.assertEqual(report["total_results"], 0)
            self.assertEqual(report["completed_count"], 0)
            self.assertEqual(report["failed_count"], 0)
            self.assertEqual(report["success_rate"], 0.0)
            self.assertEqual(report["task_id"], bogus_id)

    def test_ignores_results_from_other_tasks(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", status=STATUS_FAILED))
        report = history.get_task_success_rate("task-a")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["success_rate"], 1.0)

    def test_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_task_success_rate("task-a")
        history.get_task_success_rate("no-such-task")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_does_not_modify_the_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_task_success_rate("task-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_never_raises_on_bogus_task_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_task_success_rate(None)
            history.get_task_success_rate(123)
            history.get_task_success_rate([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_task_success_rate() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 16. get_opportunity_success_rate()
# ----------------------------------------------------------------------
class TestGetOpportunitySuccessRate(unittest.TestCase):
    def test_no_results_returns_zero_report(self):
        history = RevenueTaskResultHistory()
        report = history.get_opportunity_success_rate("opp-a")
        self.assertEqual(report, {
            "opportunity_id": "opp-a",
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
        })

    def test_one_completed_result(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        report = history.get_opportunity_success_rate("opp-a")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["success_rate"], 1.0)

    def test_one_failed_result(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_FAILED))
        report = history.get_opportunity_success_rate("opp-a")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 0)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.0)

    def test_mixed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        report = history.get_opportunity_success_rate("opp-a")
        self.assertEqual(report["total_results"], 2)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.5)

    def test_results_from_multiple_tasks_in_same_opportunity(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-c", opportunity_id="opp-1", status=STATUS_COMPLETED))
        report = history.get_opportunity_success_rate("opp-1")
        self.assertEqual(report["total_results"], 3)
        self.assertEqual(report["completed_count"], 2)
        self.assertEqual(report["failed_count"], 1)
        self.assertAlmostEqual(report["success_rate"], 2 / 3)

    def test_results_from_different_opportunities_are_excluded(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-2", status=STATUS_FAILED))
        report = history.get_opportunity_success_rate("opp-1")
        self.assertEqual(report["total_results"], 1)
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["success_rate"], 1.0)

    def test_exact_success_rate_calculation(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", opportunity_id="opp-a", status=status))
        report = history.get_opportunity_success_rate("opp-a")
        self.assertEqual(report["total_results"], 4)
        self.assertEqual(report["completed_count"], 3)
        self.assertEqual(report["failed_count"], 1)
        self.assertEqual(report["success_rate"], 0.75)

    def test_success_rate_is_always_within_zero_and_one(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_FAILED, STATUS_FAILED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", opportunity_id="opp-a", status=status))
        report = history.get_opportunity_success_rate("opp-a")
        self.assertGreaterEqual(report["success_rate"], 0.0)
        self.assertLessEqual(report["success_rate"], 1.0)
        self.assertIsInstance(report["success_rate"], float)

    def test_invalid_opportunity_id_returns_zero_report(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-opp"):
            report = history.get_opportunity_success_rate(bogus_id)
            self.assertEqual(report["total_results"], 0)
            self.assertEqual(report["completed_count"], 0)
            self.assertEqual(report["failed_count"], 0)
            self.assertEqual(report["success_rate"], 0.0)
            self.assertEqual(report["opportunity_id"], bogus_id)

    def test_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_opportunity_success_rate("opp-a")
        history.get_opportunity_success_rate("no-such-opp")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_does_not_modify_the_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_opportunity_success_rate("opp-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_never_raises_on_bogus_opportunity_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_opportunity_success_rate(None)
            history.get_opportunity_success_rate(123)
            history.get_opportunity_success_rate([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_opportunity_success_rate() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 17. get_task_result_summary()
# ----------------------------------------------------------------------
class TestGetTaskResultSummary(unittest.TestCase):
    def test_task_with_no_results(self):
        history = RevenueTaskResultHistory()
        summary = history.get_task_result_summary("task-a")
        self.assertEqual(summary, {
            "task_id": "task-a",
            "has_results": False,
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "latest_result_id": None,
            "latest_status": None,
        })

    def test_task_with_only_completed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_COMPLETED))
        summary = history.get_task_result_summary("task-a")
        self.assertTrue(summary["has_results"])
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["success_rate"], 1.0)

    def test_task_with_only_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        summary = history.get_task_result_summary("task-a")
        self.assertTrue(summary["has_results"])
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(summary["completed_count"], 0)
        self.assertEqual(summary["failed_count"], 2)
        self.assertEqual(summary["success_rate"], 0.0)

    def test_task_with_mixed_completed_and_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", status=STATUS_COMPLETED))
        summary = history.get_task_result_summary("task-a")
        self.assertEqual(summary["total_results"], 3)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["failed_count"], 1)
        self.assertAlmostEqual(summary["success_rate"], 2 / 3)

    def test_latest_result_information(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", status=STATUS_COMPLETED))
        summary = history.get_task_result_summary("task-a")
        self.assertEqual(summary["latest_result_id"], "r-3")
        self.assertEqual(summary["latest_status"], STATUS_COMPLETED)

    def test_latest_result_ignores_other_tasks(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", status=STATUS_FAILED))
        summary = history.get_task_result_summary("task-a")
        self.assertEqual(summary["latest_result_id"], "r-1")
        self.assertEqual(summary["latest_status"], STATUS_COMPLETED)

    def test_success_rate_calculation_exact(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", task_id="task-a", status=status))
        summary = history.get_task_result_summary("task-a")
        self.assertEqual(summary["success_rate"], 0.75)

    def test_invalid_task_id_returns_zero_summary(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-task"):
            summary = history.get_task_result_summary(bogus_id)
            self.assertFalse(summary["has_results"])
            self.assertEqual(summary["total_results"], 0)
            self.assertEqual(summary["completed_count"], 0)
            self.assertEqual(summary["failed_count"], 0)
            self.assertEqual(summary["success_rate"], 0.0)
            self.assertIsNone(summary["latest_result_id"])
            self.assertIsNone(summary["latest_status"])
            self.assertEqual(summary["task_id"], bogus_id)

    def test_read_only_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_task_result_summary("task-a")
        history.get_task_result_summary("no-such-task")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_read_only_does_not_modify_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_task_result_summary("task-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_never_raises_on_bogus_task_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_task_result_summary(None)
            history.get_task_result_summary(123)
            history.get_task_result_summary([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_task_result_summary() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 18. get_opportunity_result_summary()
# ----------------------------------------------------------------------
class TestGetOpportunityResultSummary(unittest.TestCase):
    def test_opportunity_with_no_results(self):
        history = RevenueTaskResultHistory()
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(summary, {
            "opportunity_id": "opp-a",
            "has_results": False,
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "task_ids": [],
            "task_count": 0,
            "latest_result_id": None,
            "latest_task_id": None,
            "latest_status": None,
        })

    def test_one_task_with_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", opportunity_id="opp-a", status=STATUS_FAILED))
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertTrue(summary["has_results"])
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(summary["task_ids"], ["task-a"])
        self.assertEqual(summary["task_count"], 1)

    def test_multiple_tasks_under_same_opportunity(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-c", opportunity_id="opp-1", status=STATUS_COMPLETED))
        summary = history.get_opportunity_result_summary("opp-1")
        self.assertEqual(summary["total_results"], 3)
        self.assertEqual(summary["task_ids"], ["task-a", "task-b", "task-c"])
        self.assertEqual(summary["task_count"], 3)

    def test_unique_task_id_collection_preserves_first_seen_order(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-4", task_id="task-b", opportunity_id="opp-1", status=STATUS_COMPLETED))
        summary = history.get_opportunity_result_summary("opp-1")
        self.assertEqual(summary["task_ids"], ["task-a", "task-b"])
        self.assertEqual(summary["task_count"], 2)
        self.assertEqual(summary["total_results"], 4)

    def test_mixed_completed_and_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", opportunity_id="opp-a", status=STATUS_COMPLETED))
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["failed_count"], 1)

    def test_success_rate_calculation_exact(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", opportunity_id="opp-a", status=status))
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(summary["success_rate"], 0.75)

    def test_latest_result_information(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-a", status=STATUS_FAILED))
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(summary["latest_result_id"], "r-2")
        self.assertEqual(summary["latest_task_id"], "task-b")
        self.assertEqual(summary["latest_status"], STATUS_FAILED)

    def test_latest_result_ignores_other_opportunities(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-b", status=STATUS_FAILED))
        summary = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(summary["latest_result_id"], "r-1")
        self.assertEqual(summary["latest_status"], STATUS_COMPLETED)

    def test_invalid_opportunity_id_returns_zero_summary(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-opp"):
            summary = history.get_opportunity_result_summary(bogus_id)
            self.assertFalse(summary["has_results"])
            self.assertEqual(summary["total_results"], 0)
            self.assertEqual(summary["completed_count"], 0)
            self.assertEqual(summary["failed_count"], 0)
            self.assertEqual(summary["success_rate"], 0.0)
            self.assertEqual(summary["task_ids"], [])
            self.assertEqual(summary["task_count"], 0)
            self.assertIsNone(summary["latest_result_id"])
            self.assertIsNone(summary["latest_task_id"])
            self.assertIsNone(summary["latest_status"])
            self.assertEqual(summary["opportunity_id"], bogus_id)

    def test_read_only_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_opportunity_result_summary("opp-a")
        history.get_opportunity_result_summary("no-such-opp")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_read_only_does_not_modify_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_opportunity_result_summary("opp-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_mutating_returned_task_ids_does_not_affect_history(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        summary = history.get_opportunity_result_summary("opp-a")
        summary["task_ids"].append("fake-task")
        fresh = history.get_opportunity_result_summary("opp-a")
        self.assertEqual(fresh["task_ids"], ["task-a"])

    def test_never_raises_on_bogus_opportunity_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_opportunity_result_summary(None)
            history.get_opportunity_result_summary(123)
            history.get_opportunity_result_summary([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_opportunity_result_summary() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 19. get_overall_result_summary()
# ----------------------------------------------------------------------
class TestGetOverallResultSummary(unittest.TestCase):
    def test_empty_history(self):
        history = RevenueTaskResultHistory()
        summary = history.get_overall_result_summary()
        self.assertEqual(summary, {
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "unique_task_count": 0,
            "unique_opportunity_count": 0,
            "latest_result_id": None,
            "latest_task_id": None,
            "latest_opportunity_id": None,
            "latest_status": None,
            "has_results": False,
        })

    def test_only_completed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", status=STATUS_COMPLETED))
        summary = history.get_overall_result_summary()
        self.assertTrue(summary["has_results"])
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["success_rate"], 1.0)

    def test_only_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-2", status=STATUS_FAILED))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(summary["completed_count"], 0)
        self.assertEqual(summary["failed_count"], 2)
        self.assertEqual(summary["success_rate"], 0.0)

    def test_mixed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", status=STATUS_COMPLETED))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["total_results"], 3)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["failed_count"], 1)

    def test_unique_task_counting(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a"))
        history.record(_make_result(result_id="r-2", task_id="task-b"))
        history.record(_make_result(result_id="r-3", task_id="task-a"))
        history.record(_make_result(result_id="r-4", task_id="task-c"))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["unique_task_count"], 3)

    def test_unique_opportunity_counting(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a"))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-b"))
        history.record(_make_result(result_id="r-3", opportunity_id="opp-a"))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["unique_opportunity_count"], 2)

    def test_success_rate_calculation_exact(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", status=status))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["success_rate"], 0.75)

    def test_latest_result_fields(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-b", status=STATUS_FAILED))
        summary = history.get_overall_result_summary()
        self.assertEqual(summary["latest_result_id"], "r-2")
        self.assertEqual(summary["latest_task_id"], "task-b")
        self.assertEqual(summary["latest_opportunity_id"], "opp-b")
        self.assertEqual(summary["latest_status"], STATUS_FAILED)

    def test_read_only_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_overall_result_summary()
        history.get_overall_result_summary()
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_read_only_does_not_modify_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_overall_result_summary()
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_never_raises_on_empty_history(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_overall_result_summary()
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_overall_result_summary() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 20. get_task_performance_report()
# ----------------------------------------------------------------------
class TestGetTaskPerformanceReport(unittest.TestCase):
    def test_no_result_data(self):
        history = RevenueTaskResultHistory()
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report, {
            "task_id": "task-a",
            "has_results": False,
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "latest_result_id": None,
            "latest_status": None,
            "performance_state": "NO_DATA",
        })

    def test_all_successful_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_COMPLETED))
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report["success_rate"], 1.0)
        self.assertEqual(report["performance_state"], "SUCCESSFUL")

    def test_all_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report["success_rate"], 0.0)
        self.assertEqual(report["performance_state"], "FAILED")

    def test_mixed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report["performance_state"], "MIXED")

    def test_latest_result_information(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", status=STATUS_COMPLETED))
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report["latest_result_id"], "r-3")
        self.assertEqual(report["latest_status"], STATUS_COMPLETED)

    def test_correct_success_rate(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", task_id="task-a", status=status))
        report = history.get_task_performance_report("task-a")
        self.assertEqual(report["success_rate"], 0.75)
        self.assertEqual(report["performance_state"], "MIXED")

    def test_read_only_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_task_performance_report("task-a")
        history.get_task_performance_report("no-such-task")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_read_only_does_not_modify_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_task_performance_report("task-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_consistency_with_get_task_result_summary(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", status=STATUS_COMPLETED))
        summary = history.get_task_result_summary("task-a")
        report = history.get_task_performance_report("task-a")
        for key in (
            "task_id", "has_results", "total_results", "completed_count",
            "failed_count", "success_rate", "latest_result_id", "latest_status",
        ):
            self.assertEqual(report[key], summary[key])

    def test_invalid_task_id_returns_no_data(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-task"):
            report = history.get_task_performance_report(bogus_id)
            self.assertEqual(report["performance_state"], "NO_DATA")
            self.assertFalse(report["has_results"])

    def test_never_raises_on_bogus_task_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_task_performance_report(None)
            history.get_task_performance_report(123)
            history.get_task_performance_report([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_task_performance_report() raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 21. get_opportunity_performance_report()
# ----------------------------------------------------------------------
class TestGetOpportunityPerformanceReport(unittest.TestCase):
    def test_opportunity_with_no_results(self):
        history = RevenueTaskResultHistory()
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report, {
            "opportunity_id": "opp-a",
            "has_results": False,
            "total_results": 0,
            "completed_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "task_count": 0,
            "task_ids": [],
            "latest_result_id": None,
            "latest_task_id": None,
            "latest_status": None,
            "performance_state": "NO_DATA",
        })

    def test_all_successful_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_COMPLETED))
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report["success_rate"], 1.0)
        self.assertEqual(report["performance_state"], "SUCCESSFUL")

    def test_all_failed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report["success_rate"], 0.0)
        self.assertEqual(report["performance_state"], "FAILED")

    def test_mixed_results(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report["performance_state"], "MIXED")

    def test_multiple_tasks(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-c", opportunity_id="opp-1", status=STATUS_COMPLETED))
        report = history.get_opportunity_performance_report("opp-1")
        self.assertEqual(report["total_results"], 3)
        self.assertEqual(report["task_count"], 3)

    def test_correct_task_ids_and_task_count(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-1", status=STATUS_FAILED))
        history.record(_make_result(result_id="r-3", task_id="task-a", opportunity_id="opp-1", status=STATUS_COMPLETED))
        report = history.get_opportunity_performance_report("opp-1")
        self.assertEqual(report["task_ids"], ["task-a", "task-b"])
        self.assertEqual(report["task_count"], 2)

    def test_correct_success_rate(self):
        history = RevenueTaskResultHistory()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        for i, status in enumerate(statuses):
            history.record(_make_result(result_id=f"r-{i}", opportunity_id="opp-a", status=status))
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report["success_rate"], 0.75)
        self.assertEqual(report["performance_state"], "MIXED")

    def test_latest_result_information(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-a", status=STATUS_FAILED))
        report = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(report["latest_result_id"], "r-2")
        self.assertEqual(report["latest_task_id"], "task-b")
        self.assertEqual(report["latest_status"], STATUS_FAILED)

    def test_correct_performance_state_transitions(self):
        history = RevenueTaskResultHistory()
        self.assertEqual(
            history.get_opportunity_performance_report("opp-a")["performance_state"], "NO_DATA"
        )
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        self.assertEqual(
            history.get_opportunity_performance_report("opp-a")["performance_state"], "SUCCESSFUL"
        )
        history.record(_make_result(result_id="r-2", opportunity_id="opp-a", status=STATUS_FAILED))
        self.assertEqual(
            history.get_opportunity_performance_report("opp-a")["performance_state"], "MIXED"
        )

    def test_read_only_does_not_modify_history_state(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-a", status=STATUS_FAILED))
        before_len = len(history)
        before_all = [r.result_id for r in history.get_all()]
        history.get_opportunity_performance_report("opp-a")
        history.get_opportunity_performance_report("no-such-opp")
        self.assertEqual(len(history), before_len)
        self.assertEqual([r.result_id for r in history.get_all()], before_all)

    def test_read_only_does_not_modify_underlying_result_objects(self):
        history = RevenueTaskResultHistory()
        result = _make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED, output={"units": 1})
        history.record(result)
        before = result.to_dict()
        history.get_opportunity_performance_report("opp-a")
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_mutating_returned_task_ids_does_not_affect_history(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        report = history.get_opportunity_performance_report("opp-a")
        report["task_ids"].append("fake-task")
        fresh = history.get_opportunity_performance_report("opp-a")
        self.assertEqual(fresh["task_ids"], ["task-a"])

    def test_consistency_with_get_opportunity_result_summary(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", task_id="task-a", opportunity_id="opp-a", status=STATUS_COMPLETED))
        history.record(_make_result(result_id="r-2", task_id="task-b", opportunity_id="opp-a", status=STATUS_FAILED))
        summary = history.get_opportunity_result_summary("opp-a")
        report = history.get_opportunity_performance_report("opp-a")
        for key in (
            "opportunity_id", "has_results", "total_results", "completed_count",
            "failed_count", "success_rate", "task_count", "task_ids",
            "latest_result_id", "latest_task_id", "latest_status",
        ):
            self.assertEqual(report[key], summary[key])

    def test_invalid_opportunity_id_returns_no_data(self):
        history = RevenueTaskResultHistory()
        history.record(_make_result(result_id="r-1", opportunity_id="opp-a", status=STATUS_COMPLETED))
        for bogus_id in (None, "", "no-such-opp"):
            report = history.get_opportunity_performance_report(bogus_id)
            self.assertEqual(report["performance_state"], "NO_DATA")
            self.assertFalse(report["has_results"])

    def test_never_raises_on_bogus_opportunity_id_types(self):
        history = RevenueTaskResultHistory()
        try:
            history.get_opportunity_performance_report(None)
            history.get_opportunity_performance_report(123)
            history.get_opportunity_performance_report([])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_opportunity_performance_report() raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
