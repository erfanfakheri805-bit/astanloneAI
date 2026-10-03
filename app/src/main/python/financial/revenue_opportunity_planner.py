"""
Revenue Opportunity Planner
==============================
`RevenueOpportunityPlanner` turns already-built `RevenueStrategy`
records (financial/revenue_strategy.py) into candidate
`RevenueOpportunity` records (financial/revenue_opportunity.py), and
can rank a set of opportunities against each other:

    RevenueStrategy (+ FinancialGoal) -> generate_from_strategy() /
        generate_from_goal() -> RevenueOpportunity records
        -> rank_opportunities() / get_top_opportunities()

This is one step in the eventual, much larger pipeline described for
this project's long-term direction:

    GOAL -> FIND OPPORTUNITIES -> CREATE STRATEGIES -> PLAN WORK ->
    USE TOOLS -> EXECUTE -> MEASURE REVENUE -> LEARN -> IMPROVE -> REPEAT

This module only ever *creates structured data* and *orders existing
structured data*. It never does any of the following, at this stage or
any later one this file might eventually grow into having neighbours
for:

- execute a business, contact a customer, or make a purchase
- transfer money, access a bank account, or create a financial
  transaction of any kind
- access a website, send a message, or publish content
- hack a system, bypass a permission, or impersonate a person
- conceal financial activity in any way
- claim or guarantee that any opportunity will definitely make money

Every method here is a pure, deterministic, in-memory transform: same
inputs always produce the same outputs, there is no randomness, no
network access, no filesystem access, and no call to any external
service (including no AI API). Nothing is stored by this class - a
caller that wants to keep a generated opportunity uses
`RevenueOpportunityManager.add_opportunity` for that (see
financial/revenue_opportunity_manager.py); this planner never touches
that store itself, so it stays reusable and independently testable.

Ranking (`rank_opportunities` / `get_top_opportunities`) deliberately
avoids collapsing confidence, estimated income, effort, and risk into
one opaque combined number - a single "hidden score" would be hard to
audit and would implicitly (and arbitrarily) decide how many dollars
of estimated income are "worth" how many points of confidence. Instead
opportunities are ordered by a fixed, documented sequence of
comparisons (see `_ranking_key`'s docstring) - a plain, inspectable
sort, not a black box.
"""

import copy

from .revenue_opportunity import (
    RevenueOpportunity,
    STATUS_DISCOVERED,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    LEVEL_HIGH,
)

# ----------------------------------------------------------------------
# Deterministic effort/risk derivation (used by generate_from_strategy)
# ----------------------------------------------------------------------
# How many combined required_capabilities + required_tools +
# required_inputs a strategy lists is used, as-is, to derive a
# discovered opportunity's effort_level. These thresholds are fixed,
# documented constants - not a learned or hidden model.
_EFFORT_LOW_MAX_REQUIREMENTS = 1
_EFFORT_MEDIUM_MAX_REQUIREMENTS = 3

# How many risks a strategy lists is used, as-is, to derive a
# discovered opportunity's risk_level. Same "fixed, documented
# constants" convention as the effort thresholds above.
_RISK_LOW_MAX_COUNT = 0
_RISK_MEDIUM_MAX_COUNT = 2


def _derive_effort_level(strategy):
    """Deterministic effort_level from how much a strategy says it
    needs (capabilities + tools + inputs, combined count). More stated
    requirements -> more effort. Never raises."""
    required_capabilities = getattr(strategy, "required_capabilities", None) or []
    required_tools = getattr(strategy, "required_tools", None) or []
    required_inputs = getattr(strategy, "required_inputs", None) or []
    total_requirements = len(required_capabilities) + len(required_tools) + len(required_inputs)

    if total_requirements <= _EFFORT_LOW_MAX_REQUIREMENTS:
        return LEVEL_LOW
    if total_requirements <= _EFFORT_MEDIUM_MAX_REQUIREMENTS:
        return LEVEL_MEDIUM
    return LEVEL_HIGH


def _derive_risk_level(strategy):
    """Deterministic risk_level from how many risks a strategy itself
    already lists. More stated risks -> more risk. Never raises."""
    risks = getattr(strategy, "risks", None) or []
    risk_count = len(risks)

    if risk_count <= _RISK_LOW_MAX_COUNT:
        return LEVEL_LOW
    if risk_count <= _RISK_MEDIUM_MAX_COUNT:
        return LEVEL_MEDIUM
    return LEVEL_HIGH


def _opportunity_id_for_strategy(strategy):
    """Deterministic, content-derived opportunity id: generating from
    the same strategy always produces the same id, so re-running
    `generate_from_strategy` on an unchanged strategy is idempotent
    (a caller storing the result via
    `RevenueOpportunityManager.add_opportunity` simply gets a rejected
    duplicate the second time, rather than a second, redundant
    opportunity). No counter, clock, or randomness involved."""
    return f"opportunity-for-{strategy.strategy_id}"


# ----------------------------------------------------------------------
# Ranking
# ----------------------------------------------------------------------
_LEVEL_RANK = {LEVEL_LOW: 0, LEVEL_MEDIUM: 1, LEVEL_HIGH: 2}
_DEFAULT_LEVEL_RANK = _LEVEL_RANK[LEVEL_MEDIUM]


