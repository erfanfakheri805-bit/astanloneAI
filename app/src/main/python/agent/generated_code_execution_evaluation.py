"""
Agent - Generated Code Execution Evaluation
===============================================
Connects the existing `execute_generated_code` result
(code_generation/generated_code_execution.py: `{status, target_file,
stdout, stderr, error}`) to `AgentLoop`'s own context, the same way
agent/code_change_evaluation.py already connects a
`code_change_apply_and_test` result and agent/test_result_evaluation.py
already connects a bare `python_test_runner` result:

    execute_generated_code() result -> build_generated_code_execution_evaluation()
        -> {status, target_file, execution_status, error,
            correction_required}

Reuses, unchanged, nothing re-derived:
  - `code_generation.generated_code_execution.STATUS_EXECUTED` /
    `STATUS_FAILED` / `STATUS_TIMEOUT` / `STATUS_REJECTED` - that
    module's own, already-existing execution vocabulary, itself
    already derived (via `_CLASSIFICATION_TO_STATUS`) from
    `agent.test_result_evaluation.classify_test_result`'s own
    PASSED/FAILED/TIMEOUT/INVALID labels;
  - `agent.test_result_evaluation.RESULT_PASSED` / `RESULT_FAILED` /
    `RESULT_TIMEOUT` / `RESULT_INVALID` - this module's own evaluation
    `status` is expressed using that exact, already-existing four-way
    vocabulary, never a second, differently-spelled one.

This module adds no new classification of *how* a generated file was
executed - it only reads the already-computed `status` field
`execute_generated_code` itself already returns and relabels it onto
the same PASSED/FAILED/TIMEOUT/INVALID vocabulary every other
evaluator in this project already uses:

    STATUS_EXECUTED  -> RESULT_PASSED   (execution succeeded)
    STATUS_FAILED    -> RESULT_FAILED   (execution returned an error)
    STATUS_TIMEOUT   -> RESULT_TIMEOUT  (execution exceeded the timeout)
    STATUS_REJECTED  -> RESULT_INVALID  (execution was rejected before
                                          running)
    anything else (not a dict, or an unrecognised status) -> RESULT_INVALID

`correction_required` (requirement: "true only for FAILED or TIMEOUT")
is derived from nothing but the evaluation `status` above:

    status == RESULT_FAILED or RESULT_TIMEOUT  -> True
    anything else (RESULT_PASSED, RESULT_INVALID) -> False

so a rejected/never-run execution (`RESULT_INVALID`) is deliberately
*not* flagged for correction here - a rejection means execution never
even started (missing preconditions, a failed sandbox/containment
check - see `execute_generated_code`'s own docstring), which is a
different, narrower situation than "ran and needs a fix" - exactly the
same narrower-than-`is_correction_required` convention
agent/code_change_evaluation.py's own `build_code_change_evaluation`
already applies for its own INVALID/CHANGE_FAILED states.

This module never re-executes generated code, never modifies it, and
never re-applies/re-writes it - it only classifies an already-produced
`execute_generated_code` result, exactly like
`build_test_evaluation`/`build_code_change_evaluation`, which it
deliberately does not duplicate. `target_file` and `error` are always
read directly from the execution result, under their own keys, so a
caller can see exactly what this evaluation was based on without a
second lookup (requirement: "preserve the original ... execution
results").

Never raises: any input that isn't a real `execute_generated_code`
result is reported as `status=RESULT_INVALID`,
`correction_required=False`, `target_file=None`, `execution_status=
None`, `error=None`, never an exception - same "always return a
structured, honest verdict" convention `classify_test_result`/
`classify_code_change_result` already follow.
"""

from code_generation.generated_code_execution import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_REJECTED,
)
from .test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID

# The exact `execute_generated_code` status vocabulary, mapped onto
# this module's own, already-existing RESULT_* vocabulary - reused,
# never re-derived. Any status outside this mapping (there is none
# today - `execute_generated_code` only ever returns one of these
# four) falls back to `RESULT_INVALID` the same conservative way as a
# malformed input, rather than being left to raise a `KeyError`.
_EXECUTION_STATUS_TO_RESULT = {
    STATUS_EXECUTED: RESULT_PASSED,
    STATUS_FAILED: RESULT_FAILED,
    STATUS_TIMEOUT: RESULT_TIMEOUT,
    STATUS_REJECTED: RESULT_INVALID,
}

# Evaluation statuses that call for correction (requirement: "true
# only for FAILED or TIMEOUT") - a plain, explicit subset of this
# module's own RESULT_* vocabulary, reused unchanged from
# agent.test_result_evaluation.
_CORRECTION_REQUIRED_STATUSES = (RESULT_FAILED, RESULT_TIMEOUT)


def classify_generated_code_execution_result(execution_result):
    """Classify `execution_result` - expected to be an
    `execute_generated_code` result dict - into exactly one of
    `RESULT_PASSED`/`RESULT_FAILED`/`RESULT_TIMEOUT`/`RESULT_INVALID`,
    using only its own already-present `status` field. See this
    module's own docstring for the exact, fixed rule. Never raises."""
    if not isinstance(execution_result, dict):
        return RESULT_INVALID
    return _EXECUTION_STATUS_TO_RESULT.get(execution_result.get("status"), RESULT_INVALID)


def build_generated_code_execution_evaluation(execution_result):
    """Build the small, structured evaluation result
    `AgentLoop.evaluate_generated_code_execution_result`
    (agent/agent_loop.py) exposes, on top of - and without duplicating
    - `execute_generated_code`'s own already-computed result.

    Always returns:
        {
            "status": <one of RESULT_PASSED/RESULT_FAILED/
                       RESULT_TIMEOUT/RESULT_INVALID - see module
                       docstring>,
            "target_file": <execution_result["target_file"], or None
                            if execution_result isn't a dict>,
            "execution_status": <the exact, unmodified
                                 execution_result["status"] (one of
                                 STATUS_EXECUTED/STATUS_FAILED/
                                 STATUS_TIMEOUT/STATUS_REJECTED), or
                                 None if execution_result isn't a
                                 dict>,
            "error": <execution_result["error"], or None>,
            "correction_required": <bool - True only when "status" is
                                    RESULT_FAILED or RESULT_TIMEOUT>,
        }

    Every field beyond `status`/`correction_required` is read directly
    from `execution_result` - never re-derived, copied-with-changes,
    or invented - so a caller can see exactly what this evaluation was
    based on without a second lookup. Never raises: an
    `execution_result` that isn't a dict yields `None` for every
    passed-through field and `status=RESULT_INVALID`,
    `correction_required=False`, exactly as
    `classify_generated_code_execution_result` already reports for
    that same input."""
    status = classify_generated_code_execution_result(execution_result)
    is_dict = isinstance(execution_result, dict)

    return {
        "status": status,
        "target_file": execution_result.get("target_file") if is_dict else None,
        "execution_status": execution_result.get("status") if is_dict else None,
        "error": execution_result.get("error") if is_dict else None,
        "correction_required": status in _CORRECTION_REQUIRED_STATUSES,
    }
