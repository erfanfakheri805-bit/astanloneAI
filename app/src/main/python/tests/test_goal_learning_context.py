"""
Tests for GoalLearningContextAnalyzer (planning/goal_learning_context.py)
- the small read-only step that assembles a goal's normalized text
with whatever relevant learning context LearningContextProvider
currently returns for it.

Run directly:
    python -m unittest tests.test_goal_learning_context -v
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
from planning.goal_learning_context import GoalLearningContextAnalyzer


class _RaisingProvider:
    """Test double simulating a broken/failing LearningContextProvider
    - raises an unrelated exception rather than returning context."""

    def get_context(self, records, pattern_prefix, **kwargs):
        raise RuntimeError("provider is broken")


class TestGetGoalLearningContext(unittest.TestCase):
    def test_goal_with_no_learning_context(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="ui.button", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="ui.button", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_goal_learning_context(
            "connect to the network", provider, records,
        )

        self.assertEqual(result["learning_context"]["match_count"], 0)
        self.assertIsNone(result["learning_context"]["best_pattern"])
        self.assertEqual(result["learning_context"]["patterns"], [])

    def test_goal_with_matching_learning_context(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="connect.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="connect.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_goal_learning_context(
            "connect to the network", provider, records,
        )

        self.assertEqual(result["learning_context"]["match_count"], 1)
        self.assertEqual(
            result["learning_context"]["patterns"][0]["pattern"], "connect.retry",
        )
        self.assertEqual(
            result["learning_context"]["best_pattern"]["pattern"], "connect.retry",
        )

    def test_normalized_goal_handling(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()

        result = analyzer.get_goal_learning_context(
            "  Connect   to   the network  \n", provider, [],
        )

        self.assertEqual(result["normalized_goal"], "Connect to the network")
        self.assertEqual(result["goal"], "  Connect   to   the network  \n")

    def test_correct_context_returned(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="connect.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="connect.retry", outcome="success", confidence=0.9),
        ]

        result = analyzer.get_goal_learning_context(
            "Connect to the network", provider, records,
        )

        self.assertEqual(result["goal"], "Connect to the network")
        self.assertEqual(result["normalized_goal"], "Connect to the network")
        self.assertEqual(result["learning_context"]["pattern_prefix"], "connect")
        self.assertEqual(
            set(result.keys()), {"goal", "normalized_goal", "learning_context"},
        )

    def test_invalid_parameters_raise_value_error(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()

        with self.assertRaises(ValueError):
            analyzer.get_goal_learning_context(
                "connect to network", provider, [], min_success_rate=1.5,
            )
        with self.assertRaises(ValueError):
            analyzer.get_goal_learning_context(
                "connect to network", provider, [], min_confidence=-0.1,
            )
        with self.assertRaises(ValueError):
            analyzer.get_goal_learning_context(
                "connect to network", provider, [], min_records=0,
            )

    def test_provider_failure_is_handled_safely(self):
        analyzer = GoalLearningContextAnalyzer()
        broken_provider = _RaisingProvider()

        result = analyzer.get_goal_learning_context(
            "connect to the network", broken_provider, [],
        )

        self.assertEqual(result["learning_context"], {
            "pattern_prefix": "connect",
            "match_count": 0,
            "best_pattern": None,
            "patterns": [],
        })
        self.assertEqual(result["normalized_goal"], "connect to the network")

    def test_provider_failure_still_raises_for_invalid_parameters(self):
        analyzer = GoalLearningContextAnalyzer()
        broken_provider = _RaisingProvider()

        # A genuinely invalid parameter should surface as ValueError
        # even against a working provider - it is not swallowed by
        # the "handle a broken provider safely" fallback.
        provider = LearningContextProvider()
        with self.assertRaises(ValueError):
            analyzer.get_goal_learning_context(
                "connect to network", provider, [], min_records=-5,
            )

    def test_read_only_behavior(self):
        analyzer = GoalLearningContextAnalyzer()
        provider = LearningContextProvider()
        records = [
            LearningRecord(source="a", pattern="connect.retry", outcome="success", confidence=0.9),
            LearningRecord(source="b", pattern="connect.retry", outcome="success", confidence=0.9),
        ]

        result_a = analyzer.get_goal_learning_context(
            "connect to the network", provider, records,
        )
        result_a["learning_context"]["patterns"][0]["pattern"] = "mutated"
        result_a["learning_context"]["patterns"].append("extra")

        result_b = analyzer.get_goal_learning_context(
            "connect to the network", provider, records,
        )

        self.assertEqual(result_b["learning_context"]["patterns"][0]["pattern"], "connect.retry")
        self.assertEqual(len(result_b["learning_context"]["patterns"]), 1)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].pattern, "connect.retry")
        self.assertEqual(records[0].confidence, 0.9)


if __name__ == "__main__":
    unittest.main()
