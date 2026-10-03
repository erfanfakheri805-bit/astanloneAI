"""
Revenue Task Result History
=============================
`RevenueTaskResultHistory` is a small, in-memory record of every
`RevenueTaskResult` (financial/revenue_task_result.py) that has been
handed to it so far:

    RevenueTaskManager.record_task_result(...) -> RevenueTaskResult
        -> RevenueTaskResultHistory.record(...)  (this module: stores
           that already-built result)

This stage only stores and retrieves `RevenueTaskResult` objects it is
given - it does not decide *whether* a task finished successfully,
does not build a `RevenueTaskResult` itself, does not call
`RevenueTaskManager.record_task_result()` or any other method, does
not touch a `RevenueTask`'s `status` or its own attached `result`
(`RevenueTask.set_result()`/`get_result()`/`has_result()`/
`clear_result()` - financial/revenue_task.py - are untouched by this
module), and does not touch the filesystem, a database, the shell,
the network, or any external AI service. History here means "what was
already recorded elsewhere", never "what should happen next" -
nothing here schedules, retries, or triggers a future execution,
completion, or failure.

Deliberately independent from persistent storage (matches the
in-memory-only convention `execution/execution_history.py` and
`planning/proposal_history.py` already follow for their own
histories): this history lives only in this process's RAM and is
cleared on process restart, or on an explicit `clear()` call. A future
stage may back this with real (e.g. SQLite) persistence; that is
explicitly out of scope here.

Same "store the exact object, never a copy, but hand back only safe
copies" convention `financial/revenue_task_manager.py`'s own
`add_task`/`get_task` pair already follows: `record()` stores the
exact `RevenueTaskResult` instance it is given (never copying or
mutating it), while every retrieval method
(`get_all`/`get_for_task`/`get_for_opportunity`/`get_latest_for_task`)
returns a fresh `copy.deepcopy` of each matching result, so a caller
mutating something it read back from this history can never corrupt
this history's own internal state (or vice versa).

Only an actual `RevenueTaskResult` that also reports `is_valid()`
(financial/revenue_task_result.py - which itself already requires a
non-empty `result_id`, among other checks) is ever accepted - same
"reject invalid input safely, never raise" convention
`RevenueTaskManager.add_task` already follows for `RevenueTask`.
Duplicate protection follows that same convention: a `result_id`
already on file is rejected outright (this history never silently
overwrites, or silently keeps, a second object under the same id -
`record()` simply declines the second call and returns `None`,
leaving the first-recorded result and this history's insertion order
completely unchanged).
"""

import copy

from .revenue_task_result import RevenueTaskResult


