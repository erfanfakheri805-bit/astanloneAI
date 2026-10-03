"""
Financial (foundation)
========================
Home for a future financial-planning capability. Each stage so far
adds only the data model and bookkeeping such a capability will
eventually need:

- `FinancialGoal` (financial_goal.py) - what the user asked for - and
  the in-memory `FinancialGoalManager` (financial_goal_manager.py)
  that creates, stores, retrieves, and updates the status of them.
- `RevenueStrategy` (revenue_strategy.py) - one possible, legal
  approach to working toward a FinancialGoal - and the in-memory
  `RevenueStrategyManager` (revenue_strategy_manager.py) that creates,
  stores, retrieves (including by goal), and updates the status of
  them.
- `RevenueOpportunity` (revenue_opportunity.py) - one concrete,
  structured candidate possibility, usually surfaced from a
  RevenueStrategy - the in-memory `RevenueOpportunityManager`
  (revenue_opportunity_manager.py) that creates, stores, retrieves
  (by goal or by strategy), and updates the status of them, and the
  deterministic `RevenueOpportunityPlanner`
  (revenue_opportunity_planner.py) that generates opportunities from
  strategies/goals and ranks them transparently.
- `RevenueOpportunitySelector` (revenue_selector.py) - chooses which
  already-ranked opportunities look most worth pursuing (built
  directly on the planner's own ranking, never a separate hidden
  score) and returns a structured `SelectionResult` explaining why.
- `RevenueLearningRecord` (revenue_learning.py) - what one already-
  finished `RevenueTaskResult` observed, and `RevenueLearningAnalyzer`
  (revenue_learning_analyzer.py) - a plain, read-only statistical
  summary over a batch of those records. `RevenueLearningPattern`
  (revenue_learning_pattern.py) is the aggregate shape one such
  analysis already found for one task/opportunity, with a stored
  `reliability` score a future stage could read. The in-memory
  `RevenueLearningPatternStore` (revenue_learning_pattern_store.py)
  stores and retrieves already-built `RevenueLearningPattern`
  objects.

This package is a structured data model only. Nothing here decides
whether a goal, strategy, or opportunity is achievable, estimates or
promises any income, generates or executes a plan, or activates
anything on its own - no banking access, no payment processing, no
account access, no web automation, no hacking, and no financial
transaction of any kind happens here or anywhere in this package. See
the module docstrings in financial_goal.py / financial_goal_manager.py
/ revenue_strategy.py / revenue_strategy_manager.py /
revenue_opportunity.py / revenue_opportunity_manager.py /
revenue_opportunity_planner.py / revenue_selector.py for detail.
"""
