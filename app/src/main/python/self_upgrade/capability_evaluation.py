"""
Self-Upgrade - Capability Evaluation
=====================================
`evaluate_capability_test_result` is the next focused stage after
controlled capability test execution
(self_upgrade.capability_test_execution.run_capability_tests,
Prompt 365): turning the already-produced, JSON-shaped
`CapabilityTestResult` into one structured, honest verdict that a
future correction system can act on:

    CapabilityTestResult (Prompt 365)
        -> evaluate_capability_test_result(test_result)
        -> {capability_name, evaluation_status, success, failure_reason,
            tests_run, tests_passed, tests_failed, errors,
            correction_required, file_path, output, execution_time,
            timeout_seconds, timed_out, test_result_status,
            original_test_result}

Reuses, never duplicates:
  - `capability_test_execution.STATUS_*` / `ALL_STATUSES` - the exact
    input vocabulary (PASSED/FAILED/TIMEOUT/BLOCKED/INVALID) and the
    exact `CapabilityTestResult` key set (`_result`'s own shape) this
    module reads; nothing is re-spelled or re-run.
  - the same "dict in, dict out, never raises, `correction_required`
    boolean" convention `agent.code_change_evaluation` and
    `agent.generated_code_execution_evaluation` already follow. This
    module adds no test runner, no subprocess, no file access and no
    second classifier of *how* tests ran - it only reads the fields
    the test-execution stage already computed.

Evaluation status (fixed, one per input):
    SUCCESS           - PASSED, and internally consistent.
    NEEDS_CORRECTION  - FAILED, and useful failure information exists
                        (`tests_failed > 0`, a non-blank error, or
                        non-blank output).
    FAILED            - FAILED, but nothing usable to correct from.
    TIMEOUT           - TIMEOUT (timeout information preserved).
    BLOCKED           - BLOCKED (passed through, never re-derived).
    INVALID           - INVALID (passed through), OR the result is not
                        a CapabilityTestResult dict, is missing keys,
                        has an unrecognised status, or is incomplete /
                        inconsistent (e.g. PASSED with failing tests,
                        PASSED with no tests run, negative or
                        non-integer counts, `passed + failed > run`,
                        missing capability_name/file_path for an
                        executed result, `errors` not a list).

`correction_required` is True for NEEDS_CORRECTION and TIMEOUT only -
the same "final FAILED or TIMEOUT test status calls for correction"
convention `agent.code_change_evaluation` already uses. SUCCESS,
FAILED (nothing to correct from), BLOCKED and INVALID are False: a
blocked/invalid result needs a different input, not a code correction.

Read-only by construction: never modifies project files or the input
(`original_test_result` is a deep copy), never corrects, retries,
activates, registers or installs anything. Never raises.
"""

import copy

from self_upgrade.capability_test_execution import (
    STATUS_PASSED as TEST_STATUS_PASSED,
    STATUS_FAILED as TEST_STATUS_FAILED,
    STATUS_TIMEOUT as TEST_STATUS_TIMEOUT,
    STATUS_BLOCKED as TEST_STATUS_BLOCKED,
    STATUS_INVALID as TEST_STATUS_INVALID,
    ALL_STATUSES as ALL_TEST_STATUSES,
)

EVAL_SUCCESS = "SUCCESS"
EVAL_FAILED = "FAILED"
EVAL_TIMEOUT = "TIMEOUT"
EVAL_BLOCKED = "BLOCKED"
EVAL_INVALID = "INVALID"
EVAL_NEEDS_CORRECTION = "NEEDS_CORRECTION"

ALL_EVALUATION_STATUSES = (
    EVAL_SUCCESS, EVAL_FAILED, EVAL_TIMEOUT,
    EVAL_BLOCKED, EVAL_INVALID, EVAL_NEEDS_CORRECTION,
)

