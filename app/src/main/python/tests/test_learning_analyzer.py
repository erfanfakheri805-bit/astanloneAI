"""
Tests for the LearningAnalyzer model (learning/learning_analyzer.py).

Covers: an empty list, one valid record, multiple valid records,
invalid records being safely ignored, the analyze_store()
convenience wrapper over LearningRecordStore, and
get_pattern_success_rate()'s success/failure ratio calculation. This
stage only computes plain numbers from records the caller already has
- nothing here mutates a record or the store.

Run directly:
    python -m unittest tests.test_learning_analyzer -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learning_analyzer import LearningAnalyzer
from learning.learning_record import LearningRecord
from learning.learning_record_store import LearningRecordStore


class TestEmptyList(unittest.TestCase):
    def test_empty_list_returns_zero_values(self):
        analyzer = LearningAnalyzer()

        result = analyzer.analyze([])

        self.assertEqual(result, {
            "total_records": 0,
            "average_confidence": 0.0,
            "highest_confidence": 0.0,
        })


class TestOneValidRecord(unittest.TestCase):
    def test_one_valid_record(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="b", outcome="c", confidence=0.7,
        )

        result = analyzer.analyze([record])

        self.assertEqual(result, {
            "total_records": 1,
            "average_confidence": 0.7,
            "highest_confidence": 0.7,
        })


class TestMultipleValidRecords(unittest.TestCase):
    def test_multiple_valid_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="ok", confidence=0.2),
            LearningRecord(source="b", pattern="p2", outcome="ok", confidence=0.9),
            LearningRecord(source="c", pattern="p3", outcome="ok", confidence=0.4),
        ]

        result = analyzer.analyze(records)

        self.assertEqual(result["total_records"], 3)
        self.assertAlmostEqual(result["average_confidence"], 0.5)
        self.assertEqual(result["highest_confidence"], 0.9)


class TestInvalidRecordsAreIgnored(unittest.TestCase):
    def test_invalid_records_are_excluded_from_the_summary(self):
        analyzer = LearningAnalyzer()
        valid = LearningRecord(source="a", pattern="b", outcome="c", confidence=0.6)
        invalid_confidence = LearningRecord(source="a", pattern="b", outcome="c", confidence=5.0)
        invalid_empty_field = LearningRecord(source="", pattern="b", outcome="c", confidence=0.5)

        result = analyzer.analyze([valid, invalid_confidence, invalid_empty_field, "not_a_record", None])

        self.assertEqual(result, {
            "total_records": 1,
            "average_confidence": 0.6,
            "highest_confidence": 0.6,
        })

    def test_all_invalid_records_returns_zero_values(self):
        analyzer = LearningAnalyzer()
        invalid = LearningRecord(source="", pattern="b", outcome="c", confidence=0.5)

        result = analyzer.analyze([invalid, "not_a_record", None])

        self.assertEqual(result, {
            "total_records": 0,
            "average_confidence": 0.0,
            "highest_confidence": 0.0,
        })


class TestAnalyzeStore(unittest.TestCase):
    def test_empty_store(self):
        analyzer = LearningAnalyzer()
        store = LearningRecordStore()

        result = analyzer.analyze_store(store)

        self.assertEqual(result, {
            "total_records": 0,
            "average_confidence": 0.0,
            "highest_confidence": 0.0,
        })

    def test_store_with_one_record(self):
        analyzer = LearningAnalyzer()
        store = LearningRecordStore()
        store.add(LearningRecord(source="a", pattern="b", outcome="c", confidence=0.7))

        result = analyzer.analyze_store(store)

        self.assertEqual(result, {
            "total_records": 1,
            "average_confidence": 0.7,
            "highest_confidence": 0.7,
        })

    def test_store_with_multiple_records(self):
        analyzer = LearningAnalyzer()
        store = LearningRecordStore()
        store.add(LearningRecord(source="a", pattern="p1", outcome="ok", confidence=0.2))
        store.add(LearningRecord(source="b", pattern="p2", outcome="ok", confidence=0.9))
        store.add(LearningRecord(source="c", pattern="p3", outcome="ok", confidence=0.4))

        result = analyzer.analyze_store(store)

        self.assertEqual(result["total_records"], 3)
        self.assertAlmostEqual(result["average_confidence"], 0.5)
        self.assertEqual(result["highest_confidence"], 0.9)

    def test_store_remains_unchanged(self):
        analyzer = LearningAnalyzer()
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="b", outcome="c", confidence=0.5, record_id="rec-1",
        ))

        analyzer.analyze_store(store)

        self.assertEqual(len(store), 1)
        stored = store.get("rec-1")
        self.assertEqual(stored.confidence, 0.5)
        self.assertEqual(stored.outcome, "c")


class TestGetPatternSuccessRate(unittest.TestCase):
    def test_no_matching_records_returns_zero(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
        ]

        result = analyzer.get_pattern_success_rate(records, "no_such_pattern")

        self.assertEqual(result, 0.0)

    def test_all_successful(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.6),
        ]

        result = analyzer.get_pattern_success_rate(records, "p1")

        self.assertEqual(result, 1.0)

    def test_all_failed(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="failure", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.6),
        ]

        result = analyzer.get_pattern_success_rate(records, "p1")

        self.assertEqual(result, 0.0)

    def test_mixed_success_and_failure(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.6),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.4),
        ]

        result = analyzer.get_pattern_success_rate(records, "p1")

        self.assertAlmostEqual(result, 2 / 3)

    def test_unrelated_patterns_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p2", outcome="failure", confidence=0.6),
        ]

        result = analyzer.get_pattern_success_rate(records, "p1")

        self.assertEqual(result, 1.0)

    def test_unrelated_outcomes_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="pending", confidence=0.6),
        ]

        result = analyzer.get_pattern_success_rate(records, "p1")

        self.assertEqual(result, 1.0)


class TestGetPatternReport(unittest.TestCase):
    def test_no_matching_records_returns_zero_values(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
        ]

        result = analyzer.get_pattern_report(records, "no_such_pattern")

        self.assertEqual(result, {
            "pattern": "no_such_pattern",
            "total_records": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "average_confidence": 0.0,
        })

    def test_empty_records_returns_zero_values(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_pattern_report([], "p1")

        self.assertEqual(result, {
            "pattern": "p1",
            "total_records": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "average_confidence": 0.0,
        })

    def test_all_successful_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.4),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.6),
        ]

        result = analyzer.get_pattern_report(records, "p1")

        self.assertEqual(result["pattern"], "p1")
        self.assertEqual(result["total_records"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["success_rate"], 1.0)
        self.assertAlmostEqual(result["average_confidence"], 0.5)

    def test_mixed_success_and_failure_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.1),
            LearningRecord(source="d", pattern="p2", outcome="failure", confidence=1.0),
            LearningRecord(source="e", pattern="p1", outcome="pending", confidence=0.7),
        ]

        result = analyzer.get_pattern_report(records, "p1")

        self.assertEqual(result["pattern"], "p1")
        self.assertEqual(result["total_records"], 3)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failure_count"], 1)
        self.assertAlmostEqual(result["success_rate"], 2 / 3)
        self.assertAlmostEqual(result["average_confidence"], (0.5 + 0.9 + 0.1) / 3)

    def test_invalid_records_are_ignored(self):
        analyzer = LearningAnalyzer()
        valid = LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5)
        invalid_confidence = LearningRecord(source="a", pattern="p1", outcome="failure", confidence=5.0)
        invalid_empty_field = LearningRecord(source="", pattern="p1", outcome="failure", confidence=0.3)

        result = analyzer.get_pattern_report(
            [valid, invalid_confidence, invalid_empty_field, "not_a_record", None], "p1",
        )

        self.assertEqual(result, {
            "pattern": "p1",
            "total_records": 1,
            "success_count": 1,
            "failure_count": 0,
            "success_rate": 1.0,
            "average_confidence": 0.5,
        })

    def test_records_remain_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.6, record_id="rec-1",
        )
        records = [record]

        analyzer.get_pattern_report(records, "p1")

        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.pattern, "p1")
        self.assertEqual(record.outcome, "success")
        self.assertEqual(record.confidence, 0.6)


class TestIsPatternReliable(unittest.TestCase):
    def test_reliable_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertTrue(result)

    def test_low_confidence_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.3),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.2),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertFalse(result)

    def test_no_records_returns_false(self):
        analyzer = LearningAnalyzer()

        result = analyzer.is_pattern_reliable([], "p1")

        self.assertFalse(result)

    def test_no_matching_records_returns_false(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="other", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertFalse(result)

    def test_custom_threshold(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.5),
        ]

        self.assertFalse(analyzer.is_pattern_reliable(records, "p1", min_confidence=0.9))
        self.assertTrue(analyzer.is_pattern_reliable(records, "p1", min_confidence=0.5))

    def test_invalid_threshold_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_confidence="high")
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_confidence=True)

    def test_records_remain_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        analyzer.is_pattern_reliable(records, "p1")

        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


    def test_one_record_not_reliable_with_default_min_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertFalse(result)

    def test_two_valid_records_can_be_reliable(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertTrue(result)

    def test_custom_min_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        self.assertFalse(analyzer.is_pattern_reliable(records, "p1", min_records=3))

        records.append(LearningRecord(source="c", pattern="p1", outcome="success", confidence=0.9))
        self.assertTrue(analyzer.is_pattern_reliable(records, "p1", min_records=3))

        self.assertTrue(analyzer.is_pattern_reliable(records, "p1", min_records=1))

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_records=1.5)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_records="2")
        with self.assertRaises(ValueError):
            analyzer.is_pattern_reliable(records, "p1", min_records=True)

    def test_default_arguments_still_work(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_reliable(records, "p1")

        self.assertTrue(result)
        self.assertFalse(analyzer.is_pattern_reliable(records, "p1", min_confidence=0.95))


class TestIsPatternLearned(unittest.TestCase):
    def test_learned_pattern_returns_true(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_learned(records, "p1")

        self.assertTrue(result)

    def test_insufficient_records_returns_false(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
        ]

        result = analyzer.is_pattern_learned(records, "p1")

        self.assertFalse(result)

    def test_low_confidence_returns_false(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.3),
        ]

        result = analyzer.is_pattern_learned(records, "p1")

        self.assertFalse(result)

    def test_only_failure_records_can_satisfy_evidence(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="failure", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.is_pattern_learned(records, "p1")

        self.assertTrue(result)

    def test_unrelated_patterns_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.9),
        ]

        self.assertFalse(analyzer.is_pattern_learned(records, "p2"))

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "p1", min_records=1.5)

    def test_invalid_pattern_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "")
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, "   ")
        with self.assertRaises(ValueError):
            analyzer.is_pattern_learned(records, None)

    def test_empty_records_returns_false(self):
        analyzer = LearningAnalyzer()

        result = analyzer.is_pattern_learned([], "p1")

        self.assertFalse(result)

    def test_no_matching_records_returns_false(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="other", outcome="success", confidence=0.9),
        ]

        result = analyzer.is_pattern_learned(records, "p1")

        self.assertFalse(result)

    def test_records_remain_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        analyzer.is_pattern_learned(records, "p1")

        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


class TestGetPatternLearningStatus(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_pattern_learning_status([], "p1")

        self.assertEqual(result, {
            "pattern": "p1",
            "record_count": 0,
            "average_confidence": 0.0,
            "success_count": 0,
            "failure_count": 0,
            "is_reliable": False,
            "is_learned": False,
        })

    def test_matching_success_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.6),
        ]

        result = analyzer.get_pattern_learning_status(records, "p1")

        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failure_count"], 0)
        self.assertAlmostEqual(result["average_confidence"], 0.7)

    def test_matching_failure_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="failure", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.7),
        ]

        result = analyzer.get_pattern_learning_status(records, "p1")

        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["failure_count"], 2)
        self.assertAlmostEqual(result["average_confidence"], 0.8)

    def test_mixed_success_and_failure_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.3),
            LearningRecord(source="c", pattern="p1", outcome="pending", confidence=0.5),
        ]

        result = analyzer.get_pattern_learning_status(records, "p1")

        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertAlmostEqual(result["average_confidence"], 0.6)

    def test_reliable_but_not_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_pattern_learning_status(records, "p1", min_records=3)

        # With min_records=3 and only 2 matching records, neither
        # reliable nor learned should be true despite high confidence.
        self.assertFalse(result["is_reliable"])
        self.assertFalse(result["is_learned"])

    def test_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
        ]

        result = analyzer.get_pattern_learning_status(records, "p1")

        self.assertTrue(result["is_reliable"])
        self.assertTrue(result["is_learned"])

    def test_unrelated_patterns_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_pattern_learning_status(records, "p2")

        self.assertEqual(result["record_count"], 1)
        self.assertFalse(result["is_reliable"])
        self.assertFalse(result["is_learned"])

    def test_invalid_pattern_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, "")
        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, None)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, "p1", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, "p1", min_confidence=-0.1)

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, "p1", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.get_pattern_learning_status(records, "p1", min_records=1.5)

    def test_returns_fresh_dict_and_records_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        result_a = analyzer.get_pattern_learning_status(records, "p1")
        result_b = analyzer.get_pattern_learning_status(records, "p1")

        self.assertIsNot(result_a, result_b)
        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


class TestFindLearnedPatterns(unittest.TestCase):
    def test_no_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.find_learned_patterns([])

        self.assertEqual(result, [])

    def test_one_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, ["p1"])

    def test_multiple_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p2", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p2", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="p1", outcome="failure", confidence=0.8),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, ["p1", "p2"])

    def test_insufficient_evidence_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, [])

    def test_low_confidence_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.3),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, [])

    def test_unrelated_patterns_not_mixed(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.1),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, ["p1"])

    def test_invalid_records_are_ignored(self):
        analyzer = LearningAnalyzer()
        valid_a = LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9)
        valid_b = LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9)
        invalid_confidence = LearningRecord(source="c", pattern="p2", outcome="success", confidence=5.0)
        invalid_empty_field = LearningRecord(source="", pattern="p2", outcome="failure", confidence=0.9)

        result = analyzer.find_learned_patterns(
            [valid_a, valid_b, invalid_confidence, invalid_empty_field, "not_a_record", None],
        )

        self.assertEqual(result, ["p1"])

    def test_non_success_failure_outcomes_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="pending", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="unknown", confidence=0.9),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, [])

    def test_deterministic_alphabetical_ordering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="f", pattern="mango", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_learned_patterns(records)

        self.assertEqual(result, ["apple", "mango", "zebra"])

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_confidence="high")
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns([], min_confidence=1.5)

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns(records, min_records=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_learned_patterns([], min_records=0)

    def test_records_remain_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        analyzer.find_learned_patterns(records)

        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


class TestGetLearnedPatternSummary(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_learned_pattern_summary([])

        self.assertEqual(result, {
            "learned_patterns": [],
            "count": 0,
            "min_confidence": 0.7,
            "min_records": 2,
        })

    def test_one_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_learned_pattern_summary(records)

        self.assertEqual(result["learned_patterns"], ["p1"])
        self.assertEqual(result["count"], 1)

    def test_multiple_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_learned_pattern_summary(records)

        self.assertEqual(result["learned_patterns"], ["apple", "zebra"])
        self.assertEqual(result["count"], 2)

    def test_no_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.1),
        ]

        result = analyzer.get_learned_pattern_summary(records)

        self.assertEqual(result["learned_patterns"], [])
        self.assertEqual(result["count"], 0)

    def test_deterministic_ordering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="banana", outcome="success", confidence=0.9),
            LearningRecord(source="f", pattern="banana", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.get_learned_pattern_summary(records)
        result_b = analyzer.get_learned_pattern_summary(records)

        self.assertEqual(result_a["learned_patterns"], ["apple", "banana", "mango"])
        self.assertEqual(result_a["learned_patterns"], result_b["learned_patterns"])

    def test_count_matches_learned_patterns_length(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="failure", confidence=0.8),
            LearningRecord(source="d", pattern="p2", outcome="failure", confidence=0.8),
            LearningRecord(source="e", pattern="p3", outcome="success", confidence=0.1),
        ]

        result = analyzer.get_learned_pattern_summary(records)

        self.assertEqual(result["count"], len(result["learned_patterns"]))
        self.assertEqual(result["count"], 2)

    def test_custom_confidence_threshold(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.5),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.5),
        ]

        low_threshold = analyzer.get_learned_pattern_summary(records, min_confidence=0.4)
        high_threshold = analyzer.get_learned_pattern_summary(records, min_confidence=0.9)

        self.assertEqual(low_threshold["learned_patterns"], ["p1"])
        self.assertEqual(low_threshold["min_confidence"], 0.4)
        self.assertEqual(high_threshold["learned_patterns"], [])
        self.assertEqual(high_threshold["min_confidence"], 0.9)

    def test_custom_min_records_threshold(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        strict = analyzer.get_learned_pattern_summary(records, min_records=3)
        lenient = analyzer.get_learned_pattern_summary(records, min_records=1)

        self.assertEqual(strict["learned_patterns"], [])
        self.assertEqual(strict["min_records"], 3)
        self.assertEqual(lenient["learned_patterns"], ["p1"])
        self.assertEqual(lenient["min_records"], 1)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_summary([], min_records=1.5)

    def test_returns_fresh_dict_and_records_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        result_a = analyzer.get_learned_pattern_summary(records)
        result_b = analyzer.get_learned_pattern_summary(records)

        self.assertIsNot(result_a, result_b)
        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


class TestGetLearnedPatternDetails(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_learned_pattern_details([])

        self.assertEqual(result, [])

    def test_one_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "p1")
        self.assertEqual(result[0]["record_count"], 2)

    def test_multiple_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertEqual([entry["pattern"] for entry in result], ["apple", "zebra"])

    def test_mixed_success_and_failure_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.7),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["record_count"], 3)
        self.assertEqual(result[0]["success_count"], 2)
        self.assertEqual(result[0]["failure_count"], 1)

    def test_correct_success_rate(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.7),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertAlmostEqual(result[0]["success_rate"], 2 / 3)

    def test_correct_average_confidence(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.7),
            LearningRecord(source="c", pattern="p1", outcome="pending", confidence=0.1),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertAlmostEqual(result[0]["average_confidence"], 0.8)

    def test_insufficient_evidence_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertEqual(result, [])

    def test_low_confidence_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.1),
        ]

        result = analyzer.get_learned_pattern_details(records)

        self.assertEqual(result, [])

    def test_deterministic_alphabetical_ordering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="banana", outcome="success", confidence=0.9),
            LearningRecord(source="f", pattern="banana", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.get_learned_pattern_details(records)
        result_b = analyzer.get_learned_pattern_details(records)

        patterns = [entry["pattern"] for entry in result_a]
        self.assertEqual(patterns, ["apple", "banana", "mango"])
        self.assertEqual(patterns, [entry["pattern"] for entry in result_b])
        self.assertIsNot(result_a, result_b)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.get_learned_pattern_details([], min_records=1.5)

    def test_records_remain_unchanged(self):
        analyzer = LearningAnalyzer()
        record = LearningRecord(
            source="a", pattern="p1", outcome="success", confidence=0.9, record_id="rec-1",
        )
        records = [record]

        analyzer.get_learned_pattern_details(records)

        self.assertEqual(len(records), 1)
        self.assertEqual(record.record_id, "rec-1")
        self.assertEqual(record.confidence, 0.9)


class TestFindHighestConfidenceLearnedPattern(unittest.TestCase):
    def test_no_learned_patterns_returns_none(self):
        analyzer = LearningAnalyzer()

        result = analyzer.find_highest_confidence_learned_pattern([])

        self.assertIsNone(result)

    def test_one_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertEqual(result["pattern"], "p1")
        self.assertAlmostEqual(result["average_confidence"], 0.85)

    def test_multiple_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertIsNotNone(result)
        self.assertIn(result["pattern"], ("p1", "p2"))

    def test_highest_confidence_is_selected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="high", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="high", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertEqual(result["pattern"], "high")
        self.assertAlmostEqual(result["average_confidence"], 0.925)

    def test_equal_confidence_uses_alphabetical_tie_break(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertEqual(result["pattern"], "apple")

    def test_insufficient_records_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="single", outcome="success", confidence=0.99),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="p1", outcome="success", confidence=0.8),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertEqual(result["pattern"], "p1")

    def test_low_confidence_patterns_are_ignored(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.1),
        ]

        result = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertIsNone(result)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.find_highest_confidence_learned_pattern([], min_records=1.5)

    def test_returned_result_is_a_safe_copy(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.find_highest_confidence_learned_pattern(records)
        result_a["pattern"] = "mutated"
        result_b = analyzer.find_highest_confidence_learned_pattern(records)

        self.assertEqual(result_b["pattern"], "p1")
        self.assertIsNot(result_a, result_b)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "p1")
        self.assertEqual(records[0].confidence, 0.8)


class TestRankLearnedPatterns(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.rank_learned_patterns([])

        self.assertEqual(result, [])

    def test_one_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "p1")

    def test_multiple_learned_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.9),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual(len(result), 2)
        self.assertEqual({entry["pattern"] for entry in result}, {"p1", "p2"})

    def test_descending_confidence_ordering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="high", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="high", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="mid", outcome="success", confidence=0.85),
            LearningRecord(source="f", pattern="mid", outcome="success", confidence=0.8),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual([entry["pattern"] for entry in result], ["high", "mid", "low"])

    def test_alphabetical_tie_breaking(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="mango", outcome="success", confidence=0.9),
            LearningRecord(source="f", pattern="mango", outcome="success", confidence=0.9),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual(
            [entry["pattern"] for entry in result], ["apple", "mango", "zebra"],
        )

    def test_insufficient_evidence_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="single", outcome="success", confidence=0.99),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="p1", outcome="success", confidence=0.8),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])

    def test_low_confidence_patterns_excluded(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.1),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual(result, [])

    def test_unrelated_patterns_ranked_independently(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="failure", confidence=0.1),
            LearningRecord(source="d", pattern="p2", outcome="failure", confidence=0.1),
        ]

        result = analyzer.rank_learned_patterns(records)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.rank_learned_patterns([], min_records=1.5)

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.rank_learned_patterns(records)
        result_a[0]["pattern"] = "mutated"
        result_b = analyzer.rank_learned_patterns(records)

        self.assertEqual(result_b[0]["pattern"], "p1")
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a[0], result_b[0])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "p1")
        self.assertEqual(records[0].confidence, 0.8)


class TestGetTopLearnedPatterns(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_top_learned_patterns([])

        self.assertEqual(result, [])

    def test_fewer_patterns_than_limit(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_top_learned_patterns(records, limit=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "p1")

    def test_exactly_limit_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.8),
        ]

        result = analyzer.get_top_learned_patterns(records, limit=2)

        self.assertEqual(len(result), 2)
        self.assertEqual([entry["pattern"] for entry in result], ["p1", "p2"])

    def test_more_patterns_than_limit(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.95),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="p3", outcome="success", confidence=0.8),
            LearningRecord(source="f", pattern="p3", outcome="success", confidence=0.8),
        ]

        result = analyzer.get_top_learned_patterns(records, limit=2)

        self.assertEqual(len(result), 2)
        self.assertEqual([entry["pattern"] for entry in result], ["p1", "p2"])

    def test_correct_ranking_order(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="high", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="high", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="mid", outcome="success", confidence=0.85),
            LearningRecord(source="f", pattern="mid", outcome="success", confidence=0.8),
        ]

        result = analyzer.get_top_learned_patterns(records, limit=3)

        self.assertEqual([entry["pattern"] for entry in result], ["high", "mid", "low"])

    def test_limit_one(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="low", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="high", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="high", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_top_learned_patterns(records, limit=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "high")

    def test_invalid_limit_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, limit=0)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, limit=-1)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, limit=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, limit="5")
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, limit=True)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.get_top_learned_patterns([], min_records=1.5)

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.get_top_learned_patterns(records, limit=1)
        result_a[0]["pattern"] = "mutated"
        result_b = analyzer.get_top_learned_patterns(records, limit=1)

        self.assertEqual(result_b[0]["pattern"], "p1")
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a[0], result_b[0])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "p1")
        self.assertEqual(records[0].confidence, 0.8)


class TestFilterLearnedPatternsBySuccessRate(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.filter_learned_patterns_by_success_rate([])

        self.assertEqual(result, [])

    def test_all_patterns_pass_threshold(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.8),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=0.5)

        self.assertEqual([entry["pattern"] for entry in result], ["p1", "p2"])

    def test_some_patterns_filtered_out(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="failure", confidence=0.8),
            LearningRecord(source="d", pattern="p2", outcome="failure", confidence=0.8),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=0.5)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])

    def test_none_pass_threshold(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="failure", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=0.5)

        self.assertEqual(result, [])

    def test_exact_threshold_match(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=0.5)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])
        self.assertAlmostEqual(result[0]["success_rate"], 0.5)

    def test_zero_success_rate(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="failure", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=0.0)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])
        self.assertAlmostEqual(result[0]["success_rate"], 0.0)

    def test_one_hundred_percent_success_rate(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=1.0)

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])
        self.assertAlmostEqual(result[0]["success_rate"], 1.0)

    def test_invalid_min_success_rate_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=1.5)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate="high")
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_success_rate=True)

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.filter_learned_patterns_by_success_rate([], min_records=1.5)

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.filter_learned_patterns_by_success_rate(records)
        result_a[0]["pattern"] = "mutated"
        result_b = analyzer.filter_learned_patterns_by_success_rate(records)

        self.assertEqual(result_b[0]["pattern"], "p1")
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a[0], result_b[0])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "p1")
        self.assertEqual(records[0].confidence, 0.8)


class TestFindReliableSuccessfulPatterns(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.find_reliable_successful_patterns([])

        self.assertEqual(result, [])

    def test_one_qualifying_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_reliable_successful_patterns(records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "p1")

    def test_multiple_qualifying_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p2", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="p2", outcome="success", confidence=0.8),
        ]

        result = analyzer.find_reliable_successful_patterns(records)

        self.assertEqual([entry["pattern"] for entry in result], ["p1", "p2"])

    def test_low_success_rate_is_rejected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="failure", confidence=0.9),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.find_reliable_successful_patterns(records, min_success_rate=0.7)

        self.assertEqual(result, [])

    def test_low_confidence_is_rejected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.3),
        ]

        result = analyzer.find_reliable_successful_patterns(records)

        self.assertEqual(result, [])

    def test_insufficient_records_are_rejected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.95),
        ]

        result = analyzer.find_reliable_successful_patterns(records)

        self.assertEqual(result, [])

    def test_exact_threshold_values_are_accepted(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.75),
        ]

        result = analyzer.find_reliable_successful_patterns(
            records, min_success_rate=2 / 3, min_confidence=0.75,
        )

        self.assertEqual([entry["pattern"] for entry in result], ["p1"])

    def test_mixed_success_and_failure_records(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="p1", outcome="failure", confidence=0.9),
        ]

        result = analyzer.find_reliable_successful_patterns(records, min_success_rate=0.5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["success_count"], 2)
        self.assertEqual(result[0]["failure_count"], 1)
        self.assertAlmostEqual(result[0]["success_rate"], 2 / 3)

    def test_invalid_min_success_rate_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_success_rate=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_success_rate="high")

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns([], min_confidence="high")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.9),
        ]

        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_records=0)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns(records, min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.find_reliable_successful_patterns([], min_records=1.5)

    def test_deterministic_ranking(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="zebra", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="apple", outcome="success", confidence=0.9),
            LearningRecord(source="e", pattern="mango", outcome="success", confidence=0.8),
            LearningRecord(source="f", pattern="mango", outcome="success", confidence=0.8),
        ]

        result_a = analyzer.find_reliable_successful_patterns(records)
        result_b = analyzer.find_reliable_successful_patterns(records)

        patterns = [entry["pattern"] for entry in result_a]
        self.assertEqual(patterns, ["apple", "zebra", "mango"])
        self.assertEqual(patterns, [entry["pattern"] for entry in result_b])

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="p1", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="p1", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.find_reliable_successful_patterns(records)
        result_a[0]["pattern"] = "mutated"
        result_b = analyzer.find_reliable_successful_patterns(records)

        self.assertEqual(result_b[0]["pattern"], "p1")
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a[0], result_b[0])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "p1")
        self.assertEqual(records[0].confidence, 0.8)


class TestFindRelevantLearnedPatterns(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.find_relevant_learned_patterns([], "net.")

        self.assertEqual(result, [])

    def test_matching_prefix(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "net.")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern"], "net.retry")

    def test_non_matching_prefix(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "ui.")

        self.assertEqual(result, [])

    def test_multiple_matching_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.8),
            LearningRecord(source="e", pattern="ui.button", outcome="success", confidence=0.95),
            LearningRecord(source="f", pattern="ui.button", outcome="success", confidence=0.95),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "net.")

        self.assertEqual(
            sorted(entry["pattern"] for entry in result),
            ["net.retry", "net.timeout"],
        )

    def test_success_rate_filtering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="failure", confidence=0.9),
            LearningRecord(source="c", pattern="net.retry", outcome="failure", confidence=0.9),
        ]

        result = analyzer.find_relevant_learned_patterns(
            records, "net.", min_success_rate=0.7,
        )

        self.assertEqual(result, [])

    def test_confidence_filtering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.3),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "net.")

        self.assertEqual(result, [])

    def test_minimum_record_filtering(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.95),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "net.")

        self.assertEqual(result, [])

    def test_correct_sorting(self):
        analyzer = LearningAnalyzer()
        records = [
            # net.a: confidence 0.8, success_rate 1.0
            LearningRecord(source="a", pattern="net.a", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.a", outcome="success", confidence=0.8),
            # net.b: confidence 0.8, success_rate 0.5 (still >= min_success_rate below)
            LearningRecord(source="c", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.b", outcome="failure", confidence=0.8),
            # net.c: confidence 0.9, success_rate 1.0
            LearningRecord(source="e", pattern="net.c", outcome="success", confidence=0.9),
            LearningRecord(source="f", pattern="net.c", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_relevant_learned_patterns(
            records, "net.", min_success_rate=0.5,
        )

        self.assertEqual(
            [entry["pattern"] for entry in result],
            ["net.c", "net.a", "net.b"],
        )

    def test_exact_prefix_behavior(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="network", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="network", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="net", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="net", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_relevant_learned_patterns(records, "net")

        self.assertEqual(
            sorted(entry["pattern"] for entry in result),
            ["net", "network"],
        )

    def test_invalid_pattern_prefix_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "")
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "   ")
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], None)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], 123)

    def test_invalid_min_success_rate_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_success_rate=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_success_rate=True)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_success_rate="0.7")

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_confidence=True)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_confidence="0.7")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_records=True)
        with self.assertRaises(ValueError):
            analyzer.find_relevant_learned_patterns([], "net.", min_records=1.5)

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.find_relevant_learned_patterns(records, "net.")
        result_a[0]["pattern"] = "mutated"
        result_b = analyzer.find_relevant_learned_patterns(records, "net.")

        self.assertEqual(result_b[0]["pattern"], "net.retry")
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a[0], result_b[0])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "net.retry")
        self.assertEqual(records[0].confidence, 0.8)


class TestFindBestRelevantLearnedPattern(unittest.TestCase):
    def test_empty_records_returns_none(self):
        analyzer = LearningAnalyzer()

        result = analyzer.find_best_relevant_learned_pattern([], "net.")

        self.assertIsNone(result)

    def test_no_matching_prefix_returns_none(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="ui.button", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="ui.button", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertIsNone(result)

    def test_one_matching_learned_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertIsNotNone(result)
        self.assertEqual(result["pattern"], "net.retry")

    def test_multiple_matching_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.9),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertEqual(result["pattern"], "net.timeout")

    def test_highest_confidence_is_selected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.a", outcome="success", confidence=0.75),
            LearningRecord(source="b", pattern="net.a", outcome="success", confidence=0.75),
            LearningRecord(source="c", pattern="net.b", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="net.b", outcome="success", confidence=0.95),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertEqual(result["pattern"], "net.b")

    def test_success_rate_tie_breaking(self):
        analyzer = LearningAnalyzer()
        records = [
            # net.a: confidence 0.8, success_rate 0.5
            LearningRecord(source="a", pattern="net.a", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.a", outcome="failure", confidence=0.8),
            # net.b: confidence 0.8, success_rate 1.0
            LearningRecord(source="c", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.b", outcome="success", confidence=0.8),
        ]

        result = analyzer.find_best_relevant_learned_pattern(
            records, "net.", min_success_rate=0.5,
        )

        self.assertEqual(result["pattern"], "net.b")

    def test_record_count_tie_breaking(self):
        analyzer = LearningAnalyzer()
        records = [
            # net.a: confidence 0.8, success_rate 1.0, record_count 2
            LearningRecord(source="a", pattern="net.a", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.a", outcome="success", confidence=0.8),
            # net.b: confidence 0.8, success_rate 1.0, record_count 3
            LearningRecord(source="c", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="e", pattern="net.b", outcome="success", confidence=0.8),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertEqual(result["pattern"], "net.b")

    def test_alphabetical_final_tie_breaking(self):
        analyzer = LearningAnalyzer()
        records = [
            # net.a and net.b: identical confidence, success_rate, record_count
            LearningRecord(source="a", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.b", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="net.a", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.a", outcome="success", confidence=0.8),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertEqual(result["pattern"], "net.a")

    def test_filtering_is_respected(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.3),
        ]

        result = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertIsNone(result)

    def test_invalid_pattern_prefix_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "")
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "   ")
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], None)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], 123)

    def test_invalid_min_success_rate_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_success_rate=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_success_rate=True)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_success_rate="0.7")

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_confidence=True)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_confidence="0.7")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_records=True)
        with self.assertRaises(ValueError):
            analyzer.find_best_relevant_learned_pattern([], "net.", min_records=1.5)

    def test_returned_result_is_a_safe_copy(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.find_best_relevant_learned_pattern(records, "net.")
        result_a["pattern"] = "mutated"
        result_b = analyzer.find_best_relevant_learned_pattern(records, "net.")

        self.assertEqual(result_b["pattern"], "net.retry")
        self.assertIsNot(result_a, result_b)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "net.retry")
        self.assertEqual(records[0].confidence, 0.8)


class TestGetRelevantLearningContext(unittest.TestCase):
    def test_empty_records(self):
        analyzer = LearningAnalyzer()

        result = analyzer.get_relevant_learning_context([], "net.")

        self.assertEqual(result, {
            "pattern_prefix": "net.",
            "match_count": 0,
            "best_pattern": None,
            "patterns": [],
        })

    def test_matching_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_relevant_learning_context(records, "net.")

        self.assertEqual([entry["pattern"] for entry in result["patterns"]], ["net.retry"])

    def test_no_matching_patterns(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="ui.button", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="ui.button", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_relevant_learning_context(records, "net.")

        self.assertEqual(result, {
            "pattern_prefix": "net.",
            "match_count": 0,
            "best_pattern": None,
            "patterns": [],
        })

    def test_correct_match_count(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.8),
        ]

        result = analyzer.get_relevant_learning_context(records, "net.")

        self.assertEqual(result["match_count"], 2)
        self.assertEqual(result["match_count"], len(result["patterns"]))

    def test_correct_best_pattern(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.95),
        ]

        result = analyzer.get_relevant_learning_context(records, "net.")

        self.assertIsNotNone(result["best_pattern"])
        self.assertEqual(result["best_pattern"]["pattern"], "net.timeout")

    def test_filtering_parameters(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.2),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.3),
        ]

        result = analyzer.get_relevant_learning_context(records, "net.")

        self.assertEqual(result["match_count"], 0)
        self.assertIsNone(result["best_pattern"])
        self.assertEqual(result["patterns"], [])

    def test_exact_prefix_matching(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="network", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="network", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="net", outcome="success", confidence=0.9),
            LearningRecord(source="d", pattern="net", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_relevant_learning_context(records, "net")

        self.assertEqual(
            sorted(entry["pattern"] for entry in result["patterns"]),
            ["net", "network"],
        )

    def test_invalid_pattern_prefix_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "")
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "   ")
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], None)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], 123)

    def test_invalid_min_success_rate_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_success_rate=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_success_rate=True)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_success_rate="0.7")

    def test_invalid_min_confidence_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_confidence=1.5)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_confidence=True)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_confidence="0.7")

    def test_invalid_min_records_raises_value_error(self):
        analyzer = LearningAnalyzer()

        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_records=0)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_records=-1)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_records=True)
        with self.assertRaises(ValueError):
            analyzer.get_relevant_learning_context([], "net.", min_records=1.5)

    def test_safe_returned_copies(self):
        analyzer = LearningAnalyzer()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.get_relevant_learning_context(records, "net.")
        result_a["patterns"][0]["pattern"] = "mutated"
        result_a["best_pattern"]["pattern"] = "mutated"
        result_a["patterns"].append("extra")
        result_b = analyzer.get_relevant_learning_context(records, "net.")

        self.assertEqual(result_b["patterns"][0]["pattern"], "net.retry")
        self.assertEqual(result_b["best_pattern"]["pattern"], "net.retry")
        self.assertEqual(len(result_b["patterns"]), 1)
        self.assertIsNot(result_a, result_b)
        self.assertIsNot(result_a["patterns"], result_b["patterns"])
        self.assertIsNot(result_a["best_pattern"], result_b["best_pattern"])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "net.retry")
        self.assertEqual(records[0].confidence, 0.8)


if __name__ == "__main__":
    unittest.main()
