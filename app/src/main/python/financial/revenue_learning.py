"""
Revenue Learning Record
=========================
`RevenueLearningRecord` is a small, standalone data record capturing
what one already-finished `RevenueTaskResult`
(financial/revenue_task_result.py) *observed* - which task and
opportunity it belongs to, whether it succeeded, and its `output`/
`error` - in a shape a future learning stage could read.

This stage only defines that shape and how one is safely built from an
already-existing `RevenueTaskResult` via `from_task_result()` - same
"plain, JSON-shaped record with a to_dict()" convention already used by
`learning/learning_record.py`'s own `LearningRecord`, and the same
"construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueTaskResult`, `RevenueTask`,
`RevenueOpportunity`, and `FinancialGoal`. It deliberately does NOT:

- Learn anything, infer a pattern, or feed itself into
  `learning/learning_system.py`, `learning/learning_analyzer.py`, or
  any other learning component - it is a plain, standalone container
  a future stage can choose to read, store, or act on, not a decision
  or a behavior change in its own right.
- Modify the `RevenueTaskResult` it is built from in any way - reading
  a result to build a record from it never mutates that result's own
  `status`, `output`, `error`, or `metadata`.
- Execute, retry, or trigger anything - it only records what already
  happened, decided and performed elsewhere.
- Persist itself anywhere (no filesystem, database, or network I/O),
  run any code (no `eval`/`exec`/`subprocess`/shell), or call out to
  any external AI service.
"""

import copy
import itertools
from datetime import datetime, timezone

from .revenue_task_result import STATUS_COMPLETED, STATUS_FAILED, ALL_STATUSES


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Safe, structured-data-only types allowed inside `output` and
# `metadata`. Same convention as RevenueTaskResult's own
# `_is_safe_structured_value` (financial/revenue_task_result.py) and
# LearningRecord's own `_is_safe_metadata_value`
# (learning/learning_record.py).
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
# by learning/learning_record.py's own `_generate_record_id` and
# financial/revenue_task_manager.py's own `_generate_task_id`/
# `_generate_result_id`: a single, process-wide, monotonically
# increasing counter as the default id source. Kept as its own
# independent counter (not shared with any other module's ids).
_id_counter = itertools.count(1)


def _generate_learning_id():
    return f"revenue-learning-{next(_id_counter)}"


