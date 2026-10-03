"""
Tests for RevenueOpportunitySelector and SelectionResult
(financial/revenue_selector.py - builds on the FinancialGoal,
RevenueStrategy, and RevenueOpportunity stages).

Covers: selecting one opportunity, selecting multiple, filtering by
goal, deterministic selection, empty input, invalid opportunities,
structured reasons, and a confirmation that the full existing test
suite (including all three previous financial stages) still passes.

Run directly:
    python -m unittest tests.test_revenue_selector -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_opportunity import RevenueOpportunity, LEVEL_LOW, LEVEL_HIGH
from financial.revenue_selector import RevenueOpportunitySelector, SelectionResult


def _make_opportunity(**overrides):
    fields = dict(
        opportunity_id="opp-test-1",
        goal_id="goal-1",
        name="Sell a small mobile game",
        description="Ship and sell a small mobile game on an app store.",
        estimated_income=500,
        currency="USD",
        time_period="monthly",
        confidence=0.5,
    )
    fields.update(overrides)
    return RevenueOpportunity(**fields)


class TestSelectionResultDefaults(unittest.TestCase):
    def test_defaults_are_empty_and_safe(self):
        result = SelectionResult()
        self.assertEqual(result.selected_opportunities, [])
        self.assertEqual(result.rejected_opportunities, [])
        self.assertEqual(result.reason, "")
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.warnings, [])

    def test_to_dict_is_json_shaped(self):
        result = SelectionResult()
        result.selected_opportunities = [_make_opportunity()]
        result.rejected_opportunities = [{"opportunity_id": "x", "reason": "because"}]
        result.reason = "some reason"
        result.confidence = 0.5
        result.warnings = ["a warning"]

        as_dict = result.to_dict()
        self.assertIsInstance(as_dict["selected_opportunities"][0], dict)
        self.assertEqual(as_dict["rejected_opportunities"], [{"opportunity_id": "x", "reason": "because"}])
        self.assertEqual(as_dict["reason"], "some reason")
        self.assertEqual(as_dict["confidence"], 0.5)
        self.assertEqual(as_dict["warnings"], ["a warning"])


# ----------------------------------------------------------------------
# 1. Selecting one opportunity
# ----------------------------------------------------------------------
class TestSelectOne(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()

    def test_selects_the_single_best_opportunity_by_default(self):
        low = _make_opportunity(opportunity_id="low", confidence=0.2)
        high = _make_opportunity(opportunity_id="high", confidence=0.9)

        result = self.selector.select([low, high])

        self.assertEqual(len(result.selected_opportunities), 1)
        self.assertEqual(result.selected_opportunities[0].opportunity_id, "high")
        self.assertEqual(result.confidence, 0.9)

    def test_never_claims_guaranteed_income(self):
        result = self.selector.select([_make_opportunity()])
        self.assertIn("does not guarantee", result.reason)


# ----------------------------------------------------------------------
# 2. Selecting multiple opportunities
# ----------------------------------------------------------------------
class TestSelectMultiple(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()
        self.opportunities = [
            _make_opportunity(opportunity_id="a", confidence=0.9),
            _make_opportunity(opportunity_id="b", confidence=0.6),
            _make_opportunity(opportunity_id="c", confidence=0.3),
        ]

    def test_selects_top_n_in_ranked_order(self):
        result = self.selector.select(self.opportunities, limit=2)
        self.assertEqual(
            [o.opportunity_id for o in result.selected_opportunities], ["a", "b"]
        )
        self.assertEqual(len(result.rejected_opportunities), 1)
        self.assertEqual(result.rejected_opportunities[0]["opportunity_id"], "c")

    def test_confidence_is_mean_of_selected(self):
        result = self.selector.select(self.opportunities, limit=2)
        self.assertAlmostEqual(result.confidence, (0.9 + 0.6) / 2)

    def test_limit_larger_than_available_selects_all_with_warning(self):
        result = self.selector.select(self.opportunities, limit=10)
        self.assertEqual(len(result.selected_opportunities), 3)
        self.assertEqual(result.rejected_opportunities, [])
        self.assertTrue(any("Only 3" in w for w in result.warnings))


# ----------------------------------------------------------------------
# 3. Filtering by goal
# ----------------------------------------------------------------------
class TestSelectForGoal(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()

    def test_only_considers_opportunities_for_the_given_goal(self):
        for_goal = _make_opportunity(opportunity_id="for-goal", goal_id="goal-A", confidence=0.4)
        other_goal = _make_opportunity(opportunity_id="other-goal", goal_id="goal-B", confidence=0.9)

        result = self.selector.select_for_goal([for_goal, other_goal], goal_id="goal-A", limit=5)

        self.assertEqual(
            [o.opportunity_id for o in result.selected_opportunities], ["for-goal"]
        )
        self.assertEqual(len(result.rejected_opportunities), 1)
        self.assertIn("different goal", result.rejected_opportunities[0]["reason"])
        self.assertEqual(result.rejected_opportunities[0]["opportunity_id"], "other-goal")

    def test_no_matching_goal_yields_empty_selection(self):
        opportunity = _make_opportunity(goal_id="goal-A")
        result = self.selector.select_for_goal([opportunity], goal_id="goal-Z", limit=1)
        self.assertEqual(result.selected_opportunities, [])
        self.assertTrue(result.warnings)


# ----------------------------------------------------------------------
# 4. Deterministic selection
# ----------------------------------------------------------------------
class TestDeterministicSelection(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()
        self.opportunities = [
            _make_opportunity(opportunity_id="a", confidence=0.4),
            _make_opportunity(opportunity_id="b", confidence=0.8),
            _make_opportunity(opportunity_id="c", confidence=0.6),
        ]

    def test_repeated_calls_produce_identical_selection(self):
        first = self.selector.select(self.opportunities, limit=2)
        second = self.selector.select(self.opportunities, limit=2)

        self.assertEqual(
            [o.opportunity_id for o in first.selected_opportunities],
            [o.opportunity_id for o in second.selected_opportunities],
        )
        self.assertEqual(first.confidence, second.confidence)

    def test_fresh_selector_instance_produces_the_same_result(self):
        result_a = RevenueOpportunitySelector().select(self.opportunities, limit=2)
        result_b = RevenueOpportunitySelector().select(self.opportunities, limit=2)
        self.assertEqual(
            [o.opportunity_id for o in result_a.selected_opportunities],
            [o.opportunity_id for o in result_b.selected_opportunities],
        )

    def test_tie_breaking_uses_risk_then_effort_then_income_like_the_planner(self):
        higher_risk = _make_opportunity(
            opportunity_id="higher-risk", confidence=0.5, risk_level=LEVEL_HIGH
        )
        lower_risk = _make_opportunity(
            opportunity_id="lower-risk", confidence=0.5, risk_level=LEVEL_LOW
        )
        result = self.selector.select([higher_risk, lower_risk], limit=1)
        self.assertEqual(result.selected_opportunities[0].opportunity_id, "lower-risk")

    def test_select_does_not_mutate_input(self):
        opportunities = [_make_opportunity(opportunity_id="a", confidence=0.5)]
        self.selector.select(opportunities, limit=1)
        self.assertEqual(opportunities[0].confidence, 0.5)


# ----------------------------------------------------------------------
# 5. Handling empty opportunity lists
# ----------------------------------------------------------------------
class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()

    def test_empty_list_returns_empty_selection_with_warning(self):
        result = self.selector.select([])
        self.assertEqual(result.selected_opportunities, [])
        self.assertEqual(result.rejected_opportunities, [])
        self.assertTrue(result.warnings)
        self.assertEqual(result.confidence, 0.0)

    def test_none_input_is_treated_as_empty(self):
        result = self.selector.select(None)
        self.assertEqual(result.selected_opportunities, [])
        self.assertTrue(result.warnings)

    def test_inspect_on_empty_list_returns_empty_report(self):
        self.assertEqual(self.selector.inspect([]), [])


# ----------------------------------------------------------------------
# 6. Handling invalid opportunities
# ----------------------------------------------------------------------
class TestInvalidOpportunities(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()

    def test_invalid_opportunity_is_excluded_and_recorded(self):
        valid = _make_opportunity(opportunity_id="valid-one", confidence=0.7)
        invalid = _make_opportunity(opportunity_id="invalid-one", estimated_income=-5)

        result = self.selector.select([valid, invalid], limit=5)

        self.assertEqual(
            [o.opportunity_id for o in result.selected_opportunities], ["valid-one"]
        )
        self.assertEqual(len(result.rejected_opportunities), 1)
        self.assertEqual(result.rejected_opportunities[0]["opportunity_id"], "invalid-one")
        self.assertIn("not a valid RevenueOpportunity", result.rejected_opportunities[0]["reason"])

    def test_non_opportunity_objects_never_raise(self):
        result = self.selector.select(["not an opportunity", None, 42], limit=1)
        self.assertEqual(result.selected_opportunities, [])
        self.assertEqual(len(result.rejected_opportunities), 3)

    def test_all_invalid_yields_empty_selection_with_warning(self):
        invalid = _make_opportunity(estimated_income=-1)
        result = self.selector.select([invalid], limit=1)
        self.assertEqual(result.selected_opportunities, [])
        self.assertTrue(result.warnings)

    def test_inspect_reports_invalid_entries_without_raising(self):
        invalid = _make_opportunity(estimated_income=-1)
        report = self.selector.inspect([invalid, "not an opportunity"])
        self.assertEqual(len(report), 2)
        self.assertFalse(report[0]["valid"])
        self.assertFalse(report[1]["valid"])
        self.assertIsNone(report[0]["rank"])


# ----------------------------------------------------------------------
# 7. Returning structured reasons
# ----------------------------------------------------------------------
class TestStructuredReasons(unittest.TestCase):
    def setUp(self):
        self.selector = RevenueOpportunitySelector()

    def test_rejected_entries_are_dicts_with_id_and_reason(self):
        a = _make_opportunity(opportunity_id="a", confidence=0.9)
        b = _make_opportunity(opportunity_id="b", confidence=0.1)
        result = self.selector.select([a, b], limit=1)

        self.assertEqual(len(result.rejected_opportunities), 1)
        entry = result.rejected_opportunities[0]
        self.assertIn("opportunity_id", entry)
        self.assertIn("reason", entry)
        self.assertIsInstance(entry["reason"], str)
        self.assertTrue(entry["reason"])

    def test_overall_reason_mentions_the_ranking_factors(self):
        result = self.selector.select([_make_opportunity()], limit=1)
        for factor in ("confidence", "risk level", "effort level", "estimated income"):
            self.assertIn(factor, result.reason)

    def test_inspect_report_entries_are_fully_structured(self):
        opportunity = _make_opportunity()
        report = self.selector.inspect([opportunity])
        entry = report[0]
        for key in (
            "opportunity_id", "valid", "rank", "confidence",
            "estimated_income", "effort_level", "risk_level", "reason",
        ):
            self.assertIn(key, entry)


# ----------------------------------------------------------------------
# No execution or real-world side effects
# ----------------------------------------------------------------------
class TestNoExecutionOrSideEffects(unittest.TestCase):
    def test_selector_exposes_no_execution_shaped_methods(self):
        selector = RevenueOpportunitySelector()
        forbidden = (
            "execute", "activate", "pay", "transfer", "withdraw", "deposit",
            "send_money", "generate_income", "run", "contact_customer",
            "make_purchase", "publish", "send_message", "access_website",
            "access_bank", "create_transaction", "fabricate_income",
        )
        for name in forbidden:
            self.assertFalse(hasattr(selector, name))


# ----------------------------------------------------------------------
# 8. Existing tests remain passing (spot check here; the full
# discovery run is done separately - see module docstring).
# ----------------------------------------------------------------------
class TestBackwardCompatibility(unittest.TestCase):
    def test_full_pipeline_goal_strategy_opportunity_selection(self):
        from financial.financial_goal_manager import FinancialGoalManager
        from financial.revenue_strategy_manager import RevenueStrategyManager
        from financial.revenue_opportunity_planner import RevenueOpportunityPlanner

        goal_manager = FinancialGoalManager()
        goal = goal_manager.create_goal(
            original_text="Generate extra monthly income",
            target_amount=1000,
            currency="USD",
            time_period="monthly",
        )

        strategy_manager = RevenueStrategyManager()
        strategy_manager.create_strategy(
            goal_id=goal.goal_id,
            name="Freelance writing",
            description="Take on freelance writing gigs.",
            estimated_income=1000,
            currency="USD",
            time_period="monthly",
            confidence=0.5,
        )
        strategy_manager.create_strategy(
            goal_id=goal.goal_id,
            name="Sell stock photos",
            description="License stock photography online.",
            estimated_income=200,
            currency="USD",
            time_period="monthly",
            confidence=0.8,
        )

        planner = RevenueOpportunityPlanner()
        opportunities = planner.generate_from_goal(goal, strategy_manager.get_all())
        self.assertEqual(len(opportunities), 2)

        selector = RevenueOpportunitySelector()
        result = selector.select_for_goal(opportunities, goal_id=goal.goal_id, limit=1)

        self.assertEqual(len(result.selected_opportunities), 1)
        self.assertEqual(result.selected_opportunities[0].name, "Sell stock photos")


if __name__ == "__main__":
    unittest.main()
