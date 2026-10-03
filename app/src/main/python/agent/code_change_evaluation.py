"""
Agent - Code Change Evaluation
=================================
Connects the existing `code_change_apply_and_test` capability's own,
already-structured result (execution/code_change_apply_and_test_capability.py:
`{change_status, test_status, test_output, error, change_result,
test_result}`) to `AgentLoop`'s own context, the same way
agent/test_result_evaluation.py already connects a bare
`python_test_runner` result:

    code_change_apply_and_test result -> build_code_change_evaluation()
        -> {state, change_status, test_status, correction_required,
            error, change_result, test_result}
        -> build_code_change_correction_decision()
        -> {correction_required, reason, source_test_status}

Reuses, unchanged, nothing re-derived:
  - `CHANGE_STATUS_APPLIED` / `CHANGE_STATUS_NOT_APPLIED` -
    execution/code_change_apply_and_test_capability.py's own,
    already-existing change vocabulary;
  - `RESULT_PASSED` / `RESULT_FAILED` / `RESULT_TIMEOUT` -
    agent/test_result_evaluation.py's own, already-existing test
    vocabulary (itself produced by that module's `classify_test_result`,
    which `code_change_apply_and_test`'s own handler already calls to
    fill in `test_status` - this module never re-classifies a raw test
    result, it only reads the label already attached to it).

This module adds no new classification of *how* a change was applied
or *how* a test ran - it only reads the two already-computed status
strings `code_change_apply_and_test`'s handler already returns and
combines them into one small, structured, five-way `state`:

    CHANGE_SUCCEEDED_TEST_PASSED - change_status APPLIED, test PASSED
    CHANGE_SUCCEEDED_TEST_FAILED - change_status APPLIED, test FAILED
    CHANGE_FAILED                - change_status NOT_APPLIED (the
                                    reused capability never starts a
                                    test on this path - see that
                                    module's own docstring)
    TEST_TIMEOUT                 - change_status APPLIED, test TIMEOUT
    INVALID                      - anything else: not a dict, a
                                    missing/unrecognised change_status,
                                    or an APPLIED change whose
                                    test_status isn't one of
                                    PASSED/FAILED/TIMEOUT (e.g.
                                    RESULT_INVALID, or None because the
                                    test run itself errored out - see
                                    `error`/`test_result` for why)

`correction_required` (requirement: "true only when the final test
status is FAILED or TIMEOUT") is derived from nothing but
`test_status` itself:

    test_status == RESULT_FAILED or RESULT_TIMEOUT  -> True
    anything else (RESULT_PASSED, None, RESULT_INVALID, ...) -> False

so `CHANGE_FAILED` (the test never ran) and `INVALID` (no confirmed
FAILED/TIMEOUT test status) are both `correction_required=False` -
deliberately narrower than `agent.test_result_evaluation.
is_correction_required`, which also flags `RESULT_INVALID`; this
integration's own requirement is stricter, so it is applied here
directly rather than through that function.

This module never applies a correction, never re-executes anything,
and never modifies the Plan - it only classifies an already-produced
result, exactly like `build_test_evaluation`/`build_correction_decision`
in agent/test_result_evaluation.py, which it deliberately does not
duplicate. `change_result` and `test_result` are always preserved
separately, completely unmodified, under their own keys - never merged
into one blob (requirement: "store the original change result and
test result separately").

Never raises: any input that isn't a real `code_change_apply_and_test`
result is reported as `state=INVALID`, `correction_required=False`,
never an exception - same "always return a structured, honest verdict"
convention `classify_test_result` itself already follows.
"""

from execution.code_change_apply_and_test_capability import (
    CHANGE_STATUS_APPLIED,
    CHANGE_STATUS_NOT_APPLIED,
)
from .test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT

STATE_CHANGE_SUCCEEDED_TEST_PASSED = "CHANGE_SUCCEEDED_TEST_PASSED"
STATE_CHANGE_SUCCEEDED_TEST_FAILED = "CHANGE_SUCCEEDED_TEST_FAILED"
STATE_CHANGE_FAILED = "CHANGE_FAILED"
STATE_TEST_TIMEOUT = "TEST_TIMEOUT"
STATE_INVALID = "INVALID"

ALL_CODE_CHANGE_STATES = (
    STATE_CHANGE_SUCCEEDED_TEST_PASSED,
    STATE_CHANGE_SUCCEEDED_TEST_FAILED,
    STATE_CHANGE_FAILED,
    STATE_TEST_TIMEOUT,
    STATE_INVALID,
)

# Final test statuses that call for correction (requirement 6) - a
# plain, explicit subset of agent/test_result_evaluation.py's own
# RESULT_* vocabulary, reused unchanged.
_CORRECTION_REQUIRED_TEST_STATUSES = (RESULT_FAILED, RESULT_TIMEOUT)


def classify_code_change_result(code_change_result):
    """Classify `code_change_result` - expected to be a
    `code_change_apply_and_test` capability result dict - into exactly
    one of `ALL_CODE_CHANGE_STATES`, using only its own already-present
    `change_status`/`test_status` fields. See this module's own
    docstring for the exact, fixed rule. Never raises."""
    if not isinstance(code_change_result, dict):
        return STATE_INVALID

    change_status = code_change_result.get("change_status")
    if change_status == CHANGE_STATUS_NOT_APPLIED:
        return STATE_CHANGE_FAILED
    if change_status != CHANGE_STATUS_APPLIED:
        return STATE_INVALID

    test_status = code_change_result.get("test_status")
    if test_status == RESULT_PASSED:
        return STATE_CHANGE_SUCCEEDED_TEST_PASSED
    if test_status == RESULT_FAILED:
        return STATE_CHANGE_SUCCEEDED_TEST_FAILED
    if test_status == RESULT_TIMEOUT:
        return STATE_TEST_TIMEOUT
    return STATE_INVALID