class RevenueTaskResultHistory:
    """Not thread-safe (matches the rest of this project - see
    ExecutionHistory/ProposalHistory/RevenueTaskManager's own notes).
    Safe to use one instance per Core / per conversation session, or
    to share one across several callers that should log to the same
    history.

    Storage is two small, always-in-sync structures - a dict keyed by
    `result_id` for O(1) lookup/duplicate-detection, and a list of
    `result_id`s in the order `record()` first accepted them, for
    order-preserving iteration - same "id-keyed dict plus an ordered
    list of ids" shape `execution/execution_history.py`'s own
    `ExecutionHistory` uses.
    """

    def __init__(self):
        self._by_result_id = {}
        self._order = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, result):
        """Store `result` (a `RevenueTaskResult`) in this history and
        return it unchanged on success, or `None` - storing nothing -
        on rejection. Never raises, and never modifies `result` in any
        way (this history's own state is the only thing that changes
        on a successful call).

        Rejected (returns `None`, leaves this history's own state
        completely unchanged) when:
        - `result` is not an actual `RevenueTaskResult` instance
        - `result.result_id` is not a non-empty string
        - `result` fails its own `is_valid()` check (financial/
          revenue_task_result.py - e.g. an unsupported `status`, or
          unsafe/unstructured `output`/`error`/`metadata`)
        - `result.result_id` is already recorded in this history (a
          duplicate id never overwrites, or is silently dropped in
          favor of, the already-stored result under that same id -
          the first result recorded under a given id always wins)

        On success, `result` is appended to this history's own
        insertion-order record - it is never inserted anywhere else,
        never re-ordered, and never recorded a second time under the
        same id.
        """
        if not isinstance(result, RevenueTaskResult):
            return None
        if not isinstance(result.result_id, str) or not result.result_id.strip():
            return None
        if not result.is_valid():
            return None
        if result.result_id in self._by_result_id:
            return None

        self._by_result_id[result.result_id] = result
        self._order.append(result.result_id)
        return result

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_all(self):
        """Every recorded `RevenueTaskResult`, oldest-first (insertion
        order), as fresh `copy.deepcopy` copies - a new list on every
        call, never a reference to this history's own internal
        collection, so mutating the returned list (or any entry in
        it) can never affect this history's own stored state."""
        return [copy.deepcopy(self._by_result_id[result_id]) for result_id in self._order]

    def get_for_task(self, task_id):
        """Every recorded `RevenueTaskResult` whose `task_id` exactly
        matches `task_id`, oldest-first (insertion order), as fresh
        `copy.deepcopy` copies. Returns an empty list - never raises -
        when `task_id` is unknown, empty, `None`, or otherwise matches
        nothing, same "read-only reporting, safe default" convention
        `RevenueTaskManager.get_for_opportunity` already follows."""
        return [
            copy.deepcopy(self._by_result_id[result_id])
            for result_id in self._order
            if self._by_result_id[result_id].task_id == task_id
        ]

    def get_for_opportunity(self, opportunity_id):
        """Every recorded `RevenueTaskResult` whose `opportunity_id`
        exactly matches `opportunity_id`, oldest-first (insertion
        order), as fresh `copy.deepcopy` copies. Returns an empty list
        - never raises - when `opportunity_id` is unknown, empty,
        `None`, or otherwise matches nothing."""
        return [
            copy.deepcopy(self._by_result_id[result_id])
            for result_id in self._order
            if self._by_result_id[result_id].opportunity_id == opportunity_id
        ]

    def get_latest_for_task(self, task_id):
        """The most recently recorded `RevenueTaskResult` whose
        `task_id` exactly matches `task_id`, as a fresh
        `copy.deepcopy` copy, or `None` if no such result is recorded
        (including an unknown `task_id`, or an otherwise-empty
        history) - never raises. "Most recently recorded" means last
        in this history's own insertion order (the same order
        `record()` accepted results in), not a re-sort by each
        result's own `created_at` field."""
        matches = self.get_for_task(task_id)
        return matches[-1] if matches else None

    def count_for_task(self, task_id):
        """The number of recorded `RevenueTaskResult`s whose `task_id`
        exactly matches `task_id`, as a plain `int` - the same
        results `get_for_task` would return, but as a count rather
        than the results themselves, so a caller that only wants "how
        many" never has to copy/discard result data it doesn't need.
        An unknown or never-used `task_id` (including an otherwise-
        empty history) returns `0` rather than raising."""
        return sum(
            1
            for result_id in self._order
            if self._by_result_id[result_id].task_id == task_id
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def get_task_success_rate(self, task_id):
        """A read-only success-rate report for `task_id`, as a plain
        `dict`:

            {
                "task_id": task_id,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
            }

        `completed_count`/`failed_count` are computed from each
        recorded result's own `is_successful()`/`is_failed()` check
        (financial/revenue_task_result.py) - this method never
        compares against `STATUS_COMPLETED`/`STATUS_FAILED` itself,
        so it can never drift from that module's own status
        definitions. `success_rate` is `completed_count /
        total_results`, or `0.0` when there are no recorded results
        (avoiding a division by zero) - always a plain `float` in the
        inclusive range 0.0-1.0.

        An unknown, empty, or `None` `task_id` (including on an
        otherwise-empty history) safely returns a zero-result report
        rather than raising - same "read-only reporting, safe
        default" convention `get_for_task`/`count_for_task` already
        follow.

        Purely a read: only iterates this history's own already-
        recorded results (via `get_for_task`, which already returns
        fresh `copy.deepcopy` copies) and returns a freshly built
        dict. Never records, edits, or removes a result, never
        touches a `RevenueTask`, `RevenueOpportunity`, or any manager
        state, and never schedules, retries, or triggers any future
        execution."""
        results = self.get_for_task(task_id)
        total_results = len(results)

        if total_results == 0:
            return {
                "task_id": task_id,
                "total_results": 0,
                "completed_count": 0,
                "failed_count": 0,
                "success_rate": 0.0,
            }

        completed_count = sum(1 for result in results if result.is_successful())
        failed_count = sum(1 for result in results if result.is_failed())

        return {
            "task_id": task_id,
            "total_results": total_results,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "success_rate": float(completed_count) / total_results,
        }

    def get_opportunity_success_rate(self, opportunity_id):
        """A read-only success-rate report for `opportunity_id`, as a
        plain `dict`:

            {
                "opportunity_id": opportunity_id,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
            }

        Same shape and rules as `get_task_success_rate`, but scoped by
        `opportunity_id` (via `get_for_opportunity`) rather than
        `task_id` - this deliberately covers every recorded result
        for the opportunity across all of its tasks, not just one
        task's results. `completed_count`/`failed_count` are computed
        from each recorded result's own `is_successful()`/
        `is_failed()` check (financial/revenue_task_result.py) - this
        method never compares against `STATUS_COMPLETED`/
        `STATUS_FAILED` itself, so it can never drift from that
        module's own status definitions, and it never looks at a
        `RevenueTask`'s own `status` - only already-recorded
        `RevenueTaskResult` objects count toward this report.
        `success_rate` is `completed_count / total_results`, or `0.0`
        when there are no recorded results (avoiding a division by
        zero) - always a plain `float` in the inclusive range
        0.0-1.0.

        An unknown, empty, or `None` `opportunity_id` (including on
        an otherwise-empty history) safely returns a zero-result
        report rather than raising - same "read-only reporting, safe
        default" convention `get_for_opportunity` already follows.

        Purely a read: only iterates this history's own already-
        recorded results (via `get_for_opportunity`, which already
        returns fresh `copy.deepcopy` copies) and returns a freshly
        built dict. Never records, edits, or removes a result, never
        touches a `RevenueTask`, `RevenueOpportunity`, or any manager
        state, and never schedules, retries, or triggers any future
        execution."""
        results = self.get_for_opportunity(opportunity_id)
        total_results = len(results)

        if total_results == 0:
            return {
                "opportunity_id": opportunity_id,
                "total_results": 0,
                "completed_count": 0,
                "failed_count": 0,
                "success_rate": 0.0,
            }

        completed_count = sum(1 for result in results if result.is_successful())
        failed_count = sum(1 for result in results if result.is_failed())

        return {
            "opportunity_id": opportunity_id,
            "total_results": total_results,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "success_rate": float(completed_count) / total_results,
        }

    def get_task_result_summary(self, task_id):
        """A read-only combined summary for `task_id`, as a plain
        `dict`:

            {
                "task_id": task_id,
                "has_results": <bool>,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "latest_result_id": <str or None>,
                "latest_status": <str or None>,
            }

        Built from `get_task_success_rate(task_id)` (for
        `total_results`/`completed_count`/`failed_count`/
        `success_rate` - see that method for the exact counting and
        zero-division rules, which this method reuses unchanged) plus
        `get_latest_for_task(task_id)` (for `latest_result_id`/
        `latest_status`, taken from that same "last in insertion
        order" result - not a re-sort by `created_at`). `has_results`
        is `True` exactly when `total_results > 0`.

        An unknown, empty, or `None` `task_id` (including on an
        otherwise-empty history) safely returns a zero-result summary
        - `has_results=False`, all counts `0`, `success_rate=0.0`,
        `latest_result_id=None`, `latest_status=None` - rather than
        raising, same "read-only reporting, safe default" convention
        `get_task_success_rate`/`get_latest_for_task` already follow.

        Purely a read: only calls this history's own existing
        read-only methods and returns a freshly built dict. Never
        records, edits, or removes a result, never touches a
        `RevenueTask`, `RevenueOpportunity`, or any manager state,
        and never schedules, retries, executes, or triggers any
        future execution."""
        rate_report = self.get_task_success_rate(task_id)
        latest = self.get_latest_for_task(task_id)

        return {
            "task_id": task_id,
            "has_results": rate_report["total_results"] > 0,
            "total_results": rate_report["total_results"],
            "completed_count": rate_report["completed_count"],
            "failed_count": rate_report["failed_count"],
            "success_rate": rate_report["success_rate"],
            "latest_result_id": latest.result_id if latest is not None else None,
            "latest_status": latest.status if latest is not None else None,
        }

    def get_opportunity_result_summary(self, opportunity_id):
        """A read-only combined summary for `opportunity_id`, as a
        plain `dict`:

            {
                "opportunity_id": opportunity_id,
                "has_results": <bool>,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "task_ids": <list of str>,
                "task_count": <int>,
                "latest_result_id": <str or None>,
                "latest_task_id": <str or None>,
                "latest_status": <str or None>,
            }

        `total_results`/`completed_count`/`failed_count`/
        `success_rate` come from `get_opportunity_success_rate`
        unchanged (see that method for the exact counting and
        zero-division rules). `task_ids` is every unique, valid
        (non-empty string) `task_id` seen across this opportunity's
        recorded results (from `get_for_opportunity`, so already in
        this history's own insertion order), each listed once in
        first-seen order; `task_count` is simply `len(task_ids)`.
        `latest_result_id`/`latest_task_id`/`latest_status` describe
        the last-in-insertion-order recorded result for this
        opportunity (the same "last in `get_for_opportunity`'s own
        order" result `get_latest_for_task` already uses for a single
        task) - not a re-sort by `created_at`. `has_results` is
        `True` exactly when `total_results > 0`.

        An unknown, empty, or `None` `opportunity_id` (including on
        an otherwise-empty history) safely returns a zero-result
        summary - `has_results=False`, all counts `0`,
        `success_rate=0.0`, `task_ids=[]`, `task_count=0`, and every
        `latest_*` field `None` - rather than raising, same
        "read-only reporting, safe default" convention
        `get_opportunity_success_rate`/`get_for_opportunity` already
        follow.

        Purely a read: only calls this history's own existing
        read-only methods and returns a freshly built dict (with a
        fresh `task_ids` list on every call). Never records, edits,
        or removes a result, never touches a `RevenueTask`,
        `RevenueOpportunity`, or any manager state, and never
        schedules, retries, executes, or triggers any future
        execution."""
        rate_report = self.get_opportunity_success_rate(opportunity_id)
        results = self.get_for_opportunity(opportunity_id)

        task_ids = []
        for result in results:
            task_id = result.task_id
            if isinstance(task_id, str) and task_id.strip() and task_id not in task_ids:
                task_ids.append(task_id)

        latest = results[-1] if results else None

        return {
            "opportunity_id": opportunity_id,
            "has_results": rate_report["total_results"] > 0,
            "total_results": rate_report["total_results"],
            "completed_count": rate_report["completed_count"],
            "failed_count": rate_report["failed_count"],
            "success_rate": rate_report["success_rate"],
            "task_ids": task_ids,
            "task_count": len(task_ids),
            "latest_result_id": latest.result_id if latest is not None else None,
            "latest_task_id": latest.task_id if latest is not None else None,
            "latest_status": latest.status if latest is not None else None,
        }

    def get_overall_result_summary(self):
        """A read-only summary across every recorded result in this
        history, as a plain `dict`:

            {
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "unique_task_count": <int>,
                "unique_opportunity_count": <int>,
                "latest_result_id": <str or None>,
                "latest_task_id": <str or None>,
                "latest_opportunity_id": <str or None>,
                "latest_status": <str or None>,
                "has_results": <bool>,
            }

        Built from `get_all()` (already fresh `copy.deepcopy` copies,
        oldest-first insertion order): `completed_count`/
        `failed_count` come from each result's own
        `is_successful()`/`is_failed()` check (financial/
        revenue_task_result.py), never a duplicated status constant.
        `unique_task_count`/`unique_opportunity_count` are the number
        of distinct, valid (non-empty string) `task_id`/
        `opportunity_id` values seen across every recorded result -
        every result in this history is already required to carry
        both (`record()` only accepts a result whose `is_valid()`
        confirms this), so this is simply a count of distinct values,
        with no per-value ordering guarantee needed. `success_rate`
        is `completed_count / total_results`, or `0.0` when there are
        no recorded results (avoiding a division by zero) - always a
        plain `float` in the inclusive range 0.0-1.0.
        `latest_result_id`/`latest_task_id`/`latest_opportunity_id`/
        `latest_status` describe the last-in-insertion-order recorded
        result across the whole history - not a re-sort by
        `created_at`. `has_results` is `True` exactly when
        `total_results > 0`.

        An empty history safely returns a zero-result summary -
        `has_results=False`, all counts `0`, `success_rate=0.0`, and
        every `latest_*` field `None` - rather than raising.

        Purely a read: only calls this history's own existing
        `get_all()` and returns a freshly built dict. Never records,
        edits, or removes a result, never touches a `RevenueTask`,
        `RevenueOpportunity`, or any manager state, and never
        schedules, retries, executes, or triggers any future
        execution."""
        results = self.get_all()
        total_results = len(results)

        if total_results == 0:
            return {
                "total_results": 0,
                "completed_count": 0,
                "failed_count": 0,
                "success_rate": 0.0,
                "unique_task_count": 0,
                "unique_opportunity_count": 0,
                "latest_result_id": None,
                "latest_task_id": None,
                "latest_opportunity_id": None,
                "latest_status": None,
                "has_results": False,
            }

        completed_count = sum(1 for result in results if result.is_successful())
        failed_count = sum(1 for result in results if result.is_failed())

        unique_task_ids = set()
        unique_opportunity_ids = set()
        for result in results:
            task_id = result.task_id
            if isinstance(task_id, str) and task_id.strip():
                unique_task_ids.add(task_id)
            opportunity_id = result.opportunity_id
            if isinstance(opportunity_id, str) and opportunity_id.strip():
                unique_opportunity_ids.add(opportunity_id)

        latest = results[-1]

        return {
            "total_results": total_results,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "success_rate": float(completed_count) / total_results,
            "unique_task_count": len(unique_task_ids),
            "unique_opportunity_count": len(unique_opportunity_ids),
            "latest_result_id": latest.result_id,
            "latest_task_id": latest.task_id,
            "latest_opportunity_id": latest.opportunity_id,
            "latest_status": latest.status,
            "has_results": True,
        }

    def get_task_performance_report(self, task_id):
        """A read-only performance report for `task_id`, as a plain
        `dict`:

            {
                "task_id": task_id,
                "has_results": <bool>,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "latest_result_id": <str or None>,
                "latest_status": <str or None>,
                "performance_state": <str>,
            }

        Every field except `performance_state` is taken directly,
        unchanged, from `get_task_result_summary(task_id)` (this
        method never recomputes counts, `success_rate`, or the
        latest-result fields itself, so it can never drift from that
        method's own counting, zero-division, or "last in insertion
        order" rules). `performance_state` is derived deterministically
        from that same summary:

        - `"NO_DATA"` when `has_results` is `False`
        - `"SUCCESSFUL"` when there are results and `success_rate ==
          1.0` (every recorded result is COMPLETED)
        - `"FAILED"` when there are results and `success_rate == 0.0`
          (every recorded result is FAILED)
        - `"MIXED"` when there are both completed and failed results
          (`0.0 < success_rate < 1.0`)

        No other `performance_state` value is ever produced. This
        looks only at recorded `RevenueTaskResult` objects (via
        `get_task_result_summary`) - it never inspects a
        `RevenueTask`'s own `status`.

        Purely a read: only calls this history's own existing
        `get_task_result_summary` and returns a freshly built dict.
        Never records, edits, or removes a result, never touches a
        `RevenueTask`, `RevenueOpportunity`, or any manager state,
        and never schedules, retries, executes, or triggers any
        future execution."""
        summary = self.get_task_result_summary(task_id)

        if not summary["has_results"]:
            performance_state = "NO_DATA"
        elif summary["success_rate"] == 1.0:
            performance_state = "SUCCESSFUL"
        elif summary["success_rate"] == 0.0:
            performance_state = "FAILED"
        else:
            performance_state = "MIXED"

        return {
            "task_id": summary["task_id"],
            "has_results": summary["has_results"],
            "total_results": summary["total_results"],
            "completed_count": summary["completed_count"],
            "failed_count": summary["failed_count"],
            "success_rate": summary["success_rate"],
            "latest_result_id": summary["latest_result_id"],
            "latest_status": summary["latest_status"],
            "performance_state": performance_state,
        }

    def get_opportunity_performance_report(self, opportunity_id):
        """A read-only performance report for `opportunity_id`, as a
        plain `dict`:

            {
                "opportunity_id": opportunity_id,
                "has_results": <bool>,
                "total_results": <int>,
                "completed_count": <int>,
                "failed_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "task_count": <int>,
                "task_ids": <list of str>,
                "latest_result_id": <str or None>,
                "latest_task_id": <str or None>,
                "latest_status": <str or None>,
                "performance_state": <str>,
            }

        Every field except `performance_state` is taken directly,
        unchanged, from `get_opportunity_result_summary(opportunity_id)`
        (this method never recomputes counts, `success_rate`,
        `task_ids`/`task_count`, or the latest-result fields itself,
        so it can never drift from that method's own counting,
        zero-division, first-seen task ordering, or "last in
        insertion order" rules) - `task_ids` is that same summary's
        own freshly built list, so mutating it here can never affect
        this history's own stored state. `performance_state` is
        derived deterministically from that same summary:

        - `"NO_DATA"` when `has_results` is `False`
        - `"SUCCESSFUL"` when there are results and `success_rate ==
          1.0` (every recorded result is COMPLETED)
        - `"FAILED"` when there are results and `success_rate == 0.0`
          (every recorded result is FAILED)
        - `"MIXED"` when there are both completed and failed results
          (`0.0 < success_rate < 1.0`)

        No other `performance_state` value is ever produced. This
        looks only at recorded `RevenueTaskResult` objects (via
        `get_opportunity_result_summary`) - it never inspects a
        `RevenueOpportunity`'s own status.

        Purely a read: only calls this history's own existing
        `get_opportunity_result_summary` and returns a freshly built
        dict. Never records, edits, or removes a result, never
        touches a `RevenueTask`, `RevenueOpportunity`, or any manager
        state, and never schedules, retries, executes, or triggers
        any future execution."""
        summary = self.get_opportunity_result_summary(opportunity_id)

        if not summary["has_results"]:
            performance_state = "NO_DATA"
        elif summary["success_rate"] == 1.0:
            performance_state = "SUCCESSFUL"
        elif summary["success_rate"] == 0.0:
            performance_state = "FAILED"
        else:
            performance_state = "MIXED"

        return {
            "opportunity_id": summary["opportunity_id"],
            "has_results": summary["has_results"],
            "total_results": summary["total_results"],
            "completed_count": summary["completed_count"],
            "failed_count": summary["failed_count"],
            "success_rate": summary["success_rate"],
            "task_count": summary["task_count"],
            "task_ids": summary["task_ids"],
            "latest_result_id": summary["latest_result_id"],
            "latest_task_id": summary["latest_task_id"],
            "latest_status": summary["latest_status"],
            "performance_state": performance_state,
        }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def clear(self):
        """Discard every recorded `RevenueTaskResult`. Only this
        history's own records are affected - no `RevenueTask`,
        `RevenueOpportunity`, or other module's state is touched (in
        particular, this never clears a `RevenueTask`'s own attached
        `result` - see `RevenueTask.clear_result()` for that,
        untouched by this method)."""
        self._by_result_id = {}
        self._order = []

    def __len__(self):
        return len(self._order)
