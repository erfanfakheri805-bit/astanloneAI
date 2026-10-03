"""
Revenue Task Manager
======================
`RevenueTaskManager` is a small, in-memory, id-keyed store for
`RevenueTask` objects (financial/revenue_task.py):

    raw fields -> RevenueTaskManager.create_task()
        -> get_task() / get_all() / get_for_opportunity() /
           get_tasks_for_opportunity() / get_task_ids_for_opportunity() /
           get_opportunity_task_status() / get_next_startable_task() /
           get_startable_tasks() / inspect_opportunity_execution_queue() /
           get_execution_queue_summary() / prepare_task_execution() /
           start_task() / complete_task() / fail_task() /
           record_task_result() / get_task_result() /
           has_task_result() / remove_task() / clear()

`get_execution_queue_summary()` is a thin, count-level re-shaping of
`inspect_opportunity_execution_queue()`'s own result - one underlying
call, never a second independent scan - into per-status counts plus
has_startable_tasks/has_blocked_tasks/has_failed_tasks/all_completed
flags. Purely read-only, same as the method it reuses.

`get_startable_tasks()` is the "all matches" sibling of
`get_next_startable_task()`'s "first match" - same eligibility checks
(`has_opportunity()`, `is_startable()`, `get_dependency_status()`'s
own `ready` flag), applied to every matching task instead of just the
first, in this manager's own insertion order. Purely read-only, same
as its sibling.

`inspect_opportunity_execution_queue()` is another purely read-only
lookup: a per-opportunity snapshot that sorts every matching task's
id into exactly one status bucket (startable, blocked, in-progress,
completed, failed, cancelled) plus a `next_startable_task_id`, built
entirely from each task's own status helpers and
`get_dependency_status()`. It only describes the queue; it never
starts, attaches, creates, or changes anything.

`get_next_startable_task()` is another purely read-only lookup: the
first task (in this manager's own insertion order) belonging to a
given opportunity whose status allows starting and whose dependencies
are satisfied - built entirely from each candidate task's own
`is_startable()` and `get_dependency_status()`, never a hand-rolled
re-implementation of either. It only identifies the task; it never
starts it, never changes its status, and never attaches, creates, or
executes anything.

`get_opportunity_task_status()` is another purely read-only lookup: a
small structured status-count summary (per-status counts plus
active/final counts and all_completed/has_failed flags) for all tasks
belonging to one opportunity, built entirely from each matching
task's own status helpers - it never changes any task's or
opportunity's status, and never creates, attaches, or executes
anything.

`get_tasks_for_opportunity()` and `get_task_ids_for_opportunity()` are
both purely read-only lookups over this manager's own stored tasks -
neither one creates, attaches, or executes a task, and neither one
changes any task's or opportunity's status. The former mirrors
`get_for_opportunity()`'s own "opportunity_id match, insertion order,
safe copies" behavior under this stage's own name; the latter returns
just the matching, de-duplicated task_id strings in that same order.

`create_task_for_opportunity()` is a thin convenience wrapper around
that same flow for the common "build one task for one opportunity and
attach it right away" case: it calls `create_task()` then
`attach_task_to_opportunity()`, rolling the new task back out of this
store (via `remove_task()`) if attachment doesn't succeed, rather than
duplicating either method's own validation/attachment logic.

`prepare_task_execution()` is another purely read-only lookup: a
structured preparation report for one stored task, built entirely
from `get_task()` plus that task's own `get_readiness_report()` and
`get_dependency_status()` (which itself already calls
`is_startable()` internally) - never a hand-rolled re-implementation
of any of those. `prepared` is True only when the task exists, has a
valid opportunity, can start, and every dependency is satisfied - the
exact same condition as that task's own `get_readiness_report()`
`ready` flag. A missing task_id yields a safe structured result with
`prepared: False` and an `error` field instead of raising. It never
executes anything, starts anything, or changes any task's or
opportunity's status/dependencies - it only reports whether a task
*looks* ready for some later, separate execution step.

`start_task()` is the one method in this module that mutates a task's
status - and it only ever performs the single READY -> IN_PROGRESS
transition, and only after re-verifying readiness through
`prepare_task_execution()` (never a hand-rolled duplicate of that
readiness logic). It rejects, without changing anything, a missing
task, a task with no valid opportunity, a task whose status is not
exactly READY (PENDING/BLOCKED/COMPLETED/FAILED/CANCELLED tasks are
all left untouched), or a READY task with unsatisfied dependencies.
The one mutation it ever performs is calling the stored task's own
`transition_to(STATUS_IN_PROGRESS)` - reusing the existing transition
table rather than setting `status` directly - so no other field on
the task, no other task, and no opportunity is ever touched. It never
executes the task, never calls a capability or tool, never creates a
plan or another task, and never accesses the network or an external
AI service.

`complete_task()` is the other method in this module that mutates a
task's status - and, like `start_task()`, it only ever performs one
specific transition (IN_PROGRESS -> COMPLETED), rejecting PENDING,
READY, BLOCKED, FAILED, and CANCELLED tasks untouched. Since the
existing `RevenueTask` model has no dedicated field or setter for
storing arbitrary completion output or post-construction metadata,
the `output`/`metadata` given to `complete_task()` are never written
onto the task - they are only echoed back in the returned result,
treated purely as opaque structured data (never executed, evaluated,
or interpreted). The one mutation it ever performs is the task's own
`transition_to(STATUS_COMPLETED)` call - reusing the existing
transition table rather than setting `status` directly - so no other
field, no other task, and no opportunity is ever touched, and nothing
is executed, planned, retried, or dispatched to a tool, capability,
or external service.

`fail_task()` is `complete_task()`'s failure-path sibling: the same
IN_PROGRESS-only precondition, the same "reuse `transition_to()`,
never duplicate transition rules" approach - here for the one
IN_PROGRESS -> FAILED transition - and the same "no dedicated model
field, so echo `error`/`metadata` back in the result instead of
writing them onto the `RevenueTask`" treatment. A `None` error is
replaced with a safe, structured placeholder string in the result
rather than left as a bare `None`. Like `complete_task()`, it never
retries or restarts anything, never executes another task or
capability, never calls a tool, never creates a task or plan, never
modifies the opportunity, and never accesses the network or an
external AI service.

`record_task_result()` is a different kind of operation from
`complete_task()`/`fail_task()`: rather than transitioning a task's
`status`, it builds a `RevenueTaskResult`
(financial/revenue_task_result.py) - a structured record of a
COMPLETED or FAILED outcome, complete with its own `output`/`error`/
`metadata` - and attaches it to the task via that task's own
`set_result()` (financial/revenue_task.py, added alongside `result`/
`get_result()`/`has_result()`/`clear_result()`). It never calls
`transition_to()` and never changes the task's `status` field, it
never calls `complete_task()` or `fail_task()` itself (and neither of
those calls it), and a task that already has a result attached is
rejected rather than silently overwritten. Result ids are generated
by this manager's own `_generate_result_id()` counter - `set_result()`
does not enforce this; this manager applies it before ever calling
`set_result()`, at this layer only.

`get_task_result()`/`has_task_result()` are `record_task_result()`'s
purely read-only siblings: thin wrappers over `get_task()` plus that
task's own existing `get_result()`/`has_result()`
(financial/revenue_task.py) - never a hand-rolled duplicate of either
lookup or of `RevenueTaskResult.is_valid()`'s own validation logic.
Both return a safe default (`None`/`False` respectively) for a
missing or invalid `task_id`, never raise, and never modify the task,
its attached result, or this manager's own storage in any way.

This stage only builds, stores, and retrieves already-built
`RevenueTask` records - it does not execute anything, does not change
a task's status, does not create opportunities or plans, does not
call any tool, and does not touch the filesystem, a database, the
shell, the network, or any external AI service. `attach_task_to_opportunity`
is the one exception to "does not attach a task to a
`RevenueOpportunity`" above: it is a thin, read-then-delegate helper
that looks up an already-stored task and hands it to that
`RevenueOpportunity`'s own `attach_task()` (financial/revenue_opportunity.py)
- it never duplicates that method's attachment/validation logic, never
changes any task's status, and never changes the opportunity's status
or any other field besides `task_ids`. Nothing here is persisted: like
`financial/revenue_opportunity_manager.py`,
`financial/revenue_strategy_manager.py`, and
`learning/learning_record_store.py`, this store lives only in this
process's RAM and is cleared on process restart (or on an explicit
`clear()` call). The existing SQLite persistence system
(memory/memory_system.py) is untouched by this stage.

No task is ever started, completed, failed, or otherwise transitioned
by this module - `status` only ever changes when a caller mutates a
`RevenueTask` directly (e.g. via its own `transition_to()`).

Two related but distinct "reject invalid input safely" conventions are
used here, matching `financial/revenue_opportunity_manager.py`'s own
precedent:

- `create_task` builds a new `RevenueTask` from raw fields and raises
  `ValueError` - storing nothing - if the result fails its own
  `is_valid()` check, or if the task_id is already taken.
- `add_task` stores an already-built `RevenueTask` and returns `None`
  - storing nothing - if it isn't a valid `RevenueTask`, its task_id
  is empty, or its id is already taken, rather than raising. Same
  "reject safely, never raise" convention as
  `revenue_opportunity_manager.py`'s own `add_opportunity`.

Either way, duplicate task ids never overwrite an existing task - the
first task stored under a given id always wins.
"""

