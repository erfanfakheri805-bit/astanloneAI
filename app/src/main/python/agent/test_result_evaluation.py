"""
Agent - Test Result Evaluation
=================================
A small, deterministic classifier that turns an already-produced
`python_test_runner` capability result (the exact structured dict
`execution.python_test_runner_capability`'s own handler already
returns - see that module's docstring: `{success, timed_out,
return_code, stdout, stderr, tests_run, failures, errors, skipped,
duration_seconds, path, requested_path, target}`) into exactly one of
four fixed outcome labels:

    python_test_runner result -> classify_test_result()
        -> "PASSED" | "FAILED" | "TIMEOUT" | "INVALID"

A small, deterministic decision sits on top of that classification,
without duplicating it: `build_correction_decision()` reuses
`build_test_evaluation()`/`classify_test_result()` completely
unchanged and exposes `correction_required` (`True` for `"FAILED"`,
`"TIMEOUT"`, or `"INVALID"`; `False` for `"PASSED"`) alongside the
original, unmodified evaluation. See `build_correction_decision`'s own
docstring below. This is a decision step, not a second planning
system, not a retry mechanism, and never modifies a file or runs a
test of its own - it only reads the classification this module
already produces and reports whether it calls for a correction.

This is a read-only evaluation step, not a second test runner and not
a second copy of `python_test_runner_capability.py`'s own execution
logic: `classify_test_result` never runs a test, never spawns a
process, never touches the filesystem, and never re-derives anything
`python_test_runner_capability.py` already computed (`success`,
`timed_out`) - it only reads those two already-present fields and maps
them onto one of the four labels above. Nothing here retries a test,
modifies a source file, or changes the test-runner result it was
handed in any way.

No equivalent classifier already existed in this project before this
module: `learning.execution_learning.ExecutionLearning.create_record`
is the closest existing "turn a result into an outcome" step, but it
classifies a `execution.execution_result.ExecutionResult`'s own
`status` (`STATUS_COMPLETED`/`STATUS_FAILED` - whether the *capability
call itself* completed or raised) into a two-way
`"success"`/`"failure"` `LearningRecord` outcome; it has no notion of
`timed_out`, and a `python_test_runner` capability call that
completed cleanly but whose *tests* failed is `STATUS_COMPLETED` at
that level (the capability ran fine) - `ExecutionLearning` would call
that a `"success"`, exactly as it should for its own purpose. This
module answers a different, narrower question - "of the tests that
were actually run, what did they report" - using only the test-runner
result's own `success`/`timed_out` fields, and is not a duplicate of
`ExecutionLearning`'s own, unrelated classification.

Deterministic vocabulary, same `RESULT_*`/`ALL_*` controlled-
vocabulary convention already used throughout this project (see
agent/agent_loop.py's `STATUS_*`/`ALL_AGENT_LOOP_STATUSES`,
planning/goal_completion.py's `STATE_*`, execution/execution_result.py's
`STATUS_*`).
"""

RESULT_PASSED = "PASSED"
RESULT_FAILED = "FAILED"
RESULT_TIMEOUT = "TIMEOUT"
RESULT_INVALID = "INVALID"

ALL_TEST_RESULT_CLASSIFICATIONS = (
    RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID,
)

# The two fields `python_test_runner_capability.py`'s own handler
# always includes, with these exact meanings, in *every* result it
# returns - both the timed-out shape and the completed-run shape (see
# that module's `make_python_test_runner_handler`). Their presence,
# with the right types, is what "this looks like a real
# python_test_runner result" means here; anything missing either one,
# or carrying the wrong type for either one, is reported as
# `RESULT_INVALID` rather than guessed at - never assumed to mean
# "failed".
_REQUIRED_BOOL_FIELDS = ("success", "timed_out")


def classify_test_result(test_result):
    """Classify `test_result` - expected to be a `python_test_runner`
    capability result dict (e.g. a `CapabilityExecutionResult.output`,
    or the equivalent `ExecutionResult.output`) - into exactly one of
    `RESULT_PASSED`/`RESULT_FAILED`/`RESULT_TIMEOUT`/`RESULT_INVALID`.

    Uses only the `timed_out` and `success` fields already present in
    `test_result` - never re-parses `stdout`/`stderr`, never re-counts
    `tests_run`/`failures`/`errors`, and never looks at anything
    outside `test_result` itself (no filesystem access, no re-running
    anything). Order of evaluation is fixed and always the same:

      1. `test_result` must be a `dict` - anything else (`None`, a
         string, a `CapabilityExecutionResult` object itself rather
         than its `.output`, ...) is `RESULT_INVALID`.
      2. Both `"success"` and `"timed_out"` must be present in
         `test_result` and must each be an actual `bool` (matching
         exactly what `python_test_runner_capability.py`'s own handler
         always produces for both fields) - missing, `None`, or a
         non-bool value (e.g. a string `"true"`, or `1`) for either
         one is `RESULT_INVALID`, never coerced or guessed at.
      3. If `timed_out` is `True`, the result is `RESULT_TIMEOUT` -
         checked before `success`, since a timed-out run's own
         `success` is already `False` for an unrelated reason (the
         process never finished) and `RESULT_TIMEOUT` is the more
         specific, more useful label for a caller deciding what to do
         next.
      4. Otherwise, `RESULT_PASSED` if `success` is `True`,
         `RESULT_FAILED` if `success` is `False`.

    Never raises for any input - the same "always return a
    structured, honest verdict" convention this project's other
    read-only evaluators already follow (see
    code_intelligence/python_inspector.py's own module docstring)."""
    if not isinstance(test_result, dict):
        return RESULT_INVALID

    for field in _REQUIRED_BOOL_FIELDS:
        if not isinstance(test_result.get(field), bool):
            return RESULT_INVALID

    if test_result["timed_out"]:
        return RESULT_TIMEOUT

    return RESULT_PASSED if test_result["success"] else RESULT_FAILED


