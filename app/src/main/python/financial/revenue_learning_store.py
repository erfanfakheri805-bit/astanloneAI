"""
Revenue Learning Record Store
================================
`RevenueLearningRecordStore` is a small, in-memory record of every
`RevenueLearningRecord` (financial/revenue_learning.py) that has been
handed to it so far - same "store the exact object, never a copy, but
hand back only safe copies" shape `financial/
revenue_task_result_history.py`'s own `RevenueTaskResultHistory`
already uses for `RevenueTaskResult`.

This stage only stores and retrieves already-built
`RevenueLearningRecord` objects, and can build one from an existing
`RevenueTaskResult` via `record_from_task_result()` (which simply
calls `RevenueLearningRecord.from_task_result()` - financial/
revenue_learning.py - and stores the result). It does NOT:

- Learn anything, infer a pattern, or feed a record into
  `learning/learning_system.py`, `learning/learning_analyzer.py`, or
  any other learning component - storing a record here is not a
  decision or a behavior change in its own right.
- Change any `RevenueTask`, `RevenueOpportunity`, or
  `RevenueStrategy`'s own state, or trigger any future execution,
  retry, or strategy change.
- Persist itself anywhere (no filesystem, database - SQLite or
  otherwise - or network I/O), run any code (no
  `eval`/`exec`/`subprocess`/shell), or call out to any external AI
  service.

Deliberately independent from persistent storage - same "lives only in
this process's RAM, cleared on process restart or an explicit clear()
call" convention `RevenueTaskResultHistory`, `execution/
execution_history.py`, and `planning/proposal_history.py` already
follow for their own histories. A future stage may back this with real
persistence; that is explicitly out of scope here.
"""

import copy

from .revenue_learning import RevenueLearningRecord
from .revenue_task_result import RevenueTaskResult


class RevenueLearningRecordStore:
    """Not thread-safe (matches the rest of this project - see
    RevenueTaskResultHistory/ExecutionHistory/ProposalHistory's own
    notes). Safe to use one instance per Core / per conversation
    session, or to share one across several callers that should log
    to the same store.

    Storage is two small, always-in-sync structures - a dict keyed by
    `learning_id` for O(1) lookup/duplicate-detection, and a list of
    `learning_id`s in the order `add_record()` first accepted them,
    for order-preserving iteration - same "id-keyed dict plus an
    ordered list of ids" shape `RevenueTaskResultHistory`/
    `ExecutionHistory` already use.
    """

    def __init__(self):
        self._by_learning_id = {}
        self._order = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def add_record(self, record):
        """Store `record` (a `RevenueLearningRecord`) in this store
        and return it unchanged on success, or `None` - storing
        nothing - on rejection. Never raises, and never modifies
        `record` in any way (this store's own state is the only thing
        that changes on a successful call).

        Rejected (returns `None`, leaves this store's own state
        completely unchanged) when:
        - `record` is not an actual `RevenueLearningRecord` instance
        - `record` fails its own `is_valid()` check (financial/
          revenue_learning.py - e.g. a missing id, an unsupported
          `result_status`, or unsafe/unstructured `output`/
          `metadata`)
        - `record.learning_id` is already stored in this store (a
          duplicate id never overwrites, or is silently dropped in
          favor of, the already-stored record under that same id -
          the first record stored under a given id always wins)

        On success, `record` is appended to this store's own
        insertion-order record - it is never inserted anywhere else,
        never re-ordered, and never stored a second time under the
        same id."""
        if not isinstance(record, RevenueLearningRecord):
            return None
        if not record.is_valid():
            return None
        if record.learning_id in self._by_learning_id:
            return None

        self._by_learning_id[record.learning_id] = record
        self._order.append(record.learning_id)
        return record

    def record_from_task_result(self, result):
        """Build a `RevenueLearningRecord` from `result` (a
        `RevenueTaskResult` - financial/revenue_task_result.py) via
        `RevenueLearningRecord.from_task_result()`, store it, and
        return the created record on success - or `None` on
        rejection, same safe-default convention `add_record()`
        already follows.

        Rejected (returns `None`, leaves this store's own state
        completely unchanged) when:
        - `result` is not an actual `RevenueTaskResult` instance
        - the record built from `result` fails `add_record()`'s own
          checks (e.g. it is somehow not valid, or its `learning_id`
          - freshly generated by `from_task_result()` - collides with
          one already stored, which cannot happen in ordinary use but
          is still handled safely rather than raising)

        Never modifies `result` in any way - only reads it (via
        `RevenueLearningRecord.from_task_result()`) to build a new,
        independent record. Never executes, retries, learns, or
        changes any strategy - this is purely a data transformation
        plus a store, same as `add_record()`."""
        if not isinstance(result, RevenueTaskResult):
            return None

        record = RevenueLearningRecord.from_task_result(result)
        return self.add_record(record)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_record(self, learning_id):
        """The stored `RevenueLearningRecord` whose `learning_id`
        exactly matches `learning_id`, as a fresh `copy.deepcopy`
        copy, or `None` if no such record is stored (including an
        unknown, empty, or `None` `learning_id`) - never raises."""
        if learning_id not in self._by_learning_id:
            return None
        return copy.deepcopy(self._by_learning_id[learning_id])

    def get_all(self):
        """Every stored `RevenueLearningRecord`, oldest-first
        (insertion order), as fresh `copy.deepcopy` copies - a new
        list on every call, never a reference to this store's own
        internal collection, so mutating the returned list (or any
        entry in it) can never affect this store's own stored
        state."""
        return [copy.deepcopy(self._by_learning_id[learning_id]) for learning_id in self._order]

    def get_for_task(self, task_id):
        """Every stored `RevenueLearningRecord` whose `task_id`
        exactly matches `task_id`, oldest-first (insertion order), as
        fresh `copy.deepcopy` copies. Returns an empty list - never
        raises - when `task_id` is unknown, empty, `None`, or
        otherwise matches nothing, same "read-only reporting, safe
        default" convention `RevenueTaskResultHistory.get_for_task`
        already follows."""
        return [
            copy.deepcopy(self._by_learning_id[learning_id])
            for learning_id in self._order
            if self._by_learning_id[learning_id].task_id == task_id
        ]

    def get_for_opportunity(self, opportunity_id):
        """Every stored `RevenueLearningRecord` whose
        `opportunity_id` exactly matches `opportunity_id`,
        oldest-first (insertion order), as fresh `copy.deepcopy`
        copies. Returns an empty list - never raises - when
        `opportunity_id` is unknown, empty, `None`, or otherwise
        matches nothing."""
        return [
            copy.deepcopy(self._by_learning_id[learning_id])
            for learning_id in self._order
            if self._by_learning_id[learning_id].opportunity_id == opportunity_id
        ]

    def count(self):
        """The number of stored `RevenueLearningRecord`s, as a plain
        `int`. Same as `len(self)`, provided as an explicit method for
        callers that prefer it."""
        return len(self._order)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def clear(self):
        """Discard every stored `RevenueLearningRecord`. Only this
        store's own records are affected - no `RevenueTask`,
        `RevenueOpportunity`, `RevenueTaskResult`, or other module's
        state is touched."""
        self._by_learning_id = {}
        self._order = []

    def __len__(self):
        return len(self._order)
