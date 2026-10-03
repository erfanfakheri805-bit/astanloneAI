"""
Revenue Strategy Manager
==========================
`RevenueStrategyManager` is a small, in-memory, id-keyed store for
`RevenueStrategy` objects (financial/revenue_strategy.py):

    raw fields -> RevenueStrategyManager.create_strategy()
        -> [later] get_strategy() / get_all() / get_for_goal() /
           update_status() / remove_strategy()

This stage only builds, stores, retrieves, and updates the status of
already-built `RevenueStrategy` records - it does not decide whether a
strategy would work, does not estimate or guarantee any income, does
not execute anything, and does not touch the filesystem, a database,
the shell, the network, banking/payment systems, or any Android API.
No money is made, moved, or pretended to be made by this module.
Nothing here is persisted: like
`financial/financial_goal_manager.py` and
`learning/learning_record_store.py`, this store lives only in this
process's RAM and is cleared on process restart (or on an explicit
`clear()` call). The existing SQLite persistence system
(memory/memory_system.py) is untouched by this stage.

No strategy is ever activated, paused, completed, or rejected on its
own: `status` only ever changes via an explicit `update_status()` call
from a caller. Nothing in this module inspects `estimated_income` or
`confidence` to decide anything - they are stored as given, purely as
data for a later (not-yet-built) planning/evaluation stage to read.

Two related but distinct "reject invalid input safely" conventions are
used here, matching `financial/financial_goal_manager.py`'s own
precedent:

- `create_strategy` builds a new `RevenueStrategy` from raw fields and
  raises `ValueError` - storing nothing - if the result fails its own
  `is_valid()` check, or if the strategy_id is already taken.
- `add_strategy` stores an already-built `RevenueStrategy` and returns
  `None` - storing nothing - if it isn't a valid `RevenueStrategy` or
  its id is already taken, rather than raising. Same "reject safely,
  never raise" convention as `learning/learning_record_store.py`'s
  `add`.

Either way, duplicate strategy ids never overwrite an existing
strategy - the first strategy stored under a given id always wins.
"""

import copy
import itertools

from .revenue_strategy import RevenueStrategy, ALL_STATUSES

# Same "always assign an id, never leave one dangling" convention used
# by financial/financial_goal_manager.py's own counter.
_id_counter = itertools.count(1)


def _generate_strategy_id():
    return f"rev-strategy-{next(_id_counter)}"


