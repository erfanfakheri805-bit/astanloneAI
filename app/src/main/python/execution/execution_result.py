"""
Execution - Execution Result
===============================
`ExecutionResult` is the lightweight, structured record the future
Execution Engine will produce for one attempt to execute a single
PlanStep:

    PLAN (planning/plan.py) -> PlanStep -> [Execution Engine: not built
    yet] -> EXECUTION RESULT

This stage only defines the *shape* of that record and how one is
safely constructed, updated, and serialized - it does not execute
anything, does not touch the filesystem, shell, network, or any
Android API, and does not change a PlanStep's own status (see
planning/plan_manager.py for that - untouched by this module). Those
responsibilities belong to the Execution Engine itself, in a later
stage.

Same convention already used by Goal (planning/goal.py), Plan/PlanStep
(planning/plan.py), UnderstandingResult (understanding/result.py),
LearningResult (learning/learning_result.py), ReasoningResult
(reasoning/reasoning_result.py), and ContextEntry
(context/context_entry.py): a plain, JSON-shaped record with a
`to_dict()` method, rather than formatted text, so a caller (a UI, a
test, the eventual Execution Engine) gets everything it needs without
re-deriving anything from a message string.

Deliberately independent from the web UI: nothing here imports or
assumes any particular presentation layer - see module docstring
convention already followed by planning/plan.py and friends.
"""

