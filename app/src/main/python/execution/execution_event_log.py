"""
Execution - Execution Event Log
===============================
`ExecutionEventLog` is a small, in-memory record of every
ExecutionEvent (execution/execution_event.py) the Execution Engine has
recorded so far:

    ExecutionEngine.execute_step(...)/execute_capability_step(...)
        -> ExecutionEvent -> ExecutionEventLog

This module only stores and retrieves the ExecutionEvent objects the
engine already builds - it does not decide *when* something noteworthy
happened, does not touch the filesystem, a database, the shell, the
network, or any Android API, and does not itself change a PlanStep's
or an ExecutionResult's status (see execution/execution_engine.py for
those - untouched by this module). Same "id-keyed dict plus an ordered
list of ids" storage shape, and the exact same duplicate-protection
and read-only, never-raises-on-a-miss retrieval conventions, as
`ExecutionHistory` (execution_history.py) already uses for
ExecutionResult - see that module's own docstring.

Deliberately independent from persistent storage, same as
`ExecutionHistory` (see that module's own docstring): this log lives
only in this process's RAM and is cleared on process restart, or via
an explicit `clear()` call. A future stage may back this with real
persistence; that is explicitly out of scope here.

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows - see execution_result.py's
module docstring. `ExecutionEventLog` never mutates or re-derives an
ExecutionEvent it's given.
"""

from .execution_event import ExecutionEvent


class ExecutionEventLog:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/ExecutionEngine/ExecutionHistory's own notes). Safe to
    use one instance per Core / per conversation session, or to share
    one across several ExecutionEngine instances that should log to
    the same event stream.

    Storage is two small, always-in-sync structures - a dict keyed by
    `event_id` for O(1) lookup/duplicate-detection, and a list of
    `event_id`s in the order `record()` first saw them, for
    order-preserving iteration - same shape `ExecutionHistory` already
    uses for `execution_id`.
    """

    def __init__(self):
        self._by_event_id = {}
        self._order = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, event):
        """Store `event` (an ExecutionEvent) in this log and return
        it.

        Raises TypeError - and stores nothing - if `event` isn't an
        ExecutionEvent instance, same "safe construction/storage only,
        never a half-built/wrong-shaped record" convention the rest of
        this project's data records already follow.

        Duplicate protection: if an ExecutionEvent with this same
        `event_id` has already been recorded, this call is a no-op -
        the *already-stored* event is returned unchanged and insertion
        order is left exactly as it was (the id is not moved or
        re-appended). This is the exact same "never silently duplicate
        an id already on file" guarantee `ExecutionHistory.record`
        already gives ExecutionResult (see that method's own
        docstring); it is what protects against accidentally recording
        the same event object twice (e.g. if it's handed to `record()`
        more than once)."""
        if not isinstance(event, ExecutionEvent):
            raise TypeError("ExecutionEventLog.record requires an ExecutionEvent instance.")

        existing = self._by_event_id.get(event.event_id)
        if existing is not None:
            return existing

        self._by_event_id[event.event_id] = event
        self._order.append(event.event_id)
        return event

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def list_all(self):
        """Every ExecutionEvent ever recorded, oldest-first (insertion
        order) - a safe copy of the internal ordering (a plain list),
        so mutating the returned list can never reach back into this
        log's own storage. Never raises."""
        return [self._by_event_id[event_id] for event_id in self._order]

    def list_for_execution(self, execution_id):
        """Every ExecutionEvent recorded for `execution_id`, in the
        order they were recorded. An unknown, never-used, or `None`
        `execution_id` simply returns [] - never raises, same
        "read-only reporting" convention as
        `ExecutionHistory.list_for_plan`."""
        return [
            event for event in self.list_all()
            if event.execution_id == execution_id
        ]

    def list_for_plan(self, plan_id):
        """Every ExecutionEvent recorded for `plan_id`, in the order
        they were recorded. An unknown or never-used `plan_id` simply
        returns [] - never raises."""
        return [
            event for event in self.list_all()
            if event.plan_id == plan_id
        ]

    def list_for_step(self, plan_id, step_id):
        """Every ExecutionEvent recorded for the single step named by
        `plan_id`/`step_id`, in the order they were recorded. An
        unknown or never-used `plan_id`/`step_id` simply returns [] -
        never raises."""
        return [
            event for event in self.list_for_plan(plan_id)
            if event.step_id == step_id
        ]

    def latest(self):
        """The most recently recorded ExecutionEvent overall, or None
        if nothing has been recorded yet (never raises on an empty
        log - same convention as `ExecutionHistory.latest_for_step`)."""
        return self._by_event_id[self._order[-1]] if self._order else None

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def clear(self):
        """Discard every recorded ExecutionEvent, resetting this log
        back to empty. Never raises; a no-op on an already-empty log.
        Purely local bookkeeping - never touches a PlanStep, an
        ExecutionResult, or anything outside this log itself."""
        self._by_event_id.clear()
        self._order.clear()

    def __len__(self):
        return len(self._order)