class RevenueStrategyManager:
    """Not thread-safe (matches the rest of this project - see
    FinancialGoalManager/LearningRecordStore's own notes). Safe to use
    one instance per Core / per conversation session.

    Storage is a single `{strategy_id: RevenueStrategy}` dict, keyed by
    each strategy's own `strategy_id` - simplest structure that still
    supports O(1) lookup by id and straightforward duplicate-id
    rejection. `get_for_goal` does a linear scan over stored strategies
    - fine at this stage's expected scale, and avoids maintaining a
    second index that could drift out of sync with `_strategies`.
    """

    def __init__(self):
        self._strategies = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_strategy(
        self,
        goal_id,
        name,
        description,
        revenue_model=None,
        estimated_income=None,
        currency=None,
        time_period=None,
        required_capabilities=None,
        required_tools=None,
        required_inputs=None,
        expected_outputs=None,
        risks=None,
        constraints=None,
        confidence=0.0,
        metadata=None,
        strategy_id=None,
    ):
        """Build a `RevenueStrategy` from the given fields, store it,
        and return a safe copy of it.

        Raises `ValueError` - and stores nothing - if:
        - `strategy_id` is given and already used by a stored
          strategy, or
        - the resulting strategy fails its own `is_valid()` check (e.g.
          a non-numeric or negative `estimated_income`, an empty
          `name`/`description`/`currency`/`time_period`, a
          `confidence` outside [0, 1], an unsupported `status`, or
          unsafe/unstructured structured fields).

        This is a controlled rejection, not a crash: this stage never
        assumes `estimated_income` is guaranteed and never activates
        the strategy - it only decides whether the record itself is
        well-formed enough to store.
        """
        resolved_strategy_id = strategy_id if strategy_id else _generate_strategy_id()
        if resolved_strategy_id in self._strategies:
            raise ValueError(
                f"A revenue strategy with id {resolved_strategy_id!r} already exists."
            )

        strategy = RevenueStrategy(
            strategy_id=resolved_strategy_id,
            goal_id=goal_id,
            name=name,
            description=description,
            revenue_model=revenue_model,
            estimated_income=estimated_income,
            currency=currency,
            time_period=time_period,
            required_capabilities=required_capabilities,
            required_tools=required_tools,
            required_inputs=required_inputs,
            expected_outputs=expected_outputs,
            risks=risks,
            constraints=constraints,
            confidence=confidence,
            metadata=metadata,
        )

        if not strategy.is_valid():
            raise ValueError(
                "Cannot create revenue strategy: one or more fields failed validation."
            )

        self._strategies[resolved_strategy_id] = strategy
        return copy.deepcopy(strategy)

    # ------------------------------------------------------------------
    # Storage of an already-built strategy
    # ------------------------------------------------------------------
    def add_strategy(self, strategy):
        """Store `strategy`, but only if it is an actual
        `RevenueStrategy` instance that reports `is_valid()` and whose
        `strategy_id` isn't already present in this store.

        Returns `strategy` unchanged on success, or `None` - and
        stores nothing - otherwise (duplicate ids never overwrite an
        existing strategy - the first strategy added under a given id
        always wins). Never raises.
        """
        if not isinstance(strategy, RevenueStrategy):
            return None
        if not strategy.is_valid():
            return None
        if strategy.strategy_id in self._strategies:
            return None

        self._strategies[strategy.strategy_id] = strategy
        return strategy

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_strategy(self, strategy_id):
        """The `RevenueStrategy` stored under `strategy_id`, or `None`
        if nothing is stored there (never raises for an unknown,
        empty, or non-string id). The returned strategy is a
        `copy.deepcopy`, so a caller mutating it can never corrupt this
        store's own internal state."""
        strategy = self._strategies.get(strategy_id)
        return copy.deepcopy(strategy) if strategy is not None else None

    def get_all(self):
        """A plain list (never None) of every stored `RevenueStrategy`,
        in the order each was first added. Each entry is a
        `copy.deepcopy` of the stored strategy, so a caller mutating an
        entry it read back can never corrupt this store's own internal
        state."""
        return [copy.deepcopy(strategy) for strategy in self._strategies.values()]

    def get_for_goal(self, goal_id):
        """A plain list (never None) of every stored `RevenueStrategy`
        whose `goal_id` exactly matches `goal_id`, in the order each
        was first added. Each entry is a `copy.deepcopy` - same
        "always return safe copies" convention as `get_all`. Returns
        an empty list (never raises) if `goal_id` is unknown, empty, or
        matches nothing."""
        return [
            copy.deepcopy(strategy)
            for strategy in self._strategies.values()
            if strategy.goal_id == goal_id
        ]

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------
    def update_status(self, strategy_id, status):
        """Update the stored strategy `strategy_id`'s status to
        `status`.

        Returns a `copy.deepcopy` of the updated strategy on success.
        Returns `None` - and changes nothing - if `strategy_id` is
        unknown or `status` isn't one of the supported values
        (`revenue_strategy.ALL_STATUSES`). Never raises. This is the
        only way a strategy's status ever changes - nothing in this
        module activates, pauses, completes, or rejects a strategy on
        its own."""
        if status not in ALL_STATUSES:
            return None

        strategy = self._strategies.get(strategy_id)
        if strategy is None:
            return None

        strategy.status = status
        return copy.deepcopy(strategy)

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------
    def remove_strategy(self, strategy_id):
        """Remove the strategy stored under `strategy_id` and return a
        `copy.deepcopy` of it, or `None` - and change nothing - if no
        such strategy exists. Never raises."""
        strategy = self._strategies.pop(strategy_id, None)
        return copy.deepcopy(strategy) if strategy is not None else None

    def clear(self):
        """Remove every strategy currently in this store. Nothing to
        return; always succeeds, even if the store was already
        empty."""
        self._strategies.clear()

    def __len__(self):
        return len(self._strategies)

    def __repr__(self):
        return f"RevenueStrategyManager({len(self._strategies)} strategy(ies))"
