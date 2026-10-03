"""
Learning Record Store
========================
`LearningRecordStore` is a small, in-memory, id-keyed store for
`LearningRecord` objects (learning/learning_record.py):

    LearningRecord -> LearningRecordStore.add()
        -> [later] get() / get_all() / find_by_pattern() /
           find_by_source() / find_by_outcome() /
           find_highest_confidence() / get_pattern_confidence() /
           get_latest_by_pattern() / get_latest_by_source()

This stage only stores and retrieves already-built `LearningRecord`
objects - it does not build/validate a record's fields beyond calling
its own `is_valid()`, does not touch the filesystem, a database, the
shell, the network, or any Android API, and does not change any plan,
proposal, capability, or the existing `learning/learning_system.py` /
`learning/learning_decision.py` pipeline in any way. Nothing here is
persisted: like `execution/execution_history.py` and
`planning/proposal_history.py`, this store lives only in this
process's RAM and is cleared on process restart (or on an explicit
`clear()` call).

Same "reject safely, never raise" convention already used by
`ProposalHistory.record` (planning/proposal_history.py): `add()`
returns `None` - and stores nothing - for anything that isn't a valid
`LearningRecord`, rather than raising. A caller can freely try to add
untrusted candidates without wrapping every call in a try/except.
"""

import copy

from .learning_record import LearningRecord


