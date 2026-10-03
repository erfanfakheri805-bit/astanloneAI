"""
Tests for the FinancialGoal model and FinancialGoalManager
(financial/ foundation).

Covers: creating a valid goal, rejecting invalid target amounts and
statuses, adding/retrieving goals, duplicate-id rejection, status
updates, removal, listing all goals, safe structured metadata, and a
basic backward-compatibility check (the rest of the project still
imports and runs unmodified).

Run directly:
    python -m unittest tests.test_financial_goal -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.financial_goal import (
    FinancialGoal,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
)
from financial.financial_goal_manager import FinancialGoalManager


def _make_goal(**overrides):
    fields = dict(
        goal_id="fin-goal-test-1",
        original_text="I want to generate 1,000,000,000 Toman per month.",
        target_amount=1_000_000_000,
        currency="Toman",
        time_period="monthly",
    )
    fields.update(overrides)
    return FinancialGoal(**fields)


# ----------------------------------------------------------------------
# 1. Creating a valid financial goal
# ----------------------------------------------------------------------
class TestCreateValidFinancialGoal(unittest.TestCase):
    def test_valid_goal_has_expected_fields_and_is_valid(self):
        goal = _make_goal()

        self.assertEqual(goal.goal_id, "fin-goal-test-1")
        self.assertEqual(
            goal.original_text, "I want to generate 1,000,000,000 Toman per month."
        )
        self.assertEqual(goal.target_amount, 1_000_000_000)
        self.assertEqual(goal.currency, "Toman")
        self.assertEqual(goal.time_period, "monthly")
        self.assertEqual(goal.status, STATUS_ACTIVE)
        self.assertTrue(goal.created_at)
        self.assertEqual(goal.constraints, {})
        self.assertEqual(goal.strategy_preferences, [])
        self.assertEqual(goal.metadata, {})
        self.assertTrue(goal.is_valid())

    def test_does_not_assume_achievability_or_promise_income(self):
        # An enormous, almost certainly unrealistic target is still a
        # structurally valid *goal record* - this stage only models
        # what was requested, it never judges feasibility.
        goal = _make_goal(target_amount=1_000_000_000_000)
        self.assertTrue(goal.is_valid())


# ----------------------------------------------------------------------
# 2. Rejecting invalid target amounts
# ----------------------------------------------------------------------
class TestInvalidTargetAmount(unittest.TestCase):
    def test_zero_target_amount_is_invalid(self):
        self.assertFalse(_make_goal(target_amount=0).is_valid())

    def test_negative_target_amount_is_invalid(self):
        self.assertFalse(_make_goal(target_amount=-500).is_valid())

    def test_non_numeric_target_amount_is_invalid(self):
        self.assertFalse(_make_goal(target_amount="a lot").is_valid())

    def test_none_target_amount_is_invalid(self):
        self.assertFalse(_make_goal(target_amount=None).is_valid())

    def test_boolean_target_amount_is_invalid(self):
        # bool is technically a subclass of int in Python - explicitly
        # excluded so `True`/`False` can never pass as an amount.
        self.assertFalse(_make_goal(target_amount=True).is_valid())

    def test_manager_rejects_invalid_target_amount(self):
        manager = FinancialGoalManager()
        with self.assertRaises(ValueError):
            manager.create_goal(
                original_text="Make some money",
                target_amount=-10,
                currency="USD",
                time_period="monthly",
            )
        self.assertEqual(len(manager), 0)


# ----------------------------------------------------------------------
# 3. Rejecting invalid statuses
# ----------------------------------------------------------------------
class TestInvalidStatus(unittest.TestCase):
    def test_unsupported_status_is_invalid(self):
        self.assertFalse(_make_goal(status="RICH").is_valid())

    def test_lowercase_status_is_invalid(self):
        # Status values are a fixed, case-sensitive vocabulary.
        self.assertFalse(_make_goal(status="active").is_valid())

    def test_all_supported_statuses_are_valid(self):
        for status in (STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_CANCELLED):
            self.assertTrue(_make_goal(status=status).is_valid())

    def test_manager_update_status_rejects_unsupported_status(self):
        manager = FinancialGoalManager()
        goal = manager.create_goal(
            original_text="Save up",
            target_amount=100,
            currency="USD",
            time_period="yearly",
        )
        result = manager.update_status(goal.goal_id, "RICH")
        self.assertIsNone(result)
        # Nothing changed.
        self.assertEqual(manager.get_goal(goal.goal_id).status, STATUS_ACTIVE)


# ----------------------------------------------------------------------
# 4. Adding and retrieving goals
# ----------------------------------------------------------------------
class TestAddAndRetrieveGoals(unittest.TestCase):
    def setUp(self):
        self.manager = FinancialGoalManager()

    def test_create_goal_then_get_goal_round_trips(self):
        created = self.manager.create_goal(
            original_text="I want to generate 1,000,000,000 Toman per month.",
            target_amount=1_000_000_000,
            currency="Toman",
            time_period="monthly",
        )
        fetched = self.manager.get_goal(created.goal_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.goal_id, created.goal_id)
        self.assertEqual(fetched.target_amount, 1_000_000_000)
        self.assertEqual(fetched.currency, "Toman")

    def test_add_goal_then_get_goal_round_trips(self):
        goal = _make_goal(goal_id="fin-goal-manual-1")
        added = self.manager.add_goal(goal)

        self.assertIs(added, goal)
        fetched = self.manager.get_goal("fin-goal-manual-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.goal_id, "fin-goal-manual-1")

    def test_get_goal_returns_none_for_unknown_id(self):
        self.assertIsNone(self.manager.get_goal("does-not-exist"))

    def test_get_goal_returns_a_safe_copy(self):
        created = self.manager.create_goal(
            original_text="Build savings",
            target_amount=500,
            currency="USD",
            time_period="monthly",
        )
        fetched = self.manager.get_goal(created.goal_id)
        fetched.target_amount = 999999

        # Mutating the returned copy must not affect the stored goal.
        self.assertEqual(self.manager.get_goal(created.goal_id).target_amount, 500)


# ----------------------------------------------------------------------
# 5. Preventing duplicate IDs
# ----------------------------------------------------------------------
class TestDuplicateIds(unittest.TestCase):
    def setUp(self):
        self.manager = FinancialGoalManager()

    def test_create_goal_with_duplicate_explicit_id_raises(self):
        self.manager.create_goal(
            original_text="First goal",
            target_amount=100,
            currency="USD",
            time_period="monthly",
            goal_id="dup-id",
        )
        with self.assertRaises(ValueError):
            self.manager.create_goal(
                original_text="Second goal, same id",
                target_amount=200,
                currency="USD",
                time_period="monthly",
                goal_id="dup-id",
            )
        # The original goal is untouched.
        self.assertEqual(self.manager.get_goal("dup-id").original_text, "First goal")
        self.assertEqual(len(self.manager), 1)

    def test_add_goal_with_duplicate_id_does_not_overwrite(self):
        first = _make_goal(goal_id="dup-add", target_amount=100)
        second = _make_goal(goal_id="dup-add", target_amount=200)

        self.assertIs(self.manager.add_goal(first), first)
        self.assertIsNone(self.manager.add_goal(second))
        self.assertEqual(self.manager.get_goal("dup-add").target_amount, 100)
        self.assertEqual(len(self.manager), 1)


# ----------------------------------------------------------------------
# 6. Updating goal status
# ----------------------------------------------------------------------
class TestUpdateStatus(unittest.TestCase):
    def setUp(self):
        self.manager = FinancialGoalManager()
        self.goal = self.manager.create_goal(
            original_text="Reach a savings target",
            target_amount=1000,
            currency="USD",
            time_period="yearly",
        )

    def test_update_status_to_supported_value(self):
        updated = self.manager.update_status(self.goal.goal_id, STATUS_PAUSED)
        self.assertEqual(updated.status, STATUS_PAUSED)
        self.assertEqual(self.manager.get_goal(self.goal.goal_id).status, STATUS_PAUSED)

    def test_update_status_for_unknown_goal_returns_none(self):
        self.assertIsNone(self.manager.update_status("no-such-goal", STATUS_COMPLETED))


# ----------------------------------------------------------------------
# 7. Removing a goal
# ----------------------------------------------------------------------
class TestRemoveGoal(unittest.TestCase):
    def setUp(self):
        self.manager = FinancialGoalManager()
        self.goal = self.manager.create_goal(
            original_text="Retire early",
            target_amount=2_000_000,
            currency="USD",
            time_period="lifetime",
        )

    def test_remove_goal_returns_removed_goal_and_deletes_it(self):
        removed = self.manager.remove_goal(self.goal.goal_id)
        self.assertEqual(removed.goal_id, self.goal.goal_id)
        self.assertIsNone(self.manager.get_goal(self.goal.goal_id))
        self.assertEqual(len(self.manager), 0)

    def test_remove_goal_for_unknown_id_returns_none(self):
        self.assertIsNone(self.manager.remove_goal("no-such-goal"))


# ----------------------------------------------------------------------
# 8. Returning all goals
# ----------------------------------------------------------------------
class TestGetAll(unittest.TestCase):
    def test_get_all_returns_every_goal_in_insertion_order(self):
        manager = FinancialGoalManager()
        first = manager.create_goal(
            original_text="Goal one", target_amount=10, currency="USD", time_period="monthly"
        )
        second = manager.create_goal(
            original_text="Goal two", target_amount=20, currency="USD", time_period="monthly"
        )

        all_goals = manager.get_all()
        self.assertEqual([g.goal_id for g in all_goals], [first.goal_id, second.goal_id])

    def test_get_all_on_empty_manager_returns_empty_list(self):
        self.assertEqual(FinancialGoalManager().get_all(), [])

    def test_clear_removes_all_goals(self):
        manager = FinancialGoalManager()
        manager.create_goal(
            original_text="Goal", target_amount=10, currency="USD", time_period="monthly"
        )
        manager.clear()
        self.assertEqual(manager.get_all(), [])
        self.assertEqual(len(manager), 0)


# ----------------------------------------------------------------------
# 9. Safe structured metadata
# ----------------------------------------------------------------------
class TestSafeStructuredData(unittest.TestCase):
    def test_plain_structured_metadata_constraints_and_preferences_are_valid(self):
        goal = _make_goal(
            metadata={"source": "chat", "tags": ["income", "monthly"]},
            constraints={"max_risk": "low", "hours_per_week": 5},
            strategy_preferences=["passive_income", "low_risk"],
        )
        self.assertTrue(goal.is_valid())
        as_dict = goal.to_dict()
        self.assertEqual(as_dict["metadata"]["source"], "chat")
        self.assertEqual(as_dict["constraints"]["max_risk"], "low")
        self.assertEqual(as_dict["strategy_preferences"], ["passive_income", "low_risk"])

    def test_metadata_with_a_callable_is_invalid(self):
        goal = _make_goal(metadata={"handler": lambda: None})
        self.assertFalse(goal.is_valid())

    def test_constraints_with_a_class_instance_is_invalid(self):
        class Unsafe:
            pass

        goal = _make_goal(constraints={"thing": Unsafe()})
        self.assertFalse(goal.is_valid())

    def test_manager_rejects_goal_with_unsafe_metadata(self):
        manager = FinancialGoalManager()
        with self.assertRaises(ValueError):
            manager.create_goal(
                original_text="Goal with unsafe metadata",
                target_amount=100,
                currency="USD",
                time_period="monthly",
                metadata={"callback": lambda: None},
            )
        self.assertEqual(len(manager), 0)

    def test_get_constraints_and_preferences_return_safe_copies(self):
        goal = _make_goal(
            constraints={"max_risk": "low"}, strategy_preferences=["passive_income"]
        )
        constraints = goal.get_constraints()
        preferences = goal.get_strategy_preferences()
        constraints["max_risk"] = "high"
        preferences.append("mutated")

        self.assertEqual(goal.get_constraints(), {"max_risk": "low"})
        self.assertEqual(goal.get_strategy_preferences(), ["passive_income"])


# ----------------------------------------------------------------------
# Accessor methods
# ----------------------------------------------------------------------
class TestAccessors(unittest.TestCase):
    def test_getter_methods_return_stored_values(self):
        goal = _make_goal(
            target_amount=1_000_000_000,
            currency="Toman",
            time_period="monthly",
            constraints={"max_risk": "low"},
            strategy_preferences=["passive_income"],
        )
        self.assertEqual(goal.get_target_amount(), 1_000_000_000)
        self.assertEqual(goal.get_currency(), "Toman")
        self.assertEqual(goal.get_time_period(), "monthly")
        self.assertEqual(goal.get_constraints(), {"max_risk": "low"})
        self.assertEqual(goal.get_strategy_preferences(), ["passive_income"])


# ----------------------------------------------------------------------
# 10. Backward compatibility with the existing project
# ----------------------------------------------------------------------
class TestBackwardCompatibility(unittest.TestCase):
    def test_core_still_initializes_unaffected_by_the_financial_module(self):
        from core.core import Core

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_memory.sqlite3")
            skills_dir = os.path.join(tmpdir, "skills")
            core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

        self.assertIsNotNone(core)
        # Existing systems (e.g. GoalManager) are untouched by this stage.
        self.assertTrue(hasattr(core, "goals"))

    def test_financial_module_performs_no_execution_or_transactions(self):
        # This stage never implements money-making actions: the manager
        # exposes only bookkeeping methods, nothing execution-shaped.
        manager = FinancialGoalManager()
        forbidden_method_names = (
            "execute",
            "pay",
            "transfer",
            "withdraw",
            "deposit",
            "send_money",
            "generate_income",
        )
        for name in forbidden_method_names:
            self.assertFalse(hasattr(manager, name))


if __name__ == "__main__":
    unittest.main()