class RevenueLearningRecord:
    """A record of what one already-finished `RevenueTaskResult`
    observed - purely a data record: construction never raises so a
    caller can freely build a `RevenueLearningRecord` from
    untrusted/partial data and then use `is_valid()` to decide
    whether it is fit to use.

    `metadata` is always a plain dict (never `None`) - same "no None
    checks needed by callers" convention as `RevenueTaskResult.metadata`.
    """

    __slots__ = (
        "learning_id", "task_id", "opportunity_id", "result_status",
        "success", "output", "error", "created_at", "metadata",
    )

    def __init__(
        self,
        task_id,
        opportunity_id,
        result_status,
        success,
        learning_id=None,
        output=None,
        error=None,
        created_at=None,
        metadata=None,
    ):
        self.learning_id = learning_id if learning_id is not None else _generate_learning_id()
        self.task_id = task_id
        self.opportunity_id = opportunity_id
        self.result_status = result_status
        self.success = success
        self.output = output
        self.error = error
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"RevenueLearningRecord(learning_id={self.learning_id!r}, "
            f"task_id={self.task_id!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"result_status={self.result_status!r}, "
            f"success={self.success!r})"
        )

    # ------------------------------------------------------------------
    # Construction from an existing result
    # ------------------------------------------------------------------
    @classmethod
    def from_task_result(cls, result):
        """Build a `RevenueLearningRecord` from an already-built
        `RevenueTaskResult` (financial/revenue_task_result.py),
        preserving its exact `task_id` and `opportunity_id`.

        `result_status` is copied unchanged from `result.status`.
        `success` is `True` exactly when `result.status ==
        STATUS_COMPLETED` (the same check `RevenueTaskResult.
        is_successful()` performs) - `False` for STATUS_FAILED or any
        other stored value. `output` and `error` are each a fresh
        `copy.deepcopy` of the result's own `output`/`error` (which
        may be arbitrarily nested structured data), never a shared
        reference - same "callers get a copy, not a handle" convention
        `RevenueTaskResult.to_dict()` already follows. A fresh
        `learning_id` is generated (this classmethod never reuses
        `result.result_id`, since a learning record is a distinct kind
        of record from the result it was built from).

        Never modifies `result` in any way - only reads its
        `task_id`/`opportunity_id`/`status`/`output`/`error`. Never
        executes, retries, or learns anything; this is purely a data
        transformation from one already-built record to another.

        Raises `TypeError` if `result` is not a `RevenueTaskResult`
        instance, same "fail loudly on the wrong type" convention a
        classmethod constructor should use rather than silently
        building a nonsensical record."""
        # Local import avoids a hard, always-loaded dependency on
        # revenue_task_result at module import time for callers that
        # only need the plain RevenueLearningRecord shape.
        from .revenue_task_result import RevenueTaskResult

        if not isinstance(result, RevenueTaskResult):
            raise TypeError(
                f"from_task_result() expects a RevenueTaskResult, got {type(result).__name__}"
            )

        return cls(
            task_id=result.task_id,
            opportunity_id=result.opportunity_id,
            result_status=result.status,
            success=(result.status == STATUS_COMPLETED),
            output=copy.deepcopy(result.output),
            error=copy.deepcopy(result.error),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A record is valid when:
        - learning_id is a non-empty string
        - task_id is a non-empty string
        - opportunity_id is a non-empty string
        - result_status is one of the supported RevenueTaskResult
          statuses (see financial/revenue_task_result.py's
          ALL_STATUSES - not duplicated here)
        - success is an actual bool (not merely truthy/falsy)
        - output and error may each be anything - including `None` -
          as long as it is safe, structured data (see
          `_is_safe_structured_value`); the same rule applies to
          `metadata`
        - created_at is a non-empty string
        - metadata contains only safe, structured data

        This intentionally says nothing about whether `success`
        actually matches `result_status` - a caller building a record
        by hand could set them inconsistently; `from_task_result()`
        itself always keeps them in sync."""
        if not isinstance(self.learning_id, str) or not self.learning_id.strip():
            return False
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            return False
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            return False
        if self.result_status not in ALL_STATUSES:
            return False
        if not isinstance(self.success, bool):
            return False
        if self.error is not None and not isinstance(self.error, str):
            return False
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            return False

        if not _is_safe_structured_value(self.output):
            return False
        if not _is_safe_structured_value(self.metadata):
            return False

        return True

    # ------------------------------------------------------------------
    # Status checks
    # ------------------------------------------------------------------
    def is_successful(self):
        """True only when `success` is exactly `True`, False
        otherwise. A plain field check - never modifies this record,
        never inspects `output`/`error`, and never executes
        anything."""
        return self.success is True

    def is_failed(self):
        """True only when `success` is exactly `False`, False
        otherwise (including for any non-bool `success` a caller may
        have set by hand). A plain field check - never modifies this
        record, never inspects `output`/`error`, and never executes
        anything."""
        return self.success is False

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation of this record.
        Always a new dict, and `output` and `metadata` are each a
        fresh, independent copy (`copy.deepcopy` for `output` - which
        may be arbitrarily nested structured data - and `dict(...)`
        for `metadata`, already a flat dict) - same "callers get a
        copy, not a handle" convention `RevenueTaskResult.to_dict()`
        already follows - so mutating the returned dict, or any value
        inside it, can never affect this record's own internal
        state."""
        return {
            "learning_id": self.learning_id,
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "result_status": self.result_status,
            "success": self.success,
            "output": copy.deepcopy(self.output),
            "error": self.error,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
