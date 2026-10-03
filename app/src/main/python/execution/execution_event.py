"""
Execution - Execution Event
===============================
`ExecutionEvent` is a small, structured record of one noteworthy thing
that happened while a plan step was being prepared for or run by the
Execution Engine:

    ExecutionEngine (execution/execution_engine.py)
        -> [something noteworthy happens]
        -> ExecutionEvent -> ExecutionEventLog (execution_event_log.py)

This module only defines the *shape* of that record and how one is
safely constructed and serialized - it does not execute anything, does
not touch the filesystem, shell, network, or any Android API, and does
not change a PlanStep's or an ExecutionResult's own status (see
execution_engine.py/execution_result.py for those - untouched by this
module). An ExecutionEvent never decides *to* do anything; it only
describes something that already happened, the same way ExecutionResult
already does for a whole execution attempt (see execution_result.py's
own module docstring) and PreflightResult already does for a single
readiness check (see preflight.py).

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows - see execution_result.py's
module docstring. `data`/`metadata` are always funneled through
`planning.plan.ensure_structured_data` (the single existing place this
project decides "is this safe structured data?" - see that function's
own docstring), so an ExecutionEvent can never silently hold anything
that isn't safe, JSON-shaped structured data - never a live object, a
callable, or anything that could be mistaken for code to run. Nothing
in this module ever calls `eval()`/`exec()`, ever executes/evaluates
`data`/`metadata`, or ever interprets either as instructions - they are
always just inert, structured data describing what already happened.
"""

import itertools
from datetime import datetime, timezone

from planning.plan import ensure_structured_data


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for event types (same *_TYPE/STATUS_* pattern
# already used by execution_result.py's STATUS_* constants and
# preflight.py's own check names) so callers can branch on it reliably
# instead of comparing against free-form strings.
EVENT_EXECUTION_CREATED = "EXECUTION_CREATED"
EVENT_PREPARATION_STARTED = "PREPARATION_STARTED"
EVENT_PREPARATION_COMPLETED = "PREPARATION_COMPLETED"
EVENT_PREPARATION_FAILED = "PREPARATION_FAILED"
EVENT_EXECUTION_STARTED = "EXECUTION_STARTED"
EVENT_CAPABILITY_STARTED = "CAPABILITY_STARTED"
EVENT_CAPABILITY_COMPLETED = "CAPABILITY_COMPLETED"
EVENT_CAPABILITY_FAILED = "CAPABILITY_FAILED"
EVENT_OUTPUT_CREATED = "OUTPUT_CREATED"
EVENT_EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
EVENT_EXECUTION_FAILED = "EXECUTION_FAILED"
EVENT_EXECUTION_CANCELLED = "EXECUTION_CANCELLED"

# Agent-level event types (agent/agent_loop.py's AgentLoop). These are
# never emitted by ExecutionEngine/StepExecutionController/
# PlanExecutionController themselves - they describe what the
# *AgentLoop* itself observed/decided (a controlled coordinator sitting
# on top of the existing, unchanged execution stack), reusing this same
# ExecutionEvent/ExecutionEventLog machinery rather than inventing a
# second, parallel event system. Same "describes something that
# already happened, never decides to do anything" contract as every
# other event type above.
EVENT_AGENT_LOOP_STARTED = "AGENT_LOOP_STARTED"
EVENT_AGENT_ITERATION_STARTED = "AGENT_ITERATION_STARTED"
EVENT_AGENT_EVALUATION_COMPLETED = "AGENT_EVALUATION_COMPLETED"
EVENT_AGENT_EXECUTION_COMPLETED = "AGENT_EXECUTION_COMPLETED"
EVENT_AGENT_LOOP_COMPLETED = "AGENT_LOOP_COMPLETED"
EVENT_AGENT_LOOP_STOPPED = "AGENT_LOOP_STOPPED"
EVENT_AGENT_LOOP_FAILED = "AGENT_LOOP_FAILED"

ALL_EVENT_TYPES = (
    EVENT_EXECUTION_CREATED,
    EVENT_PREPARATION_STARTED,
    EVENT_PREPARATION_COMPLETED,
    EVENT_PREPARATION_FAILED,
    EVENT_EXECUTION_STARTED,
    EVENT_CAPABILITY_STARTED,
    EVENT_CAPABILITY_COMPLETED,
    EVENT_CAPABILITY_FAILED,
    EVENT_OUTPUT_CREATED,
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    EVENT_EXECUTION_CANCELLED,
    EVENT_AGENT_LOOP_STARTED,
    EVENT_AGENT_ITERATION_STARTED,
    EVENT_AGENT_EVALUATION_COMPLETED,
    EVENT_AGENT_EXECUTION_COMPLETED,
    EVENT_AGENT_LOOP_COMPLETED,
    EVENT_AGENT_LOOP_STOPPED,
    EVENT_AGENT_LOOP_FAILED,
)

# Small, fixed vocabulary for event severity - same controlled-
# vocabulary convention as ALL_EVENT_TYPES/ALL_STATUSES above/elsewhere
# in this project.
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"

ALL_SEVERITIES = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR)


# Process-wide, monotonically increasing counter for default event
# ids - same "always assign an id, never leave one dangling" pattern
# already used by execution_result.py's own `_id_counter`/
# `_generate_execution_id`. Deterministic, never random/guessed, and
# always unique within one running process. A caller can still supply
# its own explicit `event_id`, in which case this counter is simply
# not consulted for that instance.
_id_counter = itertools.count(1)


def _generate_event_id():
    return f"event-{next(_id_counter)}"


