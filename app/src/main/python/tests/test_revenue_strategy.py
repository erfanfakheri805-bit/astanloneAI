"""
Tests for the RevenueStrategy model and RevenueStrategyManager
(financial/ - builds on the FinancialGoal stage).

Covers: creating a valid strategy, rejecting invalid income/confidence/
status, adding/retrieving strategies, finding strategies for a
financial goal, duplicate-id rejection, status updates, removal, and
safe structured data. Also confirms the full existing test suite
(including the previous FinancialGoal stage) still passes unmodified.

Run directly:
    python -m unittest tests.test_revenue_strategy -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_strategy import (
    RevenueStrategy,
    STATUS_PROPOSED,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_COMPLETED,
    STATUS_REJECTED,
    REVENUE_MODEL_SOFTWARE,
)
from financial.revenue_strategy_manager import RevenueStrategyManager


def _make_strategy(**overrides):
    fields = dict(
        strategy_id="rev-strategy-test-1",
        goal_id="fin-goal-test-1",
        name="Indie mobile game sales",
        description="Sell a small mobile game on an app store.",
        revenue_model=REVENUE_MODEL_SOFTWARE,
        estimated_income=500,
        currency="USD",
        time_period="monthly",
    )
    fields.update(overrides)
    return RevenueStrategy(**fields)


# ----------------------------------------------------------------------
# 1. Creating a valid strategy
# ----------------------------------------------------------------------
class TestCreateValidStrategy(unittest.TestCase):
    def test_valid_strategy_has_expected_fields_and_is_valid(self):
        strategy = _make_strategy()

        self.assertEqual(strategy.strategy_id, "rev-strategy-test-1")
        self.assertEqual(strategy.goal_id, "fin-goal-test-1")
        self.assertEqual(strategy.name, "Indie mobile game sales")
        self.assertEqual(
            strategy.description, "Sell a small mobile game on an app store."
        )
        self.assertEqual(strategy.revenue_model, REVENUE_MODEL_SOFTWARE)
        self.assertEqual(strategy.estimated_income, 500)
        self.assertEqual(strategy.currency, "USD")
        self.assertEqual(strategy.time_period, "monthly")
        self.assertEqual(strategy.status, STATUS_PROPOSED)
        self.assertEqual(strategy.confidence, 0.0)
        self.assertTrue(strategy.created_at)
        self.assertEqual(strategy.required_capabilities, [])
        self.assertEqual(strategy.required_tools, [])
        self.assertEqual(strategy.required_inputs, [])
        self.assertEqual(strategy.expected_outputs, [])
        self.assertEqual(strategy.risks, [])
        self.assertEqual(strategy.constraints, {})
        self.assertEqual(strategy.metadata, {})
        self.assertTrue(strategy.is_valid())

    def test_does_not_assume_estimated_income_is_guaranteed(self):
        # A strategy is only a structurally valid *record* of a
        # proposed approach - it never promises this income actually
        # arrives.
        strategy = _make_strategy(estimated_income=1_000_000)
        self.assertTrue(strategy.is_valid())

    def test_estimated_income_of_zero_is_valid(self):
        # >= 0 is allowed - a brand-new or purely speculative strategy
        # may have no estimate yet.
        self.assertTrue(_make_strategy(estimated_income=0).is_valid())

    def test_unknown_revenue_model_label_is_still_valid(self):
        # revenue_model is a reference vocabulary, not a closed enum.
        strategy = _make_strategy(revenue_model="SOMETHING_NEW")
        self.assertTrue(strategy.is_valid())

    def test_new_strategy_defaults_to_proposed_not_active(self):
        # Nothing about creating a strategy activates it.
        strategy = _make_strategy()
        self.assertEqual(strategy.status, STATUS_PROPOSED)
        self.assertNotEqual(strategy.status, STATUS_ACTIVE)


# ----------------------------------------------------------------------
# 2. Rejecting invalid income values
# ----------------------------------------------------------------------
class TestInvalidEstimatedIncome(unittest.TestCase):
    def test_negative_estimated_income_is_invalid(self):
        self.assertFalse(_make_strategy(estimated_income=-1).is_valid())

    def test_non_numeric_estimated_income_is_invalid(self):
        self.assertFalse(_make_strategy(estimated_income="lots").is_valid())

    def test_none_estimated_income_is_invalid(self):
        self.assertFalse(_make_strategy(estimated_income=None).is_valid())

    def test_boolean_estimated_income_is_invalid(self):
        # bool is technically a subclass of int in Python - explicitly
        # excluded so `True`/`False` can never pass as an income value.
        self.assertFalse(_make_strategy(estimated_income=True).is_valid())

    def test_manager_rejects_invalid_estimated_income(self):
        manager = RevenueStrategyManager()
        with self.assertRaises(ValueError):
            manager.create_strategy(
                goal_id="fin-goal-1",
                name="Bad strategy",
                description="Has a negative income estimate.",
                estimated_income=-50,
                currency="USD",
                time_period="monthly",
            )
        self.assertEqual(len(manager), 0)


# ----------------------------------------------------------------------
# 3. Rejecting invalid confidence
# ----------------------------------------------------------------------
class TestInvalidConfidence(unittest.TestCase):
    def test_confidence_above_one_is_invalid(self):
        self.assertFalse(_make_strategy(confidence=1.5).is_valid())

    def test_confidence_below_zero_is_invalid(self):
        self.assertFalse(_make_strategy(confidence=-0.1).is_valid())

    def test_non_numeric_confidence_is_invalid(self):
        self.assertFalse(_make_strategy(confidence="high").is_valid())

    def test_boolean_confidence_is_invalid(self):
        self.assertFalse(_make_strategy(confidence=True).is_valid())

    def test_confidence_boundaries_are_valid(self):
        self.assertTrue(_make_strategy(confidence=0.0).is_valid())
        self.assertTrue(_make_strategy(confidence=1.0).is_valid())

    def test_manager_rejects_invalid_confidence(self):
        manager = RevenueStrategyManager()
        with self.assertRaises(ValueError):
            manager.create_strategy(
                goal_id="fin-goal-1",
                name="Overconfident strategy",
                description="Confidence out of range.",
                estimated_income=100,
                currency="USD",
                time_period="monthly",
                confidence=2.0,
            )
        self.assertEqual(len(manager), 0)


# ----------------------------------------------------------------------
# 4. Rejecting invalid status
# ----------------------------------------------------------------------
class TestInvalidStatus(unittest.TestCase):
    def test_unsupported_status_is_invalid(self):
        self.assertFalse(_make_strategy(status="LAUNCHED").is_valid())

    def test_lowercase_status_is_invalid(self):
        self.assertFalse(_make_strategy(status="proposed").is_valid())

    def test_all_supported_statuses_are_valid(self):
        for status in (
            STATUS_PROPOSED, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_REJECTED,
        ):
            self.assertTrue(_make_strategy(status=status).is_valid())

    def test_manager_update_status_rejects_unsupported_status(self):
        manager = RevenueStrategyManager()
        strategy = manager.create_strategy(
            goal_id="fin-goal-1",
            name="Freelance writing",
            description="Take on freelance writing gigs.",
            estimated_income=200,
            currency="USD",
            time_period="monthly",
        )
        result = manager.update_status(strategy.strategy_id, "LAUNCHED")
        self.assertIsNone(result)
        self.assertEqual(
            manager.get_strategy(strategy.strategy_id).status, STATUS_PROPOSED
        )


# ----------------------------------------------------------------------
# 5. Adding and retrieving strategies
# ----------------------------------------------------------------------
class TestAddAndRetrieveStrategies(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueStrategyManager()

    def test_create_strategy_then_get_strategy_round_trips(self):
        created = self.manager.create_strategy(
            goal_id="fin-goal-1",
            name="Subscription newsletter",
            description="Paid weekly newsletter.",
            revenue_model="SUBSCRIPTION",
            estimated_income=300,
            currency="USD",
            time_period="monthly",
        )
        fetched = self.manager.get_strategy(created.strategy_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.strategy_id, created.strategy_id)
        self.assertEqual(fetched.goal_id, "fin-goal-1")
        self.assertEqual(fetched.estimated_income, 300)

    def test_add_strategy_then_get_strategy_round_trips(self):
        strategy = _make_strategy(strategy_id="rev-strategy-manual-1")
        added = self.manager.add_strategy(strategy)

        self.assertIs(added, strategy)
        fetched = self.manager.get_strategy("rev-strategy-manual-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.strategy_id, "rev-strategy-manual-1")

    def test_get_strategy_returns_none_for_unknown_id(self):
        self.assertIsNone(self.manager.get_strategy("does-not-exist"))

    def test_get_strategy_returns_a_safe_copy(self):
        created = self.manager.create_strategy(
            goal_id="fin-goal-1",
            name="Print on demand shop",
            description="Sell print-on-demand merchandise.",
            estimated_income=150,
            currency="USD",
            time_period="monthly",
        )
        fetched = self.manager.get_strategy(created.strategy_id)
        fetched.estimated_income = 999999

        self.assertEqual(
            self.manager.get_strategy(created.strategy_id).estimated_income, 150
        )


# ----------------------------------------------------------------------
# 6. Finding strategies for a financial goal
# ----------------------------------------------------------------------
class TestGetForGoal(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueStrategyManager()

    def test_get_for_goal_returns_only_matching_strategies_in_order(self):
        first = self.manager.create_strategy(
            goal_id="fin-goal-A",
            name="Strategy A1",
            description="First strategy for goal A.",
            estimated_income=100,
            currency="USD",
            time_period="monthly",
        )
        self.manager.create_strategy(
            goal_id="fin-goal-B",
            name="Strategy B1",
            description="A strategy for a different goal.",
            estimated_income=100,
            currency="USD",
            time_period="monthly",
        )
        second = self.manager.create_strategy(
            goal_id="fin-goal-A",
            name="Strategy A2",
            description="Second strategy for goal A.",
            estimated_income=200,
            currency="USD",
            time_period="monthly",
        )

        for_a = self.manager.get_for_goal("fin-goal-A")
        self.assertEqual([s.strategy_id for s in for_a], [first.strategy_id, second.strategy_id])

    def test_get_for_goal_with_unknown_goal_id_returns_empty_list(self):
        self.manager.create_strategy(
            goal_id="fin-goal-A",
            name="Strategy A1",
            description="A strategy.",
            estimated_income=100,
            currency="USD",
            time_period="monthly",
        )
        self.assertEqual(self.manager.get_for_goal("no-such-goal"), [])

    def test_get_for_goal_returns_safe_copies(self):
        self.manager.create_strategy(
            goal_id="fin-goal-A",
            name="Strategy A1",
            description="A strategy.",
            estimated_income=100,
            currency="USD",
            time_period="monthly",
        )
        results = self.manager.get_for_goal("fin-goal-A")
        results[0].estimated_income = 999999
        self.assertEqual(
            self.manager.get_for_goal("fin-goal-A")[0].estimated_income, 100
        )


# ----------------------------------------------------------------------
# 7. Preventing duplicate IDs
# ----------------------------------------------------------------------
class TestDuplicateIds(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueStrategyManager()

    def test_create_strategy_with_duplicate_explicit_id_raises(self):
        self.manager.create_strategy(
            goal_id="fin-goal-1",
            name="First strategy",
            description="The first one.",
            estimated_income=100,
            currency="USD",
            time_period="monthly",
            strategy_id="dup-id",
        )
        with self.assertRaises(ValueError):
            self.manager.create_strategy(
                goal_id="fin-goal-1",
                name="Second strategy, same id",
                description="Should be rejected.",
                estimated_income=200,
                currency="USD",
                time_period="monthly",
                strategy_id="dup-id",
            )
        self.assertEqual(self.manager.get_strategy("dup-id").name, "First strategy")
        self.assertEqual(len(self.manager), 1)

    def test_add_strategy_with_duplicate_id_does_not_overwrite(self):
        first = _make_strategy(strategy_id="dup-add", estimated_income=100)
        second = _make_strategy(strategy_id="dup-add", estimated_income=200)

        self.assertIs(self.manager.add_strategy(first), first)
        self.assertIsNone(self.manager.add_strategy(second))
        self.assertEqual(self.manager.get_strategy("dup-add").estimated_income, 100)
        self.assertEqual(len(self.manager), 1)


# ----------------------------------------------------------------------
# 8. Updating strategy status
# ----------------------------------------------------------------------
class TestUpdateStatus(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueStrategyManager()
        self.strategy = self.manager.create_strategy(
            goal_id="fin-goal-1",
            name="Freelance design work",
            description="Take on freelance design contracts.",
            estimated_income=800,
            currency="USD",
            time_period="monthly",
        )

    def test_update_status_to_supported_value(self):
        updated = self.manager.update_status(self.strategy.strategy_id, STATUS_ACTIVE)
        self.assertEqual(updated.status, STATUS_ACTIVE)
        self.assertEqual(
            self.manager.get_strategy(self.strategy.strategy_id).status, STATUS_ACTIVE
        )

    def test_update_status_for_unknown_strategy_returns_none(self):
        self.assertIsNone(self.manager.update_status("no-such-strategy", STATUS_REJECTED))

    def test_status_never_changes_without_an_explicit_call(self):
        # Creating, fetching, or listing strategies never mutates status.
        self.manager.get_strategy(self.strategy.strategy_id)
        self.manager.get_all()
        self.manager.get_for_goal(self.strategy.goal_id)
        self.assertEqual(
            self.manager.get_strategy(self.strategy.strategy_id).status, STATUS_PROPOSED
        )


# ----------------------------------------------------------------------
# 9. Removing strategies
# ----------------------------------------------------------------------
class TestRemoveStrategy(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueStrategyManager()
        self.strategy = self.manager.create_strategy(
            goal_id="fin-goal-1",
            name="Ad-supported blog",
            description="Run a blog monetized with ads.",
            estimated_income=50,
            currency="USD",
            time_period="monthly",
        )

    def test_remove_strategy_returns_removed_strategy_and_deletes_it(self):
        removed = self.manager.remove_strategy(self.strategy.strategy_id)
        self.assertEqual(removed.strategy_id, self.strategy.strategy_id)
        self.assertIsNone(self.manager.get_strategy(self.strategy.strategy_id))
        self.assertEqual(len(self.manager), 0)

    def test_remove_strategy_for_unknown_id_returns_none(self):
        self.assertIsNone(self.manager.remove_strategy("no-such-strategy"))

    def test_get_all_and_clear(self):
        self.assertEqual(len(self.manager.get_all()), 1)
        self.manager.clear()
        self.assertEqual(self.manager.get_all(), [])
        self.assertEqual(len(self.manager), 0)


# ----------------------------------------------------------------------
# 10. Safe structured data
# ----------------------------------------------------------------------
class TestSafeStructuredData(unittest.TestCase):
    def test_plain_structured_fields_are_valid(self):
        strategy = _make_strategy(
            required_capabilities=["writing", "basic_design"],
            required_tools=["laptop", "image_editor"],
            required_inputs=["topic_ideas"],
            expected_outputs=["published_articles"],
            risks=["inconsistent_income", "platform_policy_changes"],
            constraints={"max_hours_per_week": 10},
            metadata={"source": "chat", "tags": ["writing", "low_startup_cost"]},
        )
        self.assertTrue(strategy.is_valid())
        as_dict = strategy.to_dict()
        self.assertEqual(as_dict["required_capabilities"], ["writing", "basic_design"])
        self.assertEqual(as_dict["constraints"]["max_hours_per_week"], 10)
        self.assertEqual(as_dict["metadata"]["source"], "chat")

    def test_risks_with_a_callable_is_invalid(self):
        strategy = _make_strategy(risks=[lambda: "risk"])
        self.assertFalse(strategy.is_valid())

    def test_constraints_with_a_class_instance_is_invalid(self):
        class Unsafe:
            pass

        strategy = _make_strategy(constraints={"thing": Unsafe()})
        self.assertFalse(strategy.is_valid())

    def test_manager_rejects_strategy_with_unsafe_metadata(self):
        manager = RevenueStrategyManager()
        with self.assertRaises(ValueError):
            manager.create_strategy(
                goal_id="fin-goal-1",
                name="Bad metadata strategy",
                description="Has an unsafe metadata value.",
                estimated_income=100,
                currency="USD",
                time_period="monthly",
                metadata={"callback": lambda: None},
            )
        self.assertEqual(len(manager), 0)

    def test_getter_methods_return_safe_copies(self):
        strategy = _make_strategy(
            required_capabilities=["writing"],
            required_tools=["laptop"],
            expected_outputs=["articles"],
            risks=["low_demand"],
            constraints={"max_risk": "low"},
        )
        strategy.get_required_capabilities().append("mutated")
        strategy.get_required_tools().append("mutated")
        strategy.get_expected_outputs().append("mutated")
        strategy.get_risks().append("mutated")
        strategy.get_constraints()["max_risk"] = "high"

        self.assertEqual(strategy.get_required_capabilities(), ["writing"])
        self.assertEqual(strategy.get_required_tools(), ["laptop"])
        self.assertEqual(strategy.get_expected_outputs(), ["articles"])
        self.assertEqual(strategy.get_risks(), ["low_demand"])
        self.assertEqual(strategy.get_constraints(), {"max_risk": "low"})


# ----------------------------------------------------------------------
# No execution, activation, or financial transactions
# ----------------------------------------------------------------------
class TestNoExecutionOrActivation(unittest.TestCase):
    def test_revenue_strategy_manager_exposes_no_execution_shaped_methods(self):
        manager = RevenueStrategyManager()
        forbidden_method_names = (
            "execute",
            "activate",
            "pay",
            "transfer",
            "withdraw",
            "deposit",
            "send_money",
            "generate_income",
            "run",
        )
        for name in forbidden_method_names:
            self.assertFalse(hasattr(manager, name))


# ----------------------------------------------------------------------
# 11. Full existing test suite remains passing (spot check here; the
# full discovery run is done separately - see module docstring).
# ----------------------------------------------------------------------
class TestBackwardCompatibility(unittest.TestCase):
    def test_financial_goal_stage_is_untouched(self):
        from financial.financial_goal import FinancialGoal
        from financial.financial_goal_manager import FinancialGoalManager

        goal_manager = FinancialGoalManager()
        goal = goal_manager.create_goal(
            original_text="I want to generate 1,000,000,000 Toman per month.",
            target_amount=1_000_000_000,
            currency="Toman",
            time_period="monthly",
        )
        self.assertIsInstance(goal, FinancialGoal)
        self.assertTrue(goal.is_valid())

    def test_strategies_can_reference_a_real_financial_goal(self):
        from financial.financial_goal_manager import FinancialGoalManager

        goal_manager = FinancialGoalManager()
        goal = goal_manager.create_goal(
            original_text="Generate extra monthly income",
            target_amount=1000,
            currency="USD",
            time_period="monthly",
        )

        strategy_manager = RevenueStrategyManager()
        strategy = strategy_manager.create_strategy(
            goal_id=goal.goal_id,
            name="Freelance work",
            description="Take on freelance contracts.",
            estimated_income=1000,
            currency="USD",
            time_period="monthly",
        )

        self.assertEqual(
            [s.strategy_id for s in strategy_manager.get_for_goal(goal.goal_id)],
            [strategy.strategy_id],
        )


if __name__ == "__main__":
    unittest.main()
