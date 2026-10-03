"""
Revenue Learning Pattern
===========================
`RevenueLearningPattern` is a small, standalone data record capturing
the *aggregate* shape a `RevenueLearningAnalyzer`
(financial/revenue_learning_analyzer.py) analysis already found for
one task/opportunity - how many records it saw, how many of those
succeeded/failed, and a `reliability` score a future stage could read
- in a shape a future learning stage could use.

This stage only defines that shape and how one is safely built from an
already-computed analysis dict via `from_analysis()`, plus a short
`get_summary()` view of a subset of its own already-stored fields -
same "plain, JSON-shaped record with a to_dict()" convention already used by
`financial/revenue_learning.py`'s own `RevenueLearningRecord`, and the
same "construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueLearningRecord`, `RevenueTaskResult`,
`RevenueTask`, `RevenueOpportunity`, and `FinancialGoal`. It
deliberately does NOT:

- Learn anything, infer a new pattern beyond copying the counts/rate
  an analysis already computed, or feed itself into
  `learning/learning_system.py`, `learning/learning_analyzer.py`, or
  any other learning component - this is a plain, standalone
  container a future stage can choose to read, store, or act on, not
  a decision or a behavior change in its own right.
- Modify the analysis dict it is built from in any way - reading an
  analysis to build a pattern from it never mutates that dict.
- Select, change, or execute any `RevenueTask`, `RevenueStrategy`, or
  `RevenueOpportunity` - `reliability` is a stored number a future
  stage could read, never something this module acts on itself.
- Persist itself anywhere (no filesystem, database, or network I/O),
  run any code (no `eval`/`exec`/`subprocess`/shell), or call out to
  any external AI service.
"""

import copy
import itertools
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Safe, structured-data-only types allowed inside `metadata`. Same
# convention as RevenueLearningRecord's own
# `_is_safe_structured_value` (financial/revenue_learning.py).
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


# Same "always assign an id, never leave one dangling" convention used
# by revenue_learning.py's own `_generate_learning_id`. Kept as its
# own independent counter (not shared with any other module's ids).
_id_counter = itertools.count(1)


def _generate_pattern_id():
    return f"revenue-learning-pattern-{next(_id_counter)}"


