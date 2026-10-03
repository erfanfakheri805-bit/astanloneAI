"""
Agent - Code Correction Learning
====================================
Prompt 345: connect the existing code-correction retest/comparison
result (agent/code_correction_retest.py, Prompt 344 -
`AgentLoop.retest_code_correction`'s own result) to the existing
Learning system - `learning.learning_record.LearningRecord` and
`learning.learning_record_store.LearningRecordStore` - never a second,
differently-behaving learning system.

    retest_result (the exact dict `retest_code_correction`, Prompt
    344, already returns: {"correction_result", "original_evaluation",
    "retest_performed", "retest_evaluation", "comparison"})
        -> build_code_correction_learning_record()
        -> LearningRecord
        -> [optional] learn_from_code_correction(retest_result, store)
        -> store.add(record) -> stored LearningRecord (or None)

Reuses, never duplicates:
  - `learning.learning_record.LearningRecord` is the exact same,
    unmodified record model `learning.execution_learning.
    ExecutionLearning` already builds for the (unrelated)
    execution-result pipeline - this module builds no second record
    type, just another `LearningRecord` with its own fixed
    `source`/`pattern` vocabulary (requirement 1, 6).
  - `learning.learning_record_store.LearningRecordStore.add` is the
    exact same, unmodified storage/pattern infrastructure every other
    `LearningRecord` in this project already goes through - this
    module never persists anything itself, it only ever calls that
    store's own `add` (requirement 5).
  - `pattern` is the correction's `error_type` when one is known (the
    exact same grouping key `LearningRecordStore.find_by_pattern`
    already indexes on) - so corrections for the same kind of error
    naturally group together in the existing store, with no new
    pattern-matching logic of any kind added here.

This is deliberately observation only, the same "build the data, let
the caller decide what to do with it" boundary
`ExecutionLearning.create_record`/`learn_from_execution` already keep:
`build_code_correction_learning_record` never stores the record it
builds (a separate caller decides that), and neither function here
ever modifies `retest_result`, applies a correction, retries a retest,
or touches a plan, capability, skill, or code file (requirements 7,
8, 9) - `retest_result`'s own `correction_result`/`original_evaluation`
/`retest_evaluation`/`comparison` are only ever read, never mutated.

Success is judged by nothing but the *retest* outcome (requirement 3):
a correction is recorded as successful knowledge only when
`retest_evaluation["classification"]` is `RESULT_PASSED` - the exact,
already-computed classification `agent.test_result_evaluation.
classify_test_result` produced for the retest. Every other case - a
retest that still failed or timed out, a retest that never ran because
the correction was `REJECTED`/left `NOT_READY`/hit an `ERROR`, or any
other non-`PASSED` outcome - is recorded with `outcome=OUTCOME_FAILURE`
and the fixed, deterministic `CONFIDENCE_FAILURE` value, never treated
as successful knowledge (requirement 4) - the same deterministic,
status-only confidence convention `ExecutionLearning` already uses,
never derived from output/error content.

The six fields requirement 2 asks for (`error_type`, `original_status`,
`retest_status`, `correction_status`, `improved`, `regressed`) are
carried, unchanged, inside the record's own `metadata` dict - the same
place `ExecutionLearning.create_record` already carries its own
`plan_id`/`step_id`/`execution_id`/`error` fields - never as new
top-level `LearningRecord` attributes (`LearningRecord`'s own fixed
`__slots__` are never touched).
"""

from .test_result_evaluation import RESULT_PASSED
from learning.learning_record import LearningRecord

# Identifies the code-correction/retest pipeline as the source of
# every record this module builds - a fixed, deterministic value
# (never derived from retest_result itself), the same role
# `execution_learning.SOURCE_EXECUTION_SYSTEM` plays for that,
# separate, pipeline.
SOURCE_CODE_CORRECTION_SYSTEM = "code_correction_system"

# Fallback pattern used only when no error_type is available at all -
# still one fixed, deterministic string, never guessed at per record.
DEFAULT_PATTERN = "code_correction"

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"

# Deterministic, outcome-only confidence values (same convention
# execution_learning.py already uses for its own
# CONFIDENCE_SUCCESS/CONFIDENCE_FAILURE) - never derived from test
# output, error text, or anything else that could vary between two
# otherwise-identical retest outcomes.
CONFIDENCE_SUCCESS = 1.0
CONFIDENCE_FAILURE = 0.0


def _get(mapping, key):
    """`mapping[key]` if `mapping` is actually a dict, else `None` -
    never raises for a `None`/non-dict `mapping`, the same small,
    repeated shape every field below is read through."""
    return mapping.get(key) if isinstance(mapping, dict) else None