def build_code_change_evaluation(code_change_result):
    """Build the small, structured state
    `AgentLoop.evaluate_code_change_result` (agent/agent_loop.py)
    exposes, on top of - and without duplicating - `code_change_apply_
    and_test`'s own already-computed result.

    Always returns:
        {
            "state": <one of ALL_CODE_CHANGE_STATES>,
            "change_status": <code_change_result["change_status"], or
                              None if code_change_result isn't a dict>,
            "test_status": <code_change_result["test_status"], or None
                            if code_change_result isn't a dict, or the
                            change was never applied>,
            "correction_required": <bool - see module docstring>,
            "error": <code_change_result["error"], or None>,
            "change_result": <code_change_result["change_result"]
                              unchanged - requirement: "store the
                              original change result ... separately">,
            "test_result": <code_change_result["test_result"]
                            unchanged - requirement: "store the ...
                            test result separately">,
        }

    Every field beyond `state`/`correction_required` is read directly
    from `code_change_result` - never re-derived, copied-with-changes,
    or invented - so a caller can see exactly what this evaluation was
    based on without a second lookup. Never raises: a
    `code_change_result` that isn't a dict yields `None` for every
    passed-through field and `state=INVALID`, `correction_required=
    False`, exactly as `classify_code_change_result` already reports
    for that same input."""
    state = classify_code_change_result(code_change_result)
    is_dict = isinstance(code_change_result, dict)
    test_status = code_change_result.get("test_status") if is_dict else None

    return {
        "state": state,
        "change_status": code_change_result.get("change_status") if is_dict else None,
        "test_status": test_status,
        "correction_required": test_status in _CORRECTION_REQUIRED_TEST_STATUSES,
        "error": code_change_result.get("error") if is_dict else None,
        "change_result": code_change_result.get("change_result") if is_dict else None,
        "test_result": code_change_result.get("test_result") if is_dict else None,
    }


# Reason label for `build_code_change_correction_decision` below, one
# small fixed word per `ALL_CODE_CHANGE_STATES` value - reuses this
# module's own `RESULT_PASSED`/`RESULT_FAILED`/`RESULT_TIMEOUT`/
# `STATE_INVALID` vocabulary unchanged for the three test-outcome
# states and for INVALID, plus one extra, equally fixed label,
# "CHANGE_FAILED", for the one state a test status alone can never
# distinguish (the change itself was never applied, so no test ever
# ran - see `STATE_CHANGE_FAILED` above). Nothing here re-derives
# `state` - it is only relabelled for a caller who wants a short,
# human-readable reason without inspecting the five-way `state` value
# itself.
_CODE_CHANGE_CORRECTION_REASONS = {
    STATE_CHANGE_SUCCEEDED_TEST_PASSED: RESULT_PASSED,
    STATE_CHANGE_SUCCEEDED_TEST_FAILED: RESULT_FAILED,
    STATE_TEST_TIMEOUT: RESULT_TIMEOUT,
    STATE_CHANGE_FAILED: "CHANGE_FAILED",
    STATE_INVALID: STATE_INVALID,
}


def build_code_change_correction_decision(code_change_result):
    """Build the small, structured "does this code-change result call
    for a correction" decision `AgentLoop.evaluate_code_change_
    correction_decision` (agent/agent_loop.py) exposes, on top of - and
    without duplicating - `build_code_change_evaluation` above.

    Always returns exactly:
        {
            "correction_required": <bool - the exact, unmodified
                                    evaluation["correction_required"]
                                    build_code_change_evaluation already
                                    computed: True only when the final
                                    test status is FAILED or TIMEOUT,
                                    False for PASSED, INVALID, or a
                                    failed change (test never ran)>,
            "reason": <one fixed word from
                       _CODE_CHANGE_CORRECTION_REASONS above -
                       "PASSED"/"FAILED"/"TIMEOUT"/"CHANGE_FAILED"/
                       "INVALID" - a direct relabelling of
                       evaluation["state"], never re-derived from
                       test_status/change_status directly>,
            "source_test_status": <the exact, unmodified
                                    evaluation["test_status"] - the
                                    already-computed test status this
                                    decision was sourced from, None for
                                    a failed change or an invalid
                                    operation>,
        }

    This is purely a small decision on top of the already-existing
    `build_code_change_evaluation` - it reuses that function's own
    `state`/`correction_required`/`test_status` fields completely
    unchanged rather than re-reading `code_change_result` or
    re-deriving any classification of its own. Not a new correction
    engine and not a second evaluation/testing system: no test is run,
    no change is applied, and nothing here decides *how* a correction
    happens - it only exposes, in a small fixed shape, the same
    correction verdict `build_code_change_evaluation` already reached.

    Never raises: any input that isn't a real `code_change_apply_and_
    test` result is reported as `"reason": "INVALID"`,
    `"correction_required": False`, `"source_test_status": None`,
    exactly as `build_code_change_evaluation` itself already guarantees
    for that same input."""
    evaluation = build_code_change_evaluation(code_change_result)
    return {
        "correction_required": evaluation["correction_required"],
        "reason": _CODE_CHANGE_CORRECTION_REASONS[evaluation["state"]],
        "source_test_status": evaluation["test_status"],
    }