def _ranking_key(opportunity):
    """The sort key used by `rank_opportunities`. Opportunities are
    compared, in order, on:

    1. confidence, higher first - how sure the opportunity's own data
       says we should be that it's viable at all.
    2. risk_level, lower first (LOW < MEDIUM < HIGH) - prefer safer
       opportunities when confidence ties.
    3. effort_level, lower first (LOW < MEDIUM < HIGH) - prefer less
       effort when confidence and risk both tie.
    4. estimated_income, higher first - a final tiebreaker, not the
       primary criterion (mixing money and a 0-1 confidence score into
       one number would require an arbitrary exchange rate between
       them, which this module deliberately avoids).

    Each criterion is applied only to break ties left by the ones
    before it, so the ordering is fully determined by the opportunities'
    own stored fields - nothing hidden, nothing randomized.
    """
    return (
        -opportunity.confidence,
        _LEVEL_RANK.get(opportunity.risk_level, _DEFAULT_LEVEL_RANK),
        _LEVEL_RANK.get(opportunity.effort_level, _DEFAULT_LEVEL_RANK),
        -opportunity.estimated_income,
    )


class RevenueOpportunityPlanner:
    """Stateless (holds no data between calls) and not thread-shared
    for that reason: every method takes what it needs as arguments and
    returns a fresh result, so a single instance - or a fresh one per
    call - behaves identically. This mirrors the "no hidden state
    driving a decision" spirit of the ranking itself.
    """

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate_from_strategy(self, strategy):
        """Build a list of candidate `RevenueOpportunity` records from
        one `RevenueStrategy`.

        Returns a list containing exactly one `RevenueOpportunity`
        (a list, rather than a single object, so a future stage can
        start returning more than one candidate per strategy without
        changing this method's shape) that copies the strategy's own
        fields across, plus a deterministically derived `effort_level`
        and `risk_level` (see `_derive_effort_level` /
        `_derive_risk_level`) and `status=DISCOVERED`.

        Returns an empty list - never raises - if `strategy` isn't a
        `RevenueStrategy` instance or fails its own `is_valid()`
        check, since there is nothing well-formed to generate from.

        This method only builds and returns data; it does not store
        the result anywhere, execute anything, or contact anything
        outside this process.
        """
        try:
            from .revenue_strategy import RevenueStrategy
        except ImportError:  # pragma: no cover - defensive only
            RevenueStrategy = None

        if RevenueStrategy is not None and not isinstance(strategy, RevenueStrategy):
            return []
        if not hasattr(strategy, "is_valid") or not strategy.is_valid():
            return []

        opportunity = RevenueOpportunity(
            opportunity_id=_opportunity_id_for_strategy(strategy),
            goal_id=strategy.goal_id,
            strategy_id=strategy.strategy_id,
            name=strategy.name,
            description=strategy.description,
            revenue_model=strategy.revenue_model,
            required_capabilities=strategy.required_capabilities,
            required_tools=strategy.required_tools,
            required_inputs=strategy.required_inputs,
            expected_outputs=strategy.expected_outputs,
            estimated_income=strategy.estimated_income,
            currency=strategy.currency,
            time_period=strategy.time_period,
            effort_level=_derive_effort_level(strategy),
            risk_level=_derive_risk_level(strategy),
            confidence=strategy.confidence,
            status=STATUS_DISCOVERED,
            metadata={
                "generated_from": "strategy",
                "source_strategy_id": strategy.strategy_id,
            },
        )

        if not opportunity.is_valid():
            # Defensive only: a valid RevenueStrategy's fields should
            # always produce a valid RevenueOpportunity. If they
            # somehow don't, surface nothing rather than a broken
            # record.
            return []

        return [opportunity]

    def generate_from_goal(self, goal, strategies):
        """Build candidate `RevenueOpportunity` records for every
        strategy in `strategies` that actually belongs to `goal`.

        `strategies` may contain strategies for other goals or
        invalid/malformed entries - both are silently skipped (never
        raises) rather than assumed to be relevant. A strategy
        "belongs to" `goal` when its `goal_id` matches `goal.goal_id`.

        Returns a plain list (never None) of `RevenueOpportunity`
        records, in the same order as the matching strategies appeared
        in `strategies`. Returns an empty list if `goal` is invalid,
        `strategies` is empty, or none of them match.
        """
        if not hasattr(goal, "goal_id") or not hasattr(goal, "is_valid") or not goal.is_valid():
            return []

        opportunities = []
        for strategy in strategies or []:
            if getattr(strategy, "goal_id", None) != goal.goal_id:
                continue
            opportunities.extend(self.generate_from_strategy(strategy))
        return opportunities

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------
    def rank_opportunities(self, opportunities):
        """Return a new list of `RevenueOpportunity` records from
        `opportunities`, ordered most-promising-first using only each
        opportunity's own `confidence`, `risk_level`, `effort_level`,
        and `estimated_income` (see `_ranking_key` for the exact,
        documented comparison order).

        Entries that aren't a valid `RevenueOpportunity` are silently
        excluded from the result (never raises) - there is nothing
        well-formed to rank. `opportunities` itself is never mutated;
        the returned list holds `copy.deepcopy`s, same "always return
        safe copies" convention as `RevenueOpportunityManager`.

        The sort is stable and uses no randomness, no clock, and no
        external data, so calling this twice with the same input
        always produces the same output.
        """
        valid_opportunities = [
            o for o in (opportunities or [])
            if isinstance(o, RevenueOpportunity) and o.is_valid()
        ]
        ranked = sorted(valid_opportunities, key=_ranking_key)
        return [copy.deepcopy(o) for o in ranked]

    def get_top_opportunities(self, opportunities, limit=5):
        """The first `limit` entries of `rank_opportunities(opportunities)`.

        `limit <= 0` returns an empty list; a `limit` larger than the
        number of valid opportunities returns all of them. Never
        raises. This is a plain slice of the deterministic ranking
        above - it does not select, activate, or otherwise change the
        status of anything."""
        if limit is None or limit <= 0:
            return []
        return self.rank_opportunities(opportunities)[:limit]