class LearningRecordStore:
    """Not thread-safe (matches the rest of this project - see
    ExecutionHistory/ProposalHistory/PlanManager's own notes). Safe to
    use one instance per Core / per conversation session, or to share
    one instance across several callers that should see the same set
    of learning records.

    Storage is a single `{record_id: LearningRecord}` dict, keyed by
    each record's own `record_id` - simplest structure that still
    supports O(1) lookup by id and straightforward duplicate-id
    rejection.
    """

    def __init__(self):
        self._records = {}

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------
    def add(self, record):
        """Store `record`, but only if it is an actual `LearningRecord`
        instance that reports `is_valid()`.

        Returns `record` unchanged on success, or `None` - and stores
        nothing - if `record` isn't a `LearningRecord`, fails its own
        `is_valid()` check, or its `record_id` is already present in
        this store (duplicate ids never overwrite an existing record -
        the first record added under a given id always wins; `clear()`
        or a fresh store are the only ways to replace one). Never
        raises.
        """
        if not isinstance(record, LearningRecord):
            return None
        if not record.is_valid():
            return None
        if record.record_id in self._records:
            return None

        self._records[record.record_id] = record
        return record

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, record_id):
        """The `LearningRecord` stored under `record_id`, or `None` if
        nothing is stored there (never raises for an unknown, empty,
        or non-string id - same convention already used across this
        project's other registries/stores)."""
        return self._records.get(record_id)

    def get_all(self):
        """A plain list (never None) of every stored `LearningRecord`,
        in the order each was first added. Each entry is a
        `copy.deepcopy` of the stored record, so a caller mutating an
        entry it read back can never corrupt this store's own internal
        state (same "always return safe copies" convention
        `ProposalHistory.get_all` already follows)."""
        return [copy.deepcopy(record) for record in self._records.values()]

    def find_by_pattern(self, pattern):
        """A plain list (never None) of every stored `LearningRecord`
        whose `pattern` exactly matches `pattern`, in the order each
        was first added. Read-only: never mutates a stored record, and
        - same "always return safe copies" convention as `get_all` -
        each match is a `copy.deepcopy`, so a caller mutating an entry
        it read back can never corrupt this store's own internal
        state.

        Returns `[]` - never raises - for a `pattern` that is empty,
        not a string, or simply matches nothing (same "safe on a miss"
        convention `get`/`ExecutableCapabilityRegistry.get` already
        follow)."""
        if not isinstance(pattern, str) or not pattern:
            return []
        return [
            copy.deepcopy(record)
            for record in self._records.values()
            if record.pattern == pattern
        ]

    def find_by_source(self, source):
        """A plain list (never None) of every stored `LearningRecord`
        whose `source` exactly matches `source`, in the order each was
        first added. Read-only: never mutates a stored record, and -
        same "always return safe copies" convention as `get_all` /
        `find_by_pattern` - each match is a `copy.deepcopy`, so a
        caller mutating an entry it read back can never corrupt this
        store's own internal state.

        Returns `[]` - never raises - for a `source` that is empty,
        not a string, or simply matches nothing (same "safe on a miss"
        convention `get`/`find_by_pattern` already follow)."""
        if not isinstance(source, str) or not source:
            return []
        return [
            copy.deepcopy(record)
            for record in self._records.values()
            if record.source == source
        ]

    def find_by_outcome(self, outcome):
        """A plain list (never None) of every stored `LearningRecord`
        whose `outcome` exactly matches `outcome`, in the order each
        was first added. Read-only: never mutates a stored record, and
        - same "always return safe copies" convention as `get_all` /
        `find_by_pattern` / `find_by_source` - each match is a
        `copy.deepcopy`, so a caller mutating an entry it read back can
        never corrupt this store's own internal state.

        Returns `[]` - never raises - for an `outcome` that is empty,
        not a string, or simply matches nothing (same "safe on a miss"
        convention `get`/`find_by_pattern`/`find_by_source` already
        follow)."""
        if not isinstance(outcome, str) or not outcome:
            return []
        return [
            copy.deepcopy(record)
            for record in self._records.values()
            if record.outcome == outcome
        ]

    def find_highest_confidence(self, pattern):
        """The single stored `LearningRecord` whose `pattern` exactly
        matches `pattern` and has the highest `confidence`. When
        several matching records share the same highest confidence,
        the earliest one added is returned (insertion order into this
        store's own `dict`, same deterministic tie-break already used
        implicitly by `get_all`/`find_by_pattern`'s "in the order each
        was first added" ordering) - never a random or unstable choice
        among ties.

        Returns `None` - never raises - for a `pattern` that is empty,
        not a string, or matches nothing (same "safe on a miss"
        convention `get`/`find_by_pattern` already follow). The
        returned record is a `copy.deepcopy`, so a caller mutating it
        can never corrupt this store's own internal state (same
        "always return safe copies" convention as `get_all`/
        `find_by_pattern`/`find_by_source`/`find_by_outcome`)."""
        if not isinstance(pattern, str) or not pattern:
            return None

        best = None
        for record in self._records.values():
            if record.pattern != pattern:
                continue
            if best is None or record.confidence > best.confidence:
                best = record

        return copy.deepcopy(best) if best is not None else None

    def get_pattern_confidence(self, pattern):
        """The average `confidence` (a plain `float`) across every
        stored `LearningRecord` whose `pattern` exactly matches
        `pattern`. Only records that currently pass `is_valid()` are
        included in the average - `add()` already only ever accepts
        valid records, but this stays defensive rather than assuming
        a record already in the store is still valid (same "never
        trust a stale guarantee" reasoning `ExecutableCapabilityRegistry
        .is_available` already applies to its own handler check).

        Returns `0.0` - never raises - for a `pattern` that is empty,
        not a string, or matches no valid record (same "safe on a
        miss" convention `find_by_pattern` already follows). Never
        modifies any stored record."""
        if not isinstance(pattern, str) or not pattern:
            return 0.0

        matches = [
            record for record in self._records.values()
            if record.pattern == pattern and record.is_valid()
        ]
        if not matches:
            return 0.0

        return sum(record.confidence for record in matches) / len(matches)

    def get_latest_by_pattern(self, pattern):
        """The single stored `LearningRecord` whose `pattern` exactly
        matches `pattern` and has the most recent `created_at`. When
        several matching records share the same `created_at`, the
        most recently *added* one wins (insertion order into this
        store's own `dict` - same deterministic tie-break convention
        `find_highest_confidence` already uses, just resolving ties
        toward the latest rather than the earliest, since this method
        is specifically about recency) - never a random or unstable
        choice among ties.

        Returns `None` - never raises - for a `pattern` that is empty,
        not a string, or matches nothing (same "safe on a miss"
        convention `get`/`find_by_pattern` already follow). The
        returned record is a `copy.deepcopy`, so a caller mutating it
        can never corrupt this store's own internal state (same
        "always return safe copies" convention as `get_all`/
        `find_by_pattern`/`find_highest_confidence`)."""
        if not isinstance(pattern, str) or not pattern:
            return None

        latest = None
        for record in self._records.values():
            if record.pattern != pattern:
                continue
            if latest is None or record.created_at >= latest.created_at:
                latest = record

        return copy.deepcopy(latest) if latest is not None else None

    def get_latest_by_source(self, source):
        """The single stored `LearningRecord` whose `source` exactly
        matches `source` and has the most recent `created_at`. When
        several matching records share the same `created_at`, the
        most recently *added* one wins (insertion order into this
        store's own `dict` - same deterministic tie-break convention
        `get_latest_by_pattern` already uses) - never a random or
        unstable choice among ties.

        Returns `None` - never raises - for a `source` that is empty,
        not a string, or matches nothing (same "safe on a miss"
        convention `get`/`find_by_source`/`get_latest_by_pattern`
        already follow). The returned record is a `copy.deepcopy`, so
        a caller mutating it can never corrupt this store's own
        internal state (same "always return safe copies" convention
        as `get_all`/`find_by_source`/`get_latest_by_pattern`)."""
        if not isinstance(source, str) or not source:
            return None

        latest = None
        for record in self._records.values():
            if record.source != source:
                continue
            if latest is None or record.created_at >= latest.created_at:
                latest = record

        return copy.deepcopy(latest) if latest is not None else None

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------
    def clear(self):
        """Remove every record currently in this store. Nothing to
        return; always succeeds, even if the store was already
        empty."""
        self._records.clear()

    def __len__(self):
        return len(self._records)

    def __repr__(self):
        return f"LearningRecordStore({len(self._records)} record(s))"
