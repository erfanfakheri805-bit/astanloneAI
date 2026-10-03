"""
Agent - Code Correction Retest
=================================
Prompt 344: after one validated code correction has been applied
(agent/code_correction_application.py, Prompt 343 -
`AgentLoop.apply_code_correction`'s own result), run the existing
test/execution system again on the corrected file and compare that
retest against the original, already-produced failing result - never
a second, differently-behaving test runner or evaluator.

    correction_result (the exact dict `apply_code_correction`,
    Prompt 343, already returns: {"proposal", "validation_result",
    "application"})
        + original_test_result (the `python_test_runner` result that
          led to this correction in the first place)
        -> build_code_correction_retest()
        -> {correction_result, original_evaluation, retest_performed,
            retest_evaluation, comparison}

Reuses, never duplicates:
  - `execution.python_test_runner_capability.make_python_test_runner_handler`
    is called directly, unchanged, to run the retest - the exact same
    "python -m unittest" sandboxed runner every other test-running
    step in this project already goes through
    (execution/code_change_apply_and_test_capability.py calls the
    very same factory). This module adds no subprocess call, no
    allowed-directory check, and no timeout handling of its own.
  - `agent.test_result_evaluation.classify_test_result`/
    `build_test_evaluation` classify both the original result and the
    retest result - the exact same PASSED/FAILED/TIMEOUT/INVALID
    vocabulary used everywhere else in this project, never re-derived
    here a second way.

Retest gating (requirements 3, 4, 7) reads nothing but the two
already-computed facts a caller supplies:
  - `correction_result["application"]["status"]` must be
    `STATUS_APPLIED` (`agent.code_correction_application`'s own,
    already-computed verdict) - a `NOT_READY`/`REJECTED`/`ERROR`
    application never triggers a retest (requirement 4: "do not
    retest when the correction was rejected or not applied").
  - the *original* result must classify as `RESULT_FAILED` or
    `RESULT_TIMEOUT` - a `RESULT_PASSED` original result is
    structurally kept out of this path (requirement 7: "a successful
    original result must not enter the correction-retest path"),
    since a passing test was never something a correction should have
    been proposed for in the first place.

Both conditions must hold; either one being false means
`retest_performed=False`, `retest_evaluation=None`, `comparison=None`
- and, critically, the reused test-runner handler is never even
constructed on that path, let alone called (no test process is ever
started for a rejected/unapplied correction or an already-passing
original result).

At most one retest is ever run per call (requirements 8, 9): this
function calls the reused `python_test_runner` handler at most once,
never in a loop, and never automatically applies another correction
or retries the retest itself - a caller wanting another attempt must
explicitly call this function again with a freshly built
`correction_result`.

Both results are always preserved completely separately (requirement
5): `original_evaluation` (built from `original_test_result`) and
`retest_evaluation` (built from the freshly-run retest) are two
distinct fields, never merged into one blob, alongside the unmodified
`correction_result` itself.

The comparison (requirement 6) is a small, fixed, deterministic
mapping - see `compare_test_outcomes` below for the exact rule.

Never raises: a retest that cannot even start (an invalid/unsafe
project directory, or any other precondition the reused
`python_test_runner` handler itself raises for) is caught here and
reported via `retest_evaluation`'s own `RESULT_INVALID` classification
(built from a `None` retest result), never propagated - the same
"always return a structured, honest verdict" convention this
project's other evaluators already follow.
"""

import os

from execution.python_test_runner_capability import (
    DEFAULT_TIMEOUT_SECONDS,
    make_python_test_runner_handler,
)
from .code_correction_application import STATUS_APPLIED
from .test_result_evaluation import (
    RESULT_PASSED,
    RESULT_FAILED,
    RESULT_TIMEOUT,
    RESULT_INVALID,
    build_test_evaluation,
)

# Requirement 7's gate: only these two original classifications ever
# call for a retest at all - a successful (RESULT_PASSED) or
# unconfirmed (RESULT_INVALID) original result never enters this path.
_RETESTABLE_ORIGINAL_CLASSIFICATIONS = (RESULT_FAILED, RESULT_TIMEOUT)

# Fixed severity ordering used only to decide whether a retest outcome
# is *worse* than the original failure it followed (requirement 6's
# "regressed" rule) - never used for anything else, and never applied
# outside the two already-failing classifications this module gates
# on above. A timed-out run is treated as strictly worse than a plain
# failure (the process never even finished); RESULT_INVALID - the
# retest itself could not be confirmed one way or the other - is
# treated exactly as severely as a timeout, never assumed benign.
_SEVERITY = {
    RESULT_PASSED: 0,
    RESULT_FAILED: 1,
    RESULT_TIMEOUT: 2,
    RESULT_INVALID: 2,
}


