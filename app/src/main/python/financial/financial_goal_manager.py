"""
Financial Goal Manager
========================
`FinancialGoalManager` is a small, in-memory, id-keyed store for
`FinancialGoal` objects (financial/financial_goal.py):

    raw fields -> FinancialGoalManager.create_goal()
        -> [later] get_goal() / get_all() / update_status() /
           remove_goal()

This stage only builds, stores, retrieves, and updates the status of
already-built `FinancialGoal` records - it does not decide whether a
goal is realistic, does not generate a plan or strategy to reach it,
and does not touch the filesystem, a database, the shell, the network,
banking/payment systems, or any Android API. No money is made or moved
by this module. Nothing here is persisted: like
`learning/learning_record_store.py` and
`planning/goal_manager.py`, this store lives only in this process's
RAM and is cleared on process restart (or on an explicit `clear()`
call). The existing SQLite persistence system
(memory/memory_system.py) is untouched by this stage.

Two related but distinct "reject invalid input safely" conventions
are used here, matching existing precedent elsewhere in this project:

- `create_goal` builds a new `FinancialGoal` from raw fields and
  raises `ValueError` - storing nothing - if the result fails its own
  `is_valid()` check, or if the goal_id is already taken. Same
  "raise ValueError rather than silently creating a meaningless
  record" convention as `planning/goal_manager.py`'s `create_goal`.
- `add_goal` stores an already-built `FinancialGoal` and returns
  `None` - storing nothing - if it isn't a valid `FinancialGoal` or its
  id is already taken, rather than raising. Same "reject safely, never
  raise" convention as `learning/learning_record_store.py`'s `add`.

Either way, duplicate goal ids never overwrite an existing goal - the
first goal stored under a given id always wins.
"""

import copy
import itertools

from understanding.normalization import normalize

from .financial_goal import FinancialGoal, ALL_STATUSES

# Same "always assign an id, never leave one dangling" convention used
# by planning/goal_manager.py's own counter: a single, process-wide,
# monotonically increasing counter as the default id source.
_id_counter = itertools.count(1)


def _generate_goal_id():
    return f"fin-goal-{next(_id_counter)}"


class FinancialGoalManager:
    """Not thread-safe (matches the rest of this project - see
    GoalManager/LearningRecordStore's own notes). Safe to use one
    instance per Core / per conversation session.

    Storage is a single `{goal_id: FinancialGoal}` dict, keyed by each
    goal's own `goal_id` - simplest structure that still supports O(1)
    lookup by id and straightforward duplicate-id rejection.
    """

    def __init__(self):
        self._goals = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_goal(
        self,
        original_text,
        target_amount,
        currency,
        time_period,
        target_date=None,
        strategy_preferences=None,
        constraints=None,
        metadata=None,
        goal_id=None,
    ):
        """Build a `FinancialGoal` from the given fields, store it, and
        return a safe copy of it.

        `original_text` is passed through the same normalization used
        elsewhere in this project (`understanding.normalization`) so
        `normalized_text` is derived the same way as everywhere else
        instead of re-implementing its own variant.

        Raises `ValueError` - and stores nothing - if:
        - `goal_id` is given and already used by a stored goal, or
        - the resulting goal fails its own `is_valid()` check (e.g. a
          non-numeric or non-positive `target_amount`, an empty
          `currency`/`time_period`, an unsupported `status`, or
          unsafe/unstructured `metadata`/`constraints`/
          `strategy_preferences`).

        This is a controlled rejection, not a crash: this stage never
        assumes the requested target is achievable and never promises
        any income - it only decides whether the record itself is
        well-formed enough to store.
        """
        resolved_goal_id = goal_id if goal_id else _generate_goal_id()
        if resolved_goal_id in self._goals:
            raise ValueError(
                f"A financial goal with id {resolved_goal_id!r} already exists."
            )

        normalization = normalize(original_text)

        goal = FinancialGoal(
            goal_id=resolved_goal_id,
            original_text=normalization.original_text,
            normalized_text=normalization.normalized_text,
            target_amount=target_amount,
            currency=currency,
            time_period=time_period,
            target_date=target_date,
            strategy_preferences=strategy_preferences,
            constraints=constraints,
            metadata=metadata,
        )

        if not goal.is_valid():
            raise ValueError(
                "Cannot create financial goal: one or more fields failed validation."
            )

        self._goals[resolved_goal_id] = goal
        return copy.deepcopy(goal)

    # ------------------------------------------------------------------
    # Storage of an already-built goal
    # ------------------------------------------------------------------
    def add_goal(self, goal):
        """Store `goal`, but only if it is an actual `FinancialGoal`
        instance that reports `is_valid()` and whose `goal_id` isn't
        already present in this store.

        Returns `goal` unchanged on success, or `None` - and stores
        nothing - otherwise (duplicate ids never overwrite an existing
        goal - the first goal added under a given id always wins).
        Never raises.
        """
        if not isinstance(goal, FinancialGoal):
            return None
        if not goal.is_valid():
            return None
        if goal.goal_id in self._goals:
            return None

        self._goals[goal.goal_id] = goal
        return goal

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_goal(self, goal_id):
        """The `FinancialGoal` stored under `goal_id`, or `None` if
        nothing is stored there (never raises for an unknown, empty,
        or non-string id). The returned goal is a `copy.deepcopy`, so a
        caller mutating it can never corrupt this store's own internal
        state (same "always return safe copies" convention as
        `learning/learning_record_store.py`)."""
        goal = self._goals.get(goal_id)
        return copy.deepcopy(goal) if goal is not None else None

    def get_all(self):
        """A plain list (never None) of every stored `FinancialGoal`,
        in the order each was first added. Each entry is a
        `copy.deepcopy` of the stored goal, so a caller mutating an
        entry it read back can never corrupt this store's own internal
        state."""
        return [copy.deepcopy(goal) for goal in self._goals.values()]

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------
    def update_status(self, goal_id, status):
        """Update the stored goal `goal_id`'s status to `status`.

        Returns a `copy.deepcopy` of the updated goal on success.
        Returns `None` - and changes nothing - if `goal_id` is unknown
        or `status` isn't one of the supported values
        (`financial_goal.ALL_STATUSES`). Never raises."""
        if status not in ALL_STATUSES:
            return None

        goal = self._goals.get(goal_id)
        if goal is None:
            return None

        goal.status = status
        return copy.deepcopy(goal)

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------
    def remove_goal(self, goal_id):
        """Remove the goal stored under `goal_id` and return a
        `copy.deepcopy` of it, or `None` - and change nothing - if no
        such goal exists. Never raises."""
        goal = self._goals.pop(goal_id, None)
        return copy.deepcopy(goal) if goal is not None else None

    def clear(self):
        """Remove every goal currently in this store. Nothing to
        return; always succeeds, even if the store was already
        empty."""
        self._goals.clear()

    def __len__(self):
        return len(self._goals)

    def __repr__(self):
        return f"FinancialGoalManager({len(self._goals)} goal(s))"
