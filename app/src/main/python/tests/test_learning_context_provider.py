"""
Tests for LearningContextProvider (planning/learning_context.py) -
the small read-only adapter that hands
LearningAnalyzer.get_relevant_learning_context()'s result to planning
components, with no logic of its own.

Run directly:
    python -m unittest tests.test_learning_context_provider -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learning_record import LearningRecord
from planning.learning_context import LearningContextProvider


class TestGetContext(unittest.TestCase):
    def test_empty_records(self):
        provider = LearningContextProvider()

        result = provider.get_context([], "net.")

        self.assertEqual(result, {
            "pattern_prefix": "net.",
            "match_count": 0,
            "best_pattern": None,
            "patterns": [],
        })

    def test_matching_learned_patterns(self):
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result = provider.get_context(records, "net.")

        self.assertEqual([entry["pattern"] for entry in result["patterns"]], ["net.retry"])

    def test_no_matching_patterns(self):
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="ui.button", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="ui.button", outcome="success", confidence=0.9),
        ]

        result = provider.get_context(records, "net.")

        self.assertEqual(result, {
            "pattern_prefix": "net.",
            "match_count": 0,
            "best_pattern": None,
            "patterns": [],
        })

    def test_correct_best_pattern(self):
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.95),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.95),
        ]

        result = provider.get_context(records, "net.")

        self.assertIsNotNone(result["best_pattern"])
        self.assertEqual(result["best_pattern"]["pattern"], "net.timeout")

    def test_correct_match_count(self):
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
            LearningRecord(source="c", pattern="net.timeout", outcome="success", confidence=0.8),
            LearningRecord(source="d", pattern="net.timeout", outcome="success", confidence=0.8),
        ]

        result = provider.get_context(records, "net.")

        self.assertEqual(result["match_count"], 2)
        self.assertEqual(result["match_count"], len(result["patterns"]))

    def test_invalid_prefix_raises_value_error(self):
        provider = LearningContextProvider()

        with self.assertRaises(ValueError):
            provider.get_context([], "")
        with self.assertRaises(ValueError):
            provider.get_context([], "   ")
        with self.assertRaises(ValueError):
            provider.get_context([], None)
        with self.assertRaises(ValueError):
            provider.get_context([], 123)

    def test_invalid_confidence_raises_value_error(self):
        provider = LearningContextProvider()

        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_confidence=1.5)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_confidence=-0.1)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_confidence=True)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_confidence="0.7")

    def test_invalid_success_rate_raises_value_error(self):
        provider = LearningContextProvider()

        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_success_rate=1.5)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_success_rate=-0.1)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_success_rate=True)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_success_rate="0.7")

    def test_invalid_minimum_records_raises_value_error(self):
        provider = LearningContextProvider()

        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_records=0)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_records=-1)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_records=True)
        with self.assertRaises(ValueError):
            provider.get_context([], "net.", min_records=1.5)

    def test_safe_returned_data(self):
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="net.retry", outcome="success", confidence=0.8),
            LearningRecord(source="b", pattern="net.retry", outcome="success", confidence=0.9),
        ]

        result_a = provider.get_context(records, "net.")
        result_a["patterns"][0]["pattern"] = "mutated"
        result_a["best_pattern"]["pattern"] = "mutated"
        result_a["patterns"].append("extra")
        result_b = provider.get_context(records, "net.")

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