class RevenueLearningPattern:
    """The aggregate shape one `RevenueLearningAnalyzer` analysis
    already found for one task/opportunity - purely a data record:
    construction never raises so a caller can freely build a
    `RevenueLearningPattern` from untrusted/partial data and then use
    `is_valid()` to decide whether it is fit to use.

    `metadata` is always a plain dict (never `None`) - same "no None
    checks needed by callers" convention as `RevenueLearningRecord.
    metadata`.
    """

    __slots__ = (
        "pattern_id", "task_id", "opportunity_id", "total_records",
        "successful_records", "failed_records", "success_rate",
        "reliability", "created_at", "metadata",
    )

    def __init__(
        self,
        task_id,
        opportunity_id,
        total_records,
        successful_records,
        failed_records,
        success_rate,
        reliability,
        pattern_id=None,
        created_at=None,
        metadata=None,
    ):
        self.pattern_id = pattern_id if pattern_id is not None else _generate_pattern_id()
        self.task_id = task_id
        self.opportunity_id = opportunity_id
        self.total_records = total_records
        self.successful_records = successful_records
        self.failed_records = failed_records
        self.success_rate = success_rate
        self.reliability = reliability
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"RevenueLearningPattern(pattern_id={self.pattern_id!r}, "
            f"task_id={self.task_id!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"total_records={self.total_records!r}, "
            f"success_rate={self.success_rate!r}, "
            f"reliability={self.reliability!r})"
        )

    # ------------------------------------------------------------------
    # Construction from an existing analysis
    # ------------------------------------------------------------------
    @classmethod
    def from_analysis(cls, task_id, opportunity_id, analysis):
        """Build a `RevenueLearningPattern` from an already-computed
        analysis `dict` (as returned by `RevenueLearningAnalyzer.
        analyze()`/`analyze_store()` - financial/
        revenue_learning_analyzer.py), preserving the exact `task_id`/
        `opportunity_id` a caller supplies (never read from
        `analysis`, which describes a whole batch of records and may
        span many tasks/opportunities).

        `total_records`/`successful_records`/`failed_records`/
        `success_rate` are each copied from the matching key in
        `analysis` (defaulting to `0`/`0`/`0`/`0.0` when a key is
        missing, so a caller can hand this a partial dict and still
        get a usable pattern back rather than raising). `reliability`
        is set initially equal to the copied `success_rate` - a
        future stage may adjust it later, but a freshly-built pattern
        always starts in agreement with what the analysis observed.

        Never modifies `analysis` in any way - only reads it; nothing
        is written back into the dict a caller passed in, and no
        nested value inside it is ever mutated in place.

        Raises `TypeError` if `analysis` is not a `dict`, same "fail
        loudly on the wrong type" convention a classmethod
        constructor should use rather than silently building a
        nonsensical pattern."""
        if not isinstance(analysis, dict):
            raise TypeError(
                f"from_analysis() expects a dict, got {type(analysis).__name__}"
            )

        total_records = analysis.get("total_records", 0)
        successful_records = analysis.get("successful_records", 0)
        failed_records = analysis.get("failed_records", 0)
        success_rate = analysis.get("success_rate", 0.0)

        return cls(
            task_id=task_id,
            opportunity_id=opportunity_id,
            total_records=copy.deepcopy(total_records),
            successful_records=copy.deepcopy(successful_records),
            failed_records=copy.deepcopy(failed_records),
            success_rate=copy.deepcopy(success_rate),
            reliability=copy.deepcopy(success_rate),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A pattern is valid
        when:
        - pattern_id is a non-empty string
        - task_id is a non-empty string
        - opportunity_id is a non-empty string
        - total_records/successful_records/failed_records are each a
          non-negative int (bool is rejected even though `bool` is a
          subclass of `int` in Python, same "no True/False standing
          in for a count" convention used elsewhere in this project)
        - successful_records + failed_records == total_records
        - success_rate is a float (or int) in the inclusive range
          0.0-1.0 (bool rejected, same reasoning as above)
        - reliability is a float (or int) in the inclusive range
          0.0-1.0 (bool rejected, same reasoning as above)
        - created_at is a non-empty string
        - metadata contains only safe, structured data
        """
        if not isinstance(self.pattern_id, str) or not self.pattern_id.strip():
            return False
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            return False
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            return False

        for count in (self.total_records, self.successful_records, self.failed_records):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                return False

        if self.successful_records + self.failed_records != self.total_records:
            return False

        for rate in (self.success_rate, self.reliability):
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                return False
            if rate < 0.0 or rate > 1.0:
                return False

        if not isinstance(self.created_at, str) or not self.created_at.strip():
            return False

        if not _is_safe_structured_value(self.metadata):
            return False

        return True

    # ------------------------------------------------------------------
    # Status checks
    # ------------------------------------------------------------------
    def is_successful(self):
        """True only when there is at least one record and
        `success_rate` is exactly `1.0` - a plain field check, never
        modifies this pattern, never executes anything."""
        return self.total_records > 0 and self.success_rate == 1.0

    def is_failed(self):
        """True only when there is at least one record and
        `success_rate` is exactly `0.0` - a plain field check, never
        modifies this pattern, never executes anything."""
        return self.total_records > 0 and self.success_rate == 0.0

    def is_reliable(self, min_reliability=0.7):
        """True exactly when the stored `reliability` value is
        greater than or equal to `min_reliability`. Deterministic -
        reads only the already-stored `reliability` field (never
        `success_rate`, never `total_records`, and never recomputes
        anything from records), so calling this repeatedly with the
        same `min_reliability` always returns the same result until
        `reliability` itself is changed. Never modifies this pattern,
        never selects or executes a strategy, and never changes any
        other object's state."""
        return self.reliability >= min_reliability

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def get_summary(self):
        """A short, structured summary of this pattern - a new dict
        on every call containing only `pattern_id`, `task_id`,
        `opportunity_id`, `total_records`, `successful_records`,
        `failed_records`, `success_rate`, and `reliability` (a
        deliberately smaller subset than `to_dict()`'s full
        representation - it omits `created_at` and `metadata`).

        Values are copied exactly as stored - never recomputed,
        rounded, or otherwise transformed. Always a new dict - same
        "callers get a copy, not a handle" convention `to_dict()`
        already follows - so mutating the returned dict can never
        affect this pattern's own internal state. Read-only - never
        modifies this pattern, never raises, and never executes,
        learns from, or persists anything."""
        return {
            "pattern_id": self.pattern_id,
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "total_records": self.total_records,
            "successful_records": self.successful_records,
            "failed_records": self.failed_records,
            "success_rate": self.success_rate,
            "reliability": self.reliability,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation of this pattern.
        Always a new dict, and `metadata` is a fresh, independent
        `dict(...)` copy - same "callers get a copy, not a handle"
        convention `RevenueLearningRecord.to_dict()` already follows -
        so mutating the returned dict, or any value inside it, can
        never affect this pattern's own internal state."""
        return {
            "pattern_id": self.pattern_id,
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "total_records": self.total_records,
            "successful_records": self.successful_records,
            "failed_records": self.failed_records,
            "success_rate": self.success_rate,
            "reliability": self.reliability,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
