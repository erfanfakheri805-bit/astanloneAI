"""
Tests for the LearningRecord model (learning/learning_record.py).

Covers: a valid record, an out-of-range confidence, records missing
required string fields, and dictionary conversion. This stage adds
only the structured record itself - nothing here persists a record or
touches LearningSystem/LearningDecisionEngine.

Run directly:
    python -m unittest tests.test_learning_record -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learning_record import LearningRecord


class TestValidRecord(unittest.TestCase):
    def test_valid_record_passes_is_valid(self):
        record = LearningRecord(
            source="user_feedback",
            pattern="retry_after_timeout",
            outcome="succeeded",
            confidence=0.8,
        )

        self.assertTrue(record.is_valid())

    def test_valid_record_gets_defaults(self):
        record = LearningRecord(
            source="user_feedback",
            pattern="retry_after_timeout",
            outcome="succeeded",
            confidence=0.8,
        )

        self.assertTrue(record.record_id)
        self.assertTrue(record.created_at)
        self.assertEqual(record.metadata, {})

    def test_boundary_confidence_values_are_valid(self):
        low = LearningRecord(source="a", pattern="b", outcome="c", confidence=0.0)
        high = LearningRecord(source="a", pattern="b", outcome="c", confidence=1.0)

        self.assertTrue(low.is_valid())
        self.assertTrue(high.is_valid())


class TestInvalidConfidence(unittest.TestCase):
    def test_confidence_above_one_is_invalid(self):
        record = LearningRecord(source="a", pattern="b", outcome="c", confidence=1.5)

        self.assertFalse(record.is_valid())

    def test_negative_confidence_is_invalid(self):
        record = LearningRecord(source="a", pattern="b", outcome="c", confidence=-0.1)

        self.assertFalse(record.is_valid())

    def test_non_numeric_confidence_is_invalid(self):
        record = LearningRecord(source="a", pattern="b", outcome="c", confidence="high")

        self.assertFalse(record.is_valid())

    def test_boolean_confidence_is_invalid(self):
        # bool is technically an int subclass in Python - explicitly excluded.
        record = LearningRecord(source="a", pattern="b", outcome="c", confidence=True)

        self.assertFalse(record.is_valid())


class TestMissingRequiredFields(unittest.TestCase):
    def test_empty_source_is_invalid(self):
        record = LearningRecord(source="", pattern="b", outcome="c", confidence=0.5)

        self.assertFalse(record.is_valid())

    def test_whitespace_only_pattern_is_invalid(self):
        record = LearningRecord(source="a", pattern="   ", outcome="c", confidence=0.5)

        self.assertFalse(record.is_valid())

    def test_none_outcome_is_invalid(self):
        record = LearningRecord(source="a", pattern="b", outcome=None, confidence=0.5)

        self.assertFalse(record.is_valid())

    def test_non_string_source_is_invalid(self):
        record = LearningRecord(source=123, pattern="b", outcome="c", confidence=0.5)

        self.assertFalse(record.is_valid())

    def test_unsafe_metadata_is_invalid(self):
        record = LearningRecord(
            source="a", pattern="b", outcome="c", confidence=0.5,
            metadata={"callback": lambda: None},
        )

        self.assertFalse(record.is_valid())


class TestToDict(unittest.TestCase):
    def test_to_dict_contains_all_fields(self):
        record = LearningRecord(
            source="user_feedback",
            pattern="retry_after_timeout",
            outcome="succeeded",
            confidence=0.8,
            record_id="learning-record-test-1",
            created_at="2026-01-01T00:00:00+00:00",
            metadata={"attempts": 3},
        )

        self.assertEqual(record.to_dict(), {
            "record_id": "learning-record-test-1",
            "source": "user_feedback",
            "pattern": "retry_after_timeout",
            "outcome": "succeeded",
            "confidence": 0.8,
            "created_at": "2026-01-01T00:00:00+00:00",
            "metadata": {"attempts": 3},
        })

    def test_to_dict_round_trips_default_metadata(self):
        record = LearningRecord(source="a", pattern="b", outcome="c", confidence=0.5)

        as_dict = record.to_dict()

        self.assertEqual(as_dict["metadata"], {})
        self.assertEqual(as_dict["source"], "a")


if __name__ == "__main__":
    unittest.main()
