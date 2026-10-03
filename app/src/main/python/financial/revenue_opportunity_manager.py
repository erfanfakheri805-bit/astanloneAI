"""
Revenue Opportunity Manager
=============================
`RevenueOpportunityManager` is a small, in-memory, id-keyed store for
`RevenueOpportunity` objects (financial/revenue_opportunity.py):

    raw fields -> RevenueOpportunityManager.create_opportunity()
        -> [later] get_opportunity() / get_all() / get_for_goal() /
           get_for_strategy() / update_status() / remove_opportunity()

This stage only builds, stores, retrieves, and updates the status of
already-built `RevenueOpportunity` records - it does not decide
whether an opportunity would pay off, does not estimate or guarantee
any income, does not execute anything, and does not touch the
filesystem, a database, the shell, the network, banking/payment
systems, or any Android API. No money is made, moved, or pretended to
be made by this module. Nothing here is persisted: like
`financial/revenue_strategy_manager.py` and
`learning/learning_record_store.py`, this store lives only in this
process's RAM and is cleared on process restart (or on an explicit
`clear()` call). The existing SQLite persistence system
(memory/memory_system.py) is untouched by this stage.

No opportunity is ever selected, activated, completed, failed, or
rejected on its own: `status` only ever changes via an explicit
`update_status()` call from a caller.

Two related but distinct "reject invalid input safely" conventions are
used here, matching `financial/revenue_strategy_manager.py`'s own
precedent:

- `create_opportunity` builds a new `RevenueOpportunity` from raw
  fields and raises `ValueError` - storing nothing - if the result
  fails its own `is_valid()` check, or if the opportunity_id is
  already taken.
- `add_opportunity` stores an already-built `RevenueOpportunity` and
  returns `None` - storing nothing - if it isn't a valid
  `RevenueOpportunity` or its id is already taken, rather than
  raising. Same "reject safely, never raise" convention as
  `learning/learning_record_store.py`'s `add`. This is the method used
  by `revenue_opportunity_planner.py`, whose generated opportunities
  already carry their own deterministic ids.

Either way, duplicate opportunity ids never overwrite an existing
opportunity - the first opportunity stored under a given id always
wins.
"""

import copy
import itertools

from .revenue_opportunity import RevenueOpportunity, ALL_STATUSES

# Same "always assign an id, never leave one dangling" convention used
# by financial/revenue_strategy_manager.py's own counter. Only used by
# `create_opportunity` when no explicit id is given - opportunities
# built by RevenueOpportunityPlanner carry their own deterministic ids
# and are stored via `add_opportunity` instead.
_id_counter = itertools.count(1)


def _generate_opportunity_id():
    return f"rev-opportunity-{next(_id_counter)}"


