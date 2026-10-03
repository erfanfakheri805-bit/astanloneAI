"""
Agent - Code Correction Pattern Retrieval
=============================================
Prompt 346: let the existing `AgentLoop` look up previously-recorded,
*successful* code-correction learning records (agent/
code_correction_learning.py, Prompt 345) for a given `error_type`,
before it ever generates a new correction proposal - a small,
read-only lookup, never a second learning system or a second pattern
store.

    error_type (string)
        -> retrieve_successful_correction_patterns(store, error_type)
        -> [LearningRecord, ...]  (only ever CONFIDENCE_SUCCESS /
                                    OUTCOME_SUCCESS records for that
                                    error_type's own pattern)

Reuses, never duplicates:
  - The existing `LearningRecordStore` (learning/learning_record_store.py)
    is the one and only place these records ever live - this module
    builds no new store, no new index, and no new persistence of its
    own (requirement 6). It is looked up through, never wrapped or
    copied.
  - `LearningRecordStore.find_by_pattern` is called with `error_type`
    itself - reusing the exact same `pattern` convention `agent.
    code_correction_learning.build_code_correction_learning_record`
    (Prompt 345) already established: that module's own `pattern` is
    the correction's `error_type` whenever one is known, so looking a
    pattern up by `error_type` here is looking it up by the exact key
    it was already filed under, never a new pattern-matching algorithm
    (requirement 2).
  - `LearningRecordStore.find_by_outcome` (with `agent.code_correction_
    learning.OUTCOME_SUCCESS`) is the existing "was this reliable"
    reliability/confidence filter already available on the store, and
    is reused directly here rather than a second, independently-
    written success check (requirement 5). Combined with each
    candidate record's own already-computed `confidence` (reusing
    `agent.code_correction_learning.CONFIDENCE_SUCCESS`, the exact
    fixed value that module already assigns a truly successful
    correction) as one further, purely defensive reliability check -
    never a new confidence *model*, just reading the confidence a
    record already carries.
  - `agent.code_correction_learning.SOURCE_CODE_CORRECTION_SYSTEM` is
    reused, unchanged, so this lookup only ever considers records the
    code-correction/retest pipeline itself produced - never a record
    some other, unrelated learning source happened to file under a
    coincidentally-matching pattern string.

Purely a read-only retrieval step: never builds, stores, or mutates a
`LearningRecord`, never applies a correction, never modifies a source
file, and never runs or re-runs a test (requirements 9, 10, 11) - it
only reads what `LearningRecordStore` already holds and hands back the
subset that is both pattern-relevant and already-confirmed successful.

Never raises: an unusable `store`/`error_type` (missing, wrong type,
empty) is reported as an empty list, never an exception - the exact
same "safe on a miss" convention every `LearningRecordStore.find_*`
method already follows (requirement 7).
"""

from .code_correction_learning import (
    SOURCE_CODE_CORRECTION_SYSTEM,
    OUTCOME_SUCCESS,
    CONFIDENCE_SUCCESS,
)


def retrieve_successful_correction_patterns(store, error_type):
    """Return every previously-recorded, successful code-correction
    `LearningRecord` relevant to `error_type` - reusing only
    `store`'s own existing `find_by_pattern`/`find_by_outcome` lookups
    (see module docstring) - or `[]` when there is nothing to return.

    `store` is expected to be an already-constructed
    `LearningRecordStore` (e.g. `AgentLoop.learning_records` - see
    `AgentLoop.retrieve_successful_correction_patterns` below); `None`
    (no store configured) or anything else that doesn't offer
    `find_by_pattern`/`find_by_outcome` yields `[]`, never raised
    (requirement 7).

    `error_type` must be a non-empty string - the exact same
    `pattern` key `agent.code_correction_learning.
    build_code_correction_learning_record` already files a
    correction's own `error_type` under (requirement 2); anything
    else (`None`, an empty string, a non-string) yields `[]` (nothing
    can meaningfully be "relevant" to it).

    A record is included only when *all* of the following - each
    already computed by the existing store/Prompt 345 pipeline, never
    re-derived here - hold (requirements 4, 5):
      - `record.pattern == error_type` (via `find_by_pattern`);
      - `record.outcome == OUTCOME_SUCCESS` (via `find_by_outcome`);
      - `record.source == SOURCE_CODE_CORRECTION_SYSTEM` (only this
        pipeline's own records are ever considered here);
      - `record.confidence >= CONFIDENCE_SUCCESS` (the existing,
        already-assigned reliability score - a defensive re-check on
        top of the outcome filter, never a new scoring rule).

    Returned in the order the store itself already returns them from
    `find_by_pattern` (insertion order - see that method's own
    docstring) - each entry is already the safe `copy.deepcopy`
    `find_by_pattern` itself provides, so nothing here needs to copy
    anything a second time, and a caller mutating an entry can never
    corrupt the store's own internal state.

    Never mutates `store` or any record inside it, never applies a
    correction, never modifies a file, and never runs a test
    (requirements 9, 10, 11)."""
    if not isinstance(error_type, str) or not error_type.strip():
        return []
    if not hasattr(store, "find_by_pattern") or not hasattr(store, "find_by_outcome"):
        return []

    pattern_matches = store.find_by_pattern(error_type)
    if not pattern_matches:
        return []

    successful_ids = {record.record_id for record in store.find_by_outcome(OUTCOME_SUCCESS)}

    return [
        record for record in pattern_matches
        if record.record_id in successful_ids
        and record.source == SOURCE_CODE_CORRECTION_SYSTEM
        and record.confidence >= CONFIDENCE_SUCCESS
    ]
