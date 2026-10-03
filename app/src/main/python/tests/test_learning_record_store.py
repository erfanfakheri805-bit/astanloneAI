"""
Tests for the LearningRecordStore model (learning/learning_record_store.py).

Covers: adding and retrieving a valid record, rejecting invalid
records, rejecting a duplicate record_id without overwriting the
original, get_all returning a safe collection, find_by_pattern,
find_by_source, find_by_outcome exact matching, find_highest_confidence
tie-breaking, get_pattern_confidence averaging, get_latest_by_pattern
and get_latest_by_source recency ordering (including empty/invalid
inputs), and clear. This stage
only stores/retrieves already-built LearningRecord objects - nothing
here persists anything or touches the existing learning pipeline.

Run directly:
    python -m unittest tests.test_learning_record_store -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learning_record import LearningRecord
from learning.learning_record_store import LearningRecordStore


def _make_record(record_id=None, outcome="succeeded"):
    return LearningRecord(
        source="user_feedback",
        pattern="retry_after_timeout",
        outcome=outcome,
        confidence=0.8,
        record_id=record_id,
    )


class TestAddAndGet(unittest.TestCase):
    def test_add_then_get_returns_the_same_record(self):
        store = LearningRecordStore()
        record = _make_record(record_id="rec-1")

        added = store.add(record)

        self.assertIs(added, record)
        fetched = store.get("rec-1")
        self.assertEqual(fetched.to_dict(), record.to_dict())

    def test_get_missing_id_returns_none(self):
        store = LearningRecordStore()

        self.assertIsNone(store.get("does-not-exist"))


class TestInvalidRecordRejection(unittest.TestCase):
    def test_invalid_record_is_rejected(self):
        store = LearningRecordStore()
        invalid = LearningRecord(source="", pattern="b", outcome="c", confidence=0.5)

        result = store.add(invalid)

        self.assertIsNone(result)
        self.assertEqual(len(store), 0)

    def test_non_learning_record_is_rejected(self):
        store = LearningRecordStore()

        result = store.add({"record_id": "fake", "confidence": 0.5})

        self.assertIsNone(result)
        self.assertEqual(len(store), 0)


class TestDuplicateIdRejection(unittest.TestCase):
    def test_duplicate_id_does_not_overwrite_existing_record(self):
        store = LearningRecordStore()
        first = _make_record(record_id="rec-1", outcome="first")
        second = _make_record(record_id="rec-1", outcome="second")

        store.add(first)
        result = store.add(second)

        self.assertIsNone(result)
        self.assertEqual(store.get("rec-1").outcome, "first")
        self.assertEqual(len(store), 1)


class TestGetAll(unittest.TestCase):
    def test_get_all_returns_every_added_record(self):
        store = LearningRecordStore()
        first = _make_record(record_id="rec-1")
        second = _make_record(record_id="rec-2")
        store.add(first)
        store.add(second)

        all_records = store.get_all()

        self.assertEqual(len(all_records), 2)
        self.assertEqual({r.record_id for r in all_records}, {"rec-1", "rec-2"})

    def test_get_all_returns_safe_copies(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        all_records = store.get_all()
        all_records[0].outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "succeeded")


class TestFindByPattern(unittest.TestCase):
    def test_no_matching_records_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.find_by_pattern("no_such_pattern")

        self.assertEqual(result, [])

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        )
        store.add(match)

        result = store.find_by_pattern("retry_after_timeout")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].record_id, "rec-1")

    def test_multiple_matching_records(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="b", pattern="retry_after_timeout", outcome="failed",
            confidence=0.6, record_id="rec-2",
        ))

        result = store.find_by_pattern("retry_after_timeout")

        self.assertEqual({r.record_id for r in result}, {"rec-1", "rec-2"})

    def test_different_patterns_are_ignored(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="b", pattern="skip_after_error", outcome="ok",
            confidence=0.5, record_id="rec-2",
        ))

        result = store.find_by_pattern("retry_after_timeout")

        self.assertEqual([r.record_id for r in result], ["rec-1"])

    def test_empty_pattern_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertEqual(store.find_by_pattern(""), [])
        self.assertEqual(store.find_by_pattern(None), [])

    def test_find_by_pattern_returns_safe_copies(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.find_by_pattern("retry_after_timeout")
        result[0].outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "ok")


class TestFindBySource(unittest.TestCase):
    def test_no_matching_records_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.find_by_source("no_such_source")

        self.assertEqual(result, [])

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1",
        )
        store.add(match)

        result = store.find_by_source("user_feedback")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].record_id, "rec-1")

    def test_multiple_records_from_the_same_source(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="user_feedback", pattern="b", outcome="failed",
            confidence=0.6, record_id="rec-2",
        ))

        result = store.find_by_source("user_feedback")

        self.assertEqual({r.record_id for r in result}, {"rec-1", "rec-2"})

    def test_records_from_other_sources_are_ignored(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="system_diagnostics", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-2",
        ))

        result = store.find_by_source("user_feedback")

        self.assertEqual([r.record_id for r in result], ["rec-1"])

    def test_empty_source_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertEqual(store.find_by_source(""), [])
        self.assertEqual(store.find_by_source(None), [])

    def test_find_by_source_returns_safe_copies(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.find_by_source("user_feedback")
        result[0].outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "ok")


class TestFindByOutcome(unittest.TestCase):
    def test_no_matching_records_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.find_by_outcome("no_such_outcome")

        self.assertEqual(result, [])

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="a", pattern="b", outcome="succeeded",
            confidence=0.5, record_id="rec-1",
        )
        store.add(match)

        result = store.find_by_outcome("succeeded")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].record_id, "rec-1")

    def test_multiple_records_with_the_same_outcome(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="b", outcome="succeeded",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="c", pattern="d", outcome="succeeded",
            confidence=0.6, record_id="rec-2",
        ))

        result = store.find_by_outcome("succeeded")

        self.assertEqual({r.record_id for r in result}, {"rec-1", "rec-2"})

    def test_records_with_other_outcomes_are_ignored(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="b", outcome="succeeded",
            confidence=0.5, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="a", pattern="b", outcome="failed",
            confidence=0.5, record_id="rec-2",
        ))

        result = store.find_by_outcome("succeeded")

        self.assertEqual([r.record_id for r in result], ["rec-1"])

    def test_empty_outcome_returns_empty_list(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertEqual(store.find_by_outcome(""), [])
        self.assertEqual(store.find_by_outcome(None), [])

    def test_find_by_outcome_returns_safe_copies(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="b", outcome="succeeded",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.find_by_outcome("succeeded")
        result[0].outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "succeeded")


class TestFindHighestConfidence(unittest.TestCase):
    def test_no_matching_record_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.find_highest_confidence("no_such_pattern")

        self.assertIsNone(result)

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.4, record_id="rec-1",
        )
        store.add(match)

        result = store.find_highest_confidence("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-1")

    def test_multiple_records_with_different_confidence_values(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.3, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="b", pattern="retry_after_timeout", outcome="ok",
            confidence=0.9, record_id="rec-2",
        ))
        store.add(LearningRecord(
            source="c", pattern="retry_after_timeout", outcome="ok",
            confidence=0.6, record_id="rec-3",
        ))

        result = store.find_highest_confidence("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-2")

    def test_equal_confidence_uses_deterministic_ordering(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.7, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="b", pattern="retry_after_timeout", outcome="ok",
            confidence=0.7, record_id="rec-2",
        ))

        result = store.find_highest_confidence("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-1")

    def test_empty_pattern_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertIsNone(store.find_highest_confidence(""))
        self.assertIsNone(store.find_highest_confidence(None))

    def test_find_highest_confidence_returns_a_safe_copy(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.find_highest_confidence("retry_after_timeout")
        result.outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "ok")


class TestGetPatternConfidence(unittest.TestCase):
    def test_no_matching_records_returns_zero(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.get_pattern_confidence("no_such_pattern")

        self.assertEqual(result, 0.0)

    def test_one_record(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.6, record_id="rec-1",
        ))

        result = store.get_pattern_confidence("retry_after_timeout")

        self.assertEqual(result, 0.6)

    def test_multiple_records(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.4, record_id="rec-1",
        ))
        store.add(LearningRecord(
            source="b", pattern="retry_after_timeout", outcome="ok",
            confidence=0.8, record_id="rec-2",
        ))

        result = store.get_pattern_confidence("retry_after_timeout")

        self.assertAlmostEqual(result, 0.6)

    def test_empty_pattern_returns_zero(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertEqual(store.get_pattern_confidence(""), 0.0)
        self.assertEqual(store.get_pattern_confidence(None), 0.0)

    def test_original_records_are_unchanged(self):
        store = LearningRecordStore()
        record = LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.4, record_id="rec-1",
        )
        store.add(record)

        store.get_pattern_confidence("retry_after_timeout")

        stored = store.get("rec-1")
        self.assertEqual(stored.confidence, 0.4)
        self.assertEqual(stored.outcome, "ok")


class TestGetLatestByPattern(unittest.TestCase):
    def test_no_matching_record_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.get_latest_by_pattern("no_such_pattern")

        self.assertIsNone(result)

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        )
        store.add(match)

        result = store.get_latest_by_pattern("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-1")

    def test_multiple_matching_records_returns_the_latest(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="b", pattern="retry_after_timeout", outcome="ok",
            confidence=0.6, record_id="rec-2", created_at="2026-03-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="c", pattern="retry_after_timeout", outcome="ok",
            confidence=0.4, record_id="rec-3", created_at="2026-02-01T00:00:00+00:00",
        ))

        result = store.get_latest_by_pattern("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-2")

    def test_records_with_another_pattern_are_ignored(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="b", pattern="skip_after_error", outcome="ok",
            confidence=0.5, record_id="rec-2", created_at="2026-05-01T00:00:00+00:00",
        ))

        result = store.get_latest_by_pattern("retry_after_timeout")

        self.assertEqual(result.record_id, "rec-1")

    def test_empty_pattern_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertIsNone(store.get_latest_by_pattern(""))
        self.assertIsNone(store.get_latest_by_pattern(None))

    def test_get_latest_by_pattern_returns_a_safe_copy(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="retry_after_timeout", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.get_latest_by_pattern("retry_after_timeout")
        result.outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "ok")


class TestGetLatestBySource(unittest.TestCase):
    def test_no_matching_record_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        result = store.get_latest_by_source("no_such_source")

        self.assertIsNone(result)

    def test_one_matching_record(self):
        store = LearningRecordStore()
        match = LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        )
        store.add(match)

        result = store.get_latest_by_source("user_feedback")

        self.assertEqual(result.record_id, "rec-1")

    def test_multiple_records_returns_the_latest(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="user_feedback", pattern="b", outcome="ok",
            confidence=0.6, record_id="rec-2", created_at="2026-03-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="user_feedback", pattern="c", outcome="ok",
            confidence=0.4, record_id="rec-3", created_at="2026-02-01T00:00:00+00:00",
        ))

        result = store.get_latest_by_source("user_feedback")

        self.assertEqual(result.record_id, "rec-2")

    def test_records_from_another_source_are_ignored(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1", created_at="2026-01-01T00:00:00+00:00",
        ))
        store.add(LearningRecord(
            source="system_diagnostics", pattern="b", outcome="ok",
            confidence=0.5, record_id="rec-2", created_at="2026-05-01T00:00:00+00:00",
        ))

        result = store.get_latest_by_source("user_feedback")

        self.assertEqual(result.record_id, "rec-1")

    def test_empty_source_returns_none(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))

        self.assertIsNone(store.get_latest_by_source(""))
        self.assertIsNone(store.get_latest_by_source(None))

    def test_get_latest_by_source_returns_a_safe_copy(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="user_feedback", pattern="a", outcome="ok",
            confidence=0.5, record_id="rec-1",
        ))

        result = store.get_latest_by_source("user_feedback")
        result.outcome = "tampered"

        self.assertEqual(store.get("rec-1").outcome, "ok")


class TestClear(unittest.TestCase):
    def test_clear_empties_the_store(self):
        store = LearningRecordStore()
        store.add(_make_record(record_id="rec-1"))
        store.add(_make_record(record_id="rec-2"))

        store.clear()

        self.assertEqual(len(store), 0)
        self.assertEqual(store.get_all(), [])
        self.assertIsNone(store.get("rec-1"))

    def test_clear_on_empty_store_is_safe(self):
        store = LearningRecordStore()

        store.clear()

        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
