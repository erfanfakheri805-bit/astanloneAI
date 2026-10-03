"""
Execution - Execution History
===============================
`ExecutionHistory` is a small, in-memory record of every
ExecutionResult (execution/execution_result.py) the Execution Engine
has produced so far:

    ExecutionEngine.execute_step(...) -> ExecutionResult -> ExecutionHistory

This stage only stores and retrieves the ExecutionResult objects the
engine already builds - it does not decide *to* execute anything, does
not touch the filesystem, a database, the shell, the network, or any
Android API, and does not itself change a PlanStep's status (see
execution/execution_engine.py for that - untouched by this module).
History here means "what already happened", never "what should happen
next" - nothing here schedules or triggers a future execution.

Deliberately independent from persistent storage (matches the
in-memory-only convention planning/plan_manager.py's own module
docstring documents for candidate plans - see that docstring's
PLAN MANAGER / PERSISTENT MEMORY table): this history lives only in
this process's RAM and is cleared on process restart. A future stage
may back this with real persistence; that is explicitly out of scope
here (see requirement "Do not implement persistent execution history
yet").

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows - see execution_result.py's
module docstring. `ExecutionHistory` never copies, mutates, or
re-derives an ExecutionResult it's given; it stores the exact object
so a caller reading it back gets the same structured data (including
any later in-place changes to that same object, same "the caller
already owns this object" convention already used elsewhere in this
project) the engine originally produced.
"""

from .execution_result import ExecutionResult


class ExecutionHistory:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/GoalManager/ExecutionEngine's own notes). Safe to use
    one instance per Core / per conversation session, or to share one
    across several ExecutionEngine instances that should log to the
    same history.

    Storage is two small, always-in-sync structures - a dict keyed by
    `execution_id` for O(1) lookup/duplicate-detection, and a list of
    `execution_id`s in the order `record()` first saw them, for
    order-preserving iteration - same "id-keyed dict plus an ordered
    list of ids" shape PlanManager uses for its plans.
    """

    def __init__(self):
        self._by_execution_id = {}
        self._order = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, result):
        """Store `result` (an ExecutionResult) in this history and
        return it.

        Raises TypeError - and stores nothing - if `result` isn't an
        ExecutionResult instance, same "safe construction only, never
        a half-built/wrong-shaped record" convention the rest of this
        project's data records already follow.

        Duplicate protection: if an ExecutionResult with this same
        `execution_id` has already been recorded, this call is a
        no-op - the *already-stored* record is returned unchanged and
        execution order is left exactly as it was (the id is not
        moved or re-appended). This is what keeps a caller safe from
        accidentally recording the same execution twice (e.g. if a
        result is handed to record() more than once) without ever
        silently swapping in a second, possibly-different object for
        an id already on file.
        """
        if not isinstance(result, ExecutionResult):
            raise TypeError("ExecutionHistory.record requires an ExecutionResult instance.")

        existing = self._by_execution_id.get(result.execution_id)
        if existing is not None:
            return existing

        self._by_execution_id[result.execution_id] = result
        self._order.append(result.execution_id)
        return result

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get(self, execution_id):
        """Return the ExecutionResult recorded under `execution_id`,
        or None if no such execution is known (never raises for an
        unknown id - same convention as PlanManager.get_plan/get_step).
        """
        return self._by_execution_id.get(execution_id)

    def list_for_plan(self, plan_id):
        """Every ExecutionResult recorded for `plan_id`, in the order
        they were recorded (see `record`). An unknown or never-used
        `plan_id` simply returns [] - never raises, same
        "read-only reporting" convention as
        PlanManager.get_ready_step_ids."""
        return [
            self._by_execution_id[execution_id]
            for execution_id in self._order
            if self._by_execution_id[execution_id].plan_id == plan_id
        ]

    def list_for_step(self, plan_id, step_id):
        """Every ExecutionResult recorded for the single step named by
        `plan_id`/`step_id`, in the order they were recorded. An
        unknown or never-used `plan_id`/`step_id` simply returns [] -
        never raises."""
        return [
            result for result in self.list_for_plan(plan_id)
            if result.step_id == step_id
        ]

    def latest_for_step(self, plan_id, step_id):
        """The most recently recorded ExecutionResult for
        `plan_id`/`step_id`, or None if that step has no recorded
        execution yet (never raises for an unknown plan/step - same
        convention as `get`)."""
        step_history = self.list_for_step(plan_id, step_id)
        return step_history[-1] if step_history else None

    # ------------------------------------------------------------------
    # Debugging
    # ------------------------------------------------------------------
    def all_results(self):
        """Every ExecutionResult ever recorded, oldest-first
        (insertion order) - a convenience for a caller that wants the
        whole history rather than one plan's/step's slice of it."""
        return [self._by_execution_id[execution_id] for execution_id in self._order]

    def __len__(self):
        return len(self._order)