def compare_test_outcomes(original_status, retest_status):
    """Deterministically compare an already-classified `original_status`
    (expected to be `RESULT_FAILED`/`RESULT_TIMEOUT` - see module
    docstring's gating rule) against an already-classified
    `retest_status`, into the small, fixed shape requirement 6
    describes.

    Always returns exactly:
        {
            "original_status": original_status,
            "retest_status": retest_status,
            "improved": <bool>,
            "regressed": <bool>,
            "unchanged": <bool>,
        }

    Exactly one of `improved`/`regressed`/`unchanged` is ever `True`.
    The fixed rule (requirement 6):
      - `retest_status == RESULT_PASSED` -> `improved=True`.
      - otherwise, `retest_status` strictly more severe than
        `original_status` (see `_SEVERITY` above - e.g. original
        FAILED, retest TIMEOUT or INVALID) -> `regressed=True`.
      - otherwise (retest still FAILED/TIMEOUT/INVALID, no more
        severe than the original) -> `unchanged=True` - this is the
        "original FAILED/TIMEOUT + retest FAILED/TIMEOUT" case the
        requirement calls out explicitly.

    Pure lookup over two already-computed classification strings: never
    re-classifies a raw test result itself, and never re-runs anything.
    Never raises for any input - an `original_status`/`retest_status`
    outside the known vocabulary is treated as maximally severe
    (`_SEVERITY.get(..., 2)`), the same conservative default
    `RESULT_INVALID` already uses, rather than silently assumed
    benign."""
    if retest_status == RESULT_PASSED:
        return {
            "original_status": original_status,
            "retest_status": retest_status,
            "improved": True,
            "regressed": False,
            "unchanged": False,
        }

    original_severity = _SEVERITY.get(original_status, 2)
    retest_severity = _SEVERITY.get(retest_status, 2)
    regressed = retest_severity > original_severity

    return {
        "original_status": original_status,
        "retest_status": retest_status,
        "improved": False,
        "regressed": regressed,
        "unchanged": not regressed,
    }


def build_code_correction_retest(
    correction_result, original_test_result, test_path=None, target=None,
    allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Run the existing `python_test_runner` system again against the
    file `correction_result` (Prompt 343's `apply_code_correction`
    result) reports as corrected, but only when that correction was
    actually applied and the original result it followed was a real
    failure - see module docstring for the exact gating rule - and
    compare the two.

    Always returns:
        {
            "correction_result": <the exact, unmodified
                correction_result this function was called with -
                requirement 1: "reuse the existing correction result
                from Prompt 343">,
            "original_evaluation": <the exact dict
                build_test_evaluation(original_test_result) itself
                would return - requirement 5: "preserve ... original
                execution/evaluation result">,
            "retest_performed": <bool - True only when the gate above
                held and the reused test-runner handler was actually
                invoked>,
            "retest_evaluation": <the exact dict
                build_test_evaluation(retest_test_result) itself
                would return, if "retest_performed" is True;
                otherwise None - requirement 5: "preserve ... 
                correction retest result">,
            "comparison": <the exact dict
                compare_test_outcomes(original_status, retest_status)
                itself would return, if "retest_performed" is True;
                otherwise None - requirement 6>,
        }

    `test_path`, if given, is the project directory the retest runs
    in; omitted, the directory of `correction_result["application"]
    ["target_file"]` is used - the file the correction actually
    modified, exactly the same "test the file that was just changed"
    default `code_change_apply_and_test` (execution/
    code_change_apply_and_test_capability.py) already uses. `target`,
    if given, selects one specific test the same way a direct
    `python_test_runner` call would. `allowed_dirs`/`timeout_seconds`
    are forwarded unchanged to the reused handler.

    Never runs a second test, never applies another correction, and
    never retries the retest itself (requirements 8, 9) - the reused
    `python_test_runner` handler is called, at most, exactly once.

    Never raises: a retest that cannot even start (an invalid/unsafe
    project directory, a missing file, or any other precondition the
    reused handler itself raises for) is caught here and reported as
    `retest_evaluation={"classification": "INVALID", "test_result":
    None}` (via `build_test_evaluation(None)`, unchanged) alongside a
    `comparison` computed against that `RESULT_INVALID` retest
    outcome, never an exception propagating out of this function."""
    is_dict = isinstance(correction_result, dict)
    application = correction_result.get("application") if is_dict else None
    application_status = application.get("status") if isinstance(application, dict) else None

    original_evaluation = build_test_evaluation(original_test_result)
    original_status = original_evaluation["classification"]

    if application_status != STATUS_APPLIED or original_status not in _RETESTABLE_ORIGINAL_CLASSIFICATIONS:
        return {
            "correction_result": correction_result,
            "original_evaluation": original_evaluation,
            "retest_performed": False,
            "retest_evaluation": None,
            "comparison": None,
        }

    target_file = application.get("target_file")
    resolved_test_path = (
        test_path if isinstance(test_path, str) and test_path.strip()
        else os.path.dirname(target_file) if isinstance(target_file, str) else None
    )

    test_data = {"path": resolved_test_path}
    if isinstance(target, str) and target.strip():
        test_data["target"] = target

    handler = make_python_test_runner_handler(
        allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds,
    )
    try:
        retest_test_result = handler(test_data)
    except Exception:
        retest_test_result = None

    retest_evaluation = build_test_evaluation(retest_test_result)
    comparison = compare_test_outcomes(original_status, retest_evaluation["classification"])

    return {
        "correction_result": correction_result,
        "original_evaluation": original_evaluation,
        "retest_performed": True,
        "retest_evaluation": retest_evaluation,
        "comparison": comparison,
    }