def build_code_correction_learning_record(retest_result):
    """Build one `LearningRecord` describing the already-produced
    `retest_result` (typically `AgentLoop.retest_code_correction(...)`
    above, Prompt 344) - always a record, never `None`, since "a
    correction was evaluated" (requirement 2) already holds the moment
    a real `retest_result` shape is handed in, whether or not a retest
    actually ran (a REJECTED/NOT_READY correction is itself something
    to learn from - requirement 4 - not something to stay silent
    about).

    Reads, never mutates, exactly:
        - `retest_result["correction_result"]["proposal"]["error_type"]`
          -> `error_type` (requirement 2) and this record's `pattern`
          (falling back to `DEFAULT_PATTERN` when no `error_type` is
          present, so there is always something to group by).
        - `retest_result["correction_result"]["application"]["status"]`
          -> `correction_status` (requirement 2) - the exact, already-
          computed `agent.code_correction_application` verdict
          (`APPLIED`/`NOT_READY`/`REJECTED`/`ERROR`), never re-derived.
        - `retest_result["original_evaluation"]["classification"]`
          -> `original_status` (requirement 2).
        - `retest_result["retest_evaluation"]["classification"]`
          -> `retest_status` (requirement 2) - `None` when no retest
          ever ran (`retest_performed=False`).
        - `retest_result["comparison"]["improved"]`/`["regressed"]`
          -> `improved`/`regressed` (requirement 2) - `False` for
          either one when no retest ever ran, since nothing was
          actually compared.

    `outcome`/`confidence` follow requirement 3 exactly: `OUTCOME_
    SUCCESS`/`CONFIDENCE_SUCCESS` only when `retest_status ==
    RESULT_PASSED`; `OUTCOME_FAILURE`/`CONFIDENCE_FAILURE` for every
    other case - a failed/timed-out retest, an invalid retest, or no
    retest at all - so a rejected or otherwise-unsuccessful correction
    is recorded, but never as successful knowledge (requirement 4).

    Always returns a `LearningRecord` - construction itself never
    raises (see `LearningRecord.__init__`'s own docstring) - a caller
    checking `record.is_valid()` (e.g. before storing it) is the same
    safety net `LearningRecordStore.add` itself already applies.
    Never stores the record it builds; never touches `retest_result`,
    a plan, a capability, a skill, or a code file."""
    correction_result = _get(retest_result, "correction_result")
    proposal = _get(correction_result, "proposal")
    application = _get(correction_result, "application")
    original_evaluation = _get(retest_result, "original_evaluation")
    retest_evaluation = _get(retest_result, "retest_evaluation")
    comparison = _get(retest_result, "comparison")

    error_type = _get(proposal, "error_type")
    correction_status = _get(application, "status")
    original_status = _get(original_evaluation, "classification")
    retest_status = _get(retest_evaluation, "classification")
    improved = bool(_get(comparison, "improved"))
    regressed = bool(_get(comparison, "regressed"))

    is_successful = retest_status == RESULT_PASSED
    outcome = OUTCOME_SUCCESS if is_successful else OUTCOME_FAILURE
    confidence = CONFIDENCE_SUCCESS if is_successful else CONFIDENCE_FAILURE

    pattern = error_type if isinstance(error_type, str) and error_type.strip() else DEFAULT_PATTERN

    metadata = {
        "error_type": error_type,
        "original_status": original_status,
        "retest_status": retest_status,
        "correction_status": correction_status,
        "improved": improved,
        "regressed": regressed,
    }

    return LearningRecord(
        source=SOURCE_CODE_CORRECTION_SYSTEM,
        pattern=pattern,
        outcome=outcome,
        confidence=confidence,
        metadata=metadata,
    )


def learn_from_code_correction(retest_result, store):
    """Convenience wrapper: build a record via
    `build_code_correction_learning_record` and add it to the existing
    `store` (an already-constructed `LearningRecordStore` - this never
    creates one of its own - requirement 6), the same
    "build, then let the existing store decide" wrapper
    `ExecutionLearning.learn_from_execution` already provides for its
    own, separate pipeline.

    Returns whatever `store.add(record)` returns: the stored
    `LearningRecord` on success, or `None` if the store itself
    rejected it (an invalid record, or a colliding `record_id`) - this
    function never overrides that store's own accept/reject decision.

    Never mutates `retest_result`, never constructs a new
    `LearningRecordStore`, never retries a retest, and never applies
    another correction (requirements 7, 8, 9)."""
    record = build_code_correction_learning_record(retest_result)
    return store.add(record)