def build_test_evaluation(test_result):
    """Wrap `classify_test_result(test_result)` together with the
    exact result it was derived from into one small, structured,
    JSON-shaped dict - the "evaluation result"
    `AgentLoop.evaluate_test_result` (agent/agent_loop.py) exposes.

    Always returns `{"classification": <one of
    ALL_TEST_RESULT_CLASSIFICATIONS>, "test_result": test_result}` -
    `test_result` is included completely unchanged (never copied-with-
    changes, never re-derived) so a caller can see exactly what the
    classification was based on without a second lookup. Never
    raises - delegates every input-shape decision to
    `classify_test_result` above."""
    return {
        "classification": classify_test_result(test_result),
        "test_result": test_result,
    }


# Classifications that mean "something needs to be corrected before this
# can be considered done" - every label except RESULT_PASSED. Fixed,
# deterministic mapping (no heuristics, nothing learned, nothing
# invented): a FAILED or TIMEOUT run genuinely needs a fix, and an
# INVALID result means the evaluation itself could not confirm a pass,
# so it is treated the same conservative way rather than assumed fine.
_CLASSIFICATIONS_REQUIRING_CORRECTION = (RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID)


def is_correction_required(classification):
    """Deterministically decide whether `classification` - one of
    `ALL_TEST_RESULT_CLASSIFICATIONS` - means a correction is required.

    `RESULT_PASSED` -> `False`. `RESULT_FAILED`/`RESULT_TIMEOUT`/
    `RESULT_INVALID` -> `True`. A `classification` outside
    `ALL_TEST_RESULT_CLASSIFICATIONS` (which `classify_test_result`
    itself never produces) is treated the same conservative way as
    `RESULT_INVALID` - `True` - rather than silently assumed to mean no
    correction is needed.

    Pure lookup, no side effects: makes no decision beyond this mapping,
    never inspects `test_result` itself (that already happened in
    `classify_test_result`), and never modifies anything."""
    return classification != RESULT_PASSED


def build_correction_decision(test_result):
    """Build the small, structured "does this test result require a
    correction" decision this module exposes, on top of - and without
    duplicating - `build_test_evaluation`/`classify_test_result` above.

    Always returns:
        {
            "correction_required": <bool - see is_correction_required>,
            "reason": <the same classification string
                       ALL_TEST_RESULT_CLASSIFICATIONS restricts to -
                       PASSED/FAILED/TIMEOUT/INVALID>,
            "evaluation": <the exact, unmodified dict
                           build_test_evaluation(test_result) itself
                           already returns, i.e.
                           {"classification": ..., "test_result": ...}>,
        }

    This is purely a small, deterministic decision on top of the
    already-existing evaluation - it reuses `build_test_evaluation`
    unchanged rather than re-deriving `classification` or re-reading
    `test_result` itself, and the original evaluation (classification
    together with the exact `test_result` it was derived from) is kept
    completely intact under `"evaluation"`, never dropped or
    summarized away. `"reason"` duplicates `evaluation["classification"]`
    only for convenient, explicit access to *why* a correction is (or
    is not) required, without making a caller reach into `"evaluation"`
    for that.

    A read-only decision step, exactly like `build_test_evaluation`:
    never runs a test, never retries anything, never modifies a source
    file or any other file, and never executes another step or plan of
    its own - it only classifies the already-produced `test_result` it
    was handed and reports whether that classification calls for a
    correction. Never raises - delegates every input-shape decision to
    `build_test_evaluation`/`classify_test_result`, so a malformed
    `test_result` becomes `"reason": "INVALID"` /
    `"correction_required": True`, never an exception."""
    evaluation = build_test_evaluation(test_result)
    classification = evaluation["classification"]
    return {
        "correction_required": is_correction_required(classification),
        "reason": classification,
        "evaluation": evaluation,
    }
