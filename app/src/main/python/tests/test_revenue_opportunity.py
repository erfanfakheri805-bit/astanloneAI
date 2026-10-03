"""
Tests for the RevenueOpportunity model, RevenueOpportunityManager, and
RevenueOpportunityPlanner (financial/ - builds on the FinancialGoal and
RevenueStrategy stages).

Covers: creating a valid opportunity, validation failures, strategy-to-
opportunity and goal-to-opportunity generation, filtering by goal/
strategy, deterministic ranking, top-opportunity selection, safe
rejection of invalid objects, and a confirmation that the full existing
test suite (including both previous financial stages) still passes.

Run directly:
    python -m unittest tests.test_revenue_opportunity -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_opportunity import (
    RevenueOpportunity,
    STATUS_DISCOVERED,
    STATUS_PROPOSED,
    STATUS_SELECTED,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REJECTED,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    LEVEL_HIGH,
)
from financial.revenue_opportunity_manager import RevenueOpportunityManager
from financial.revenue_opportunity_planner import RevenueOpportunityPlanner
from financial.revenue_strategy import RevenueStrategy
from financial.financial_goal import FinancialGoal
from financial.revenue_task import RevenueTask, STATUS_PENDING


def _make_opportunity(**overrides):
    fields = dict(
        opportunity_id="opp-test-1",
        goal_id="fin-goal-test-1",
        strategy_id="rev-strategy-test-1",
        name="Sell a small mobile game",
        description="Ship and sell a small mobile game on an app store.",
        revenue_model="GAME",
        estimated_income=500,
        currency="USD",
        time_period="monthly",
        confidence=0.6,
    )
    fields.update(overrides)
    return RevenueOpportunity(**fields)


def _make_strategy(**overrides):
    fields = dict(
        strategy_id="rev-strategy-test-1",
        goal_id="fin-goal-test-1",
        name="Indie mobile game sales",
        description="Sell a small mobile game on an app store.",
        revenue_model="GAME",
        estimated_income=500,
        currency="USD",
        time_period="monthly",
        confidence=0.6,
    )
    fields.update(overrides)
    return RevenueStrategy(**fields)


def _make_goal(**overrides):
    fields = dict(
        goal_id="fin-goal-test-1",
        original_text="I want extra monthly income.",
        target_amount=1000,
        currency="USD",
        time_period="monthly",
    )
    fields.update(overrides)
    return FinancialGoal(**fields)


# ----------------------------------------------------------------------
# 1. Valid opportunity creation
# ----------------------------------------------------------------------
class TestCreateValidOpportunity(unittest.TestCase):
    def test_valid_opportunity_has_expected_fields_and_is_valid(self):
        opportunity = _make_opportunity()

        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.strategy_id, "rev-strategy-test-1")
        self.assertEqual(opportunity.name, "Sell a small mobile game")
        self.assertEqual(opportunity.revenue_model, "GAME")
        self.assertEqual(opportunity.estimated_income, 500)
        self.assertEqual(opportunity.currency, "USD")
        self.assertEqual(opportunity.time_period, "monthly")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertEqual(opportunity.effort_level, LEVEL_MEDIUM)
        self.assertEqual(opportunity.risk_level, LEVEL_MEDIUM)
        self.assertTrue(opportunity.created_at)
        self.assertEqual(opportunity.required_capabilities, [])
        self.assertEqual(opportunity.metadata, {})
        self.assertTrue(opportunity.is_valid())

    def test_strategy_id_may_be_none(self):
        opportunity = _make_opportunity(strategy_id=None)
        self.assertTrue(opportunity.is_valid())

    def test_does_not_promise_income(self):
        opportunity = _make_opportunity(estimated_income=1_000_000)
        self.assertTrue(opportunity.is_valid())
        # It's still just an estimate/target - the class makes no
        # further claim than storing the number.
        self.assertEqual(opportunity.get_estimated_income(), 1_000_000)

    def test_new_opportunity_defaults_to_discovered_not_active(self):
        opportunity = _make_opportunity()
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertNotEqual(opportunity.status, STATUS_ACTIVE)


# ----------------------------------------------------------------------
# 2. Validation failures
# ----------------------------------------------------------------------
class TestValidationFailures(unittest.TestCase):
    def test_empty_opportunity_id_is_invalid(self):
        self.assertFalse(_make_opportunity(opportunity_id="").is_valid())

    def test_empty_goal_id_is_invalid(self):
        self.assertFalse(_make_opportunity(goal_id="").is_valid())

    def test_empty_strategy_id_string_is_invalid(self):
        # None is allowed, but an empty string is not.
        self.assertFalse(_make_opportunity(strategy_id="").is_valid())

    def test_empty_name_or_description_is_invalid(self):
        self.assertFalse(_make_opportunity(name="").is_valid())
        self.assertFalse(_make_opportunity(description="").is_valid())

    def test_negative_estimated_income_is_invalid(self):
        self.assertFalse(_make_opportunity(estimated_income=-1).is_valid())

    def test_non_numeric_estimated_income_is_invalid(self):
        self.assertFalse(_make_opportunity(estimated_income="lots").is_valid())

    def test_boolean_estimated_income_is_invalid(self):
        self.assertFalse(_make_opportunity(estimated_income=True).is_valid())

    def test_empty_currency_or_time_period_is_invalid(self):
        self.assertFalse(_make_opportunity(currency="").is_valid())
        self.assertFalse(_make_opportunity(time_period="").is_valid())

    def test_invalid_effort_level_is_invalid(self):
        self.assertFalse(_make_opportunity(effort_level="EXTREME").is_valid())

    def test_invalid_risk_level_is_invalid(self):
        self.assertFalse(_make_opportunity(risk_level="EXTREME").is_valid())

    def test_confidence_out_of_range_is_invalid(self):
        self.assertFalse(_make_opportunity(confidence=1.5).is_valid())
        self.assertFalse(_make_opportunity(confidence=-0.1).is_valid())

    def test_boolean_confidence_is_invalid(self):
        self.assertFalse(_make_opportunity(confidence=True).is_valid())

    def test_invalid_status_is_invalid(self):
        self.assertFalse(_make_opportunity(status="LAUNCHED").is_valid())

    def test_all_supported_statuses_are_valid(self):
        for status in (
            STATUS_DISCOVERED, STATUS_PROPOSED, STATUS_SELECTED, STATUS_ACTIVE,
            STATUS_COMPLETED, STATUS_FAILED, STATUS_REJECTED,
        ):
            self.assertTrue(_make_opportunity(status=status).is_valid())

    def test_all_supported_levels_are_valid(self):
        for level in (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH):
            self.assertTrue(_make_opportunity(effort_level=level).is_valid())
            self.assertTrue(_make_opportunity(risk_level=level).is_valid())

    def test_unsafe_metadata_is_invalid(self):
        self.assertFalse(_make_opportunity(metadata={"callback": lambda: None}).is_valid())

    def test_unsafe_required_tools_is_invalid(self):
        class Unsafe:
            pass

        self.assertFalse(_make_opportunity(required_tools=[Unsafe()]).is_valid())


# ----------------------------------------------------------------------
# 3. Strategy-to-opportunity generation
# ----------------------------------------------------------------------
class TestGenerateFromStrategy(unittest.TestCase):
    def setUp(self):
        self.planner = RevenueOpportunityPlanner()

    def test_generates_one_opportunity_matching_strategy_fields(self):
        strategy = _make_strategy(
            required_capabilities=["writing"],
            required_tools=["laptop"],
            risks=["inconsistent_demand"],
        )
        opportunities = self.planner.generate_from_strategy(strategy)

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertTrue(opportunity.is_valid())
        self.assertEqual(opportunity.goal_id, strategy.goal_id)
        self.assertEqual(opportunity.strategy_id, strategy.strategy_id)
        self.assertEqual(opportunity.name, strategy.name)
        self.assertEqual(opportunity.estimated_income, strategy.estimated_income)
        self.assertEqual(opportunity.confidence, strategy.confidence)
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)

    def test_generation_is_deterministic_and_idempotent(self):
        strategy = _make_strategy()
        first = self.planner.generate_from_strategy(strategy)
        second = self.planner.generate_from_strategy(strategy)

        self.assertEqual(first[0].opportunity_id, second[0].opportunity_id)
        self.assertEqual(first[0].to_dict()["estimated_income"], second[0].to_dict()["estimated_income"])

    def test_effort_level_increases_with_requirement_count(self):
        low = self.planner.generate_from_strategy(_make_strategy(strategy_id="s-low"))[0]
        high = self.planner.generate_from_strategy(
            _make_strategy(
                strategy_id="s-high",
                required_capabilities=["a", "b"],
                required_tools=["c", "d"],
                required_inputs=["e"],
            )
        )[0]
        self.assertEqual(low.effort_level, LEVEL_LOW)
        self.assertEqual(high.effort_level, LEVEL_HIGH)

    def test_risk_level_increases_with_risk_count(self):
        low = self.planner.generate_from_strategy(_make_strategy(strategy_id="s-low-risk"))[0]
        high = self.planner.generate_from_strategy(
            _make_strategy(
                strategy_id="s-high-risk",
                risks=["risk1", "risk2", "risk3"],
            )
        )[0]
        self.assertEqual(low.risk_level, LEVEL_LOW)
        self.assertEqual(high.risk_level, LEVEL_HIGH)

    def test_invalid_strategy_object_yields_no_opportunities(self):
        self.assertEqual(self.planner.generate_from_strategy("not a strategy"), [])
        self.assertEqual(self.planner.generate_from_strategy(None), [])

    def test_structurally_invalid_strategy_yields_no_opportunities(self):
        broken = _make_strategy(estimated_income=-100)  # fails is_valid()
        self.assertEqual(self.planner.generate_from_strategy(broken), [])

    def test_never_produces_an_active_or_completed_status(self):
        strategy = _make_strategy()
        opportunity = self.planner.generate_from_strategy(strategy)[0]
        self.assertNotIn(opportunity.status, (STATUS_ACTIVE, STATUS_COMPLETED, STATUS_SELECTED))


# ----------------------------------------------------------------------
# 4. Goal-to-opportunity generation
# ----------------------------------------------------------------------
class TestGenerateFromGoal(unittest.TestCase):
    def setUp(self):
        self.planner = RevenueOpportunityPlanner()
        self.goal = _make_goal()

    def test_generates_opportunities_only_for_matching_strategies(self):
        matching = _make_strategy(strategy_id="match-1", goal_id=self.goal.goal_id)
        other_goal = _make_strategy(strategy_id="other-1", goal_id="some-other-goal")

        opportunities = self.planner.generate_from_goal(self.goal, [matching, other_goal])

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].strategy_id, "match-1")

    def test_invalid_goal_yields_no_opportunities(self):
        broken_goal = _make_goal(target_amount=-5)
        strategy = _make_strategy(goal_id=broken_goal.goal_id)
        self.assertEqual(self.planner.generate_from_goal(broken_goal, [strategy]), [])

    def test_empty_strategy_list_yields_no_opportunities(self):
        self.assertEqual(self.planner.generate_from_goal(self.goal, []), [])
        self.assertEqual(self.planner.generate_from_goal(self.goal, None), [])

    def test_invalid_entries_in_strategies_are_skipped(self):
        matching = _make_strategy(strategy_id="match-2", goal_id=self.goal.goal_id)
        opportunities = self.planner.generate_from_goal(
            self.goal, [matching, "not a strategy", None]
        )
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].strategy_id, "match-2")


# ----------------------------------------------------------------------
# 5. Filtering by goal
# ----------------------------------------------------------------------
class TestGetForGoal(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueOpportunityManager()

    def test_get_for_goal_returns_only_matching_opportunities_in_order(self):
        first = self.manager.create_opportunity(
            goal_id="goal-A", name="Opp A1", description="First for goal A.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        self.manager.create_opportunity(
            goal_id="goal-B", name="Opp B1", description="For a different goal.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        second = self.manager.create_opportunity(
            goal_id="goal-A", name="Opp A2", description="Second for goal A.",
            estimated_income=200, currency="USD", time_period="monthly",
        )

        for_a = self.manager.get_for_goal("goal-A")
        self.assertEqual(
            [o.opportunity_id for o in for_a], [first.opportunity_id, second.opportunity_id]
        )

    def test_get_for_goal_with_unknown_id_returns_empty_list(self):
        self.assertEqual(self.manager.get_for_goal("no-such-goal"), [])


# ----------------------------------------------------------------------
# 6. Filtering by strategy
# ----------------------------------------------------------------------
class TestGetForStrategy(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueOpportunityManager()

    def test_get_for_strategy_returns_only_matching_opportunities(self):
        first = self.manager.create_opportunity(
            goal_id="goal-A", strategy_id="strategy-1", name="Opp 1",
            description="First for strategy 1.", estimated_income=100,
            currency="USD", time_period="monthly",
        )
        self.manager.create_opportunity(
            goal_id="goal-A", strategy_id="strategy-2", name="Opp 2",
            description="For a different strategy.", estimated_income=100,
            currency="USD", time_period="monthly",
        )

        for_strategy = self.manager.get_for_strategy("strategy-1")
        self.assertEqual([o.opportunity_id for o in for_strategy], [first.opportunity_id])

    def test_get_for_strategy_with_unknown_id_returns_empty_list(self):
        self.assertEqual(self.manager.get_for_strategy("no-such-strategy"), [])

    def test_get_for_strategy_with_none_matches_strategyless_opportunities(self):
        opp = self.manager.create_opportunity(
            goal_id="goal-A", strategy_id=None, name="Standalone opportunity",
            description="Not tied to a strategy.", estimated_income=50,
            currency="USD", time_period="monthly",
        )
        self.assertEqual([o.opportunity_id for o in self.manager.get_for_strategy(None)], [opp.opportunity_id])


# ----------------------------------------------------------------------
# 7. Deterministic ranking
# ----------------------------------------------------------------------
class TestRankOpportunities(unittest.TestCase):
    def setUp(self):
        self.planner = RevenueOpportunityPlanner()

    def test_higher_confidence_ranks_first(self):
        low_conf = _make_opportunity(opportunity_id="low-conf", confidence=0.2)
        high_conf = _make_opportunity(opportunity_id="high-conf", confidence=0.9)

        ranked = self.planner.rank_opportunities([low_conf, high_conf])
        self.assertEqual([o.opportunity_id for o in ranked], ["high-conf", "low-conf"])

    def test_lower_risk_breaks_confidence_ties(self):
        higher_risk = _make_opportunity(
            opportunity_id="higher-risk", confidence=0.5, risk_level=LEVEL_HIGH
        )
        lower_risk = _make_opportunity(
            opportunity_id="lower-risk", confidence=0.5, risk_level=LEVEL_LOW
        )
        ranked = self.planner.rank_opportunities([higher_risk, lower_risk])
        self.assertEqual([o.opportunity_id for o in ranked], ["lower-risk", "higher-risk"])

    def test_lower_effort_breaks_confidence_and_risk_ties(self):
        higher_effort = _make_opportunity(
            opportunity_id="higher-effort", confidence=0.5, risk_level=LEVEL_LOW, effort_level=LEVEL_HIGH
        )
        lower_effort = _make_opportunity(
            opportunity_id="lower-effort", confidence=0.5, risk_level=LEVEL_LOW, effort_level=LEVEL_LOW
        )
        ranked = self.planner.rank_opportunities([higher_effort, lower_effort])
        self.assertEqual([o.opportunity_id for o in ranked], ["lower-effort", "higher-effort"])

    def test_higher_income_breaks_remaining_ties(self):
        lower_income = _make_opportunity(
            opportunity_id="lower-income", confidence=0.5, risk_level=LEVEL_LOW,
            effort_level=LEVEL_LOW, estimated_income=100,
        )
        higher_income = _make_opportunity(
            opportunity_id="higher-income", confidence=0.5, risk_level=LEVEL_LOW,
            effort_level=LEVEL_LOW, estimated_income=900,
        )
        ranked = self.planner.rank_opportunities([lower_income, higher_income])
        self.assertEqual([o.opportunity_id for o in ranked], ["higher-income", "lower-income"])

    def test_ranking_is_deterministic_across_repeated_calls(self):
        opportunities = [
            _make_opportunity(opportunity_id="a", confidence=0.4),
            _make_opportunity(opportunity_id="b", confidence=0.8),
            _make_opportunity(opportunity_id="c", confidence=0.6),
        ]
        first = [o.opportunity_id for o in self.planner.rank_opportunities(opportunities)]
        second = [o.opportunity_id for o in self.planner.rank_opportunities(opportunities)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["b", "c", "a"])

    def test_invalid_entries_are_excluded_from_ranking(self):
        valid = _make_opportunity(opportunity_id="valid-one")
        invalid = _make_opportunity(opportunity_id="invalid-one", estimated_income=-1)
        ranked = self.planner.rank_opportunities([valid, invalid, "not an opportunity", None])
        self.assertEqual([o.opportunity_id for o in ranked], ["valid-one"])

    def test_rank_opportunities_does_not_mutate_input(self):
        opportunities = [_make_opportunity(opportunity_id="a", confidence=0.5)]
        ranked = self.planner.rank_opportunities(opportunities)
        ranked[0].confidence = 0.99
        self.assertEqual(opportunities[0].confidence, 0.5)


# ----------------------------------------------------------------------
# 8. Top-opportunity selection
# ----------------------------------------------------------------------
class TestGetTopOpportunities(unittest.TestCase):
    def setUp(self):
        self.planner = RevenueOpportunityPlanner()
        self.opportunities = [
            _make_opportunity(opportunity_id="a", confidence=0.3),
            _make_opportunity(opportunity_id="b", confidence=0.9),
            _make_opportunity(opportunity_id="c", confidence=0.6),
            _make_opportunity(opportunity_id="d", confidence=0.1),
        ]

    def test_returns_top_n_in_ranked_order(self):
        top_two = self.planner.get_top_opportunities(self.opportunities, limit=2)
        self.assertEqual([o.opportunity_id for o in top_two], ["b", "c"])

    def test_limit_larger_than_available_returns_all_ranked(self):
        top = self.planner.get_top_opportunities(self.opportunities, limit=100)
        self.assertEqual(len(top), 4)

    def test_limit_zero_or_negative_returns_empty_list(self):
        self.assertEqual(self.planner.get_top_opportunities(self.opportunities, limit=0), [])
        self.assertEqual(self.planner.get_top_opportunities(self.opportunities, limit=-1), [])

    def test_default_limit_is_five(self):
        six_opportunities = self.opportunities + [
            _make_opportunity(opportunity_id="e", confidence=0.05),
            _make_opportunity(opportunity_id="f", confidence=0.95),
        ]
        top = self.planner.get_top_opportunities(six_opportunities)
        self.assertEqual(len(top), 5)


# ----------------------------------------------------------------------
# 9. Invalid opportunities are rejected safely
# ----------------------------------------------------------------------
class TestInvalidOpportunitiesRejectedSafely(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueOpportunityManager()

    def test_manager_create_opportunity_rejects_invalid_fields(self):
        with self.assertRaises(ValueError):
            self.manager.create_opportunity(
                goal_id="goal-1", name="Bad opportunity", description="Negative income.",
                estimated_income=-10, currency="USD", time_period="monthly",
            )
        self.assertEqual(len(self.manager), 0)

    def test_manager_add_opportunity_rejects_invalid_instance(self):
        self.assertIsNone(self.manager.add_opportunity("not an opportunity"))
        self.assertIsNone(self.manager.add_opportunity(None))
        self.assertEqual(len(self.manager), 0)

    def test_manager_add_opportunity_rejects_structurally_invalid_opportunity(self):
        broken = _make_opportunity(confidence=5.0)
        self.assertIsNone(self.manager.add_opportunity(broken))
        self.assertEqual(len(self.manager), 0)

    def test_duplicate_ids_do_not_overwrite(self):
        first = self.manager.create_opportunity(
            goal_id="goal-1", name="First", description="First one.",
            estimated_income=100, currency="USD", time_period="monthly",
            opportunity_id="dup-id",
        )
        with self.assertRaises(ValueError):
            self.manager.create_opportunity(
                goal_id="goal-1", name="Second", description="Should be rejected.",
                estimated_income=200, currency="USD", time_period="monthly",
                opportunity_id="dup-id",
            )
        self.assertEqual(self.manager.get_opportunity("dup-id").name, "First")
        self.assertEqual(len(self.manager), 1)

    def test_update_status_rejects_unsupported_status(self):
        opportunity = self.manager.create_opportunity(
            goal_id="goal-1", name="Opp", description="An opportunity.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        self.assertIsNone(self.manager.update_status(opportunity.opportunity_id, "LAUNCHED"))
        self.assertEqual(
            self.manager.get_opportunity(opportunity.opportunity_id).status, STATUS_DISCOVERED
        )

    def test_remove_and_clear(self):
        opportunity = self.manager.create_opportunity(
            goal_id="goal-1", name="Opp", description="An opportunity.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        removed = self.manager.remove_opportunity(opportunity.opportunity_id)
        self.assertEqual(removed.opportunity_id, opportunity.opportunity_id)
        self.assertIsNone(self.manager.remove_opportunity("no-such-id"))

        self.manager.create_opportunity(
            goal_id="goal-1", name="Opp2", description="Another opportunity.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        self.manager.clear()
        self.assertEqual(self.manager.get_all(), [])
        self.assertEqual(len(self.manager), 0)

    def test_get_returns_safe_copies(self):
        opportunity = self.manager.create_opportunity(
            goal_id="goal-1", name="Opp", description="An opportunity.",
            estimated_income=100, currency="USD", time_period="monthly",
        )
        fetched = self.manager.get_opportunity(opportunity.opportunity_id)
        fetched.estimated_income = 999999
        self.assertEqual(
            self.manager.get_opportunity(opportunity.opportunity_id).estimated_income, 100
        )


# ----------------------------------------------------------------------
# No execution or real-world side effects
# ----------------------------------------------------------------------
class TestNoExecutionOrSideEffects(unittest.TestCase):
    def test_manager_exposes_no_execution_shaped_methods(self):
        manager = RevenueOpportunityManager()
        forbidden = (
            "execute", "activate", "pay", "transfer", "withdraw", "deposit",
            "send_money", "generate_income", "run", "contact_customer",
            "make_purchase", "publish", "send_message", "access_website",
        )
        for name in forbidden:
            self.assertFalse(hasattr(manager, name))

    def test_planner_exposes_no_execution_shaped_methods(self):
        planner = RevenueOpportunityPlanner()
        forbidden = (
            "execute", "activate", "pay", "transfer", "withdraw", "deposit",
            "send_money", "generate_income", "run", "contact_customer",
            "make_purchase", "publish", "send_message", "access_website",
        )
        for name in forbidden:
            self.assertFalse(hasattr(planner, name))


# ----------------------------------------------------------------------
# 10. Existing test suite remains passing (spot check here; the full
# discovery run is done separately - see module docstring).
# ----------------------------------------------------------------------
class TestBackwardCompatibility(unittest.TestCase):
    def test_previous_financial_stages_are_untouched(self):
        from financial.financial_goal_manager import FinancialGoalManager
        from financial.revenue_strategy_manager import RevenueStrategyManager

        goal_manager = FinancialGoalManager()
        goal = goal_manager.create_goal(
            original_text="I want to generate 1,000,000,000 Toman per month.",
            target_amount=1_000_000_000,
            currency="Toman",
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
        self.assertTrue(goal.is_valid())
        self.assertTrue(strategy.is_valid())

    def test_full_pipeline_goal_strategy_opportunity(self):
        from financial.financial_goal_manager import FinancialGoalManager
        from financial.revenue_strategy_manager import RevenueStrategyManager

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
            name="Freelance writing",
            description="Take on freelance writing gigs.",
            estimated_income=1000,
            currency="USD",
            time_period="monthly",
            confidence=0.5,
        )

        planner = RevenueOpportunityPlanner()
        opportunities = planner.generate_from_goal(goal, strategy_manager.get_all())
        self.assertEqual(len(opportunities), 1)

        opportunity_manager = RevenueOpportunityManager()
        stored = opportunity_manager.add_opportunity(opportunities[0])
        self.assertIsNotNone(stored)
        self.assertEqual(
            [o.opportunity_id for o in opportunity_manager.get_for_goal(goal.goal_id)],
            [stored.opportunity_id],
        )
        self.assertEqual(
            [o.opportunity_id for o in opportunity_manager.get_for_strategy(strategy.strategy_id)],
            [stored.opportunity_id],
        )


def _make_task(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        name="Draft the store listing",
        status=STATUS_PENDING,
    )
    fields.update(overrides)
    return RevenueTask(**fields)


# ----------------------------------------------------------------------
# X. can_accept_task()
# ----------------------------------------------------------------------
class TestCanAcceptTask(unittest.TestCase):
    def test_valid_task_with_matching_opportunity_id_returns_true(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="opp-test-1")
        self.assertTrue(opportunity.can_accept_task(task))

    def test_valid_task_with_different_opportunity_id_returns_false(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="opp-other")
        self.assertFalse(opportunity.can_accept_task(task))

    def test_task_with_empty_opportunity_id_returns_false(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="")
        self.assertFalse(opportunity.can_accept_task(task))

    def test_invalid_task_object_returns_false(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        self.assertFalse(opportunity.can_accept_task("not-a-task"))
        self.assertFalse(opportunity.can_accept_task(None))
        self.assertFalse(opportunity.can_accept_task(123))
        self.assertFalse(opportunity.can_accept_task({"opportunity_id": "opp-test-1"}))

    def test_task_that_fails_is_valid_returns_false(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="opp-test-1", name="")
        self.assertFalse(task.is_valid())
        self.assertFalse(opportunity.can_accept_task(task))

    def test_calling_it_does_not_modify_the_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="opp-test-1", status=STATUS_PENDING)
        opportunity.can_accept_task(task)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.status, STATUS_PENDING)

    def test_calling_it_does_not_modify_the_opportunity(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(opportunity_id="opp-test-1")
        opportunity.can_accept_task(task)
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_existing_opportunity_and_task_behavior_unchanged(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        self.assertTrue(opportunity.is_valid())
        self.assertEqual(opportunity.get_estimated_income(), 500)

        task = _make_task(opportunity_id="opp-test-1")
        self.assertTrue(task.is_valid())
        self.assertTrue(task.has_opportunity())
        self.assertTrue(task.belongs_to_opportunity("opp-test-1"))


# ----------------------------------------------------------------------
# Y. task_ids tracking
# ----------------------------------------------------------------------
class TestTaskIdsTracking(unittest.TestCase):
    def test_default_task_ids_is_empty_list(self):
        opportunity = _make_opportunity()
        self.assertEqual(opportunity.task_ids, [])

    def test_task_ids_none_becomes_empty_list(self):
        opportunity = _make_opportunity(task_ids=None)
        self.assertEqual(opportunity.task_ids, [])

    def test_existing_list_is_copied_not_aliased(self):
        source = ["task-a", "task-b"]
        opportunity = _make_opportunity(task_ids=source)
        self.assertEqual(opportunity.task_ids, ["task-a", "task-b"])
        opportunity.task_ids.append("task-c")
        self.assertEqual(source, ["task-a", "task-b"])

    def test_invalid_non_list_input_becomes_empty_list(self):
        self.assertEqual(_make_opportunity(task_ids="task-a").task_ids, [])
        self.assertEqual(_make_opportunity(task_ids=123).task_ids, [])
        self.assertEqual(_make_opportunity(task_ids={"a": 1}).task_ids, [])

    def test_tuple_input_is_copied_as_list(self):
        opportunity = _make_opportunity(task_ids=("task-a", "task-b"))
        self.assertEqual(opportunity.task_ids, ["task-a", "task-b"])

    def test_get_task_ids_returns_a_copy(self):
        opportunity = _make_opportunity(task_ids=["task-a"])
        result = opportunity.get_task_ids()
        self.assertEqual(result, ["task-a"])
        result.append("task-b")
        self.assertEqual(opportunity.task_ids, ["task-a"])

    def test_has_tasks_false_when_empty(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertFalse(opportunity.has_tasks())

    def test_has_tasks_true_with_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-a"])
        self.assertTrue(opportunity.has_tasks())

    def test_has_tasks_false_with_only_invalid_entries(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123])
        self.assertFalse(opportunity.has_tasks())

    def test_has_tasks_true_with_mixed_valid_and_invalid_entries(self):
        opportunity = _make_opportunity(task_ids=["", "task-a", None])
        self.assertTrue(opportunity.has_tasks())

    def test_to_dict_includes_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-a", "task-b"])
        self.assertEqual(opportunity.to_dict()["task_ids"], ["task-a", "task-b"])

    def test_to_dict_task_ids_is_a_copy(self):
        opportunity = _make_opportunity(task_ids=["task-a"])
        data = opportunity.to_dict()
        data["task_ids"].append("task-b")
        self.assertEqual(opportunity.task_ids, ["task-a"])

    def test_existing_behavior_and_validity_unaffected(self):
        opportunity = _make_opportunity(task_ids=["task-a"])
        self.assertTrue(opportunity.is_valid())
        self.assertEqual(opportunity.get_estimated_income(), 500)
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)


# ----------------------------------------------------------------------
# Z. attach_task()
# ----------------------------------------------------------------------
class TestAttachTask(unittest.TestCase):
    def test_attaching_a_valid_matching_task_succeeds(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        self.assertTrue(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_rejects_task_for_another_opportunity(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-other")
        self.assertFalse(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, [])

    def test_rejects_invalid_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        self.assertFalse(opportunity.attach_task("not-a-task"))
        self.assertFalse(opportunity.attach_task(None))
        self.assertEqual(opportunity.task_ids, [])

        invalid_task = _make_task(
            task_id="task-1", opportunity_id="opp-test-1", name=""
        )
        self.assertFalse(invalid_task.is_valid())
        self.assertFalse(opportunity.attach_task(invalid_task))
        self.assertEqual(opportunity.task_ids, [])

    def test_prevents_duplicate_task_ids(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        self.assertTrue(opportunity.attach_task(task))
        self.assertFalse(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_only_the_task_id_is_stored(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        opportunity.attach_task(task)
        for stored in opportunity.task_ids:
            self.assertIsInstance(stored, str)
        self.assertNotIn(task, opportunity.task_ids)

    def test_attach_task_does_not_modify_the_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(
            task_id="task-1", opportunity_id="opp-test-1", status=STATUS_PENDING
        )
        opportunity.attach_task(task)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.status, STATUS_PENDING)

    def test_existing_can_accept_task_behavior_unchanged(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        matching_task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        other_task = _make_task(task_id="task-2", opportunity_id="opp-other")
        self.assertTrue(opportunity.can_accept_task(matching_task))
        self.assertFalse(opportunity.can_accept_task(other_task))


# ----------------------------------------------------------------------
# AA. remove_task()
# ----------------------------------------------------------------------
class TestRemoveTask(unittest.TestCase):
    def test_removing_an_existing_task_succeeds(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task("task-1"))
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_removing_a_non_existing_task_returns_false(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.remove_task("task-missing"))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_invalid_task_id_returns_false(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.remove_task(""))
        self.assertFalse(opportunity.remove_task("   "))
        self.assertFalse(opportunity.remove_task(None))
        self.assertFalse(opportunity.remove_task(123))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_removing_the_same_task_twice(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.remove_task("task-1"))
        self.assertFalse(opportunity.remove_task("task-1"))
        self.assertEqual(opportunity.task_ids, [])

    def test_other_task_ids_remain_unchanged(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        opportunity.remove_task("task-2")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-3"])

    def test_remove_task_does_not_affect_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.remove_task("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_attach_task_still_works(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        self.assertTrue(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, ["task-1"])
        self.assertTrue(opportunity.remove_task("task-1"))
        self.assertTrue(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, ["task-1"])


# ----------------------------------------------------------------------
# AB. has_task()
# ----------------------------------------------------------------------
class TestHasTask(unittest.TestCase):
    def test_attached_task_returns_true(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.has_task("task-1"))

    def test_unknown_task_returns_false(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.has_task("task-missing"))

    def test_empty_task_id_returns_false(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.has_task(""))
        self.assertFalse(opportunity.has_task("   "))

    def test_invalid_task_id_types_return_false(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.has_task(None))
        self.assertFalse(opportunity.has_task(123))
        self.assertFalse(opportunity.has_task(["task-1"]))

    def test_calling_it_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.has_task("task-1")
        opportunity.has_task("task-missing")
        opportunity.has_task("")
        opportunity.has_task(None)
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_calling_it_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.has_task("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_reflects_attach_and_remove_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")

        self.assertFalse(opportunity.has_task("task-1"))
        opportunity.attach_task(task)
        self.assertTrue(opportunity.has_task("task-1"))
        opportunity.remove_task("task-1")
        self.assertFalse(opportunity.has_task("task-1"))


# ----------------------------------------------------------------------
# AC. get_task_count()
# ----------------------------------------------------------------------
class TestGetTaskCount(unittest.TestCase):
    def test_zero_attached_tasks(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_task_count(), 0)

    def test_default_task_ids_count_is_zero(self):
        opportunity = _make_opportunity()
        self.assertEqual(opportunity.get_task_count(), 0)

    def test_one_attached_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_task_count(), 1)

    def test_multiple_attached_tasks(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_task_count(), 3)

    def test_invalid_and_empty_ids_are_not_counted(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, "task-2"]
        )
        self.assertEqual(opportunity.get_task_count(), 2)

    def test_all_invalid_ids_gives_zero(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123])
        self.assertEqual(opportunity.get_task_count(), 0)

    def test_calling_it_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-2"])
        opportunity.get_task_count()
        self.assertEqual(opportunity.task_ids, ["task-1", "", "task-2"])

    def test_calling_it_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_count()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_reflects_attach_and_remove_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")

        self.assertEqual(opportunity.get_task_count(), 0)
        opportunity.attach_task(task)
        self.assertEqual(opportunity.get_task_count(), 1)
        opportunity.remove_task("task-1")
        self.assertEqual(opportunity.get_task_count(), 0)


# ----------------------------------------------------------------------
# AD. get_task_summary()
# ----------------------------------------------------------------------
class TestGetTaskSummary(unittest.TestCase):
    def test_empty_task_summary(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.get_task_summary(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 0,
                "has_tasks": False,
                "task_ids": [],
            },
        )

    def test_one_attached_task(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        self.assertEqual(
            opportunity.get_task_summary(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 1,
                "has_tasks": True,
                "task_ids": ["task-1"],
            },
        )

    def test_multiple_attached_tasks(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_summary(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 3,
                "has_tasks": True,
                "task_ids": ["task-1", "task-2", "task-3"],
            },
        )

    def test_returned_task_ids_are_safely_copied(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        summary = opportunity.get_task_summary()
        summary["task_ids"].append("task-2")
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_returned_dict_is_a_new_dict(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        summary = opportunity.get_task_summary()
        summary["opportunity_id"] = "changed"
        summary["task_count"] = 999
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.get_task_count(), 1)

    def test_summary_values_match_existing_helper_methods(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "", "task-2"]
        )
        summary = opportunity.get_task_summary()
        self.assertEqual(summary["task_count"], opportunity.get_task_count())
        self.assertEqual(summary["has_tasks"], opportunity.has_tasks())
        self.assertEqual(summary["task_ids"], opportunity.get_task_ids())

    def test_calling_it_does_not_modify_the_opportunity(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_summary()
        self.assertEqual(opportunity.task_ids, ["task-1"])
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AE. get_task_id()
# ----------------------------------------------------------------------
class TestGetTaskId(unittest.TestCase):
    def test_retrieving_an_existing_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(opportunity.get_task_id("task-1"), "task-1")

    def test_unknown_task_id_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_id("task-missing"))

    def test_empty_task_id_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_id(""))
        self.assertIsNone(opportunity.get_task_id("   "))

    def test_invalid_task_id_types_return_none(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_id(None))
        self.assertIsNone(opportunity.get_task_id(123))
        self.assertIsNone(opportunity.get_task_id(["task-1"]))

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.get_task_id("task-1")
        opportunity.get_task_id("task-missing")
        opportunity.get_task_id("")
        opportunity.get_task_id(None)
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_id("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_reflects_attach_and_remove_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")

        self.assertIsNone(opportunity.get_task_id("task-1"))
        opportunity.attach_task(task)
        self.assertEqual(opportunity.get_task_id("task-1"), "task-1")
        opportunity.remove_task("task-1")
        self.assertIsNone(opportunity.get_task_id("task-1"))

    def test_consistent_with_has_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.has_task("task-1"))
        self.assertIsNotNone(opportunity.get_task_id("task-1"))
        self.assertFalse(opportunity.has_task("task-2"))
        self.assertIsNone(opportunity.get_task_id("task-2"))


# ----------------------------------------------------------------------
# AF. get_attached_task_ids()
# ----------------------------------------------------------------------
class TestGetAttachedTaskIds(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_attached_task_ids(), [])

    def test_one_attached_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_attached_task_ids(), ["task-1"])

    def test_multiple_attached_tasks(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(
            opportunity.get_attached_task_ids(), ["task-1", "task-2", "task-3"]
        )

    def test_invalid_and_empty_ids_are_excluded(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, "task-2"]
        )
        self.assertEqual(
            opportunity.get_attached_task_ids(), ["task-1", "task-2"]
        )

    def test_returned_list_is_a_safe_copy(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        result = opportunity.get_attached_task_ids()
        result.append("task-2")
        self.assertEqual(opportunity.task_ids, ["task-1"])
        self.assertIsNot(result, opportunity.task_ids)

    def test_calling_it_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-2"])
        opportunity.get_attached_task_ids()
        self.assertEqual(opportunity.task_ids, ["task-1", "", "task-2"])

    def test_calling_it_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_attached_task_ids()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertTrue(opportunity.is_valid())

    def test_reflects_attach_and_remove_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")

        self.assertEqual(opportunity.get_attached_task_ids(), [])
        opportunity.attach_task(task)
        self.assertEqual(opportunity.get_attached_task_ids(), ["task-1"])
        opportunity.remove_task("task-1")
        self.assertEqual(opportunity.get_attached_task_ids(), [])


# ----------------------------------------------------------------------
# AG. clear_tasks()
# ----------------------------------------------------------------------
class TestClearTasks(unittest.TestCase):
    def test_clear_one_attached_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.clear_tasks())
        self.assertEqual(opportunity.task_ids, [])

    def test_clear_multiple_attached_tasks(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertTrue(opportunity.clear_tasks())
        self.assertEqual(opportunity.task_ids, [])

    def test_clear_already_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.clear_tasks())
        self.assertEqual(opportunity.task_ids, [])

    def test_clear_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.clear_tasks()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.strategy_id, "rev-strategy-test-1")
        self.assertEqual(opportunity.name, "Sell a small mobile game")
        self.assertEqual(
            opportunity.description,
            "Ship and sell a small mobile game on an app store.",
        )
        self.assertEqual(opportunity.revenue_model, "GAME")
        self.assertEqual(opportunity.estimated_income, 500)
        self.assertEqual(opportunity.currency, "USD")
        self.assertEqual(opportunity.time_period, "monthly")
        self.assertEqual(opportunity.confidence, 0.6)
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_task_ids_becomes_empty_list(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.clear_tasks()
        self.assertEqual(opportunity.task_ids, [])
        self.assertIsInstance(opportunity.task_ids, list)
        self.assertEqual(opportunity.get_task_count(), 0)
        self.assertFalse(opportunity.has_tasks())
        self.assertEqual(opportunity.get_attached_task_ids(), [])

    def test_does_not_affect_underlying_task_object(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        opportunity.attach_task(task)

        opportunity.clear_tasks()

        self.assertEqual(opportunity.task_ids, [])
        self.assertTrue(task.is_valid())
        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(task.opportunity_id, "opp-test-1")

    def test_can_attach_again_after_clear(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")
        opportunity.attach_task(task)

        opportunity.clear_tasks()

        self.assertTrue(opportunity.attach_task(task))
        self.assertEqual(opportunity.task_ids, ["task-1"])


# ----------------------------------------------------------------------
# AH. can_work_on_tasks()
# ----------------------------------------------------------------------
class TestCanWorkOnTasks(unittest.TestCase):
    def test_no_tasks_attached(self):
        opportunity = _make_opportunity()
        self.assertFalse(opportunity.can_work_on_tasks())

    def test_empty_task_ids(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertFalse(opportunity.can_work_on_tasks())

    def test_one_valid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.can_work_on_tasks())

    def test_multiple_valid_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.can_work_on_tasks())

    def test_only_invalid_or_empty_task_ids(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123])
        self.assertFalse(opportunity.can_work_on_tasks())

    def test_mixed_valid_and_invalid_task_ids(self):
        opportunity = _make_opportunity(task_ids=["", None, "task-1"])
        self.assertTrue(opportunity.can_work_on_tasks())

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-2"])
        opportunity.can_work_on_tasks()
        self.assertEqual(opportunity.task_ids, ["task-1", "", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.can_work_on_tasks()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_reflects_attach_clear_and_remove_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1")
        task = _make_task(task_id="task-1", opportunity_id="opp-test-1")

        self.assertFalse(opportunity.can_work_on_tasks())
        opportunity.attach_task(task)
        self.assertTrue(opportunity.can_work_on_tasks())
        opportunity.remove_task("task-1")
        self.assertFalse(opportunity.can_work_on_tasks())
        opportunity.attach_task(task)
        self.assertTrue(opportunity.can_work_on_tasks())
        opportunity.clear_tasks()
        self.assertFalse(opportunity.can_work_on_tasks())


# ----------------------------------------------------------------------
# AI. validate_task_ids()
# ----------------------------------------------------------------------
class TestValidateTaskIds(unittest.TestCase):
    def test_empty_task_ids(self):
        opportunity = _make_opportunity(task_ids=[])
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": True,
                "total": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "invalid_ids": [],
            },
        )

    def test_one_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": True,
                "total": 1,
                "valid_count": 1,
                "invalid_count": 0,
                "invalid_ids": [],
            },
        )

    def test_multiple_valid_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": True,
                "total": 3,
                "valid_count": 3,
                "invalid_count": 0,
                "invalid_ids": [],
            },
        )

    def test_empty_string_id(self):
        opportunity = _make_opportunity(task_ids=[""])
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": False,
                "total": 1,
                "valid_count": 0,
                "invalid_count": 1,
                "invalid_ids": [""],
            },
        )

    def test_whitespace_only_id(self):
        opportunity = _make_opportunity(task_ids=["   "])
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": False,
                "total": 1,
                "valid_count": 0,
                "invalid_count": 1,
                "invalid_ids": ["   "],
            },
        )

    def test_invalid_non_string_values(self):
        opportunity = _make_opportunity(task_ids=[None, 123, 4.5, True, [], {}])
        result = opportunity.validate_task_ids()
        self.assertEqual(result["valid"], False)
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["valid_count"], 0)
        self.assertEqual(result["invalid_count"], 6)
        self.assertEqual(result["invalid_ids"], [None, 123, 4.5, True, [], {}])

    def test_mixed_valid_and_invalid_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, "task-2", 123]
        )
        result = opportunity.validate_task_ids()
        self.assertEqual(
            result,
            {
                "valid": False,
                "total": 6,
                "valid_count": 2,
                "invalid_count": 4,
                "invalid_ids": ["", "   ", None, 123],
            },
        )

    def test_does_not_modify_task_ids(self):
        original = ["task-1", "", "   ", None, "task-2", 123]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.validate_task_ids()
        self.assertEqual(opportunity.task_ids, original)

    def test_invalid_ids_result_is_a_safe_copy(self):
        opportunity = _make_opportunity(task_ids=["task-1", ""])
        result = opportunity.validate_task_ids()
        result["invalid_ids"].append("bogus")
        self.assertEqual(opportunity.task_ids, ["task-1", ""])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", ""]
        )
        opportunity.validate_task_ids()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AJ. normalize_task_ids()
# ----------------------------------------------------------------------
class TestNormalizeTaskIds(unittest.TestCase):
    def test_trims_whitespace(self):
        opportunity = _make_opportunity(task_ids=[" task_1 ", "task_2 ", " task_3"])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2", "task_3"])

    def test_removes_duplicates(self):
        opportunity = _make_opportunity(task_ids=["task_1", "task_2", "task_1"])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2"])

    def test_preserves_order(self):
        opportunity = _make_opportunity(
            task_ids=["task_3", "task_1", "task_2", "task_1"]
        )
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_3", "task_1", "task_2"])

    def test_removes_empty_strings(self):
        opportunity = _make_opportunity(task_ids=["task_1", "", "task_2"])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2"])

    def test_removes_whitespace_only_strings(self):
        opportunity = _make_opportunity(task_ids=["task_1", "   ", "task_2"])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2"])

    def test_removes_non_string_values(self):
        opportunity = _make_opportunity(
            task_ids=["task_1", 123, None, 4.5, True, [], {}, "task_2"]
        )
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2"])

    def test_already_normalized_ids_unchanged(self):
        opportunity = _make_opportunity(task_ids=["task_1", "task_2", "task_3"])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2", "task_3"])

    def test_example_from_spec(self):
        opportunity = _make_opportunity(
            task_ids=[" task_1 ", "task_2", "task_1", "", "   ", 123]
        )
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_1", "task_2"])

    def test_empty_task_ids_stays_empty(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, [])

    def test_all_invalid_entries_result_in_empty_list(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123, []])
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, [])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=[" task_1 ", "task_1"]
        )
        opportunity.normalize_task_ids()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_final_task_ids_list_is_correct(self):
        opportunity = _make_opportunity(
            task_ids=["task_2", " task_1 ", "task_2", "", "task_1", None]
        )
        self.assertTrue(opportunity.normalize_task_ids())
        self.assertEqual(opportunity.task_ids, ["task_2", "task_1"])
        self.assertIsInstance(opportunity.task_ids, list)


# ----------------------------------------------------------------------
# AK. add_task_ids()
# ----------------------------------------------------------------------
class TestAddTaskIds(unittest.TestCase):
    def test_adding_one_valid_id(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.add_task_ids(["task-1"]))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_adding_multiple_valid_ids(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.add_task_ids(["task-1", "task-2", "task-3"]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_trims_whitespace(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.add_task_ids([" task-1 ", "task-2 "]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_ignores_duplicates_within_input(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(opportunity.add_task_ids(["task-1", "task-1", "task-2"]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_ignores_already_attached_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.add_task_ids(["task-1", "task-2"]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_ignores_invalid_values(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(
            opportunity.add_task_ids(["task-1", "", "   ", None, 123, [], "task-2"])
        )
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_preserves_order(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertTrue(
            opportunity.add_task_ids(["task-3", "task-1", "task-2"])
        )
        self.assertEqual(opportunity.task_ids, ["task-3", "task-1", "task-2"])

    def test_preserves_order_with_existing_ids(self):
        opportunity = _make_opportunity(task_ids=["task-0"])
        self.assertTrue(opportunity.add_task_ids(["task-2", "task-1"]))
        self.assertEqual(opportunity.task_ids, ["task-0", "task-2", "task-1"])

    def test_none_input_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.add_task_ids(None))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_non_list_input_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.add_task_ids("task-2"))
        self.assertFalse(opportunity.add_task_ids(("task-2",)))
        self.assertFalse(opportunity.add_task_ids({"task-2"}))
        self.assertFalse(opportunity.add_task_ids(123))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_stores_only_ids_not_task_objects(self):
        opportunity = _make_opportunity(task_ids=[])
        task = _make_task(task_id="task-1", opportunity_id=opportunity.opportunity_id)
        self.assertTrue(opportunity.add_task_ids([task.task_id]))
        self.assertEqual(opportunity.task_ids, ["task-1"])
        for stored in opportunity.task_ids:
            self.assertIsInstance(stored, str)

    def test_only_task_ids_changes(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.add_task_ids(["task-2"])
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.strategy_id, "rev-strategy-test-1")
        self.assertEqual(opportunity.name, "Sell a small mobile game")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AL. remove_task_ids()
# ----------------------------------------------------------------------
class TestRemoveTaskIds(unittest.TestCase):
    def test_removing_one_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task_ids(["task-1"]))
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_removing_multiple_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.remove_task_ids(["task-1", "task-3"]))
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_removing_a_non_existent_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertTrue(opportunity.remove_task_ids(["task-missing"]))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_trims_whitespace(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task_ids([" task-1 "]))
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_ignores_invalid_values(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(
            opportunity.remove_task_ids(["task-1", "", "   ", None, 123, []])
        )
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_preserves_order_of_remaining_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3", "task-4"]
        )
        self.assertTrue(opportunity.remove_task_ids(["task-2"]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-3", "task-4"])

    def test_duplicate_ids_in_input(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task_ids(["task-1", "task-1"]))
        self.assertEqual(opportunity.task_ids, ["task-2"])

    def test_none_input_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.remove_task_ids(None))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_non_list_input_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertFalse(opportunity.remove_task_ids("task-1"))
        self.assertFalse(opportunity.remove_task_ids(("task-1",)))
        self.assertFalse(opportunity.remove_task_ids({"task-1"}))
        self.assertFalse(opportunity.remove_task_ids(123))
        self.assertEqual(opportunity.task_ids, ["task-1"])

    def test_only_task_ids_changes(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.remove_task_ids(["task-1"])
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.strategy_id, "rev-strategy-test-1")
        self.assertEqual(opportunity.name, "Sell a small mobile game")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_removing_all_ids_leaves_empty_list(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task_ids(["task-1", "task-2"]))
        self.assertEqual(opportunity.task_ids, [])

    def test_empty_removal_list_is_a_no_op(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(opportunity.remove_task_ids([]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])


# ----------------------------------------------------------------------
# AM. get_task_index()
# ----------------------------------------------------------------------
class TestGetTaskIndex(unittest.TestCase):
    def test_first_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_task_index("task-1"), 0)

    def test_middle_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_task_index("task-2"), 1)

    def test_last_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_task_index("task-3"), 2)

    def test_unknown_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(opportunity.get_task_index("task-missing"), -1)

    def test_empty_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_task_index(""), -1)
        self.assertEqual(opportunity.get_task_index("   "), -1)

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(opportunity.get_task_index(" task-1 "), 0)
        self.assertEqual(opportunity.get_task_index("task-2 "), 1)

    def test_invalid_task_id_types(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_task_index(None), -1)
        self.assertEqual(opportunity.get_task_index(123), -1)
        self.assertEqual(opportunity.get_task_index(4.5), -1)
        self.assertEqual(opportunity.get_task_index(True), -1)
        self.assertEqual(opportunity.get_task_index([]), -1)
        self.assertEqual(opportunity.get_task_index({}), -1)

    def test_empty_task_ids_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_task_index("task-1"), -1)

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.get_task_index("task-1")
        opportunity.get_task_index("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_index("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AN. get_task_overview()
# ----------------------------------------------------------------------
class TestGetTaskOverview(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.get_task_overview(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 0,
                "has_tasks": False,
                "task_ids": [],
                "first_task_id": None,
                "last_task_id": None,
            },
        )

    def test_one_task(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        self.assertEqual(
            opportunity.get_task_overview(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 1,
                "has_tasks": True,
                "task_ids": ["task-1"],
                "first_task_id": "task-1",
                "last_task_id": "task-1",
            },
        )

    def test_multiple_tasks(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1",
            task_ids=["task-1", "task-2", "task-3"],
        )
        self.assertEqual(
            opportunity.get_task_overview(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 3,
                "has_tasks": True,
                "task_ids": ["task-1", "task-2", "task-3"],
                "first_task_id": "task-1",
                "last_task_id": "task-3",
            },
        )

    def test_first_and_last_ignore_invalid_entries(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1",
            task_ids=["", None, "task-1", "task-2", "   ", 123],
        )
        overview = opportunity.get_task_overview()
        self.assertEqual(overview["first_task_id"], "task-1")
        self.assertEqual(overview["last_task_id"], "task-2")
        self.assertEqual(overview["task_count"], 2)

    def test_task_ids_is_a_safe_copy(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        overview = opportunity.get_task_overview()
        overview["task_ids"].append("task-3")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-2"])
        opportunity.get_task_overview()
        self.assertEqual(opportunity.task_ids, ["task-1", "", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_overview()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AO. move_task()
# ----------------------------------------------------------------------
class TestMoveTask(unittest.TestCase):
    def test_moving_first_task_to_last_position(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.move_task("task-1", 2))
        self.assertEqual(opportunity.task_ids, ["task-2", "task-3", "task-1"])

    def test_moving_last_task_to_first_position(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.move_task("task-3", 0))
        self.assertEqual(opportunity.task_ids, ["task-3", "task-1", "task-2"])

    def test_moving_a_middle_task(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3", "task-4"]
        )
        self.assertTrue(opportunity.move_task("task-2", 3))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-3", "task-4", "task-2"])

    def test_moving_to_current_position(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.move_task("task-2", 1))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_unknown_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertFalse(opportunity.move_task("task-missing", 0))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_invalid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertFalse(opportunity.move_task("", 0))
        self.assertFalse(opportunity.move_task("   ", 0))
        self.assertFalse(opportunity.move_task(None, 0))
        self.assertFalse(opportunity.move_task(123, 0))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_negative_index(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertFalse(opportunity.move_task("task-1", -1))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_index_beyond_valid_range(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertFalse(opportunity.move_task("task-1", 3))
        self.assertFalse(opportunity.move_task("task-1", 100))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_invalid_index_types(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertFalse(opportunity.move_task("task-1", "1"))
        self.assertFalse(opportunity.move_task("task-1", 1.5))
        self.assertFalse(opportunity.move_task("task-1", True))
        self.assertFalse(opportunity.move_task("task-1", None))
        self.assertFalse(opportunity.move_task("task-1", [1]))
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_whitespace_around_task_id_is_trimmed(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertTrue(opportunity.move_task(" task-1 ", 2))
        self.assertEqual(opportunity.task_ids, ["task-2", "task-3", "task-1"])

    def test_other_task_ids_remain_unchanged(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3", "task-4"]
        )
        opportunity.move_task("task-4", 0)
        self.assertEqual(set(opportunity.task_ids), {"task-1", "task-2", "task-3", "task-4"})
        self.assertEqual(len(opportunity.task_ids), 4)

    def test_invalid_operations_do_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.move_task("task-missing", 0)
        opportunity.move_task("task-1", -5)
        opportunity.move_task("task-1", 50)
        opportunity.move_task("task-1", "0")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.move_task("task-1", 1)
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AP. get_task_reference()
# ----------------------------------------------------------------------
class TestGetTaskReference(unittest.TestCase):
    def test_valid_attached_task(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        self.assertEqual(
            opportunity.get_task_reference("task-1"),
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-1",
                "index": 0,
                "attached": True,
            },
        )

    def test_first_task_index(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        result = opportunity.get_task_reference("task-1")
        self.assertEqual(result["index"], 0)

    def test_middle_task_index(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        result = opportunity.get_task_reference("task-2")
        self.assertEqual(result["index"], 1)

    def test_unknown_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_reference("task-missing"))

    def test_invalid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_reference(""))
        self.assertIsNone(opportunity.get_task_reference("   "))
        self.assertIsNone(opportunity.get_task_reference(None))
        self.assertIsNone(opportunity.get_task_reference(123))

    def test_whitespace_around_task_id(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        self.assertEqual(
            opportunity.get_task_reference(" task-1 "),
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-1",
                "index": 0,
                "attached": True,
            },
        )

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        result = opportunity.get_task_reference("task-1")
        result["task_id"] = "tampered"
        result["index"] = 99
        second_result = opportunity.get_task_reference("task-1")
        self.assertEqual(second_result["task_id"], "task-1")
        self.assertEqual(second_result["index"], 0)

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.get_task_reference("task-1")
        opportunity.get_task_reference("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_reference("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AQ. check_task_attachment_consistency()
# ----------------------------------------------------------------------
class TestCheckTaskAttachmentConsistency(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.check_task_attachment_consistency(),
            {
                "opportunity_id": "opp-test-1",
                "valid": True,
                "task_count": 0,
                "valid_task_count": 0,
                "invalid_task_count": 0,
                "duplicate_count": 0,
                "issues": [],
            },
        )

    def test_all_valid_unique_ids(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.check_task_attachment_consistency(),
            {
                "opportunity_id": "opp-test-1",
                "valid": True,
                "task_count": 3,
                "valid_task_count": 3,
                "invalid_task_count": 0,
                "duplicate_count": 0,
                "issues": [],
            },
        )

    def test_duplicate_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-1"])
        result = opportunity.check_task_attachment_consistency()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 3)
        self.assertEqual(result["valid_task_count"], 3)
        self.assertEqual(result["invalid_task_count"], 0)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(len(result["issues"]), 1)

    def test_empty_strings(self):
        opportunity = _make_opportunity(task_ids=["task-1", ""])
        result = opportunity.check_task_attachment_consistency()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["valid_task_count"], 1)
        self.assertEqual(result["invalid_task_count"], 1)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(len(result["issues"]), 1)

    def test_whitespace_only_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "   "])
        result = opportunity.check_task_attachment_consistency()
        self.assertFalse(result["valid"])
        self.assertEqual(result["valid_task_count"], 1)
        self.assertEqual(result["invalid_task_count"], 1)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(len(result["issues"]), 1)

    def test_non_string_values(self):
        opportunity = _make_opportunity(task_ids=[None, 123, 4.5, True, [], {}])
        result = opportunity.check_task_attachment_consistency()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 6)
        self.assertEqual(result["valid_task_count"], 0)
        self.assertEqual(result["invalid_task_count"], 6)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(len(result["issues"]), 6)

    def test_mixed_valid_and_invalid_values(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, "task-2", "task-1", 123]
        )
        result = opportunity.check_task_attachment_consistency()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 7)
        self.assertEqual(result["valid_task_count"], 3)
        self.assertEqual(result["invalid_task_count"], 4)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(len(result["issues"]), 5)

    def test_task_ids_unchanged_after_check(self):
        original = ["task-1", "", "task-1", None, "task-2"]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.check_task_attachment_consistency()
        self.assertEqual(opportunity.task_ids, original)

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-1"])
        result = opportunity.check_task_attachment_consistency()
        result["issues"].append("tampered")
        result["valid"] = True
        second_result = opportunity.check_task_attachment_consistency()
        self.assertNotEqual(second_result["issues"], result["issues"])
        self.assertFalse(second_result["valid"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", ""]
        )
        opportunity.check_task_attachment_consistency()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AR. get_valid_task_ids()
# ----------------------------------------------------------------------
class TestGetValidTaskIds(unittest.TestCase):
    def test_empty_task_ids(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_valid_task_ids(), [])

    def test_one_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1"])

    def test_multiple_valid_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(
            opportunity.get_valid_task_ids(), ["task-1", "task-2", "task-3"]
        )

    def test_whitespace_around_ids(self):
        opportunity = _make_opportunity(task_ids=[" task-1 ", "task-2 ", " task-3"])
        self.assertEqual(
            opportunity.get_valid_task_ids(), ["task-1", "task-2", "task-3"]
        )

    def test_duplicate_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-1"])
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1", "task-2"])

    def test_empty_strings(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-2"])
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1", "task-2"])

    def test_whitespace_only_strings(self):
        opportunity = _make_opportunity(task_ids=["task-1", "   ", "task-2"])
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1", "task-2"])

    def test_non_string_values(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", 123, None, 4.5, True, [], {}, "task-2"]
        )
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1", "task-2"])

    def test_mixed_valid_and_invalid_values(self):
        opportunity = _make_opportunity(
            task_ids=["task-2", " task-1 ", "task-2", "", "task-1", None]
        )
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-2", "task-1"])

    def test_preserves_original_order(self):
        opportunity = _make_opportunity(
            task_ids=["task-3", "task-1", "task-2", "task-1"]
        )
        self.assertEqual(
            opportunity.get_valid_task_ids(), ["task-3", "task-1", "task-2"]
        )

    def test_original_task_ids_unchanged(self):
        original = [" task_1 ", "task_2", "task_1", "", "   ", 123]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_valid_task_ids()
        self.assertEqual(opportunity.task_ids, original)

    def test_returned_list_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        result = opportunity.get_valid_task_ids()
        result.append("task-3")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])
        self.assertEqual(opportunity.get_valid_task_ids(), ["task-1", "task-2"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=[" task-1 ", "task-1"]
        )
        opportunity.get_valid_task_ids()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AS. get_task_readiness()
# ----------------------------------------------------------------------
class TestGetTaskReadiness(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.get_task_readiness(),
            {
                "opportunity_id": "opp-test-1",
                "ready": False,
                "has_tasks": False,
                "task_count": 0,
                "valid_task_count": 0,
                "invalid_task_count": 0,
                "issues": [],
            },
        )

    def test_one_valid_task(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        self.assertEqual(
            opportunity.get_task_readiness(),
            {
                "opportunity_id": "opp-test-1",
                "ready": True,
                "has_tasks": True,
                "task_count": 1,
                "valid_task_count": 1,
                "invalid_task_count": 0,
                "issues": [],
            },
        )

    def test_multiple_valid_unique_tasks(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_readiness(),
            {
                "opportunity_id": "opp-test-1",
                "ready": True,
                "has_tasks": True,
                "task_count": 3,
                "valid_task_count": 3,
                "invalid_task_count": 0,
                "issues": [],
            },
        )

    def test_duplicate_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-1"])
        result = opportunity.get_task_readiness()
        self.assertFalse(result["ready"])
        self.assertTrue(result["has_tasks"])
        self.assertEqual(result["task_count"], 3)
        self.assertEqual(result["valid_task_count"], 2)
        self.assertEqual(result["invalid_task_count"], 0)
        self.assertEqual(len(result["issues"]), 1)

    def test_invalid_task_ids(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123])
        result = opportunity.get_task_readiness()
        self.assertFalse(result["ready"])
        self.assertFalse(result["has_tasks"])
        self.assertEqual(result["task_count"], 4)
        self.assertEqual(result["valid_task_count"], 0)
        self.assertEqual(result["invalid_task_count"], 4)
        self.assertEqual(len(result["issues"]), 4)

    def test_mixed_valid_and_invalid_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", None, "task-1"]
        )
        result = opportunity.get_task_readiness()
        self.assertFalse(result["ready"])
        self.assertTrue(result["has_tasks"])
        self.assertEqual(result["task_count"], 5)
        self.assertEqual(result["valid_task_count"], 2)
        self.assertEqual(result["invalid_task_count"], 2)
        self.assertEqual(len(result["issues"]), 3)

    def test_correct_readiness_result(self):
        ready_opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertTrue(ready_opportunity.get_task_readiness()["ready"])

        not_ready_opportunity = _make_opportunity(task_ids=["task-1", "task-1"])
        self.assertFalse(not_ready_opportunity.get_task_readiness()["ready"])

        empty_opportunity = _make_opportunity(task_ids=[])
        self.assertFalse(empty_opportunity.get_task_readiness()["ready"])

    def test_task_ids_unchanged(self):
        original = ["task-1", "", "task-1", None, "task-2"]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_task_readiness()
        self.assertEqual(opportunity.task_ids, original)

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_readiness()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-1"])
        result = opportunity.get_task_readiness()
        result["issues"].append("tampered")
        result["ready"] = True
        second_result = opportunity.get_task_readiness()
        self.assertNotEqual(second_result["issues"], result["issues"])
        self.assertFalse(second_result["ready"])


# ----------------------------------------------------------------------
# AT. get_task_status()
# ----------------------------------------------------------------------
class TestGetTaskStatus(unittest.TestCase):
    def test_no_tasks(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.get_task_status(),
            {
                "opportunity_id": "opp-test-1",
                "has_tasks": False,
                "task_count": 0,
                "valid_task_count": 0,
                "invalid_task_count": 0,
                "ready": False,
                "status": "NO_TASKS",
            },
        )

    def test_valid_tasks(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        self.assertEqual(
            opportunity.get_task_status(),
            {
                "opportunity_id": "opp-test-1",
                "has_tasks": True,
                "task_count": 2,
                "valid_task_count": 2,
                "invalid_task_count": 0,
                "ready": True,
                "status": "READY",
            },
        )

    def test_duplicate_task_ids(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-1"]
        )
        result = opportunity.get_task_status()
        self.assertEqual(result["status"], "INVALID_TASKS")
        self.assertFalse(result["ready"])
        self.assertTrue(result["has_tasks"])
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["valid_task_count"], 1)
        self.assertEqual(result["invalid_task_count"], 0)

    def test_invalid_task_ids(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["", "   ", None, 123]
        )
        result = opportunity.get_task_status()
        self.assertEqual(result["status"], "NO_TASKS")
        self.assertFalse(result["ready"])
        self.assertFalse(result["has_tasks"])
        self.assertEqual(result["task_count"], 4)
        self.assertEqual(result["valid_task_count"], 0)
        self.assertEqual(result["invalid_task_count"], 4)

    def test_mixed_valid_and_invalid_ids(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1",
            task_ids=["task-1", "", "task-2", None, "task-1"],
        )
        result = opportunity.get_task_status()
        self.assertEqual(result["status"], "INVALID_TASKS")
        self.assertFalse(result["ready"])
        self.assertTrue(result["has_tasks"])
        self.assertEqual(result["task_count"], 5)
        self.assertEqual(result["valid_task_count"], 2)
        self.assertEqual(result["invalid_task_count"], 2)

    def test_correct_status_values(self):
        no_tasks = _make_opportunity(task_ids=[])
        self.assertEqual(no_tasks.get_task_status()["status"], "NO_TASKS")

        only_invalid = _make_opportunity(task_ids=["", None])
        self.assertEqual(only_invalid.get_task_status()["status"], "NO_TASKS")

        with_duplicates = _make_opportunity(task_ids=["task-1", "task-1"])
        self.assertEqual(
            with_duplicates.get_task_status()["status"], "INVALID_TASKS"
        )

        mixed = _make_opportunity(task_ids=["task-1", ""])
        self.assertEqual(mixed.get_task_status()["status"], "INVALID_TASKS")

        ready = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(ready.get_task_status()["status"], "READY")

    def test_task_ids_unchanged(self):
        original = ["task-1", "", "task-1", None, "task-2"]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_task_status()
        self.assertEqual(opportunity.task_ids, original)

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_task_status()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AU. get_task_validation_report()
# ----------------------------------------------------------------------
class TestGetTaskValidationReport(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(opportunity_id="opp-test-1", task_ids=[])
        self.assertEqual(
            opportunity.get_task_validation_report(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 0,
                "valid_task_count": 0,
                "invalid_task_count": 0,
                "duplicate_count": 0,
                "valid": True,
                "issues": [],
            },
        )

    def test_all_valid_unique_task_ids(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_validation_report(),
            {
                "opportunity_id": "opp-test-1",
                "task_count": 3,
                "valid_task_count": 3,
                "invalid_task_count": 0,
                "duplicate_count": 0,
                "valid": True,
                "issues": [],
            },
        )

    def test_duplicate_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-1"])
        result = opportunity.get_task_validation_report()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 3)
        self.assertEqual(result["valid_task_count"], 3)
        self.assertEqual(result["invalid_task_count"], 0)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(len(result["issues"]), 1)

    def test_invalid_ids(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123])
        result = opportunity.get_task_validation_report()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 4)
        self.assertEqual(result["valid_task_count"], 0)
        self.assertEqual(result["invalid_task_count"], 4)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(len(result["issues"]), 4)

    def test_mixed_valid_and_invalid_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", None, "task-1"]
        )
        result = opportunity.get_task_validation_report()
        self.assertFalse(result["valid"])
        self.assertEqual(result["task_count"], 5)
        self.assertEqual(result["valid_task_count"], 3)
        self.assertEqual(result["invalid_task_count"], 2)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(len(result["issues"]), 3)

    def test_correct_counts(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-1", "", None]
        )
        result = opportunity.get_task_validation_report()
        self.assertEqual(
            result["task_count"],
            result["valid_task_count"] + result["invalid_task_count"],
        )
        self.assertEqual(result["valid_task_count"], 3)
        self.assertEqual(result["invalid_task_count"], 2)
        self.assertEqual(result["duplicate_count"], 1)

    def test_correct_valid_value(self):
        self.assertTrue(
            _make_opportunity(task_ids=[]).get_task_validation_report()["valid"]
        )
        self.assertTrue(
            _make_opportunity(task_ids=["task-1"]).get_task_validation_report()[
                "valid"
            ]
        )
        self.assertFalse(
            _make_opportunity(
                task_ids=["task-1", "task-1"]
            ).get_task_validation_report()["valid"]
        )
        self.assertFalse(
            _make_opportunity(task_ids=["task-1", ""]).get_task_validation_report()[
                "valid"
            ]
        )

    def test_returned_dictionary_and_list_are_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "task-1"])
        result = opportunity.get_task_validation_report()
        result["issues"].append("tampered")
        result["valid"] = True
        second_result = opportunity.get_task_validation_report()
        self.assertNotEqual(second_result["issues"], result["issues"])
        self.assertFalse(second_result["valid"])

    def test_original_task_ids_unchanged(self):
        original = ["task-1", "", "task-1", None, "task-2"]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_task_validation_report()
        self.assertEqual(opportunity.task_ids, original)

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", ""]
        )
        opportunity.get_task_validation_report()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AV. get_next_task_id()
# ----------------------------------------------------------------------
class TestGetNextTaskId(unittest.TestCase):
    def test_first_task_returns_second_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_next_task_id("task-1"), "task-2")

    def test_middle_task_returns_next_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_next_task_id("task-2"), "task-3")

    def test_last_task_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertIsNone(opportunity.get_next_task_id("task-3"))

    def test_unknown_task_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_next_task_id("task-missing"))

    def test_empty_task_id_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_next_task_id(""))
        self.assertIsNone(opportunity.get_next_task_id("   "))

    def test_invalid_task_id_types_return_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_next_task_id(None))
        self.assertIsNone(opportunity.get_next_task_id(123))
        self.assertIsNone(opportunity.get_next_task_id(4.5))
        self.assertIsNone(opportunity.get_next_task_id(True))
        self.assertIsNone(opportunity.get_next_task_id([]))
        self.assertIsNone(opportunity.get_next_task_id({}))

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_next_task_id(" task-1 "), "task-2")
        self.assertEqual(opportunity.get_next_task_id("task-2 "), "task-3")

    def test_skips_invalid_entries_to_find_next_valid_id(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, "task-2"]
        )
        self.assertEqual(opportunity.get_next_task_id("task-1"), "task-2")

    def test_only_invalid_entries_after_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "", "   ", None])
        self.assertIsNone(opportunity.get_next_task_id("task-1"))

    def test_empty_task_ids_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertIsNone(opportunity.get_next_task_id("task-1"))

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        opportunity.get_next_task_id("task-1")
        opportunity.get_next_task_id("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.get_next_task_id("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AW. get_previous_task_id()
# ----------------------------------------------------------------------
class TestGetPreviousTaskId(unittest.TestCase):
    def test_second_task_returns_first_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_previous_task_id("task-2"), "task-1")

    def test_middle_task_returns_previous_task(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3", "task-4"]
        )
        self.assertEqual(opportunity.get_previous_task_id("task-3"), "task-2")

    def test_first_task_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertIsNone(opportunity.get_previous_task_id("task-1"))

    def test_last_task_returns_previous_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_previous_task_id("task-3"), "task-2")

    def test_unknown_task_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_previous_task_id("task-missing"))

    def test_empty_task_id_returns_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_previous_task_id(""))
        self.assertIsNone(opportunity.get_previous_task_id("   "))

    def test_invalid_task_id_types_return_none(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_previous_task_id(None))
        self.assertIsNone(opportunity.get_previous_task_id(123))
        self.assertIsNone(opportunity.get_previous_task_id(4.5))
        self.assertIsNone(opportunity.get_previous_task_id(True))
        self.assertIsNone(opportunity.get_previous_task_id([]))
        self.assertIsNone(opportunity.get_previous_task_id({}))

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_previous_task_id(" task-2 "), "task-1")
        self.assertEqual(opportunity.get_previous_task_id("task-3 "), "task-2")

    def test_skips_invalid_entries_to_find_previous_valid_id(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", None, "   ", "", "task-2"]
        )
        self.assertEqual(opportunity.get_previous_task_id("task-2"), "task-1")

    def test_only_invalid_entries_before_returns_none(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, "task-1"])
        self.assertIsNone(opportunity.get_previous_task_id("task-1"))

    def test_empty_task_ids_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertIsNone(opportunity.get_previous_task_id("task-1"))

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        opportunity.get_previous_task_id("task-2")
        opportunity.get_previous_task_id("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.get_previous_task_id("task-2")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AX. get_first_task_id()
# ----------------------------------------------------------------------
class TestGetFirstTaskId(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertIsNone(opportunity.get_first_task_id())

    def test_one_valid_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_first_task_id(), "task-1")

    def test_multiple_tasks(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_first_task_id(), "task-1")

    def test_invalid_values_before_a_valid_task(self):
        opportunity = _make_opportunity(
            task_ids=["", "   ", None, 123, "task-1", "task-2"]
        )
        self.assertEqual(opportunity.get_first_task_id(), "task-1")

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=[" task-1 ", "task-2"])
        self.assertEqual(opportunity.get_first_task_id(), "task-1")

    def test_no_valid_ids(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123, [], {}])
        self.assertIsNone(opportunity.get_first_task_id())

    def test_does_not_modify_task_ids(self):
        original = ["", "   ", None, "task-1", "task-2"]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_first_task_id()
        self.assertEqual(opportunity.task_ids, original)

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_first_task_id()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AY. get_last_task_id()
# ----------------------------------------------------------------------
class TestGetLastTaskId(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertIsNone(opportunity.get_last_task_id())

    def test_one_valid_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_last_task_id(), "task-1")

    def test_multiple_valid_tasks(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(opportunity.get_last_task_id(), "task-3")

    def test_invalid_values_after_a_valid_task(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "", "   ", None, 123]
        )
        self.assertEqual(opportunity.get_last_task_id(), "task-2")

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", " task-2 "])
        self.assertEqual(opportunity.get_last_task_id(), "task-2")

    def test_no_valid_ids(self):
        opportunity = _make_opportunity(task_ids=["", "   ", None, 123, [], {}])
        self.assertIsNone(opportunity.get_last_task_id())

    def test_does_not_modify_task_ids(self):
        original = ["task-1", "task-2", "", "   ", None]
        opportunity = _make_opportunity(task_ids=list(original))
        opportunity.get_last_task_id()
        self.assertEqual(opportunity.task_ids, original)

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1"]
        )
        opportunity.get_last_task_id()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# AZ. get_adjacent_task_ids()
# ----------------------------------------------------------------------
class TestGetAdjacentTaskIds(unittest.TestCase):
    def test_middle_task_with_both_neighbors(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_adjacent_task_ids("task-2"),
            {"previous_task_id": "task-1", "next_task_id": "task-3"},
        )

    def test_first_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(
            opportunity.get_adjacent_task_ids("task-1"),
            {"previous_task_id": None, "next_task_id": "task-2"},
        )

    def test_last_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(
            opportunity.get_adjacent_task_ids("task-3"),
            {"previous_task_id": "task-2", "next_task_id": None},
        )

    def test_only_one_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(
            opportunity.get_adjacent_task_ids("task-1"),
            {"previous_task_id": None, "next_task_id": None},
        )

    def test_unknown_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_adjacent_task_ids("task-missing"))

    def test_invalid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_adjacent_task_ids(""))
        self.assertIsNone(opportunity.get_adjacent_task_ids("   "))
        self.assertIsNone(opportunity.get_adjacent_task_ids(None))
        self.assertIsNone(opportunity.get_adjacent_task_ids(123))

    def test_whitespace_around_a_valid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        self.assertEqual(
            opportunity.get_adjacent_task_ids(" task-2 "),
            {"previous_task_id": "task-1", "next_task_id": "task-3"},
        )

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        opportunity.get_adjacent_task_ids("task-2")
        opportunity.get_adjacent_task_ids("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2", "task-3"])

    def test_does_not_modify_other_fields(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.get_adjacent_task_ids("task-1")
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertTrue(opportunity.is_valid())

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2", "task-3"])
        result = opportunity.get_adjacent_task_ids("task-2")
        result["previous_task_id"] = "tampered"
        result["next_task_id"] = "tampered"
        second_result = opportunity.get_adjacent_task_ids("task-2")
        self.assertEqual(second_result["previous_task_id"], "task-1")
        self.assertEqual(second_result["next_task_id"], "task-3")


# ----------------------------------------------------------------------
# BA. get_task_snapshot()
# ----------------------------------------------------------------------
class TestGetTaskSnapshot(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(
            opportunity.get_task_snapshot(),
            {
                "opportunity_id": "opp-test-1",
                "task_ids": [],
                "task_count": 0,
                "first_task_id": None,
                "last_task_id": None,
            },
        )

    def test_one_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(
            opportunity.get_task_snapshot(),
            {
                "opportunity_id": "opp-test-1",
                "task_ids": ["task-1"],
                "task_count": 1,
                "first_task_id": "task-1",
                "last_task_id": "task-1",
            },
        )

    def test_multiple_tasks(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_snapshot(),
            {
                "opportunity_id": "opp-test-1",
                "task_ids": ["task-1", "task-2", "task-3"],
                "task_count": 3,
                "first_task_id": "task-1",
                "last_task_id": "task-3",
            },
        )

    def test_correct_task_count(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", "   ", None, 123]
        )
        snapshot = opportunity.get_task_snapshot()
        self.assertEqual(snapshot["task_count"], 2)
        self.assertEqual(snapshot["task_count"], opportunity.get_task_count())

    def test_correct_first_and_last_task(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        snapshot = opportunity.get_task_snapshot()
        self.assertEqual(snapshot["first_task_id"], "task-1")
        self.assertEqual(snapshot["last_task_id"], "task-3")
        self.assertEqual(snapshot["first_task_id"], opportunity.get_first_task_id())
        self.assertEqual(snapshot["last_task_id"], opportunity.get_last_task_id())

    def test_independent_task_ids_list(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        snapshot = opportunity.get_task_snapshot()
        self.assertIsNot(snapshot["task_ids"], opportunity.task_ids)

    def test_modifying_snapshot_does_not_modify_opportunity(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        snapshot = opportunity.get_task_snapshot()
        snapshot["task_ids"].append("tampered")
        snapshot["task_ids"][0] = "tampered-again"
        snapshot["task_count"] = 999
        snapshot["opportunity_id"] = "tampered-id"
        snapshot["first_task_id"] = "tampered"
        snapshot["last_task_id"] = "tampered"
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_original_object_remains_unchanged(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-test-1", task_ids=["task-1", "task-2"]
        )
        opportunity.get_task_snapshot()
        self.assertEqual(opportunity.opportunity_id, "opp-test-1")
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# BB. get_task_attachment_status()
# ----------------------------------------------------------------------
class TestGetTaskAttachmentStatus(unittest.TestCase):
    def test_attached_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(
            opportunity.get_task_attachment_status("task-1"),
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-1",
                "attached": True,
                "index": 0,
            },
        )

    def test_non_attached_task(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(
            opportunity.get_task_attachment_status("task-missing"),
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-missing",
                "attached": False,
                "index": -1,
            },
        )

    def test_first_task_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        result = opportunity.get_task_attachment_status("task-1")
        self.assertTrue(result["attached"])
        self.assertEqual(result["index"], 0)

    def test_middle_task_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        result = opportunity.get_task_attachment_status("task-2")
        self.assertTrue(result["attached"])
        self.assertEqual(result["index"], 1)

    def test_last_task_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        result = opportunity.get_task_attachment_status("task-3")
        self.assertTrue(result["attached"])
        self.assertEqual(result["index"], 2)

    def test_invalid_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_attachment_status(None))
        self.assertIsNone(opportunity.get_task_attachment_status(123))
        self.assertIsNone(opportunity.get_task_attachment_status([]))

    def test_empty_task_id(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertIsNone(opportunity.get_task_attachment_status(""))
        self.assertIsNone(opportunity.get_task_attachment_status("   "))

    def test_whitespace_around_a_valid_id(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(
            opportunity.get_task_attachment_status(" task-2 "),
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-2",
                "attached": True,
                "index": 1,
            },
        )

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        opportunity.get_task_attachment_status("task-1")
        opportunity.get_task_attachment_status("task-missing")
        self.assertEqual(opportunity.task_ids, ["task-1", "task-2"])

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        result = opportunity.get_task_attachment_status("task-1")
        result["attached"] = False
        result["index"] = 999
        result["task_id"] = "tampered"
        result["opportunity_id"] = "tampered"
        second_result = opportunity.get_task_attachment_status("task-1")
        self.assertEqual(
            second_result,
            {
                "opportunity_id": "opp-test-1",
                "task_id": "task-1",
                "attached": True,
                "index": 0,
            },
        )


# ----------------------------------------------------------------------
# BC. get_task_positions()
# ----------------------------------------------------------------------
class TestGetTaskPositions(unittest.TestCase):
    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_task_positions(), {})

    def test_one_valid_task(self):
        opportunity = _make_opportunity(task_ids=["task-1"])
        self.assertEqual(opportunity.get_task_positions(), {"task-1": 0})

    def test_multiple_valid_tasks(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_positions(),
            {"task-1": 0, "task-2": 1, "task-3": 2},
        )

    def test_correct_zero_based_positions(self):
        opportunity = _make_opportunity(
            task_ids=["task-a", "task-b", "task-c", "task-d"]
        )
        positions = opportunity.get_task_positions()
        self.assertEqual(positions["task-a"], 0)
        self.assertEqual(positions["task-b"], 1)
        self.assertEqual(positions["task-c"], 2)
        self.assertEqual(positions["task-d"], 3)

    def test_whitespace_around_ids(self):
        opportunity = _make_opportunity(
            task_ids=[" task-1 ", "task-2\t", "\ntask-3"]
        )
        self.assertEqual(
            opportunity.get_task_positions(),
            {"task-1": 0, "task-2": 1, "task-3": 2},
        )

    def test_invalid_values(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, [], "task-2"]
        )
        self.assertEqual(
            opportunity.get_task_positions(),
            {"task-1": 0, "task-2": 6},
        )

    def test_duplicate_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-1", "task-3", "task-2"]
        )
        self.assertEqual(
            opportunity.get_task_positions(),
            {"task-1": 0, "task-2": 1, "task-3": 3},
        )

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", "task-1"]
        )
        opportunity.get_task_positions()
        self.assertEqual(
            opportunity.task_ids, ["task-1", "", "task-2", "task-1"]
        )

    def test_returned_dictionary_is_independent(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        result = opportunity.get_task_positions()
        result["task-1"] = 999
        result["tampered"] = 0
        second_result = opportunity.get_task_positions()
        self.assertEqual(second_result, {"task-1": 0, "task-2": 1})


# ----------------------------------------------------------------------
# BD. get_task_id_at()
# ----------------------------------------------------------------------
class TestGetTaskIdAt(unittest.TestCase):
    def test_first_position(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_id_at(0), "task-1")

    def test_middle_position(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_id_at(1), "task-2")

    def test_last_position(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_id_at(2), "task-3")

    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertIsNone(opportunity.get_task_id_at(0))

    def test_negative_index(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_task_id_at(-1))
        self.assertIsNone(opportunity.get_task_id_at(-100))

    def test_index_beyond_range(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_task_id_at(2))
        self.assertIsNone(opportunity.get_task_id_at(100))

    def test_invalid_index_types(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertIsNone(opportunity.get_task_id_at("0"))
        self.assertIsNone(opportunity.get_task_id_at(1.0))
        self.assertIsNone(opportunity.get_task_id_at(None))
        self.assertIsNone(opportunity.get_task_id_at([]))
        self.assertIsNone(opportunity.get_task_id_at(True))
        self.assertIsNone(opportunity.get_task_id_at(False))

    def test_invalid_values_inside_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, "task-2"]
        )
        self.assertEqual(opportunity.get_task_id_at(0), "task-1")
        self.assertEqual(opportunity.get_task_id_at(1), "task-2")
        self.assertIsNone(opportunity.get_task_id_at(2))

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", None]
        )
        opportunity.get_task_id_at(0)
        opportunity.get_task_id_at(5)
        opportunity.get_task_id_at(-1)
        self.assertEqual(
            opportunity.task_ids, ["task-1", "", "task-2", None]
        )


# ----------------------------------------------------------------------
# BE. is_valid_task_index()
# ----------------------------------------------------------------------
class TestIsValidTaskIndex(unittest.TestCase):
    def test_first_valid_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertTrue(opportunity.is_valid_task_index(0))

    def test_middle_valid_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertTrue(opportunity.is_valid_task_index(1))

    def test_last_valid_index(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertTrue(opportunity.is_valid_task_index(2))

    def test_negative_index(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertFalse(opportunity.is_valid_task_index(-1))
        self.assertFalse(opportunity.is_valid_task_index(-100))

    def test_index_beyond_range(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertFalse(opportunity.is_valid_task_index(2))
        self.assertFalse(opportunity.is_valid_task_index(100))

    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertFalse(opportunity.is_valid_task_index(0))

    def test_invalid_index_types(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertFalse(opportunity.is_valid_task_index("0"))
        self.assertFalse(opportunity.is_valid_task_index(1.0))
        self.assertFalse(opportunity.is_valid_task_index(None))
        self.assertFalse(opportunity.is_valid_task_index([]))
        self.assertFalse(opportunity.is_valid_task_index(True))
        self.assertFalse(opportunity.is_valid_task_index(False))

    def test_invalid_values_inside_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, "task-2"]
        )
        self.assertTrue(opportunity.is_valid_task_index(0))
        self.assertTrue(opportunity.is_valid_task_index(1))
        self.assertFalse(opportunity.is_valid_task_index(2))

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", None]
        )
        opportunity.is_valid_task_index(0)
        opportunity.is_valid_task_index(5)
        opportunity.is_valid_task_index(-1)
        self.assertEqual(
            opportunity.task_ids, ["task-1", "", "task-2", None]
        )


# ----------------------------------------------------------------------
# BF. get_task_range()
# ----------------------------------------------------------------------
class TestGetTaskRange(unittest.TestCase):
    def test_normal_range(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3", "task-4"]
        )
        self.assertEqual(
            opportunity.get_task_range(1, 3), ["task-2", "task-3"]
        )

    def test_first_to_last_range(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_range(0, 3),
            ["task-1", "task-2", "task-3"],
        )

    def test_single_item_range(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_range(1, 2), ["task-2"])

    def test_empty_range(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_range(1, 1), [])
        self.assertEqual(opportunity.get_task_range(2, 1), [])
        self.assertEqual(opportunity.get_task_range(0, 0), [])

    def test_out_of_range_values(self):
        opportunity = _make_opportunity(task_ids=["task-1", "task-2"])
        self.assertEqual(opportunity.get_task_range(0, 100), ["task-1", "task-2"])
        self.assertEqual(opportunity.get_task_range(5, 10), [])
        self.assertEqual(opportunity.get_task_range(1, 100), ["task-2"])

    def test_empty_task_list(self):
        opportunity = _make_opportunity(task_ids=[])
        self.assertEqual(opportunity.get_task_range(0, 5), [])

    def test_negative_indexes(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_range(-1, 2), [])
        self.assertEqual(opportunity.get_task_range(0, -1), [])
        self.assertEqual(opportunity.get_task_range(-2, -1), [])

    def test_invalid_index_types(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        self.assertEqual(opportunity.get_task_range("0", 2), [])
        self.assertEqual(opportunity.get_task_range(0, "2"), [])
        self.assertEqual(opportunity.get_task_range(1.0, 2), [])
        self.assertEqual(opportunity.get_task_range(0, 2.0), [])
        self.assertEqual(opportunity.get_task_range(None, 2), [])
        self.assertEqual(opportunity.get_task_range(0, None), [])
        self.assertEqual(opportunity.get_task_range(True, 2), [])
        self.assertEqual(opportunity.get_task_range(0, False), [])

    def test_invalid_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "   ", None, 123, "task-2", "task-3"]
        )
        self.assertEqual(
            opportunity.get_task_range(0, 3),
            ["task-1", "task-2", "task-3"],
        )

    def test_does_not_modify_task_ids(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "", "task-2", None, "task-3"]
        )
        opportunity.get_task_range(0, 5)
        opportunity.get_task_range(-1, 2)
        opportunity.get_task_range(2, 1)
        self.assertEqual(
            opportunity.task_ids,
            ["task-1", "", "task-2", None, "task-3"],
        )

    def test_returned_list_is_independent(self):
        opportunity = _make_opportunity(
            task_ids=["task-1", "task-2", "task-3"]
        )
        result = opportunity.get_task_range(0, 2)
        result.append("tampered")
        result[0] = "tampered-again"
        second_result = opportunity.get_task_range(0, 2)
        self.assertEqual(second_result, ["task-1", "task-2"])


if __name__ == "__main__":
    unittest.main()