import copy
import itertools

from .revenue_task import RevenueTask, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED
from .revenue_opportunity import RevenueOpportunity
from .revenue_task_result import (
    RevenueTaskResult,
    ALL_STATUSES as _RESULT_ALL_STATUSES,
)

# Same "always assign an id, never leave one dangling" convention used
# by financial/revenue_opportunity_manager.py's own counter. Only used
# by `create_task` when no explicit id is given.
_id_counter = itertools.count(1)


def _generate_task_id():
    return f"rev-task-{next(_id_counter)}"


# Separate counter for RevenueTaskResult ids - same "single,
# process-wide, monotonically increasing counter" convention as
# `_id_counter` above and as execution/execution_result.py's own
# `_generate_execution_id`, kept as its own independent counter (not
# `_id_counter`) so task ids and result ids never collide or
# interleave with one another. Only used by `record_task_result` -
# `RevenueTaskResult` itself never generates its own id (see
# financial/revenue_task_result.py's own docstring).
_result_id_counter = itertools.count(1)


def _generate_result_id():
    return f"rev-task-result-{next(_result_id_counter)}"


# Safe, structured (plain string) stand-in used by `fail_task()` when
# no `error` detail is given - never executed or interpreted, just a
# readable placeholder so `failed: True` results always carry some
# error value.
_DEFAULT_FAILURE_ERROR = "No error detail provided."


