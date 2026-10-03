"""
Tests for RevenueLearningAnalyzer
(financial/revenue_learning_analyzer.py).

Covers: analyze() over empty/successful/failed/mixed record lists,
unique task/opportunity counting, success-rate calculation, latest
record fields, analyze_store() over a RevenueLearningRecordStore,
read-only behavior (neither the supplied records nor the store are
modified), and safe handling of invalid records mixed into the input.

This stage only computes a plain statistical summary over already-
built RevenueLearningRecord objects - it does not learn anything, does
not execute anything, and is not wired into any learning decision
system yet.

Run directly:
    python -m unittest tests.test_revenue_learning_analyzer -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_learning_analyzer import RevenueLearningAnalyzer
from financial.revenue_learning_store import RevenueLearningRecordStore
from financial.revenue_learning import RevenueLearningRecord
from financial.revenue_task_result import STATUS_COMPLETED, STATUS_FAILED


def _make_record(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        result_status=STATUS_COMPLETED,
        success=True,
        learning_id="learning-test-1",
    )
    fields.update(overrides)
    return RevenueLearningRecord(**fields)


# ----------------------------------------------------------------------
# 1. Empty records
# ----------------------------------------------------------------------
class TestEmptyRecords(unittest.TestCase):
    def test_empty_list_returns_zero_summary(self):
        analyzer = RevenueLearningAnalyzer()
        result = analyzer.analyze([])
        self.assertEqual(result, {
            "total_records": 0,
            "successful_records": 0,
            "failed_records": 0,
            "success_rate": 0.0,
            "unique_task_count": 0,
            "unique_opportunity_count": 0,
            "latest_learning_id": None,
            "latest_task_id": None,
            "latest_opportunity_id": None,
            "latest_status": None,
            "has_data": False,
        })

    def test_none_input_returns_zero_summary(self):
        analyzer = RevenueLearningAnalyzer()
        result = analyzer.analyze(None)
        self.assertFalse(result["has_data"])
        self.assertEqual(result["total_records"], 0)


# ----------------------------------------------------------------------
# 2. Successful records
# ----------------------------------------------------------------------
class TestSuccessfulRecords(unittest.TestCase):
    def test_all_successful(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", success=True, result_status=STATUS_COMPLETED),
            _make_record(learning_id="lr-2", success=True, result_status=STATUS_COMPLETED),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["successful_records"], 2)
        self.assertEqual(result["failed_records"], 0)
        self.assertEqual(result["success_rate"], 1.0)


# ----------------------------------------------------------------------
# 3. Failed records
# ----------------------------------------------------------------------
class TestFailedRecords(unittest.TestCase):
    def test_all_failed(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", success=False, result_status=STATUS_FAILED),
            _make_record(learning_id="lr-2", success=False, result_status=STATUS_FAILED),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["successful_records"], 0)
        self.assertEqual(result["failed_records"], 2)
        self.assertEqual(result["success_rate"], 0.0)


# ----------------------------------------------------------------------
# 4. Mixed records
# ----------------------------------------------------------------------
class TestMixedRecords(unittest.TestCase):
    def test_mixed_success_and_failure(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", success=True, result_status=STATUS_COMPLETED),
            _make_record(learning_id="lr-2", success=False, result_status=STATUS_FAILED),
            _make_record(learning_id="lr-3", success=True, result_status=STATUS_COMPLETED),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["total_records"], 3)
        self.assertEqual(result["successful_records"], 2)
        self.assertEqual(result["failed_records"], 1)
        self.assertAlmostEqual(result["success_rate"], 2 / 3)


# ----------------------------------------------------------------------
# 5. Unique task counting
# ----------------------------------------------------------------------
class TestUniqueTaskCounting(unittest.TestCase):
    def test_counts_distinct_task_ids(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", task_id="task-a"),
            _make_record(learning_id="lr-2", task_id="task-b"),
            _make_record(learning_id="lr-3", task_id="task-a"),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["unique_task_count"], 2)


# ----------------------------------------------------------------------
# 6. Unique opportunity counting
# ----------------------------------------------------------------------
class TestUniqueOpportunityCounting(unittest.TestCase):
    def test_counts_distinct_opportunity_ids(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", opportunity_id="opp-a"),
            _make_record(learning_id="lr-2", opportunity_id="opp-b"),
            _make_record(learning_id="lr-3", opportunity_id="opp-a"),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["unique_opportunity_count"], 2)


# ----------------------------------------------------------------------
# 7. Success-rate calculation
# ----------------------------------------------------------------------
class TestSuccessRateCalculation(unittest.TestCase):
    def test_exact_success_rate(self):
        analyzer = RevenueLearningAnalyzer()
        statuses = [STATUS_COMPLETED, STATUS_COMPLETED, STATUS_COMPLETED, STATUS_FAILED]
        records = [
            _make_record(learning_id=f"lr-{i}", success=(status == STATUS_COMPLETED), result_status=status)
            for i, status in enumerate(statuses)
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["success_rate"], 0.75)

    def test_success_rate_within_bounds(self):
        analyzer = RevenueLearningAnalyzer()
        statuses = [STATUS_COMPLETED, STATUS_FAILED, STATUS_FAILED, STATUS_COMPLETED, STATUS_FAILED]
        records = [
            _make_record(learning_id=f"lr-{i}", success=(status == STATUS_COMPLETED), result_status=status)
            for i, status in enumerate(statuses)
        ]
        result = analyzer.analyze(records)
        self.assertGreaterEqual(result["success_rate"], 0.0)
        self.assertLessEqual(result["success_rate"], 1.0)
        self.assertIsInstance(result["success_rate"], float)


# ----------------------------------------------------------------------
# 8. Latest record information
# ----------------------------------------------------------------------
class TestLatestRecordInformation(unittest.TestCase):
    def test_latest_fields_match_last_valid_record(self):
        analyzer = RevenueLearningAnalyzer()
        records = [
            _make_record(learning_id="lr-1", task_id="task-a", opportunity_id="opp-a", result_status=STATUS_COMPLETED, success=True),
            _make_record(learning_id="lr-2", task_id="task-b", opportunity_id="opp-b", result_status=STATUS_FAILED, success=False),
        ]
        result = analyzer.analyze(records)
        self.assertEqual(result["latest_learning_id"], "lr-2")
        self.assertEqual(result["latest_task_id"], "task-b")
        self.assertEqual(result["latest_opportunity_id"], "opp-b")
        self.assertEqual(result["latest_status"], STATUS_FAILED)

    def test_latest_skips_trailing_invalid_records(self):
        analyzer = RevenueLearningAnalyzer()
        valid = _make_record(learning_id="lr-1", task_id="task-a")
        invalid = _make_record(learning_id="", task_id="task-b")  # invalid: empty learning_id
        result = analyzer.analyze([valid, invalid])
        self.assertEqual(result["latest_learning_id"], "lr-1")
        self.assertEqual(result["total_records"], 1)


# ----------------------------------------------------------------------
# 9. analyze_store()
# ----------------------------------------------------------------------
class TestAnalyzeStore(unittest.TestCase):
    def test_analyze_store_matches_analyze_of_get_all(self):
        analyzer = RevenueLearningAnalyzer()
        store = RevenueLearningRecordStore()
        store.add_record(_make_record(learning_id="lr-1", success=True, result_status=STATUS_COMPLETED))
        store.add_record(_make_record(learning_id="lr-2", success=False, result_status=STATUS_FAILED))
        via_store = analyzer.analyze_store(store)
        via_direct = analyzer.analyze(store.get_all())
        self.assertEqual(via_store, via_direct)

    def test_analyze_store_empty_store(self):
        analyzer = RevenueLearningAnalyzer()
        store = RevenueLearningRecordStore()
        result = analyzer.analyze_store(store)
        self.assertFalse(result["has_data"])
        self.assertEqual(result["total_records"], 0)

    def test_analyze_store_with_non_store_object_is_safe(self):
        analyzer = RevenueLearningAnalyzer()
        result = analyzer.analyze_store(object())
        self.assertFalse(result["has_data"])
        self.assertEqual(result["total_records"], 0)

    def test_analyze_store_with_none_is_safe(self):
        analyzer = RevenueLearningAnalyzer()
        result = analyzer.analyze_store(None)
        self.assertFalse(result["has_data"])


# ----------------------------------------------------------------------
# 10. Read-only behavior
# ----------------------------------------------------------------------
class TestReadOnlyBehavior(unittest.TestCase):
    def test_analyze_does_not_modify_the_supplied_records(self):
        analyzer = RevenueLearningAnalyzer()
        record = _make_record(learning_id="lr-1", output={"units": 3})
        before = record.to_dict()
        analyzer.analyze([record])
        after = record.to_dict()
        self.assertEqual(before, after)

    def test_analyze_does_not_reorder_the_supplied_list(self):
        analyzer = RevenueLearningAnalyzer()
        r1 = _make_record(learning_id="lr-1")
        r2 = _make_record(learning_id="lr-2")
        records = [r2, r1]
        analyzer.analyze(records)
        self.assertEqual([r.learning_id for r in records], ["lr-2", "lr-1"])

    def test_analyze_store_does_not_modify_the_store(self):
        analyzer = RevenueLearningAnalyzer()
        store = RevenueLearningRecordStore()
        store.add_record(_make_record(learning_id="lr-1"))
        store.add_record(_make_record(learning_id="lr-2"))
        before_len = len(store)
        before_all = [r.learning_id for r in store.get_all()]
        analyzer.analyze_store(store)
        self.assertEqual(len(store), before_len)
        self.assertEqual([r.learning_id for r in store.get_all()], before_all)


# ----------------------------------------------------------------------
# 11. Invalid records are handled safely
# ----------------------------------------------------------------------
class TestInvalidRecordsHandledSafely(unittest.TestCase):
    def test_none_entries_are_skipped(self):
        analyzer = RevenueLearningAnalyzer()
        records = [_make_record(learning_id="lr-1"), None]
        result = analyzer.analyze(records)
        self.assertEqual(result["total_records"], 1)

    def test_non_record_entries_are_skipped(self):
        analyzer = RevenueLearningAnalyzer()
        records = [_make_record(learning_id="lr-1"), "not a record", {"fake": True}, 42]
        result = analyzer.analyze(records)
        self.assertEqual(result["total_records"], 1)

    def test_invalid_record_instances_are_skipped(self):
        analyzer = RevenueLearningAnalyzer()
        invalid = _make_record(learning_id="lr-bad", result_status="BOGUS")
        valid = _make_record(learning_id="lr-good")
        result = analyzer.analyze([invalid, valid])
        self.assertEqual(result["total_records"], 1)
        self.assertEqual(result["latest_learning_id"], "lr-good")

    def test_all_invalid_returns_zero_summary(self):
        analyzer = RevenueLearningAnalyzer()
        records = [None, "not a record", 123]
        result = analyzer.analyze(records)
        self.assertFalse(result["has_data"])
        self.assertEqual(result["total_records"], 0)

    def test_never_raises_on_garbage_input(self):
        analyzer = RevenueLearningAnalyzer()
        try:
            analyzer.analyze(None)
            analyzer.analyze("not a list")
            analyzer.analyze(123)
            analyzer.analyze([None, "x", {}, 1, 2.5])
            analyzer.analyze_store(None)
            analyzer.analyze_store(object())
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"analyzer raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