import itertools
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for execution status (same STATUS_* pattern
# used by planning/plan.py, planning/goal.py, and
# reasoning/reasoning_result.py) so callers can branch on it reliably
# instead of comparing against free-form strings.
STATUS_PENDING = "pending"        # created, not yet started
STATUS_RUNNING = "running"        # in progress
STATUS_COMPLETED = "completed"    # finished successfully
STATUS_FAILED = "failed"          # finished with an error
STATUS_CANCELLED = "cancelled"    # stopped before finishing, not an error

ALL_STATUSES = (
    STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
)

# No ExecutionManager exists yet (that's later-stage Execution Engine
# work), so - same "always assign an id, never leave one dangling"
# convention already used everywhere else in the project (see
# planning/plan_manager.py's plan-id/step-id counters,
# context/conversation_context.py's entry-id counter) - this module
# owns a single, process-wide, monotonically increasing counter as the
# default id source. Deterministic (never random, never guessed - same
# rule goal_manager.py/plan_manager.py apply to confidence scoring),
# and always unique within one running process. A future
# ExecutionManager can still assign its own ids explicitly via the
# `execution_id` constructor argument, in which case this counter is
# simply not consulted for that instance.
_id_counter = itertools.count(1)


def _generate_execution_id():
    return f"execution-{next(_id_counter)}"


class ExecutionResult:
    """The outcome (or in-progress record) of one attempt to execute a
    single PlanStep. Purely a data record - nothing here decides *to*
    execute anything, calls out to the filesystem/shell/network/Android
    APIs, or reaches into planning/plan_manager.py to change a
    PlanStep's status. The small `mark_*` helpers below are bookkeeping
    only: they record a status transition and a timestamp on *this*
    record, the same way PlanStep.set_status/update_step_status record
    a step's status - they never run anything themselves.

    `metadata` is always a plain dict (never None) so callers can
    read/update it immediately without a None check - same convention
    as Goal.metadata / Plan.metadata.

    `capability_outputs` (added alongside capability_output.py's
    `CapabilityOutput`) is an entirely optional, additive
    `{capability_name: CapabilityOutput}` map - always a plain dict
    (never None), always starts empty, and is only ever populated
    through `attach_capability_output` below, never at construction.
    Nothing about this record's existing shape changes because of it:
    `to_dict()` only ever includes a `"capability_outputs"` key when
    at least one has actually been attached (see `to_dict` below), so
    an ExecutionResult that never touches CapabilityOutput at all
    serializes exactly as it always has (requirement 8: "ExecutionResult
    should remain backward compatible while being able to reference or
    contain a standardized CapabilityOutput where appropriate").
    """

    __slots__ = (
        "execution_id", "plan_id", "step_id", "status", "output", "error",
        "started_at", "finished_at", "metadata", "capability_outputs",
    )

    def __init__(
        self,
        plan_id,
        step_id,
        status=STATUS_PENDING,
        output=None,
        error=None,
        started_at=None,
        finished_at=None,
        metadata=None,
        execution_id=None,
    ):
        """Safe construction: always ends with a fully-formed, valid
        record or raises ValueError (and creates nothing) - never a
        half-built object. `plan_id`/`step_id` must be given (an
        execution result always names what it's the result *of*, same
        "never a dangling reference" rule PlanManager.create_plan
        already applies to goal_id); `status`, if given, must be one
        of ALL_STATUSES. `execution_id` is optional - if omitted, one
        is generated for you (see _generate_execution_id) so every
        ExecutionResult always has a unique id, even before an
        Execution Engine/ExecutionManager exists to assign one."""
        if not plan_id:
            raise ValueError("ExecutionResult requires a plan_id.")
        if not step_id:
            raise ValueError("ExecutionResult requires a step_id.")
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown execution status: {status!r}")

        self.execution_id = execution_id if execution_id is not None else _generate_execution_id()
        self.plan_id = plan_id
        self.step_id = step_id
        self.status = status
        self.output = output
        self.error = error
        self.started_at = started_at
        self.finished_at = finished_at
        self.metadata = dict(metadata) if metadata else {}
        self.capability_outputs = {}

    def __repr__(self):
        return (
            f"ExecutionResult(execution_id={self.execution_id!r}, "
            f"plan_id={self.plan_id!r}, step_id={self.step_id!r}, "
            f"status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Status handling
    # ------------------------------------------------------------------
    # Deliberately small: a safe way to set this record's status
    # directly, plus one convenience "mark_*" helper per terminal/
    # in-progress outcome that also stamps the relevant timestamp.
    # None of these execute anything - they only ever record a status
    # and/or a timestamp already known to the caller.
    def set_status(self, new_status):
        """Safely set this record's status. Raises ValueError - and
        leaves the record untouched - if `new_status` isn't one of
        ALL_STATUSES. Same convention as PlanStep.set_status."""
        if new_status not in ALL_STATUSES:
            raise ValueError(f"Unknown execution status: {new_status!r}")
        self.status = new_status
        return self

    def mark_running(self):
        """Record that execution has started: status -> RUNNING, and
        stamps `started_at` with the current time if it isn't already
        set. Does not run anything."""
        self.set_status(STATUS_RUNNING)
        if self.started_at is None:
            self.started_at = _now_iso()
        return self

    def mark_completed(self, output=None):
        """Record a successful finish: status -> COMPLETED, stores
        `output` when given, and stamps `finished_at` with the current
        time if it isn't already set. Does not run anything."""
        self.set_status(STATUS_COMPLETED)
        if output is not None:
            self.output = output
        if self.finished_at is None:
            self.finished_at = _now_iso()
        return self

    def mark_failed(self, error):
        """Record a failed finish: status -> FAILED, stores `error`,
        and stamps `finished_at` with the current time if it isn't
        already set. Does not run anything."""
        self.set_status(STATUS_FAILED)
        self.error = error
        if self.finished_at is None:
            self.finished_at = _now_iso()
        return self

    def mark_cancelled(self, reason=None):
        """Record a cancellation (not a failure): status -> CANCELLED,
        stores `reason` in `error` when given, and stamps
        `finished_at` with the current time if it isn't already set.
        Does not run anything or decide *to* cancel - that decision
        belongs to whatever future caller invokes this."""
        self.set_status(STATUS_CANCELLED)
        if reason is not None:
            self.error = reason
        if self.finished_at is None:
            self.finished_at = _now_iso()
        return self

    # ------------------------------------------------------------------
    # CapabilityOutput integration (requirement 8, capability_output.py)
    # ------------------------------------------------------------------
    def attach_capability_output(self, capability_name, capability_output):
        """Record `capability_output` (a `CapabilityOutput` -
        execution/capability_output.py) as the standardized output
        produced for `capability_name` during this execution attempt.
        Purely additive bookkeeping - same "record only, never decide
        or execute" rule the `mark_*` helpers above already follow;
        this never changes `status`/`output`/`error`, never touches a
        PlanStep, and is entirely optional (a caller that never calls
        this gets an ExecutionResult that behaves exactly as it always
        has). Raises ValueError - and stores nothing - if
        `capability_name` is empty, whitespace-only, or not a string.
        Raises TypeError - and stores nothing - if `capability_output`
        isn't a `CapabilityOutput` instance (imported lazily to avoid
        a hard import cycle between this module and
        capability_output.py). Overwrites any existing entry for the
        same `capability_name`. Returns `self`, for convenience."""
        from .capability_output import CapabilityOutput
        if not capability_name or not isinstance(capability_name, str) or not capability_name.strip():
            raise ValueError("attach_capability_output requires a non-empty capability_name string.")
        if not isinstance(capability_output, CapabilityOutput):
            raise TypeError("attach_capability_output requires a CapabilityOutput instance.")
        self.capability_outputs[capability_name.strip()] = capability_output
        return self

    def get_capability_output(self, capability_name):
        """The `CapabilityOutput` attached for `capability_name`, or
        `None` if none was ever attached (never raises for an unknown
        name - same "read-only-safe on a miss" convention
        ExecutionHistory.get/PlanManager.get_plan already follow)."""
        return self.capability_outputs.get(capability_name)

    def get_capability_outputs(self):
        """A defensive copy of the `{capability_name: CapabilityOutput}`
        map attached so far - same "callers get a copy, not a handle"
        convention `to_dict()`'s own `metadata` copy already follows."""
        return dict(self.capability_outputs)

    # ------------------------------------------------------------------
    # Derived data / serialization
    # ------------------------------------------------------------------
    @property
    def duration(self):
        """Seconds between `started_at` and `finished_at`, or None if
        either timestamp is missing or unparseable. Always derived
        fresh from the two stored ISO timestamps - never stored
        separately, so it can never drift out of sync with them, and
        never guessed when one side is missing."""
        if not self.started_at or not self.finished_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.finished_at)
        except (TypeError, ValueError):
            return None
        return (end - start).total_seconds()

    def to_dict(self):
        """Structured (JSON-shaped) representation - the general-
        purpose serialization for a UI, a test, or the eventual
        Execution Engine. See module docstring for the convention this
        follows.

        `"capability_outputs"` is only ever included when at least one
        `CapabilityOutput` has actually been attached via
        `attach_capability_output` - an ExecutionResult that never
        touches CapabilityOutput serializes with exactly the same key
        set it always has (requirement 8: backward compatibility)."""
        data = {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "metadata": dict(self.metadata),
        }
        if self.capability_outputs:
            data["capability_outputs"] = {
                name: capability_output.to_dict()
                for name, capability_output in self.capability_outputs.items()
            }
        return data