class RevenueOpportunityManager:
    """Not thread-safe (matches the rest of this project - see
    RevenueStrategyManager/LearningRecordStore's own notes). Safe to
    use one instance per Core / per conversation session.

    Storage is a single `{opportunity_id: RevenueOpportunity}` dict,
    keyed by each opportunity's own `opportunity_id` - simplest
    structure that still supports O(1) lookup by id and straightforward
    duplicate-id rejection. `get_for_goal` and `get_for_strategy` do a
    linear scan over stored opportunities - fine at this stage's
    expected scale, and avoids maintaining extra indexes that could
    drift out of sync with `_opportunities`.
    """

    def __init__(self):
        self._opportunities = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_opportunity(
        self,
        goal_id,
        name,
        description,
        strategy_id=None,
        revenue_model=None,
        required_capabilities=None,
        required_tools=None,
        required_inputs=None,
        expected_outputs=None,
        estimated_income=None,
        currency=None,
        time_period=None,
        effort_level=None,
        risk_level=None,
        confidence=0.0,
        metadata=None,
        opportunity_id=None,
    ):
        """Build a `RevenueOpportunity` from the given fields, store
        it, and return a safe copy of it.

        Raises `ValueError` - and stores nothing - if:
        - `opportunity_id` is given and already used by a stored
          opportunity, or
        - the resulting opportunity fails its own `is_valid()` check
          (e.g. a non-numeric or negative `estimated_income`, an empty
          `name`/`description`/`currency`/`time_period`, an
          unsupported `effort_level`/`risk_level`/`status`, a
          `confidence` outside [0, 1], or unsafe/unstructured
          structured fields).

        This is a controlled rejection, not a crash: this stage never
        assumes the opportunity will pay off and never activates it -
        it only decides whether the record itself is well-formed
        enough to store.
        """
        resolved_opportunity_id = (
            opportunity_id if opportunity_id else _generate_opportunity_id()
        )
        if resolved_opportunity_id in self._opportunities:
            raise ValueError(
                f"A revenue opportunity with id {resolved_opportunity_id!r} already exists."
            )

        kwargs = dict(
            opportunity_id=resolved_opportunity_id,
            goal_id=goal_id,
            strategy_id=strategy_id,
            name=name,
            description=description,
            revenue_model=revenue_model,
            required_capabilities=required_capabilities,
            required_tools=required_tools,
            required_inputs=required_inputs,
            expected_outputs=expected_outputs,
            estimated_income=estimated_income,
            currency=currency,
            time_period=time_period,
            confidence=confidence,
            metadata=metadata,
        )
        # Only override the model's own defaults when a level was
        # actually given, so create_opportunity(...) without
        # effort_level/risk_level still gets RevenueOpportunity's
        # documented defaults rather than `None`.
        if effort_level is not None:
            kwargs["effort_level"] = effort_level
        if risk_level is not None:
            kwargs["risk_level"] = risk_level

        opportunity = RevenueOpportunity(**kwargs)

        if not opportunity.is_valid():
            raise ValueError(
                "Cannot create revenue opportunity: one or more fields failed validation."
            )

        self._opportunities[resolved_opportunity_id] = opportunity
        return copy.deepcopy(opportunity)

    # ------------------------------------------------------------------
    # Storage of an already-built opportunity
    # ------------------------------------------------------------------
    def add_opportunity(self, opportunity):
        """Store `opportunity`, but only if it is an actual
        `RevenueOpportunity` instance that reports `is_valid()` and
        whose `opportunity_id` isn't already present in this store.

        Returns `opportunity` unchanged on success, or `None` - and
        stores nothing - otherwise (duplicate ids never overwrite an
        existing opportunity - the first opportunity added under a
        given id always wins). Never raises.
        """
        if not isinstance(opportunity, RevenueOpportunity):
            return None
        if not opportunity.is_valid():
            return None
        if opportunity.opportunity_id in self._opportunities:
            return None

        self._opportunities[opportunity.opportunity_id] = opportunity
        return opportunity

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_opportunity(self, opportunity_id):
        """The `RevenueOpportunity` stored under `opportunity_id`, or
        `None` if nothing is stored there (never raises for an
        unknown, empty, or non-string id). The returned opportunity is
        a `copy.deepcopy`, so a caller mutating it can never corrupt
        this store's own internal state."""
        opportunity = self._opportunities.get(opportunity_id)
        return copy.deepcopy(opportunity) if opportunity is not None else None

    def get_all(self):
        """A plain list (never None) of every stored
        `RevenueOpportunity`, in the order each was first added. Each
        entry is a `copy.deepcopy` of the stored opportunity, so a
        caller mutating an entry it read back can never corrupt this
        store's own internal state."""
        return [copy.deepcopy(o) for o in self._opportunities.values()]

    def get_for_goal(self, goal_id):
        """A plain list (never None) of every stored
        `RevenueOpportunity` whose `goal_id` exactly matches `goal_id`,
        in the order each was first added. Each entry is a
        `copy.deepcopy` - same "always return safe copies" convention
        as `get_all`. Returns an empty list (never raises) if
        `goal_id` is unknown, empty, or matches nothing."""
        return [
            copy.deepcopy(o) for o in self._opportunities.values() if o.goal_id == goal_id
        ]

    def get_for_strategy(self, strategy_id):
        """A plain list (never None) of every stored
        `RevenueOpportunity` whose `strategy_id` exactly matches
        `strategy_id`, in the order each was first added. Each entry
        is a `copy.deepcopy` - same "always return safe copies"
        convention as `get_all`. Returns an empty list (never raises)
        if `strategy_id` is unknown, empty, `None`, or matches
        nothing."""
        return [
            copy.deepcopy(o)
            for o in self._opportunities.values()
            if o.strategy_id == strategy_id
        ]

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------
    def update_status(self, opportunity_id, status):
        """Update the stored opportunity `opportunity_id`'s status to
        `status`.

        Returns a `copy.deepcopy` of the updated opportunity on
        success. Returns `None` - and changes nothing - if
        `opportunity_id` is unknown or `status` isn't one of the
        supported values (`revenue_opportunity.ALL_STATUSES`). Never
        raises. This is the only way an opportunity's status ever
        changes - nothing in this module selects, activates, completes,
        fails, or rejects an opportunity on its own."""
        if status not in ALL_STATUSES:
            return None

        opportunity = self._opportunities.get(opportunity_id)
        if opportunity is None:
            return None

        opportunity.status = status
        return copy.deepcopy(opportunity)

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------
    def remove_opportunity(self, opportunity_id):
        """Remove the opportunity stored under `opportunity_id` and
        return a `copy.deepcopy` of it, or `None` - and change nothing
        - if no such opportunity exists. Never raises."""
        opportunity = self._opportunities.pop(opportunity_id, None)
        return copy.deepcopy(opportunity) if opportunity is not None else None

    def clear(self):
        """Remove every opportunity currently in this store. Nothing
        to return; always succeeds, even if the store was already
        empty."""
        self._opportunities.clear()

    def __len__(self):
        return len(self._opportunities)

    def __repr__(self):
        return f"RevenueOpportunityManager({len(self._opportunities)} opportunity(ies))"
