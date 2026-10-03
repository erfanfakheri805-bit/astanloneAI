"""
Tests for RevenueLearningRecordStore
(financial/revenue_learning_store.py).

Covers: valid record storage, duplicate learning IDs, get_record(),
get_all(), get_for_task(), get_for_opportunity(), count(), clear(),
insertion order, record_from_task_result() (building and storing a
RevenueLearningRecord from a RevenueTaskResult), invalid inputs, and
that returned records/lists are independent from this store's own
internal state.

This stage only stores and retrieves already-built
RevenueLearningRecord objects (or builds one from an existing
RevenueTaskResult) - it does not learn anything, does not execute
anything, and does not persist anything.

Run directly:
    python -m unittest tests.test_revenue_learning_store -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_learning_store import RevenueLearningRecordStore
from financial.revenue_learning import RevenueLearningRecord
from financial.revenue_task_result import (
    RevenueTaskResult,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


def _make_learning_record(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        result_status=STATUS_COMPLETED,
        success=True,
        learning_id="learning-test-1",
    )
    fields.update(overrides)
    return RevenueLearningRecord(**fields)


def _make_task_result(**overrides):
    fields = dict(
        result_id="result-test-1",
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        status=STATUS_COMPLETED,
    )
    fields.update(overrides)
    return RevenueTaskResult(**fields)


# ----------------------------------------------------------------------
# 1. Adding a valid record
# ----------------------------------------------------------------------
class TestAddingAValidRecord(unittest.TestCase):
    def test_add_record_returns_the_same_record_on_success(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record()
        self.assertIs(store.add_record(record), record)

    def test_add_record_increases_store_length(self):
        store = RevenueLearningRecordStore()
        self.assertEqual(len(store), 0)
        store.add_record(_make_learning_record())
        self.assertEqual(len(store), 1)

    def test_successful_and_failed_records_both_accepted(self):
        store = RevenueLearningRecordStore()
        successful = _make_learning_record(learning_id="lr-1", success=True, result_status=STATUS_COMPLETED)
        failed = _make_learning_record(learning_id="lr-2", success=False, result_status=STATUS_FAILED)
        self.assertIs(store.add_record(successful), successful)
        self.assertIs(store.add_record(failed), failed)
        self.assertEqual(len(store), 2)


# ----------------------------------------------------------------------
# 2. Retrieving by learning ID
# ----------------------------------------------------------------------
class TestGetRecord(unittest.TestCase):
    def test_returns_the_matching_record(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(learning_id="lr-1")
        store.add_record(record)
        fetched = store.get_record("lr-1")
        self.assertEqual(fetched.learning_id, "lr-1")

    def test_unknown_learning_id_returns_none(self):
        store = RevenueLearningRecordStore()
        self.assertIsNone(store.get_record("no-such-id"))

    def test_returned_record_is_an_independent_copy(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(learning_id="lr-1", output={"units": 1})
        store.add_record(record)
        fetched = store.get_record("lr-1")
        fetched.output["units"] = 999
        fresh = store.get_record("lr-1")
        self.assertEqual(fresh.output, {"units": 1})


# ----------------------------------------------------------------------
# 3. Retrieving all records
# ----------------------------------------------------------------------
class TestGetAll(unittest.TestCase):
    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningRecordStore()
        self.assertEqual(store.get_all(), [])

    def test_returns_every_stored_record(self):
        store = RevenueLearningRecordStore()
        r1 = _make_learning_record(learning_id="lr-1")
        r2 = _make_learning_record(learning_id="lr-2")
        store.add_record(r1)
        store.add_record(r2)
        all_records = store.get_all()
        self.assertEqual(len(all_records), 2)
        self.assertEqual([r.learning_id for r in all_records], ["lr-1", "lr-2"])


# ----------------------------------------------------------------------
# 4. Retrieving records by task
# ----------------------------------------------------------------------
class TestGetForTask(unittest.TestCase):
    def test_returns_only_matching_task(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1", task_id="task-a"))
        store.add_record(_make_learning_record(learning_id="lr-2", task_id="task-b"))
        store.add_record(_make_learning_record(learning_id="lr-3", task_id="task-a"))
        records = store.get_for_task("task-a")
        self.assertEqual([r.learning_id for r in records], ["lr-1", "lr-3"])

    def test_unknown_task_id_returns_empty_list(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record())
        self.assertEqual(store.get_for_task("no-such-task"), [])


# ----------------------------------------------------------------------
# 5. Retrieving records by opportunity
# ----------------------------------------------------------------------
class TestGetForOpportunity(unittest.TestCase):
    def test_returns_only_matching_opportunity(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1", opportunity_id="opp-a"))
        store.add_record(_make_learning_record(learning_id="lr-2", opportunity_id="opp-b"))
        store.add_record(_make_learning_record(learning_id="lr-3", opportunity_id="opp-a"))
        records = store.get_for_opportunity("opp-a")
        self.assertEqual([r.learning_id for r in records], ["lr-1", "lr-3"])

    def test_unknown_opportunity_id_returns_empty_list(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record())
        self.assertEqual(store.get_for_opportunity("no-such-opp"), [])


# ----------------------------------------------------------------------
# 6. Duplicate learning ID protection
# ----------------------------------------------------------------------
class TestDuplicateLearningIds(unittest.TestCase):
    def test_second_add_with_same_id_is_rejected(self):
        store = RevenueLearningRecordStore()
        first = _make_learning_record(learning_id="dup-1")
        second = _make_learning_record(learning_id="dup-1", output={"different": True})
        self.assertIs(store.add_record(first), first)
        self.assertIsNone(store.add_record(second))
        self.assertEqual(len(store), 1)

    def test_original_record_is_kept_on_duplicate(self):
        store = RevenueLearningRecordStore()
        first = _make_learning_record(learning_id="dup-2", output={"units": 1})
        second = _make_learning_record(learning_id="dup-2", output={"units": 999})
        store.add_record(first)
        store.add_record(second)
        stored = store.get_all()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].output, {"units": 1})


# ----------------------------------------------------------------------
# 7. Insertion order
# ----------------------------------------------------------------------
class TestInsertionOrder(unittest.TestCase):
    def test_get_all_preserves_insertion_order(self):
        store = RevenueLearningRecordStore()
        ids = ["lr-3", "lr-1", "lr-2"]
        for learning_id in ids:
            store.add_record(_make_learning_record(learning_id=learning_id))
        self.assertEqual([r.learning_id for r in store.get_all()], ids)

    def test_rejected_duplicate_does_not_disturb_order(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1"))
        store.add_record(_make_learning_record(learning_id="lr-2"))
        store.add_record(_make_learning_record(learning_id="lr-1"))  # duplicate, rejected
        self.assertEqual([r.learning_id for r in store.get_all()], ["lr-1", "lr-2"])


# ----------------------------------------------------------------------
# 8. Count
# ----------------------------------------------------------------------
class TestCount(unittest.TestCase):
    def test_count_matches_len(self):
        store = RevenueLearningRecordStore()
        self.assertEqual(store.count(), 0)
        store.add_record(_make_learning_record(learning_id="lr-1"))
        store.add_record(_make_learning_record(learning_id="lr-2"))
        self.assertEqual(store.count(), 2)
        self.assertEqual(store.count(), len(store))


# ----------------------------------------------------------------------
# 9. Clear
# ----------------------------------------------------------------------
class TestClear(unittest.TestCase):
    def test_clear_empties_the_store(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1"))
        store.add_record(_make_learning_record(learning_id="lr-2"))
        store.clear()
        self.assertEqual(len(store), 0)
        self.assertEqual(store.get_all(), [])

    def test_clear_allows_reusing_a_previously_used_id(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1"))
        store.clear()
        record = _make_learning_record(learning_id="lr-1")
        self.assertIs(store.add_record(record), record)


# ----------------------------------------------------------------------
# 10. record_from_task_result()
# ----------------------------------------------------------------------
class TestRecordFromTaskResult(unittest.TestCase):
    def test_creates_and_stores_a_record(self):
        store = RevenueLearningRecordStore()
        result = _make_task_result(status=STATUS_COMPLETED)
        record = store.record_from_task_result(result)
        self.assertIsInstance(record, RevenueLearningRecord)
        self.assertEqual(len(store), 1)

    def test_returned_record_reflects_the_task_result(self):
        store = RevenueLearningRecordStore()
        result = _make_task_result(task_id="task-x", opportunity_id="opp-x", status=STATUS_FAILED, error="boom")
        record = store.record_from_task_result(result)
        self.assertEqual(record.task_id, "task-x")
        self.assertEqual(record.opportunity_id, "opp-x")
        self.assertEqual(record.result_status, STATUS_FAILED)
        self.assertFalse(record.success)
        self.assertEqual(record.error, "boom")

    def test_the_stored_record_is_retrievable(self):
        store = RevenueLearningRecordStore()
        result = _make_task_result(status=STATUS_COMPLETED)
        record = store.record_from_task_result(result)
        fetched = store.get_record(record.learning_id)
        self.assertEqual(fetched.learning_id, record.learning_id)

    def test_does_not_modify_the_original_result(self):
        store = RevenueLearningRecordStore()
        result = _make_task_result(status=STATUS_COMPLETED, output={"units": 3}, metadata={"note": "ok"})
        before = result.to_dict()
        store.record_from_task_result(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_invalid_result_type_returns_none_safely(self):
        store = RevenueLearningRecordStore()
        self.assertIsNone(store.record_from_task_result("not a result"))
        self.assertIsNone(store.record_from_task_result(None))
        self.assertEqual(len(store), 0)

    def test_multiple_results_produce_multiple_stored_records(self):
        store = RevenueLearningRecordStore()
        store.record_from_task_result(_make_task_result(result_id="r-1", status=STATUS_COMPLETED))
        store.record_from_task_result(_make_task_result(result_id="r-2", status=STATUS_FAILED))
        self.assertEqual(len(store), 2)


# ----------------------------------------------------------------------
# 11. Invalid input handling
# ----------------------------------------------------------------------
class TestInvalidInputs(unittest.TestCase):
    def test_none_is_rejected(self):
        store = RevenueLearningRecordStore()
        self.assertIsNone(store.add_record(None))
        self.assertEqual(len(store), 0)

    def test_plain_dict_is_rejected(self):
        store = RevenueLearningRecordStore()
        fake = {"learning_id": "lr-1", "task_id": "task-a"}
        self.assertIsNone(store.add_record(fake))
        self.assertEqual(len(store), 0)

    def test_string_is_rejected(self):
        store = RevenueLearningRecordStore()
        self.assertIsNone(store.add_record("not a record"))
        self.assertEqual(len(store), 0)

    def test_empty_learning_id_is_rejected(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(learning_id="")
        self.assertIsNone(store.add_record(record))
        self.assertEqual(len(store), 0)

    def test_invalid_result_status_is_rejected(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(result_status="BOGUS")
        self.assertIsNone(store.add_record(record))
        self.assertEqual(len(store), 0)

    def test_non_bool_success_is_rejected(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(success="yes")
        self.assertIsNone(store.add_record(record))
        self.assertEqual(len(store), 0)

    def test_never_raises_on_invalid_input(self):
        store = RevenueLearningRecordStore()
        try:
            store.add_record(None)
            store.add_record(123)
            store.add_record({"not": "a record"})
            store.record_from_task_result(None)
            store.record_from_task_result("not a result")
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"store raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 12. Returned collections are safe copies
# ----------------------------------------------------------------------
class TestReturnedCollectionsAreSafeCopies(unittest.TestCase):
    def test_mutating_get_all_list_does_not_affect_store(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1"))
        records = store.get_all()
        records.append(_make_learning_record(learning_id="fake"))
        records.clear()
        self.assertEqual(len(store), 1)
        self.assertEqual(len(store.get_all()), 1)

    def test_mutating_returned_record_does_not_affect_store(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(learning_id="lr-1", output={"units": 3})
        store.add_record(record)
        fetched = store.get_all()[0]
        fetched.output["units"] = 999
        fetched.metadata["extra"] = "changed"

        fresh = store.get_all()[0]
        self.assertEqual(fresh.output, {"units": 3})
        self.assertEqual(fresh.metadata, {})

    def test_two_calls_return_independent_objects(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1"))
        first = store.get_all()[0]
        second = store.get_all()[0]
        self.assertIsNot(first, second)
        self.assertEqual(first.learning_id, second.learning_id)

    def test_get_for_task_returns_independent_list(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1", task_id="task-a"))
        records = store.get_for_task("task-a")
        records.append("garbage")
        self.assertEqual(len(store.get_for_task("task-a")), 1)

    def test_get_for_opportunity_returns_independent_list(self):
        store = RevenueLearningRecordStore()
        store.add_record(_make_learning_record(learning_id="lr-1", opportunity_id="opp-a"))
        records = store.get_for_opportunity("opp-a")
        records.append("garbage")
        self.assertEqual(len(store.get_for_opportunity("opp-a")), 1)

    def test_adding_the_original_record_does_not_mutate_on_store_side_effects(self):
        store = RevenueLearningRecordStore()
        record = _make_learning_record(learning_id="lr-1", output={"units": 3})
        before = record.to_dict()
        store.add_record(record)
        after = record.to_dict()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
