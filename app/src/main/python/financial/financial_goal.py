"""
Financial Goal
================
`FinancialGoal` is a small, standalone data record representing a
user's stated financial objective - for example:

    "I want to generate 1,000,000,000 Toman per month."

    USER INPUT -> ... -> FinancialGoal -> [Financial Planning: not built yet]

This stage only defines the *shape* of a financial goal:

- It does NOT assume the target is achievable.
- It does NOT promise, estimate, or guarantee any specific income.
- It does NOT decide how to reach the goal (no plan/strategy
  generation).
- It does NOT execute anything: no banking access, no payment
  processing, no account access, no web automation, no hacking, and no
  financial transaction of any kind happens here.

A FinancialGoal only records what the user asked for, so a later
Financial Planning stage has something structured to reason about.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `LearningRecord`
(learning/learning_record.py) and `Plan` (planning/plan.py): a caller
can freely build a FinancialGoal from untrusted/partial input (e.g.
something extracted from free-form user text) and then call
`is_valid()` to decide whether it is fit to use, rather than having to
wrap construction in a try/except.
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for goal status (matches the STATUS_* pattern
# already used by planning/goal.py and reasoning/reasoning_result.py)
# so callers can branch on it reliably instead of comparing against
# free-form strings.
STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"

ALL_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_CANCELLED)

DEFAULT_STATUS = STATUS_ACTIVE

# Safe, structured-data-only types allowed inside `metadata`,
# `constraints`, and `strategy_preferences`. Anything else (functions,
# class instances, file handles, etc.) is rejected by is_valid() so
# these fields always stay plain and JSON-shaped - never a place to
# smuggle in something that could be called or executed later. Same
# convention as learning/learning_record.py's own
# `_is_safe_metadata_value`.
_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def _is_safe_structured_value(value):
    """True if `value` is made only of plain, structured data (str,
    int, float, bool, None, list/tuple, dict with string keys) -
    recursively. No functions, class instances, or other objects that
    could carry behavior."""
    if isinstance(value, _SAFE_SCALAR_TYPES):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_safe_structured_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_safe_structured_value(val)
            for key, val in value.items()
        )
    return False


class FinancialGoal:
    """One user-stated financial objective, captured but not yet acted
    on. Purely a data record: construction never raises (unlike e.g.
    ExecutionResult) so a caller can freely build a FinancialGoal from
    untrusted/partial data and then use `is_valid()` to decide whether
    it is fit to use.

    `strategy_preferences` is always a plain list (never None) and
    `constraints`/`metadata` are always plain dicts (never None), same
    "no None checks needed by callers" convention as
    Goal.requirements/metadata (planning/goal.py).
    """

    __slots__ = (
        "goal_id", "original_text", "normalized_text", "target_amount",
        "currency", "time_period", "target_date", "strategy_preferences",
        "constraints", "status", "created_at", "metadata",
    )

    def __init__(
        self,
        goal_id,
        original_text,
        normalized_text=None,
        target_amount=None,
        currency=None,
        time_period=None,
        target_date=None,
        strategy_preferences=None,
        constraints=None,
        status=DEFAULT_STATUS,
        created_at=None,
        metadata=None,
    ):
        self.goal_id = goal_id
        self.original_text = original_text
        self.normalized_text = (
            normalized_text if normalized_text is not None else original_text
        )
        self.target_amount = target_amount
        self.currency = currency
        self.time_period = time_period
        self.target_date = target_date
        self.strategy_preferences = (
            list(strategy_preferences) if strategy_preferences else []
        )
        self.constraints = dict(constraints) if constraints else {}
        self.status = status
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"FinancialGoal(goal_id={self.goal_id!r}, "
            f"target_amount={self.target_amount!r}, currency={self.currency!r}, "
            f"time_period={self.time_period!r}, status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A goal is valid when:
        - goal_id and original_text are non-empty strings
        - target_amount is numeric (int/float, not bool) and > 0
        - currency and time_period are non-empty strings
        - status is one of the supported values (see ALL_STATUSES)
        - metadata, constraints, and strategy_preferences contain only
          safe, structured data (see `_is_safe_structured_value`)

        This intentionally says nothing about whether the goal itself
        is realistic or achievable - only whether the record is
        well-formed enough to use.
        """
        if not isinstance(self.goal_id, str) or not self.goal_id.strip():
            return False
        if not isinstance(self.original_text, str) or not self.original_text.strip():
            return False

        if isinstance(self.target_amount, bool):
            return False
        if not isinstance(self.target_amount, (int, float)):
            return False
        if not (self.target_amount > 0):
            return False

        if not isinstance(self.currency, str) or not self.currency.strip():
            return False
        if not isinstance(self.time_period, str) or not self.time_period.strip():
            return False

        if self.status not in ALL_STATUSES:
            return False

        if not _is_safe_structured_value(self.metadata):
            return False
        if not _is_safe_structured_value(self.constraints):
            return False
        if not _is_safe_structured_value(self.strategy_preferences):
            return False

        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_target_amount(self):
        """The requested target amount, exactly as stored - no
        rounding, currency conversion, or feasibility judgement."""
        return self.target_amount

    def get_currency(self):
        return self.currency

    def get_time_period(self):
        return self.time_period

    def get_constraints(self):
        """A plain dict (never None) of user-stated constraints on how
        the goal should be pursued (e.g. risk tolerance, time
        available). This stage never interprets or acts on them."""
        return dict(self.constraints)

    def get_strategy_preferences(self):
        """A plain list (never None) of user-stated strategy
        preferences (e.g. "low risk", "passive income"). This stage
        never interprets or acts on them."""
        return list(self.strategy_preferences)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation - used both as the
        general-purpose serialization and as
        FinancialGoalManager's debugging view."""
        return {
            "goal_id": self.goal_id,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "target_amount": self.target_amount,
            "currency": self.currency,
            "time_period": self.time_period,
            "target_date": self.target_date,
            "strategy_preferences": list(self.strategy_preferences),
            "constraints": dict(self.constraints),
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