class RevenueTaskManager:
    """Not thread-safe (matches the rest of this project - see
    RevenueOpportunityManager/RevenueStrategyManager's own notes).
    Safe to use one instance per Core / per conversation session.

    Storage is a single `{task_id: RevenueTask}` dict, keyed by each
    task's own `task_id` - simplest structure that still supports
    O(1) lookup by id and straightforward duplicate-id rejection.
    `get_for_opportunity` does a linear scan over stored tasks - fine
    at this stage's expected scale, and avoids maintaining extra
    indexes that could drift out of sync with `_tasks`.
    """

    def __init__(self):
        self._tasks = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_task(
        self,
        opportunity_id,
        name=None,
        description=None,
        status=None,
        priority=None,
        estimated_duration=None,
        dependencies=None,
        metadata=None,
        task_id=None,
    ):
        """Build a `RevenueTask` from the given fields, store it
        through `add_task`, and return a safe copy of it.

        Raises `ValueError` - and stores nothing - if:
        - `task_id` is given and already used by a stored task, or
        - the resulting task fails its own `is_valid()` check (e.g.
          an empty/invalid `opportunity_id` or `name`/`description`,
          an unsupported `status`/`priority`, a malformed
          `dependencies` list, or unsafe/unstructured `metadata`).

        This is a controlled rejection, not a crash: this stage never
        executes the task and never changes its status on its own -
        it only decides whether the record itself is well-formed
        enough to store.
        """
        resolved_task_id = task_id if task_id else _generate_task_id()
        if resolved_task_id in self._tasks:
            raise ValueError(
                f"A revenue task with id {resolved_task_id!r} already exists."
            )

        kwargs = dict(
            task_id=resolved_task_id,
            opportunity_id=opportunity_id,
            name=name,
            description=description,
            dependencies=dependencies,
            metadata=metadata,
        )
        # Only override the model's own defaults when a value was
        # actually given, so create_task(...) without
        # status/priority/estimated_duration still gets RevenueTask's
        # documented defaults rather than `None`.
        if status is not None:
            kwargs["status"] = status
        if priority is not None:
            kwargs["priority"] = priority
        if estimated_duration is not None:
            kwargs["estimated_duration"] = estimated_duration

        task = RevenueTask(**kwargs)

        if not task.is_valid():
            raise ValueError(
                "Cannot create revenue task: one or more fields failed validation."
            )

        stored = self.add_task(task)
        if stored is None:
            # add_task only rejects on duplicate id or invalidity,
            # both already ruled out above - kept as a defensive
            # safeguard rather than assumed unreachable.
            raise ValueError(
                "Cannot create revenue task: failed to store the new task."
            )
        return copy.deepcopy(stored)

    # ------------------------------------------------------------------
    # Creation + attachment (combined convenience)
    # ------------------------------------------------------------------
    def create_task_for_opportunity(
        self,
        opportunity,
        name,
        description="",
        priority=0,
        estimated_duration=None,
        dependencies=None,
        metadata=None,
    ):
        """Build a new `RevenueTask` for `opportunity` and attach it in
        one step, without duplicating either `RevenueTask`'s own
        validation (`create_task` -> `RevenueTask.is_valid()`) or
        `RevenueOpportunity`'s own attachment logic
        (`attach_task_to_opportunity` -> `opportunity.attach_task()`).

        `priority` follows the same "falsy means unset" convention as
        `create_task`'s own `status`/`priority`/`estimated_duration`
        arguments: a falsy `priority` (the `0` default, `None`, or
        `""`) is treated as "not given" so `RevenueTask`'s own default
        priority (NORMAL) applies; any other value is passed straight
        through to `create_task`, which is left to validate it.

        Always returns a new, structured (JSON-shaped) result dict.
        Never raises.

        On success:
            {"success": True, "task_id": <new id>,
             "opportunity_id": opportunity.opportunity_id,
             "created": True, "attached": True}

        On failure - nothing is stored and nothing is attached:
            {"success": False, "task_id": None,
             "opportunity_id": <best-effort id or None>,
             "created": False, "attached": False, "error": <reason>}

        Fails safely, without creating or attaching anything, when:
        - `opportunity` is not a valid `RevenueOpportunity` instance
          (error: "invalid_opportunity")
        - `opportunity.opportunity_id` is not a non-empty string
          (error: "invalid_opportunity_id")
        - `name` is not a non-empty string
          (error: "invalid_name")
        - the underlying `create_task()` call rejects the resulting
          task (error: `create_task`'s own `ValueError` message, e.g.
          an invalid `estimated_duration`/`dependencies`/`metadata`)

        The new task's id is always generated by `create_task`'s own
        `_generate_task_id()` convention (an incrementing counter,
        checked against every id already stored here) - this method
        never accepts or guesses an explicit `task_id`, so it can
        never collide with, or overwrite, an existing task.

        If the task is built and stored but the follow-up
        `attach_task_to_opportunity()` call does not report success
        (including if `opportunity.attach_task()` itself declines the
        task for any reason), the just-created task is removed from
        this manager via `remove_task()` before returning a failure
        result - so a caller never ends up with a task that exists in
        this store but isn't attached to the opportunity it was made
        for. `opportunity` itself is only ever changed by that one
        `attach_task()` call (its `task_ids` list gaining the new
        task's id) - nothing here executes the task, changes its
        status, changes the opportunity's status, creates a plan,
        calls a tool, or touches the network."""
        opportunity_id = getattr(opportunity, "opportunity_id", None)

        def _failure(error):
            return {
                "success": False,
                "task_id": None,
                "opportunity_id": opportunity_id,
                "created": False,
                "attached": False,
                "error": error,
            }

        if not isinstance(opportunity, RevenueOpportunity) or not opportunity.is_valid():
            return _failure("invalid_opportunity")

        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return _failure("invalid_opportunity_id")

        if not isinstance(name, str) or not name.strip():
            return _failure("invalid_name")

        try:
            task = self.create_task(
                opportunity_id=opportunity_id,
                name=name,
                description=description,
                priority=priority if priority else None,
                estimated_duration=estimated_duration,
                dependencies=dependencies,
                metadata=metadata,
            )
        except ValueError as exc:
            return _failure(str(exc))

        attach_result = self.attach_task_to_opportunity(task.task_id, opportunity)
        if not attach_result.get("success"):
            # Creation succeeded but attachment didn't - don't leave a
            # task sitting in this store that the opportunity doesn't
            # actually know about.
            self.remove_task(task.task_id)
            return _failure(attach_result.get("error", "attachment_failed"))

        return {
            "success": True,
            "task_id": task.task_id,
            "opportunity_id": opportunity_id,
            "created": True,
            "attached": True,
        }

    # ------------------------------------------------------------------
    # Storage of an already-built task
    # ------------------------------------------------------------------
    def add_task(self, task):
        """Store `task`, but only if it is an actual `RevenueTask`
        instance that reports `is_valid()`, has a non-empty
        `task_id`, and whose `task_id` isn't already present in this
        store.

        Returns `task` unchanged on success, or `None` - and stores
        nothing - otherwise (duplicate ids never overwrite an
        existing task - the first task added under a given id always
        wins). Never raises, never modifies `task` itself."""
        if not isinstance(task, RevenueTask):
            return None
        if not task.is_valid():
            return None
        if not isinstance(task.task_id, str) or not task.task_id.strip():
            return None
        if task.task_id in self._tasks:
            return None

        self._tasks[task.task_id] = task
        return task

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_task(self, task_id):
        """The `RevenueTask` stored under `task_id`, or `None` if
        nothing is stored there (never raises for an unknown, empty,
        or non-string id). The returned task is a `copy.deepcopy`, so
        a caller mutating it can never corrupt this store's own
        internal state."""
        task = self._tasks.get(task_id)
        return copy.deepcopy(task) if task is not None else None

    def get_all(self):
        """A plain list (never None) of every stored `RevenueTask`,
        in the order each was first added. Each entry is a
        `copy.deepcopy` of the stored task, so a caller mutating an
        entry it read back can never corrupt this store's own
        internal state."""
        return [copy.deepcopy(t) for t in self._tasks.values()]

    def get_for_opportunity(self, opportunity_id):
        """A plain list (never None) of every stored `RevenueTask`
        whose `opportunity_id` exactly matches `opportunity_id`, in
        the order each was first added. Each entry is a
        `copy.deepcopy` - same "always return safe copies" convention
        as `get_all`. Returns an empty list (never raises) if
        `opportunity_id` is unknown, empty, `None`, or matches
        nothing."""
        return [
            copy.deepcopy(t)
            for t in self._tasks.values()
            if t.opportunity_id == opportunity_id
        ]

    def get_tasks_for_opportunity(self, opportunity_id):
        """A plain list (never None) of every stored `RevenueTask`
        whose `opportunity_id` exactly matches `opportunity_id`, in
        the order each was first added - functionally the same
        "opportunity_id" match and insertion-order guarantee as
        `get_for_opportunity`, kept as its own explicitly-named
        method per this stage's own naming convention. Each entry is
        a `copy.deepcopy`, so a caller mutating an entry it read back
        can never corrupt this store's own internal state, and
        mutating the returned list itself never affects this store
        (a fresh list is built on every call).

        Returns an empty list - never raises - when `opportunity_id`
        is not a non-empty string, or when it is a non-empty string
        that simply matches no stored task. Purely a read: never
        creates, attaches, or executes a task, never changes any
        task's or opportunity's status, and never performs a database
        or network operation."""
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return []
        return [
            copy.deepcopy(t)
            for t in self._tasks.values()
            if t.opportunity_id == opportunity_id
        ]

    def get_task_ids_for_opportunity(self, opportunity_id):
        """A plain list (never None) of the distinct task IDs, drawn
        from this manager's own stored `RevenueTask` objects, whose
        `opportunity_id` exactly matches `opportunity_id` - in the
        order each underlying task was first added, and with any
        repeated id kept only at its first occurrence (stored task
        ids can't actually collide per `add_task`'s own duplicate-id
        rejection, but this method stays defensive rather than
        assuming that invariant holds).

        Only "valid" ids - non-empty strings - are included; a stored
        task somehow carrying a non-string or empty `task_id` (not
        possible via this manager's own `add_task`/`create_task`, but
        not assumed impossible here either) is silently skipped
        rather than included as-is or raising.

        Returns an empty list - never raises - when `opportunity_id`
        is not a non-empty string, or when it is a non-empty string
        that simply matches no stored task. Always a fresh list, so
        mutating it never affects this store's own internal state.
        Purely a read: never modifies any task's `task_id` or any
        other field, never creates, attaches, or executes a task,
        never changes any task's or opportunity's status, and never
        performs a database or network operation."""
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return []

        task_ids = []
        seen = set()
        for task in self._tasks.values():
            if task.opportunity_id != opportunity_id:
                continue
            task_id = task.task_id
            if not isinstance(task_id, str) or not task_id.strip():
                continue
            if task_id in seen:
                continue
            seen.add(task_id)
            task_ids.append(task_id)
        return task_ids

    # ------------------------------------------------------------------
    # Status summary
    # ------------------------------------------------------------------
    def get_opportunity_task_status(self, opportunity_id):
        """A new, structured (JSON-shaped) status summary of every
        stored `RevenueTask` whose `opportunity_id` exactly matches
        `opportunity_id` - a per-status breakdown plus a few small
        derived counts/flags, built entirely from each matching
        task's own `status` (via its own `is_pending()`/`is_ready()`/
        `is_in_progress()`/`is_completed()`/`is_failed()`/
        `is_blocked()`/`is_cancelled()`/`is_active()`/`is_final()`
        helpers - never a second, hand-rolled comparison against
        `RevenueTask`'s STATUS_* constants).

        Returns:
            {"opportunity_id": opportunity_id, "task_count": <int>,
             "pending": <int>, "ready": <int>, "in_progress": <int>,
             "completed": <int>, "failed": <int>, "blocked": <int>,
             "cancelled": <int>, "active_count": <int>,
             "final_count": <int>, "all_completed": <bool>,
             "has_failed": <bool>}

        - `active_count` is exactly `RevenueTask.is_active()`'s own
          rule (READY or IN_PROGRESS), summed across matching tasks.
        - `final_count` is exactly `RevenueTask.is_final()`'s own
          rule (COMPLETED, FAILED, or CANCELLED), summed across
          matching tasks.
        - `all_completed` is True only when at least one task matched
          AND every matching task is COMPLETED (an opportunity with
          no tasks at all is not considered "all completed").
        - `has_failed` is True when at least one matching task is
          FAILED.

        For an invalid `opportunity_id` (not a non-empty string) -
        including one that simply matches no stored task - every
        counter is 0, `all_completed` and `has_failed` are both
        False, and `opportunity_id` is still echoed back exactly as
        given. Never raises.

        Always a fresh dict, independent of this store's own internal
        state. Purely a read: iterates this manager's own stored
        tasks, but never reassigns, reorders, or otherwise modifies
        any of them, never calls `transition_to()` or any other
        mutator, never changes any task's or opportunity's status,
        never modifies any task list (this manager's own storage or
        an opportunity's `task_ids`), never creates or attaches a
        task, and never executes anything."""
        empty_summary = {
            "opportunity_id": opportunity_id,
            "task_count": 0,
            "pending": 0,
            "ready": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
            "blocked": 0,
            "cancelled": 0,
            "active_count": 0,
            "final_count": 0,
            "all_completed": False,
            "has_failed": False,
        }

        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return empty_summary

        matching = [
            task for task in self._tasks.values()
            if task.opportunity_id == opportunity_id
        ]
        task_count = len(matching)
        if task_count == 0:
            return empty_summary

        pending = sum(1 for task in matching if task.is_pending())
        ready = sum(1 for task in matching if task.is_ready())
        in_progress = sum(1 for task in matching if task.is_in_progress())
        completed = sum(1 for task in matching if task.is_completed())
        failed = sum(1 for task in matching if task.is_failed())
        blocked = sum(1 for task in matching if task.is_blocked())
        cancelled = sum(1 for task in matching if task.is_cancelled())
        active_count = sum(1 for task in matching if task.is_active())
        final_count = sum(1 for task in matching if task.is_final())

        return {
            "opportunity_id": opportunity_id,
            "task_count": task_count,
            "pending": pending,
            "ready": ready,
            "in_progress": in_progress,
            "completed": completed,
            "failed": failed,
            "blocked": blocked,
            "cancelled": cancelled,
            "active_count": active_count,
            "final_count": final_count,
            "all_completed": completed == task_count,
            "has_failed": failed > 0,
        }

    # ------------------------------------------------------------------
    # Startability
    # ------------------------------------------------------------------
    def get_next_startable_task(self, opportunity_id, completed_task_ids=None):
        """The first stored `RevenueTask` belonging to `opportunity_id`
        that is currently startable, in this manager's own insertion
        order - or `None` if no such task exists. Never raises.

        A task is eligible only when, in this order:
        - its `opportunity_id` exactly matches the requested
          `opportunity_id`
        - `has_opportunity()` is True (a defensive re-check - any task
          matching the line above already satisfies this, since
          `opportunity_id` itself is required to be a non-empty
          string to get this far)
        - `is_startable()` is True (status allows starting, per that
          method's own `can_start()`/`is_ready()` check, combined with
          `has_opportunity()`)
        - `get_dependency_status(completed_task_ids)`'s own `ready`
          flag is True (every dependency is satisfied) - this method
          never re-implements that comparison itself, it only reads
          the `ready` flag straight back

        `completed_task_ids` is passed straight through to each
        task's own `get_dependency_status()`; `None` is accepted and,
        per that method's own contract, treated as an empty
        collection - so a task with unmet dependencies is correctly
        skipped even when no completed ids are supplied at all.

        Returns `None` - without raising - when `opportunity_id` is
        not a non-empty string, or when it is a non-empty string that
        matches no currently-startable task.

        The returned task, if any, is a `copy.deepcopy` - same
        "always return safe copies" convention as `get_task`/
        `get_all`/`get_for_opportunity` - so a caller mutating it can
        never corrupt this store's own internal state.

        Completely read-only: only ever calls existing read-only
        helpers (`has_opportunity()`, `is_startable()`,
        `get_dependency_status()`) on each candidate task. Never
        changes any task's status, never modifies any task's
        dependencies or any other field, never modifies this
        manager's own storage or any opportunity's `task_ids`, never
        creates or attaches a task, and never executes, plans, or
        calls a tool."""
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return None

        for task in self._tasks.values():
            if task.opportunity_id != opportunity_id:
                continue
            if not task.has_opportunity():
                continue
            if not task.is_startable():
                continue
            dependency_status = task.get_dependency_status(completed_task_ids)
            if not dependency_status["ready"]:
                continue
            return copy.deepcopy(task)

        return None

    def get_startable_tasks(self, opportunity_id, completed_task_ids=None):
        """A new list (never `None`) of every stored `RevenueTask`
        belonging to `opportunity_id` that is currently startable, in
        this manager's own insertion order - the "all matches" sibling
        of `get_next_startable_task()`'s "first match", built from
        exactly the same eligibility checks so the two never drift
        out of sync. Never raises.

        A task is included only when, in this order:
        - its `opportunity_id` exactly matches the requested
          `opportunity_id`
        - `has_opportunity()` is True (a defensive re-check - any
          task matching the line above already satisfies this, since
          `opportunity_id` itself is required to be a non-empty
          string to get this far)
        - `is_startable()` is True (status allows starting, per that
          method's own `can_start()`/`is_ready()` check, combined
          with `has_opportunity()`)
        - `get_dependency_status(completed_task_ids)`'s own `ready`
          flag is True (every dependency is satisfied) - this method
          never re-implements that comparison itself, it only reads
          the `ready` flag straight back

        `completed_task_ids` is passed straight through to each
        task's own `get_dependency_status()`; `None` is accepted and,
        per that method's own contract, treated as an empty
        collection - so a task with unmet dependencies is correctly
        excluded even when no completed ids are supplied at all.

        Returns an empty list - never raises - when `opportunity_id`
        is not a non-empty string, or when it is a non-empty string
        that matches no currently-startable task.

        Each returned task is a `copy.deepcopy` - same "always return
        safe copies" convention as `get_task`/`get_all`/
        `get_for_opportunity`/`get_next_startable_task` - and the
        list itself is always freshly built, so neither the list nor
        any entry in it is ever a reference to this manager's own
        internal storage; mutating either can never corrupt this
        store's own state.

        Completely read-only: only ever calls existing read-only
        helpers (`has_opportunity()`, `is_startable()`,
        `get_dependency_status()`) on each candidate task. Never
        changes any task's status, never modifies any task's
        dependencies or any other field, never modifies this
        manager's own storage or any opportunity's `task_ids`, never
        creates or attaches a task, and never executes, plans, calls
        a tool, or accesses the network."""
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return []

        startable_tasks = []
        for task in self._tasks.values():
            if task.opportunity_id != opportunity_id:
                continue
            if not task.has_opportunity():
                continue
            if not task.is_startable():
                continue
            dependency_status = task.get_dependency_status(completed_task_ids)
            if not dependency_status["ready"]:
                continue
            startable_tasks.append(copy.deepcopy(task))

        return startable_tasks

    # ------------------------------------------------------------------
    # Execution queue inspection
    # ------------------------------------------------------------------
    def inspect_opportunity_execution_queue(
        self, opportunity_id, completed_task_ids=None
    ):
        """A new, structured (JSON-shaped) snapshot of every stored
        `RevenueTask` belonging to `opportunity_id`, sorted into
        status-based id buckets, in this manager's own insertion
        order within each bucket. Never raises.

        Returns:
            {"opportunity_id": opportunity_id, "task_count": <int>,
             "startable_task_ids": [...], "blocked_task_ids": [...],
             "in_progress_task_ids": [...], "completed_task_ids": [...],
             "failed_task_ids": [...], "cancelled_task_ids": [...],
             "next_startable_task_id": <id or None>}

        Each matching task lands in exactly one bucket, checked in
        this order:
        - `in_progress_task_ids` when `is_in_progress()`
        - `completed_task_ids` when `is_completed()`
        - `failed_task_ids` when `is_failed()`
        - `cancelled_task_ids` when `is_cancelled()`
        - otherwise, `startable_task_ids` when the task belongs to
          the opportunity (`has_opportunity()`), `is_startable()` is
          True (status allows starting), and
          `get_dependency_status(completed_task_ids)`'s own `ready`
          flag is True - this method never re-implements that
          dependency comparison itself, it only reads the `ready`
          flag straight back
        - otherwise, `blocked_task_ids` - every remaining task that
          cannot currently start, whether because a required
          dependency isn't complete yet, its status simply isn't
          READY (e.g. PENDING or BLOCKED), or it has no valid
          opportunity reference

        `next_startable_task_id` is exactly the first entry of
        `startable_task_ids` (so `None` whenever that list is empty) -
        never independently re-derived.

        `completed_task_ids` (the parameter - ids to treat as already
        done for dependency purposes) is passed straight through to
        each task's own `get_dependency_status()`; `None` is accepted
        and, per that method's own contract, treated as an empty
        collection. This is a distinct thing from this report's own
        `completed_task_ids` key, which lists the ids of tasks whose
        actual `status` is COMPLETED.

        For an invalid `opportunity_id` (not a non-empty string) -
        including one that simply matches no stored task - every id
        list is empty, `task_count` is 0, and
        `next_startable_task_id` is `None`, with `opportunity_id`
        still echoed back exactly as given.

        Every list returned is a new list - never a reference to this
        manager's own internal storage or to any task's own
        `dependencies`/other fields - so mutating a returned list can
        never corrupt this store's state.

        Completely read-only: only ever calls existing read-only
        helpers (`is_in_progress()`, `is_completed()`, `is_failed()`,
        `is_cancelled()`, `has_opportunity()`, `is_startable()`,
        `get_dependency_status()`) on each candidate task. Never
        changes any task's status or dependencies, never modifies
        this manager's own storage or any opportunity's `task_ids`,
        never creates or attaches a task, and never executes, plans,
        or calls a tool."""
        empty_report = {
            "opportunity_id": opportunity_id,
            "task_count": 0,
            "startable_task_ids": [],
            "blocked_task_ids": [],
            "in_progress_task_ids": [],
            "completed_task_ids": [],
            "failed_task_ids": [],
            "cancelled_task_ids": [],
            "next_startable_task_id": None,
        }

        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return empty_report

        matching = [
            task for task in self._tasks.values()
            if task.opportunity_id == opportunity_id
        ]
        if not matching:
            return empty_report

        startable_task_ids = []
        blocked_task_ids = []
        in_progress_task_ids = []
        completed_task_ids_result = []
        failed_task_ids = []
        cancelled_task_ids = []

        for task in matching:
            if task.is_in_progress():
                in_progress_task_ids.append(task.task_id)
                continue
            if task.is_completed():
                completed_task_ids_result.append(task.task_id)
                continue
            if task.is_failed():
                failed_task_ids.append(task.task_id)
                continue
            if task.is_cancelled():
                cancelled_task_ids.append(task.task_id)
                continue

            dependency_status = task.get_dependency_status(completed_task_ids)
            if (
                task.has_opportunity()
                and task.is_startable()
                and dependency_status["ready"]
            ):
                startable_task_ids.append(task.task_id)
            else:
                blocked_task_ids.append(task.task_id)

        next_startable_task_id = (
            startable_task_ids[0] if startable_task_ids else None
        )

        return {
            "opportunity_id": opportunity_id,
            "task_count": len(matching),
            "startable_task_ids": startable_task_ids,
            "blocked_task_ids": blocked_task_ids,
            "in_progress_task_ids": in_progress_task_ids,
            "completed_task_ids": completed_task_ids_result,
            "failed_task_ids": failed_task_ids,
            "cancelled_task_ids": cancelled_task_ids,
            "next_startable_task_id": next_startable_task_id,
        }

    def get_execution_queue_summary(self, opportunity_id, completed_task_ids=None):
        """A new, structured (JSON-shaped) count-level summary of the
        same per-opportunity execution queue `inspect_opportunity_
        execution_queue()` already describes in full, id-list form -
        this method is a thin re-shaping of that one call's result
        into counts and a few derived booleans, never a second,
        independent pass over this manager's own stored tasks. That
        single underlying call already does exactly what
        `get_startable_tasks()` and `get_next_startable_task()` would
        each separately recompute (matching this opportunity's tasks
        against `is_startable()`/`get_dependency_status()`), so
        reusing it here - rather than calling all three and
        re-deriving the same eligibility a second and third time -
        is how this method avoids duplicating that status/dependency
        logic: `startable_count` is `len(startable_task_ids)`, and
        `next_startable_task_id` is copied straight through, exactly
        as `get_startable_tasks()` and `get_next_startable_task()`
        would themselves report for the same inputs.

        Returns:
            {"opportunity_id": opportunity_id, "task_count": <int>,
             "startable_count": <int>, "blocked_count": <int>,
             "in_progress_count": <int>, "completed_count": <int>,
             "failed_count": <int>, "cancelled_count": <int>,
             "next_startable_task_id": <id or None>,
             "has_startable_tasks": <bool>, "has_blocked_tasks": <bool>,
             "has_failed_tasks": <bool>, "all_completed": <bool>}

        - `has_startable_tasks` is `startable_count > 0`.
        - `has_blocked_tasks` is `blocked_count > 0`.
        - `has_failed_tasks` is `failed_count > 0`.
        - `all_completed` is True only when at least one task matched
          (`task_count > 0`) AND `completed_count == task_count`.

        `completed_task_ids` (ids to treat as already done for
        dependency purposes) is passed straight through to the
        underlying `inspect_opportunity_execution_queue()` call,
        which itself passes it straight through to each task's own
        `get_dependency_status()`; `None` is accepted and treated as
        an empty collection, same as that method's own contract.

        For an invalid `opportunity_id` (not a non-empty string) -
        including one that simply matches no stored task - every
        count is 0, every `has_*`/`all_completed` flag is False,
        `next_startable_task_id` is `None`, and `opportunity_id` is
        still echoed back exactly as given. Never raises.

        Always a fresh dict, independent of this store's own internal
        state - nothing returned here is a reference to this
        manager's own storage or to any task's own fields. Completely
        read-only: the one underlying call it makes is itself
        read-only, and this method performs no further inspection of
        any task, never changes any task's status or dependencies,
        never modifies this manager's own storage or any
        opportunity's `task_ids`, never creates or attaches a task,
        and never executes, plans, calls a tool, or accesses the
        network."""
        queue = self.inspect_opportunity_execution_queue(
            opportunity_id, completed_task_ids
        )

        task_count = queue["task_count"]
        startable_count = len(queue["startable_task_ids"])
        blocked_count = len(queue["blocked_task_ids"])
        in_progress_count = len(queue["in_progress_task_ids"])
        completed_count = len(queue["completed_task_ids"])
        failed_count = len(queue["failed_task_ids"])
        cancelled_count = len(queue["cancelled_task_ids"])

        return {
            "opportunity_id": queue["opportunity_id"],
            "task_count": task_count,
            "startable_count": startable_count,
            "blocked_count": blocked_count,
            "in_progress_count": in_progress_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "next_startable_task_id": queue["next_startable_task_id"],
            "has_startable_tasks": startable_count > 0,
            "has_blocked_tasks": blocked_count > 0,
            "has_failed_tasks": failed_count > 0,
            "all_completed": task_count > 0 and completed_count == task_count,
        }

    # ------------------------------------------------------------------
    # Execution preparation (read-only)
    # ------------------------------------------------------------------
    def prepare_task_execution(self, task_id, completed_task_ids=None):
        """A new, structured (JSON-shaped), read-only preparation
        report for the task stored under `task_id` - built entirely
        from `get_task()` and that task's own `get_readiness_report()`,
        `get_dependency_status()`, and `is_startable()` helpers, never
        a hand-rolled re-implementation of any of them.

        `completed_task_ids` is passed straight through to the
        underlying task's own `get_readiness_report()` and
        `get_dependency_status()` calls, both of which already treat
        `None` as an empty collection - so a `None` here is likewise
        treated as an empty collection.

        Returns:
            {"task_id": task_id, "opportunity_id": <task's own>,
             "status": <task's own>, "ready": <bool>,
             "startable": <bool>, "has_opportunity": <bool>,
             "dependency_status": <dict>, "prepared": <bool>}

        - `status` is the task's own `status`, exactly as stored.
        - `ready`, `has_opportunity`, and `startable` are the
          identically-named values from that task's own
          `get_readiness_report(completed_task_ids)` - never
          re-derived here.
        - `dependency_status` is that task's own
          `get_dependency_status(completed_task_ids)` result, passed
          through unchanged.
        - `prepared` is True only when the task exists, has a valid
          opportunity (`has_opportunity`), can start (`startable`),
          and every dependency is satisfied (`dependency_status`'s own
          `ready` flag) - i.e. only when the task's own
          `get_readiness_report()` already reports `ready: True`.

        If no task is stored under `task_id`, returns a safe,
        structured result instead of raising:
            {"task_id": task_id, "opportunity_id": None,
             "status": None, "ready": False, "startable": False,
             "has_opportunity": False,
             "dependency_status": None, "prepared": False,
             "error": "task_not_found"}

        Completely read-only: `get_task()` already returns an
        independent `copy.deepcopy`, and every value here comes from
        that copy's own read-only helper methods - this method never
        calls `transition_to()` or any other mutator, never changes
        any task's or opportunity's status, never modifies
        dependencies, never attaches, creates, or removes a task,
        never modifies this manager's own storage, and never
        executes, plans, calls a tool, or accesses the network or an
        external AI service. Nothing is ever executed by this
        method - it only reports whether the task looks ready to be
        executed by some later, separate step."""
        task = self.get_task(task_id)
        if task is None:
            return {
                "task_id": task_id,
                "opportunity_id": None,
                "status": None,
                "ready": False,
                "startable": False,
                "has_opportunity": False,
                "dependency_status": None,
                "prepared": False,
                "error": "task_not_found",
            }

        readiness = task.get_readiness_report(completed_task_ids)
        dependency_status = task.get_dependency_status(completed_task_ids)

        return {
            "task_id": task.task_id,
            "opportunity_id": task.opportunity_id,
            "status": task.status,
            "ready": readiness["ready"],
            "startable": readiness["startable"],
            "has_opportunity": readiness["has_opportunity"],
            "dependency_status": dependency_status,
            "prepared": readiness["ready"],
        }

    # ------------------------------------------------------------------
    # Controlled start (READY -> IN_PROGRESS only)
    # ------------------------------------------------------------------
    def start_task(self, task_id, completed_task_ids=None):
        """Start the task stored under `task_id`, moving it from
        STATUS_READY to STATUS_IN_PROGRESS - and only that one
        transition - after re-checking its readiness via
        `prepare_task_execution()` (never a hand-rolled duplicate of
        that readiness logic). `completed_task_ids` is passed straight
        through to `prepare_task_execution()`, which itself treats
        `None` as an empty collection.

        Always returns a new, structured (JSON-shaped) result dict.
        Never raises.

        On success:
            {"success": True, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": "READY", "status": "IN_PROGRESS",
             "started": True}

        On failure - the task is left completely unchanged - one of:
            {"success": False, "task_id": task_id,
             "opportunity_id": None, "previous_status": None,
             "status": None, "started": False,
             "error": "task_not_found"}
        when no task is stored under `task_id`, or:
            {"success": False, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": <task's own current status>,
             "status": <task's own current status, unchanged>,
             "started": False, "error": <reason>}
        when the task exists but preparation did not report
        `prepared: True`, with `error` one of:
        - "no_opportunity" - the task has no valid opportunity
        - "not_ready" - the task's status is not exactly READY (e.g.
          PENDING, BLOCKED, COMPLETED, FAILED, or CANCELLED - none of
          these may become IN_PROGRESS directly)
        - "dependencies_not_satisfied" - the task is READY and has a
          valid opportunity, but at least one dependency (per
          `completed_task_ids`) is not yet completed
        - "transition_rejected" - kept as a defensive safeguard for
          the otherwise-unreachable case where `prepare_task_execution`
          reports `prepared: True` but the underlying
          `transition_to(STATUS_IN_PROGRESS)` call still declines the
          transition

        The one and only mutation this method ever performs is calling
        the stored task's own `transition_to(STATUS_IN_PROGRESS)` -
        reusing that existing transition system (and, through it, the
        same fixed READY -> IN_PROGRESS allowance already enforced by
        `is_valid_transition()`) rather than duplicating any status- or
        transition-validation logic, and rather than ever setting
        `status` directly. No other field on the task changes
        (opportunity_id, dependencies, priority, metadata, etc.), this
        manager's own storage is not otherwise modified, and no other
        task is touched. This method never executes the task, never
        calls a capability or tool, never creates a plan, never
        creates or attaches another task, never modifies the
        opportunity, never retries a failed task, and never accesses
        the network or an external AI service."""
        if task_id not in self._tasks:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "started": False,
                "error": "task_not_found",
            }

        prep = self.prepare_task_execution(task_id, completed_task_ids)

        if not prep["prepared"]:
            if not prep["has_opportunity"]:
                error = "no_opportunity"
            elif not prep["startable"]:
                error = "not_ready"
            else:
                error = "dependencies_not_satisfied"
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": prep["opportunity_id"],
                "previous_status": prep["status"],
                "status": prep["status"],
                "started": False,
                "error": error,
            }

        stored_task = self._tasks[task_id]
        previous_status = stored_task.status

        if not stored_task.transition_to(STATUS_IN_PROGRESS):
            # Defensive safeguard: prepare_task_execution() reporting
            # prepared: True already implies READY -> IN_PROGRESS is
            # an allowed transition, so this branch should not be
            # reachable in practice.
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": stored_task.opportunity_id,
                "previous_status": previous_status,
                "status": stored_task.status,
                "started": False,
                "error": "transition_rejected",
            }

        return {
            "success": True,
            "task_id": task_id,
            "opportunity_id": stored_task.opportunity_id,
            "previous_status": previous_status,
            "status": stored_task.status,
            "started": True,
        }

    # ------------------------------------------------------------------
    # Controlled completion (IN_PROGRESS -> COMPLETED only)
    # ------------------------------------------------------------------
    def complete_task(self, task_id, output=None, metadata=None):
        """Complete the task stored under `task_id`, moving it from
        STATUS_IN_PROGRESS to STATUS_COMPLETED - and only that one
        transition - using the task's own existing transition system
        (`transition_to()` / `is_valid_transition()`), never a
        hand-rolled duplicate of that transition logic.

        `task_id` is looked up via `get_task()` to confirm the task
        exists and read its current status. `output` and `metadata`
        are treated purely as opaque, structured data describing the
        result of work done elsewhere: they are never executed,
        evaluated, or interpreted in any way by this method.

        The existing `RevenueTask` model (financial/revenue_task.py)
        has no dedicated field or setter for storing arbitrary
        completion output, and no supported way to attach extra
        metadata onto a task after construction (its own `metadata`
        field is set only at construction time - see
        `RevenueTask.__init__`). Rather than reach into the task and
        mutate a field with no dedicated, validated setter (which
        `set_status`/`change_status`/`transition_to`/
        `set_opportunity_id` all are, but no such method exists for
        this), `output` and `metadata` are simply echoed back
        unchanged in the returned result instead of being stored on
        the `RevenueTask` itself - so the model is never modified
        beyond the one status transition, and a caller who needs to
        keep the output/metadata is responsible for persisting it
        wherever this stage's own broader system already does that
        (e.g. `metadata/memory_system.py`), not on this in-memory
        record.

        Always returns a new, structured (JSON-shaped) result dict.
        Never raises.

        On success:
            {"success": True, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": "IN_PROGRESS", "status": "COMPLETED",
             "completed": True, "output": output,
             "metadata": metadata}

        On failure - the task is left completely unchanged:
            {"success": False, "task_id": task_id,
             "opportunity_id": None, "previous_status": None,
             "status": None, "completed": False,
             "error": "task_not_found"}
        when no task is stored under `task_id`, or:
            {"success": False, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": <task's own current status>,
             "status": <task's own current status, unchanged>,
             "completed": False, "error": "not_in_progress"}
        when the task exists but its current status is not exactly
        IN_PROGRESS - PENDING, READY, BLOCKED, FAILED, and CANCELLED
        tasks are all rejected this way and left untouched (none of
        these may become COMPLETED directly; a READY task must first
        be started via `start_task()`), or:
            {"success": False, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": "IN_PROGRESS",
             "status": "IN_PROGRESS", "completed": False,
             "error": "transition_rejected"}
        kept as a defensive safeguard for the otherwise-unreachable
        case where the task's own `transition_to(STATUS_COMPLETED)`
        call declines the transition despite the status already being
        IN_PROGRESS.

        The one and only mutation this method ever performs is
        calling the stored task's own `transition_to(STATUS_COMPLETED)`
        - reusing the existing transition table rather than ever
        setting `status` directly. No other field on the task changes
        (opportunity_id, dependencies, priority, metadata, etc.), this
        manager's own storage is not otherwise modified, and no other
        task is touched. This method never executes a capability or
        tool, never starts or creates another task, never creates a
        plan, never modifies the opportunity's status, never retries a
        task, and never accesses the network or an external AI
        service."""
        task = self.get_task(task_id)
        if task is None:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "completed": False,
                "error": "task_not_found",
            }

        if task.status != STATUS_IN_PROGRESS:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": task.opportunity_id,
                "previous_status": task.status,
                "status": task.status,
                "completed": False,
                "error": "not_in_progress",
            }

        stored_task = self._tasks[task_id]
        previous_status = stored_task.status

        if not stored_task.transition_to(STATUS_COMPLETED):
            # Defensive safeguard: IN_PROGRESS -> COMPLETED is an
            # allowed transition per _ALLOWED_TRANSITIONS whenever the
            # status is already confirmed IN_PROGRESS above, so this
            # branch should not be reachable in practice.
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": stored_task.opportunity_id,
                "previous_status": previous_status,
                "status": stored_task.status,
                "completed": False,
                "error": "transition_rejected",
            }

        return {
            "success": True,
            "task_id": task_id,
            "opportunity_id": stored_task.opportunity_id,
            "previous_status": previous_status,
            "status": stored_task.status,
            "completed": True,
            "output": output,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Controlled failure (IN_PROGRESS -> FAILED only)
    # ------------------------------------------------------------------
    def fail_task(self, task_id, error=None, metadata=None):
        """Mark the task stored under `task_id` as failed, moving it
        from STATUS_IN_PROGRESS to STATUS_FAILED - and only that one
        transition - using the task's own existing transition system
        (`transition_to()` / `is_valid_transition()`), never a
        hand-rolled duplicate of that transition logic.

        `task_id` is looked up via `get_task()` to confirm the task
        exists and read its current status. `error` and `metadata` are
        treated purely as opaque, structured data describing why the
        task failed: they are never executed, evaluated, or
        interpreted in any way by this method - same "structured data
        only" convention as `complete_task()`'s own `output`/
        `metadata`.

        Like `complete_task()`, the existing `RevenueTask` model has
        no dedicated field or setter for storing arbitrary failure
        information, and no supported way to attach extra metadata
        onto a task after construction. Rather than reach into the
        task and mutate a field with no dedicated, validated setter,
        `error` and `metadata` are simply echoed back in the returned
        result instead of being stored on the `RevenueTask` itself -
        so the model is never modified beyond the one status
        transition.

        If `error` is `None`, a safe, structured placeholder string
        (`"No error detail provided."`) is used in its place in the
        returned result, so a successful `failed: True` result always
        carries some error value rather than a bare `None`.

        Always returns a new, structured (JSON-shaped) result dict.
        Never raises.

        On success:
            {"success": True, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": "IN_PROGRESS", "status": "FAILED",
             "failed": True,
             "error": error if error is not None else
                      "No error detail provided.",
             "metadata": metadata}

        On failure - the task is left completely unchanged:
            {"success": False, "task_id": task_id,
             "opportunity_id": None, "previous_status": None,
             "status": None, "failed": False,
             "error": "task_not_found"}
        when no task is stored under `task_id`, or:
            {"success": False, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": <task's own current status>,
             "status": <task's own current status, unchanged>,
             "failed": False, "error": "not_in_progress"}
        when the task exists but its current status is not exactly
        IN_PROGRESS - PENDING, READY, BLOCKED, COMPLETED, and
        CANCELLED tasks are all rejected this way and left untouched
        (none of these may become FAILED directly), or:
            {"success": False, "task_id": task_id,
             "opportunity_id": <task's own>,
             "previous_status": "IN_PROGRESS",
             "status": "IN_PROGRESS", "failed": False,
             "error": "transition_rejected"}
        kept as a defensive safeguard for the otherwise-unreachable
        case where the task's own `transition_to(STATUS_FAILED)` call
        declines the transition despite the status already being
        IN_PROGRESS.

        The one and only mutation this method ever performs is
        calling the stored task's own `transition_to(STATUS_FAILED)` -
        reusing the existing transition table rather than ever setting
        `status` directly. No other field on the task changes
        (opportunity_id, dependencies, priority, metadata, etc.), this
        manager's own storage is not otherwise modified, and no other
        task is touched. This method never retries or restarts the
        task, never executes another task or capability, never calls a
        tool, never creates another task or a plan, never modifies the
        opportunity's status, and never accesses the network or an
        external AI service."""
        task = self.get_task(task_id)
        if task is None:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "failed": False,
                "error": "task_not_found",
            }

        if task.status != STATUS_IN_PROGRESS:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": task.opportunity_id,
                "previous_status": task.status,
                "status": task.status,
                "failed": False,
                "error": "not_in_progress",
            }

        stored_task = self._tasks[task_id]
        previous_status = stored_task.status

        if not stored_task.transition_to(STATUS_FAILED):
            # Defensive safeguard: IN_PROGRESS -> FAILED is an allowed
            # transition per _ALLOWED_TRANSITIONS whenever the status
            # is already confirmed IN_PROGRESS above, so this branch
            # should not be reachable in practice.
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": stored_task.opportunity_id,
                "previous_status": previous_status,
                "status": stored_task.status,
                "failed": False,
                "error": "transition_rejected",
            }

        return {
            "success": True,
            "task_id": task_id,
            "opportunity_id": stored_task.opportunity_id,
            "previous_status": previous_status,
            "status": stored_task.status,
            "failed": True,
            "error": error if error is not None else _DEFAULT_FAILURE_ERROR,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Result recording (attaches a RevenueTaskResult - status untouched)
    # ------------------------------------------------------------------
    def record_task_result(self, task_id, status, output=None, error=None, metadata=None):
        """Build a `RevenueTaskResult` (financial/revenue_task_result.py)
        describing an already-finished outcome for the task stored
        under `task_id`, and attach it to that task via its own
        `set_result()` (financial/revenue_task.py) - never a
        hand-rolled duplicate of that attachment/validation logic.

        `task_id` is looked up via `get_task()` to confirm the task
        exists, matching the same "look up via `get_task()`" step
        `complete_task()`/`fail_task()` already use. `status` must be
        exactly `RevenueTaskResult.STATUS_COMPLETED` or
        `RevenueTaskResult.STATUS_FAILED` - the same closed
        `RevenueTaskResult.ALL_STATUSES` vocabulary that model's own
        `is_valid()` already enforces, never a hand-rolled second
        vocabulary. `output`, `error`, and `metadata` are treated
        purely as opaque, structured data - same "structured data
        only, never executed, evaluated, or interpreted" convention
        `complete_task()`/`fail_task()` already apply to their own
        `output`/`error`/`metadata` parameters; here that safety check
        is enforced by the constructed `RevenueTaskResult`'s own
        `is_valid()` rather than a second, duplicated check.

        This method only *records* a result - unlike `complete_task()`
        and `fail_task()`, it never calls `transition_to()` and never
        changes the task's `status` field in any way, regardless of
        the `status` given here (a task may be recorded as COMPLETED
        or FAILED while its own status remains PENDING, READY,
        IN_PROGRESS, BLOCKED, or CANCELLED - this method does not
        care, check, or change it). It never calls `complete_task()`
        or `fail_task()` itself, and this stage does not call it from
        either of those methods - recording a result today is always
        a separate, explicit step from transitioning a task's status.

        A task may only ever be recorded once: if the task already has
        a result attached (per its own `has_result()`), this method
        rejects the call and leaves the existing result completely
        untouched rather than silently overwriting it - `set_result()`
        itself does not enforce this on its own (financial/revenue_task.py's
        own `set_result()` intentionally allows a caller who wants
        replacement to attach a new result directly), so this manager
        applies the "no silent overwrite" rule itself, at this layer,
        before ever calling `set_result()`.

        Always returns a new, structured (JSON-shaped) result dict.
        Never raises.

        On success:
            {"success": True, "result_id": <newly generated>,
             "task_id": <task's own>, "opportunity_id": <task's own>,
             "status": status, "recorded": True}

        On failure - the task (and any result already attached to it)
        is left completely unchanged:
            {"success": False, "result_id": None, "task_id": task_id,
             "opportunity_id": None, "status": status,
             "recorded": False, "error": "task_not_found"}
        when no task is stored under `task_id`, or:
            {"success": False, "result_id": None, "task_id": task_id,
             "opportunity_id": <task's own>, "status": status,
             "recorded": False, "error": "invalid_status"}
        when `status` is not exactly STATUS_COMPLETED or STATUS_FAILED
        (see `RevenueTaskResult.ALL_STATUSES`), or:
            {"success": False, "result_id": None, "task_id": task_id,
             "opportunity_id": <task's own>, "status": status,
             "recorded": False, "error": "result_already_recorded"}
        when the task already has a valid result attached, or:
            {"success": False, "result_id": None, "task_id": task_id,
             "opportunity_id": <task's own>, "status": status,
             "recorded": False, "error": "invalid_result_data"}
        when `output`, `error`, or `metadata` is not safe, structured
        data (per `RevenueTaskResult.is_valid()` - e.g. a function,
        class instance, or other object that could carry behavior), or:
            {"success": False, "result_id": None, "task_id": task_id,
             "opportunity_id": <task's own>, "status": status,
             "recorded": False, "error": "attachment_rejected"}
        kept as a defensive safeguard for the otherwise-unreachable
        case where the constructed `RevenueTaskResult`'s own
        `task_id`/`opportunity_id` fail the stored task's own
        `set_result()` cross-check despite being built from that same
        task's own `task_id`/`opportunity_id` just above.

        The one and only mutation this method ever performs is calling
        the stored task's own `set_result()` with a freshly built
        `RevenueTaskResult` - reusing that existing attachment/
        validation logic rather than ever setting the task's `result`
        field directly. No other field on the task changes (status,
        opportunity_id, dependencies, priority, metadata, etc.), this
        manager's own storage is not otherwise modified, and no other
        task is touched. This method never executes anything, never
        calls a capability or tool, never retries or restarts
        anything, never persists to a database, and never accesses the
        network or an external AI service."""
        task = self.get_task(task_id)
        if task is None:
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": None,
                "status": status,
                "recorded": False,
                "error": "task_not_found",
            }

        if status not in _RESULT_ALL_STATUSES:
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": task.opportunity_id,
                "status": status,
                "recorded": False,
                "error": "invalid_status",
            }

        if task.has_result():
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": task.opportunity_id,
                "status": status,
                "recorded": False,
                "error": "result_already_recorded",
            }

        result = RevenueTaskResult(
            result_id=_generate_result_id(),
            task_id=task.task_id,
            opportunity_id=task.opportunity_id,
            status=status,
            output=output,
            error=error,
            metadata=metadata,
        )

        if not result.is_valid():
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": task.opportunity_id,
                "status": status,
                "recorded": False,
                "error": "invalid_result_data",
            }

        stored_task = self._tasks[task_id]

        # Re-check on the actual stored task, not just the `get_task()`
        # copy above, in case a result was already attached to it
        # (defensive - nothing between the earlier check and here can
        # actually change stored_task in this single-threaded manager,
        # but this mirrors the "never trust a snapshot for the
        # mutation itself" pattern complete_task()/fail_task() already
        # follow with `previous_status`).
        if stored_task.has_result():
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": stored_task.opportunity_id,
                "status": status,
                "recorded": False,
                "error": "result_already_recorded",
            }

        if not stored_task.set_result(result):
            # Defensive safeguard: `result` was built from
            # stored_task's own task_id/opportunity_id just above, so
            # set_result()'s own task_id/opportunity_id cross-check
            # should always pass - this branch should not be
            # reachable in practice.
            return {
                "success": False,
                "result_id": None,
                "task_id": task_id,
                "opportunity_id": stored_task.opportunity_id,
                "status": status,
                "recorded": False,
                "error": "attachment_rejected",
            }

        return {
            "success": True,
            "result_id": result.result_id,
            "task_id": stored_task.task_id,
            "opportunity_id": stored_task.opportunity_id,
            "status": status,
            "recorded": True,
        }

    # ------------------------------------------------------------------
    # Result retrieval (read-only)
    # ------------------------------------------------------------------
    def get_task_result(self, task_id):
        """The `RevenueTaskResult` (financial/revenue_task_result.py)
        currently attached to the task stored under `task_id`, or
        `None` when there is no task stored under `task_id`, or the
        task exists but has no result attached.

        Built entirely on top of `get_task()` and that task's own
        `get_result()` (financial/revenue_task.py) - never a
        hand-rolled duplicate of either lookup, and never re-deriving
        or re-validating the result itself. `get_task()` already
        returns a `copy.deepcopy` of the stored task, so the
        `RevenueTaskResult` returned here lives on that same safe
        copy - not the manager's own internal `RevenueTask` instance -
        and mutating it can never affect this manager's stored task or
        its attached result.

        Completely read-only: never modifies the task, the attached
        result, or this manager's own storage, never changes the
        task's status, never creates a result, and never executes,
        retries, or dispatches anything to a tool, capability, or
        external service."""
        task = self.get_task(task_id)
        if task is None:
            return None
        return task.get_result()

    def has_task_result(self, task_id):
        """True only when a task is stored under `task_id` AND that
        task's own `has_result()` (financial/revenue_task.py) reports
        `True` - i.e. a valid `RevenueTaskResult` is currently
        attached. `False` for a missing, empty, non-string, or
        otherwise invalid `task_id`, and `False` for a task that
        exists but has no result attached.

        Built entirely on top of `get_task()` and that task's own
        `has_result()` - never a hand-rolled duplicate of either
        lookup or of `RevenueTaskResult.is_valid()`'s own validation
        logic.

        Completely read-only: never modifies the task, any attached
        result, or this manager's own storage, never changes the
        task's status, never creates a result, and never executes,
        retries, or dispatches anything to a tool, capability, or
        external service."""
        task = self.get_task(task_id)
        if task is None:
            return False
        return task.has_result()

    # ------------------------------------------------------------------
    # Attachment
    # ------------------------------------------------------------------
    def attach_task_to_opportunity(self, task_id, opportunity):
        """Attach the task stored under `task_id` to `opportunity` by
        delegating to that opportunity's own `attach_task()`
        (financial/revenue_opportunity.py) - this method never
        duplicates that method's attachment/validation logic, it only
        looks up the stored task and hands it over.

        Always returns a new, structured (JSON-shaped) result dict
        with at least `success`, `task_id`, `opportunity_id`,
        `attached`, and (on failure) `error`. Never raises.

        Fails safely, without attaching anything, when:
        - `opportunity` is not an actual `RevenueOpportunity`
          instance or fails its own `is_valid()` check
          (error: "invalid_opportunity")
        - `task_id` is not a non-empty string
          (error: "invalid_task_id")
        - no task is stored under `task_id` in this manager
          (error: "task_not_found")
        - the stored task's `opportunity_id` does not exactly match
          `opportunity.opportunity_id`
          (error: "opportunity_mismatch")
        - `opportunity.attach_task()` itself declines the task for
          any other reason (error: "attachment_rejected") - kept as a
          defensive safeguard rather than assumed unreachable, since
          every case already checked above is also checked by
          `attach_task()`'s own `can_accept_task()`

        When the task is already attached (per `opportunity.has_task()`),
        nothing is attached again (no duplicate is created) and a
        successful, idempotent result is returned with an additional
        `already_attached: True` field.

        On a genuine new attachment, `opportunity.attach_task()` is
        called and its `task_ids` list gains the task's id - no other
        field on `opportunity` changes, no field on the stored task
        changes, no task or opportunity status changes, nothing is
        executed, and no tool, network, or external AI service is
        used."""
        opportunity_id = getattr(opportunity, "opportunity_id", None)

        if not isinstance(opportunity, RevenueOpportunity) or not opportunity.is_valid():
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": False,
                "error": "invalid_opportunity",
            }

        if not isinstance(task_id, str) or not task_id.strip():
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": False,
                "error": "invalid_task_id",
            }

        task = self._tasks.get(task_id)
        if task is None:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": False,
                "error": "task_not_found",
            }

        if task.opportunity_id != opportunity.opportunity_id:
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": False,
                "error": "opportunity_mismatch",
            }

        if opportunity.has_task(task_id):
            return {
                "success": True,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": True,
                "already_attached": True,
            }

        if not opportunity.attach_task(task):
            return {
                "success": False,
                "task_id": task_id,
                "opportunity_id": opportunity_id,
                "attached": False,
                "error": "attachment_rejected",
            }

        return {
            "success": True,
            "task_id": task_id,
            "opportunity_id": opportunity_id,
            "attached": True,
        }

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------
    def remove_task(self, task_id):
        """Remove the task stored under `task_id` and return a
        `copy.deepcopy` of it, or `None` - and change nothing - if no
        such task exists. Never raises."""
        task = self._tasks.pop(task_id, None)
        return copy.deepcopy(task) if task is not None else None

    def clear(self):
        """Remove every task currently in this store. Nothing to
        return; always succeeds, even if the store was already
        empty."""
        self._tasks.clear()

    def __len__(self):
        return len(self._tasks)

    def __repr__(self):
        return f"RevenueTaskManager({len(self._tasks)} task(s))"