_EXPECTED_KEYS = (
    "capability_name", "file_path", "status", "tests_run", "tests_passed",
    "tests_failed", "execution_time", "output", "errors", "timeout_seconds",
)
_COUNT_KEYS = ("tests_run", "tests_passed", "tests_failed")
_EXECUTED_STATUSES = (TEST_STATUS_PASSED, TEST_STATUS_FAILED, TEST_STATUS_TIMEOUT)
_CORRECTION_REQUIRED_STATUSES = (EVAL_NEEDS_CORRECTION, EVAL_TIMEOUT)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _find_inconsistency(test_result):
    """Return a human-readable reason if `test_result` is incomplete or
    inconsistent, else None. Assumes a dict with all expected keys and a
    recognised status."""
    status = test_result["status"]
    errors = test_result["errors"]

    if not isinstance(errors, list) or not all(isinstance(e, str) for e in errors):
        return "errors must be a list of strings."

    for key in _COUNT_KEYS:
        value = test_result[key]
        if value is not None and not _is_count(value):
            return f"{key} must be a non-negative integer or None, got {value!r}."

    run, passed, failed = (test_result[key] for key in _COUNT_KEYS)
    if run is not None and passed is not None and failed is not None \
            and passed + failed > run:
        return "tests_passed + tests_failed exceeds tests_run."
    if run is not None and passed is not None and passed > run:
        return "tests_passed exceeds tests_run."
    if run is not None and failed is not None and failed > run:
        return "tests_failed exceeds tests_run."

    if status in _EXECUTED_STATUSES:
        if not _non_blank(test_result["capability_name"]):
            return "capability_name is missing."
        if not _non_blank(test_result["file_path"]):
            return "file_path is missing."

    if status == TEST_STATUS_PASSED:
        if run is None or passed is None or failed is None:
            return "PASSED result is missing test counts."
        if run == 0:
            return "PASSED result ran no tests."
        if failed != 0:
            return "PASSED result reports failed tests."
        if passed == 0:
            return "PASSED result reports no passed tests."

    return None


def _has_useful_failure_info(test_result):
    failed = test_result["tests_failed"]
    if _is_count(failed) and failed > 0:
        return True
    if any(_non_blank(e) for e in test_result["errors"]):
        return True
    return _non_blank(test_result["output"])


def _build(test_result, evaluation_status, failure_reason, original, valid_shape):
    def field(key):
        return test_result.get(key) if valid_shape else None

    errors = test_result.get("errors") if valid_shape else None
    return {
        "capability_name": field("capability_name"),
        "evaluation_status": evaluation_status,
        "success": evaluation_status == EVAL_SUCCESS,
        "failure_reason": failure_reason,
        "tests_run": field("tests_run"),
        "tests_passed": field("tests_passed"),
        "tests_failed": field("tests_failed"),
        "errors": list(errors) if isinstance(errors, list) else [],
        "correction_required": evaluation_status in _CORRECTION_REQUIRED_STATUSES,
        "file_path": field("file_path"),
        "output": field("output"),
        "execution_time": field("execution_time"),
        "timeout_seconds": field("timeout_seconds"),
        "timed_out": evaluation_status == EVAL_TIMEOUT,
        "test_result_status": field("status"),
        "original_test_result": original,
    }


def _first_error(test_result):
    for error in test_result.get("errors") or []:
        if _non_blank(error):
            return error.strip()
    return None


def evaluate_capability_test_result(test_result):
    """Evaluate a `CapabilityTestResult` (the dict
    `run_capability_tests` returns) into a structured
    `CapabilityEvaluationResult` dict. See module docstring for the
    fixed rules. Never raises, never mutates `test_result`."""
    if not isinstance(test_result, dict):
        return _build({}, EVAL_INVALID,
                      "test_result must be a CapabilityTestResult dict.", None, False)

    try:
        original = copy.deepcopy(test_result)
    except Exception:
        original = None

    if any(key not in test_result for key in _EXPECTED_KEYS):
        return _build(test_result, EVAL_INVALID,
                      "test_result is missing expected CapabilityTestResult keys.",
                      original, False)

    status = test_result["status"]
    if status not in ALL_TEST_STATUSES:
        return _build(test_result, EVAL_INVALID,
                      f"test_result has an unrecognized status: {status!r}.",
                      original, False)

    problem = _find_inconsistency(test_result)
    if problem is not None:
        return _build(test_result, EVAL_INVALID,
                      f"Incomplete or inconsistent test result: {problem}",
                      original, True)

    if status == TEST_STATUS_PASSED:
        return _build(test_result, EVAL_SUCCESS, None, original, True)

    if status == TEST_STATUS_TIMEOUT:
        seconds = test_result["timeout_seconds"]
        reason = "Capability tests timed out"
        reason += f" after {seconds} seconds." if seconds is not None else "."
        return _build(test_result, EVAL_TIMEOUT, reason, original, True)

    if status == TEST_STATUS_BLOCKED:
        reason = _first_error(test_result) or "Capability test execution was blocked."
        return _build(test_result, EVAL_BLOCKED, reason, original, True)

    if status == TEST_STATUS_INVALID:
        reason = _first_error(test_result) or "Capability test execution was invalid."
        return _build(test_result, EVAL_INVALID, reason, original, True)

    # TEST_STATUS_FAILED
    failed = test_result["tests_failed"]
    if _has_useful_failure_info(test_result):
        reason = (f"{failed} capability test(s) failed."
                  if _is_count(failed) and failed > 0
                  else "Capability tests failed.")
        return _build(test_result, EVAL_NEEDS_CORRECTION, reason, original, True)
    return _build(test_result, EVAL_FAILED,
                  "Capability tests failed with no usable failure information.",
                  original, True)