class ExecutionEvent:
    """One structured, immutable-in-spirit record of something
    noteworthy that happened during plan-step preparation or
    execution. Purely a data record - nothing here decides *to* do
    anything, calls a handler/capability, touches a PlanStep or an
    ExecutionResult, or reaches into the filesystem/shell/network/an
    Android API. Recording *when* something happened is
    `ExecutionEngine`'s job (execution_engine.py); this class only
    describes it safely once that decision has already been made.

    `data`/`metadata` are always plain dicts (never `None`) so callers
    can read them immediately without a `None` check - same convention
    as `ExecutionResult.metadata`/`Goal.metadata`. Both are always
    passed through `planning.plan.ensure_structured_data` at
    construction time, so an ExecutionEvent can never hold anything
    that isn't safe, JSON-shaped structured data; this class never
    evaluates or executes either of them - they are inert bookkeeping
    only.
    """

    __slots__ = (
        "event_id", "execution_id", "plan_id", "step_id", "event_type",
        "message", "timestamp", "data", "severity", "metadata",
    )

    def __init__(
        self,
        event_type,
        plan_id,
        step_id,
        execution_id=None,
        message="",
        data=None,
        severity=SEVERITY_INFO,
        metadata=None,
        timestamp=None,
        event_id=None,
    ):
        """Safe construction: always ends with a fully-formed, valid
        record, or raises (and creates nothing) - never a half-built
        object.

        Required identifiers - `plan_id` and `step_id` must both be
        given as non-empty strings (same "an event always names what
        it's about" rule `ExecutionResult` already applies to its own
        `plan_id`/`step_id`); missing/empty either raises ValueError.
        `execution_id`, if given, must be a non-empty string - `None`
        is allowed, since some events (e.g. a preparation check that
        hasn't yet produced an ExecutionResult) legitimately have no
        execution id yet; an empty/whitespace-only string is rejected
        the same way a missing `plan_id`/`step_id` is.

        `event_type` must be one of `ALL_EVENT_TYPES` and `severity`
        must be one of `ALL_SEVERITIES` - both controlled vocabularies,
        never a free-form string - or this raises ValueError.

        `data`/`metadata` are funneled through
        `planning.plan.ensure_structured_data`, so anything that isn't
        safe, JSON-shaped structured data (a live object, a callable,
        a container that contains itself, ...) raises TypeError here,
        the exact same guarantee `PlanStep.set_input`/`set_output`
        already give their own structured-data fields. `None` for
        either is stored as `{}` (never `None`), matching the
        "metadata is always a plain dict" convention above.

        `event_id`, if omitted, is generated for you (see
        `_generate_event_id`) so every ExecutionEvent always has a
        unique id even before an `ExecutionEventLog` exists to assign
        one. `timestamp`, if omitted, is stamped with the current time
        (UTC, ISO-8601) - matching `ExecutionResult`'s own
        `started_at`/`finished_at` timestamp format so the two can be
        compared/sorted directly.
        """
        if not plan_id or not isinstance(plan_id, str):
            raise ValueError("ExecutionEvent requires a non-empty plan_id.")
        if not step_id or not isinstance(step_id, str):
            raise ValueError("ExecutionEvent requires a non-empty step_id.")
        if execution_id is not None and (
            not isinstance(execution_id, str) or not execution_id.strip()
        ):
            raise ValueError(
                "ExecutionEvent's execution_id must be a non-empty string, or None."
            )
        if event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown execution event type: {event_type!r}")
        if severity not in ALL_SEVERITIES:
            raise ValueError(f"Unknown execution event severity: {severity!r}")
        if not isinstance(message, str):
            raise ValueError("ExecutionEvent's message must be a string.")

        # Never executed/evaluated - purely a safety check that these
        # two fields hold only inert, JSON-shaped structured data (see
        # module docstring and ensure_structured_data's own
        # docstring). Raises TypeError - and stores nothing - the
        # first time either contains anything unsafe.
        safe_data = ensure_structured_data(data) if data is not None else {}
        safe_metadata = ensure_structured_data(metadata) if metadata is not None else {}
        if not isinstance(safe_data, dict):
            raise TypeError("ExecutionEvent's data must be a dict (or None).")
        if not isinstance(safe_metadata, dict):
            raise TypeError("ExecutionEvent's metadata must be a dict (or None).")

        self.event_id = event_id if event_id is not None else _generate_event_id()
        self.execution_id = execution_id
        self.plan_id = plan_id
        self.step_id = step_id
        self.event_type = event_type
        self.message = message
        self.timestamp = timestamp if timestamp is not None else _now_iso()
        self.data = safe_data
        self.severity = severity
        self.metadata = safe_metadata

    def __repr__(self):
        return (
            f"ExecutionEvent(event_id={self.event_id!r}, "
            f"event_type={self.event_type!r}, plan_id={self.plan_id!r}, "
            f"step_id={self.step_id!r}, severity={self.severity!r})"
        )

    def is_error(self):
        """True when this event's `severity` is `SEVERITY_ERROR`,
        False otherwise. Read-only; never raises."""
        return self.severity == SEVERITY_ERROR

    def to_dict(self):
        """A deterministic, JSON-shaped dictionary representation -
        always the same key set, in the same order, for every
        ExecutionEvent (see module docstring for the convention this
        follows). `data`/`metadata` are returned as defensive copies
        (same "callers get a copy, not a handle" convention
        `ExecutionResult.to_dict`'s own `metadata` copy already
        follows), so mutating the returned dict can never reach back
        into this event's own stored state."""
        return {
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp,
            "data": dict(self.data),
            "severity": self.severity,
            "metadata": dict(self.metadata),
        }
