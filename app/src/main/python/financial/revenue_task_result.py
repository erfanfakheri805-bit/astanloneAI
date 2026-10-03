"""
Revenue Task Result
======================
`RevenueTaskResult` is a small, standalone data record capturing the
*outcome* of one already-finished `RevenueTask`
(financial/revenue_task.py) - either a COMPLETED result carrying its
`output`, or a FAILED result carrying its `error`:

    RevenueTask (IN_PROGRESS) -> [some future execution stage: not
    built yet] -> RevenueTaskResult (COMPLETED or FAILED)

This stage only defines the *shape* of that record and how one is
safely constructed and serialized - it does NOT:

- Execute, evaluate, or interpret `output`, `error`, or `metadata` in
  any way. They are always treated as plain, structured data, never
  as code, commands, or instructions to act on.
- Connect to `RevenueTaskManager` (financial/revenue_task_manager.py),
  `RevenueTask.transition_to()`, or any other system - it is a plain,
  standalone record, not wired into task execution or the learning
  system (learning/) in this stage.
- Persist itself anywhere (no filesystem, database, or network I/O).
- Retry, restart, or re-execute anything - it only records what
  already happened, decided and performed elsewhere.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueTask` (financial/revenue_task.py),
`RevenueOpportunity` (financial/revenue_opportunity.py),
`RevenueStrategy` (financial/revenue_strategy.py), and `FinancialGoal`
(financial/financial_goal.py): a caller can freely build a
RevenueTaskResult from untrusted/partial input and then call
`is_valid()` to decide whether it is fit to use, rather than having to
wrap construction in a try/except.
"""

from datetime import datetime, timezone
import copy


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for result status - deliberately just the
# two terminal outcomes a RevenueTask can be recorded with (see
# RevenueTaskManager.complete_task()/fail_task(),
# financial/revenue_task_manager.py): a RevenueTaskResult only ever
# exists to describe a task that has already finished, one way or the
# other. Same STATUS_* pattern used throughout financial/.
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

ALL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED)

# Safe, structured-data-only types allowed inside `output`, `error`,
# and `metadata`. Same convention as RevenueTask's own
# `_is_safe_structured_value` (financial/revenue_task.py).
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


class RevenueTaskResult:
    """The recorded outcome of one already-finished RevenueTask -
    either COMPLETED (with `output`) or FAILED (with `error`). Purely
    a data record: construction never raises so a caller can freely
    build a RevenueTaskResult from untrusted/partial data and then use
    `is_valid()` to decide whether it is fit to use.

    `output` and `error` may both be `None` - a COMPLETED result need
    not carry any output, and a FAILED result need not carry any error
    detail (same "may be absent" allowance
    `RevenueTaskManager.complete_task()`/`fail_task()` already apply
    to their own `output`/`error` parameters). `metadata` is always a
    plain dict (never `None`) - same "no None checks needed by
    callers" convention as `RevenueTask.metadata`.

    This model does not generate its own `result_id` - unlike
    `RevenueTaskManager.create_task()`'s own `_generate_task_id()`
    convention for `RevenueTask`, no manager exists yet for this
    record, so a caller must supply `result_id` explicitly (same
    "construction never raises, but a caller must supply an id it
    means to keep" contract `RevenueTask.__init__` already applies to
    `task_id`).
    """

    __slots__ = (
        "result_id", "task_id", "opportunity_id", "status", "output",
        "error", "metadata", "created_at",
    )

    def __init__(
        self,
        result_id,
        task_id,
        opportunity_id,
        status,
        output=None,
        error=None,
        metadata=None,
        created_at=None,
    ):
        self.result_id = result_id
        self.task_id = task_id
        self.opportunity_id = opportunity_id
        self.status = status
        self.output = output
        self.error = error
        self.metadata = dict(metadata) if metadata else {}
        self.created_at = created_at if created_at is not None else _now_iso()

    def __repr__(self):
        return (
            f"RevenueTaskResult(result_id={self.result_id!r}, "
            f"task_id={self.task_id!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A result is valid when:
        - result_id is a non-empty string
        - task_id is a non-empty string
        - opportunity_id is a non-empty string
        - status is one of the supported values (see ALL_STATUSES)
        - output and error may each be anything - including `None` -
          as long as it is safe, structured data (see
          `_is_safe_structured_value`); the same rule `is_valid()`
          already applies to `metadata`
        - metadata contains only safe, structured data (see
          `_is_safe_structured_value`)

        This intentionally says nothing about whether the underlying
        RevenueTask actually finished the way this record claims -
        only whether the record itself is well-formed enough to use.
        """
        if not isinstance(self.result_id, str) or not self.result_id.strip():
            return False
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            return False
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            return False
        if self.status not in ALL_STATUSES:
            return False

        if not _is_safe_structured_value(self.output):
            return False
        if not _is_safe_structured_value(self.error):
            return False
        if not _is_safe_structured_value(self.metadata):
            return False

        return True

    # ------------------------------------------------------------------
    # Status checks
    # ------------------------------------------------------------------
    def is_successful(self):
        """True only when status is exactly STATUS_COMPLETED, False
        otherwise (including for STATUS_FAILED or any other stored
        value). A plain status check - never modifies this record,
        never inspects `output`/`error`, and never executes
        anything."""
        return self.status == STATUS_COMPLETED

    def is_failed(self):
        """True only when status is exactly STATUS_FAILED, False
        otherwise (including for STATUS_COMPLETED or any other stored
        value). A plain status check - never modifies this record,
        never inspects `output`/`error`, and never executes
        anything."""
        return self.status == STATUS_FAILED

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation of this result.
        Always a new dict, and `output`, `error`, and `metadata` are
        each a fresh, independent copy (`copy.deepcopy` for
        `output`/`error` - which may be arbitrarily nested structured
        data - and `dict(...)` for `metadata`, already a flat dict) -
        same "callers get a copy, not a handle" convention
        `RevenueTask.to_dict()`/`RevenueTaskManager.get_task()` already
        follow - so mutating the returned dict, or any value inside
        it, can never affect this record's own internal state."""
        return {
            "result_id": self.result_id,
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "status": self.status,
            "output": copy.deepcopy(self.output),
            "error": copy.deepcopy(self.error),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }
