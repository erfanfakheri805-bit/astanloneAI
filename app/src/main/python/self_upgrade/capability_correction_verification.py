"""
Self-Upgrade - Capability Correction Verification
==================================================
`verify_capability_correction` is the stage after controlled correction
application (self_upgrade.capability_correction_apply, Prompt 368):
explicitly re-running the capability's focused tests once and comparing
that result with the failure that triggered the correction:

    previous CapabilityTestResult (Prompt 365)
        + CapabilityCorrectionApplyResult (Prompt 368, APPLIED)
        + project_dir / test_target   (the same ones as the original run)
        -> verify_capability_correction(...)
        -> {capability_name, previous_test_result, retest_result,
            previous_status, retest_status, improved,
            correction_verified, status, errors, ...}

Reuses, never duplicates:
  - `capability_test_execution.run_capability_tests` (Prompt 365) is
    the only thing that runs tests - called exactly once. It owns the
    sandboxed `python_test_runner`, the allowed-workspace check, the
    required specific `test_target` and the timeout. No subprocess or
    second runner exists in this module.
  - `capability_evaluation.evaluate_capability_test_result` (Prompt 366)
    classifies both the previous and the retest result, so the
    before/after verdicts use the same vocabulary and consistency rules.
  - `run_capability_tests` needs a `CapabilityFileApply`-shaped input;
    it is built from the APPLIED correction (`capability_name`,
    `file_path`, `byte_size`, and a VALID `validation_result` only when
    the correction's own `code_validation` said the corrected source
    parsed - never assumed).

The caller passes the same `project_dir` and `test_target` as the
original test so the two runs are comparable (a `CapabilityTestResult`
does not record them). `timeout_seconds` defaults to the previous
result's own, when it has one.

Verification (before any test runs):
  - the previous result must be a well-formed failure (evaluation
    NEEDS_CORRECTION or FAILED);
  - the correction result must be APPLIED with `correction_applied`;
  - capability names match and file paths resolve to the same file.
Any failure is `INVALID` and nothing is run. Workspace containment and
execution permission are enforced by `run_capability_tests` itself
(`BLOCKED`/`INVALID` are read straight from its result).

Status (`status`):
    VERIFIED - retest evaluated SUCCESS (`correction_verified=True`).
    FAILED   - retest still failing (NEEDS_CORRECTION/FAILED).
    TIMEOUT  - retest timed out.
    BLOCKED  - retest was blocked.
    INVALID  - inputs invalid/inconsistent, or the retest result was
               INVALID/inconsistent.
`improved` is True for VERIFIED, and for FAILED when the retest has
fewer failing tests than the previous run; otherwise False.

The previous result, the retest result, both evaluations and the
correction result are all preserved (deep copies). Nothing is modified,
corrected, retried, registered or activated - this module never writes
a file. Never raises.
"""

import copy
import os

from code_generation.generated_code_validator import VALIDATION_VALID
from self_upgrade.capability_correction_apply import STATUS_APPLIED as CORRECTION_APPLIED
from self_upgrade.capability_evaluation import (
    evaluate_capability_test_result,
    EVAL_SUCCESS, EVAL_FAILED, EVAL_TIMEOUT, EVAL_BLOCKED, EVAL_INVALID,
    EVAL_NEEDS_CORRECTION,
)
from self_upgrade.capability_file_apply import STATUS_APPLIED as APPLY_STATUS_APPLIED
from self_upgrade.capability_test_execution import (
    run_capability_tests,
    DEFAULT_TIMEOUT_SECONDS,
)

STATUS_VERIFIED = "VERIFIED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID"

ALL_STATUSES = (STATUS_VERIFIED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID)

_RETEST_STATUS_MAP = {
    EVAL_SUCCESS: STATUS_VERIFIED,
    EVAL_NEEDS_CORRECTION: STATUS_FAILED,
    EVAL_FAILED: STATUS_FAILED,
    EVAL_TIMEOUT: STATUS_TIMEOUT,
    EVAL_BLOCKED: STATUS_BLOCKED,
    EVAL_INVALID: STATUS_INVALID,
}


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _copy(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return None


def _result(status, previous, correction, previous_evaluation=None, retest=None,
            retest_evaluation=None, errors=None, improved=False):
    previous_dict = previous if isinstance(previous, dict) else {}
    correction_dict = correction if isinstance(correction, dict) else {}
    return {
        "capability_name": previous_dict.get("capability_name") or correction_dict.get("capability_name"),
        "file_path": previous_dict.get("file_path") or correction_dict.get("file_path"),
        "previous_test_result": _copy(previous),
        "retest_result": _copy(retest),
        "previous_status": previous_dict.get("status"),
        "retest_status": retest.get("status") if isinstance(retest, dict) else None,
        "previous_evaluation": previous_evaluation,
        "retest_evaluation": retest_evaluation,
        "improved": bool(improved),
        "correction_verified": status == STATUS_VERIFIED,
        "status": status,
        "errors": list(errors or []),
        "correction_apply_result": _copy(correction),
    }


def _invalid(previous, correction, message, previous_evaluation=None):
    return _result(STATUS_INVALID, previous, correction,
                   previous_evaluation=previous_evaluation, errors=[message])


def _fewer_failures(previous, retest):
    before, after = previous.get("tests_failed"), retest.get("tests_failed")
    return (isinstance(before, int) and isinstance(after, int)
            and not isinstance(before, bool) and not isinstance(after, bool)
            and after < before)


def verify_capability_correction(previous_test_result, correction_apply_result,
                                 project_dir, test_target, allowed_dirs=None,
                                 timeout_seconds=None):
    """Retest a capability once after an APPLIED correction and compare
    with the previous failure. See module docstring. Never raises."""
    try:
        return _verify(previous_test_result, correction_apply_result, project_dir,
                       test_target, allowed_dirs, timeout_seconds)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(STATUS_INVALID, previous_test_result, correction_apply_result,
                       errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _verify(previous, correction, project_dir, test_target, allowed_dirs, timeout_seconds):
    previous_evaluation = evaluate_capability_test_result(previous)
    if previous_evaluation["evaluation_status"] not in (EVAL_NEEDS_CORRECTION, EVAL_FAILED):
        return _invalid(previous, correction,
                        "previous_test_result must be a well-formed failed test result "
                        f"(evaluated {previous_evaluation['evaluation_status']}).",
                        previous_evaluation)

    if not isinstance(correction, dict) or "status" not in correction:
        return _invalid(previous, correction,
                        "correction_apply_result must be a CapabilityCorrectionApplyResult dict.",
                        previous_evaluation)
    if correction.get("status") != CORRECTION_APPLIED or correction.get("correction_applied") is not True:
        return _invalid(previous, correction,
                        f"Only an APPLIED correction can be retested (status={correction.get('status')!r}).",
                        previous_evaluation)

    name, file_path = correction.get("capability_name"), correction.get("file_path")
    if not _non_blank(name) or name != previous["capability_name"]:
        return _invalid(previous, correction,
                        "Capability name of the correction does not match the previous test result.",
                        previous_evaluation)
    if not _non_blank(file_path) or \
            os.path.realpath(file_path) != os.path.realpath(previous["file_path"]):
        return _invalid(previous, correction,
                        "File path of the correction does not match the previous test result.",
                        previous_evaluation)

    code_validation = correction.get("code_validation")
    if not isinstance(code_validation, dict) or code_validation.get("valid") is not True:
        return _invalid(previous, correction,
                        "The applied correction has no confirmed valid-source check.",
                        previous_evaluation)

    metadata = correction.get("change_metadata") if isinstance(correction.get("change_metadata"), dict) else {}
    apply_shaped = {
        "capability_name": name,
        "target_module": None,
        "status": APPLY_STATUS_APPLIED,
        "file_path": file_path,
        "bytes_written": metadata.get("byte_size"),
        "validation_result": {"status": VALIDATION_VALID, "error": None},
        "error": None,
    }
    if timeout_seconds is None:
        previous_timeout = previous.get("timeout_seconds")
        timeout_seconds = previous_timeout if isinstance(previous_timeout, (int, float)) \
            and not isinstance(previous_timeout, bool) else DEFAULT_TIMEOUT_SECONDS

    retest = run_capability_tests(
        apply_shaped, project_dir, test_target,
        allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds)
    retest_evaluation = evaluate_capability_test_result(retest)
    status = _RETEST_STATUS_MAP[retest_evaluation["evaluation_status"]]

    errors = []
    if status != STATUS_VERIFIED:
        reason = retest_evaluation.get("failure_reason")
        errors = [reason] if reason else [f"Retest was {status}."]
    improved = status == STATUS_VERIFIED or (
        status == STATUS_FAILED and _fewer_failures(previous, retest))
    return _result(status, previous, correction, previous_evaluation, retest,
                   retest_evaluation, errors, improved)
