"""
Self-Upgrade - First-Pass Test Verification (Prompt 384 integration hook)
==========================================================================
`verify_capability_first_pass` is the one small hook the end-to-end
dry run (Prompt 384) needed between two *existing, unchanged* stages:

    run_capability_tests (Prompt 365)         -> CapabilityTestResult
    evaluate_capability_test_result (366)     -> CapabilityEvaluation
    ???
    request_capability_human_approval (370)   -> version snapshot +
                                                 HumanApprovalRequest

`request_capability_human_approval` only ever accepts a
`CapabilityCorrectionVerificationResult` whose `status` is
`STATUS_VERIFIED` (`verify_capability_correction`, Prompt 369) - the
result of re-running the tests *after a correction was applied*. A
capability whose very first focused test run already PASSED has no
failure to correct, so no such result exists for it, and nothing in the
project turned a first-pass PASS into the input the snapshot stage
reads. This function is exactly that bridge - nothing more:

    CapabilityTestResult (PASSED, Prompt 365)
        -> verify_capability_first_pass(test_result)
        -> CapabilityCorrectionVerificationResult-shaped dict
           {status=VERIFIED, capability_name, file_path, retest_result,
            retest_evaluation, ...}

It does NOT weaken the "only a verified result may reach a snapshot"
rule; it applies that same rule to a first-pass result:

  - The result is judged by the existing, unchanged
    `capability_evaluation.evaluate_capability_test_result`, and its
    verdict is mapped to a status through the exact same
    `_RETEST_STATUS_MAP` `verify_capability_correction` already uses.
    Only an evaluation of SUCCESS (a genuinely PASSED, self-consistent
    test result) becomes `VERIFIED`; a FAILED / NEEDS_CORRECTION /
    TIMEOUT / BLOCKED / INVALID result becomes the matching non-VERIFIED
    status, which `request_capability_human_approval` already refuses
    (INVALID - no snapshot, no approval request).
  - A VERIFIED result additionally needs a non-blank `capability_name`
    and `file_path`; without them it is INVALID, never guessed.

THIS FUNCTION ONLY RE-LABELS AN ALREADY-PRODUCED TEST RESULT. It never
runs a test, never spawns a process, never reads or writes a file,
never creates a version snapshot, never approves or rejects anything,
never registers, activates, or executes a capability (or any generated
code), and never retries. `correction_verified` is always `False`
(no correction was applied) and `correction_apply_result` /
`previous_test_result` / `previous_evaluation` are always `None`; the
extra `verification_basis` key says why. Never mutates `test_result`;
never raises.
"""

import copy

from self_upgrade.capability_correction_verification import (
    STATUS_VERIFIED,
    STATUS_INVALID,
    _RETEST_STATUS_MAP,
    _non_blank,
)
from self_upgrade.capability_evaluation import evaluate_capability_test_result

VERIFICATION_BASIS_FIRST_PASS = "FIRST_PASS_TESTS"


def _copy(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return None


def _result(status, test_result, evaluation=None, errors=None):
    """Same keys as `capability_correction_verification._result`, plus
    `verification_basis`."""
    test_dict = test_result if isinstance(test_result, dict) else {}
    return {
        "capability_name": test_dict.get("capability_name"),
        "file_path": test_dict.get("file_path"),
        "previous_test_result": None,
        "retest_result": _copy(test_result) if isinstance(test_result, dict) else None,
        "previous_status": None,
        "retest_status": test_dict.get("status"),
        "previous_evaluation": None,
        "retest_evaluation": evaluation,
        "improved": False,
        "correction_verified": False,
        "status": status,
        "errors": list(errors or []),
        "correction_apply_result": None,
        "verification_basis": VERIFICATION_BASIS_FIRST_PASS,
    }


def verify_capability_first_pass(test_result):
    """Package an already-produced first-run `CapabilityTestResult` (the
    dict `run_capability_tests` returns) as the VERIFIED-shaped
    verification result `request_capability_human_approval` reads. See
    the module docstring for the full rules. Never raises."""
    try:
        return _verify(test_result)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(STATUS_INVALID, test_result,
                       errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _verify(test_result):
    if not isinstance(test_result, dict):
        return _result(STATUS_INVALID, test_result,
                       errors=["test_result must be a CapabilityTestResult dict."])

    evaluation = evaluate_capability_test_result(test_result)
    status = _RETEST_STATUS_MAP[evaluation["evaluation_status"]]

    if status != STATUS_VERIFIED:
        reason = evaluation.get("failure_reason")
        return _result(status, test_result, evaluation,
                       errors=[reason] if reason else [f"First-pass tests were {status}."])

    problems = []
    if not _non_blank(test_result.get("capability_name")):
        problems.append("capability_name is missing from the test result.")
    if not _non_blank(test_result.get("file_path")):
        problems.append("file_path is missing from the test result.")
    if problems:
        return _result(STATUS_INVALID, test_result, evaluation, errors=problems)

    return _result(STATUS_VERIFIED, test_result, evaluation)
