"""
Tests for the Goal model and GoalManager (planning/ foundation).

Covers: creating a goal, retrieving a goal, invalid/empty input, and
the structured (debugging) representation - plus a couple of checks
that Core wires GoalManager in without touching existing behaviour.

Run directly:
    python -m unittest tests.test_goal_manager -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal import Goal, STATUS_PENDING, DEFAULT_GOAL_TYPE
from planning.goal_manager import GoalManager
from core.core import Core


class TestCreateGoal(unittest.TestCase):
    def setUp(self):
        self.manager = GoalManager()

    def test_create_goal_returns_a_goal_with_expected_fields(self):
        goal = self.manager.create_goal("Book a flight to Tokyo")

        self.assertIsInstance(goal, Goal)
        self.assertTrue(goal.goal_id)
        self.assertEqual(goal.original_text, "Book a flight to Tokyo")
        self.assertEqual(goal.normalized_text, "Book a flight to Tokyo")
        self.assertEqual(goal.goal_type, DEFAULT_GOAL_TYPE)
        self.assertEqual(goal.requirements, [])
        self.assertEqual(goal.status, STATUS_PENDING)
        self.assertTrue(goal.created_at)
        self.assertEqual(goal.metadata, {})
        self.assertGreaterEqual(goal.confidence, 0.0)
        self.assertLessEqual(goal.confidence, 1.0)

    def test_create_goal_normalizes_whitespace_but_keeps_original(self):
        goal = self.manager.create_goal("  Book   a   flight  ")
        self.assertEqual(goal.original_text, "  Book   a   flight  ")
        self.assertEqual(goal.normalized_text, "Book a flight")

    def test_create_goal_accepts_goal_type_requirements_and_metadata(self):
        goal = self.manager.create_goal(
            "Plan a birthday party",
            goal_type="event_planning",
            requirements=["venue", "guest list"],
            metadata={"priority": "high"},
        )
        self.assertEqual(goal.goal_type, "event_planning")
        self.assertEqual(goal.requirements, ["venue", "guest list"])
        self.assertEqual(goal.metadata, {"priority": "high"})

    def test_created_goals_are_stored_and_get_unique_ids(self):
        first = self.manager.create_goal("Learn Python")
        second = self.manager.create_goal("Learn Python")
        self.assertNotEqual(first.goal_id, second.goal_id)
        self.assertEqual(len(self.manager), 2)


class TestRetrieveGoal(unittest.TestCase):
    def setUp(self):
        self.manager = GoalManager()

    def test_get_goal_returns_the_stored_goal(self):
        created = self.manager.create_goal("Write a report")
        fetched = self.manager.get_goal(created.goal_id)
        self.assertIs(fetched, created)

    def test_get_goal_returns_none_for_unknown_id(self):
        self.assertIsNone(self.manager.get_goal("does-not-exist"))

    def test_all_goals_returns_every_stored_goal(self):
        first = self.manager.create_goal("Goal one")
        second = self.manager.create_goal("Goal two")
        self.assertEqual(self.manager.all_goals(), [first, second])


class TestInvalidInput(unittest.TestCase):
    def setUp(self):
        self.manager = GoalManager()

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            self.manager.create_goal("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            self.manager.create_goal("   \n\t  ")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            self.manager.create_goal(None)

    def test_failed_creation_stores_nothing(self):
        try:
            self.manager.create_goal("")
        except ValueError:
            pass
        self.assertEqual(len(self.manager), 0)

    def test_goal_rejects_unknown_status_directly(self):
        with self.assertRaises(ValueError):
            Goal(
                goal_id="goal-x",
                original_text="x",
                normalized_text="x",
                status="not_a_real_status",
            )


class TestStructuredRepresentation(unittest.TestCase):
    def setUp(self):
        self.manager = GoalManager()

    def test_describe_goal_matches_to_dict(self):
        goal = self.manager.create_goal("Ship the feature", requirements=["tests pass"])
        described = self.manager.describe_goal(goal.goal_id)
        self.assertEqual(described, goal.to_dict())

    def test_describe_goal_is_json_shaped(self):
        goal = self.manager.create_goal("Ship the feature")
        described = self.manager.describe_goal(goal.goal_id)
        for key in (
            "goal_id", "original_text", "normalized_text", "goal_type",
            "requirements", "confidence", "status", "created_at", "metadata",
        ):
            self.assertIn(key, described)

    def test_describe_goal_returns_none_for_unknown_id(self):
        self.assertIsNone(self.manager.describe_goal("does-not-exist"))

    def test_debug_state_reports_every_goal(self):
        self.manager.create_goal("First goal")
        self.manager.create_goal("Second goal")
        state = self.manager.debug_state()
        self.assertEqual(state["goal_count"], 2)
        self.assertEqual(len(state["goals"]), 2)


class TestCoreIntegration(unittest.TestCase):
    """Confirms GoalManager is wired into Core without changing any
    existing behaviour (AEL/conversation routing untouched)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_exposes_goal_creation_and_retrieval(self):
        goal = self.core.create_goal("Refactor the parser")
        self.assertEqual(self.core.get_goal(goal.goal_id).goal_id, goal.goal_id)
        self.assertEqual(self.core.describe_goal(goal.goal_id)["original_text"], "Refactor the parser")

    def test_existing_conversation_flow_is_unaffected(self):
        reply = self.core.process_input("hello")
        self.assertIsInstance(reply, str)
        self.assertEqual(len(self.core.goals), 0)


if __name__ == "__main__":
    unittest.main()
