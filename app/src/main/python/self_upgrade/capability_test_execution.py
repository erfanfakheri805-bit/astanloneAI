"""
Self-Upgrade - Capability Test Execution
=========================================
`run_capability_tests` is the next focused stage after controlled file
application (self_upgrade.capability_file_apply.apply_capability,
Prompt 364): running *only the focused tests for the newly applied
capability*, using the existing, unmodified sandboxed Python test
runner, and reporting a structured, JSON-shaped `CapabilityTestResult`
- never a raw subprocess transcript:

    CapabilityFileApply result (Prompt 364)
        -> run_capability_tests(apply_result, project_dir, test_target, ...)
        -> {capability_name, file_path, status, tests_run,
            tests_passed, tests_failed, execution_time, output,
            errors, timeout_seconds}

Reuses, never duplicates (requirement 4, 6):
  - `execution.python_test_runner_capability.
    create_python_test_runner_capability` is the *only* place this
    module ever spawns a subprocess, resolves/validates a test
    `target`, enforces an execution timeout, or strips the child
    process's environment. This module builds exactly the small input
    dict (`path`/`target`) that capability's own `input_schema`
    already expects and calls its own `Capability.execute` - no
    `subprocess` import anywhere in this module, and no second test
    runner, discovery mechanism, or timeout implementation.
  - `execution.project_structure_inspect_capability.
    _is_within_or_equal_allowed_dirs` and `execution.
    text_file_read_capability._resolve_allowed_dirs` are the exact,
    unchanged containment/allowed-directory helpers this module reuses
    to confirm the *applied file itself* (`apply_result["file_path"]`)
    sits inside the allowed workspace before ever asking the test
    runner to do anything - same functions
    `python_test_runner_capability.py` itself already reuses from
    those two modules, imported here rather than re-implemented a
    third time.
  - `code_generation.generated_code_validator.VALIDATION_VALID` is
    read, never re-derived: this module trusts the exact
    `validation_result` the apply result already carries (itself
    carried forward, unchanged, from the `CapabilityApplyRequest`,
    Prompt 363) rather than re-validating the source a second time.
  - Status vocabulary for the "did the write even succeed" question
    reuses, unchanged, `self_upgrade.capability_file_apply.
    STATUS_APPLIED` - never a re-derived or re-spelled copy.

Validates, before ever attempting execution (requirement 3):
    `apply_result` is a `CapabilityFileApply`-result-shaped dict at
        all;
    its own `status` is `APPLIED` (an `INVALID`/`BLOCKED` apply result
        is passed through as `INVALID`/`BLOCKED` respectively - never
        re-derived; a `FAILED` apply result - the write itself did not
        succeed, so there is no real file to test - is reported
        `INVALID`, since there is nothing left to safely execute);
    `file_path` is present and actually exists on disk (a `TOCTOU`-
        style final check - `apply_capability` already wrote it, but
        this module never assumes a file it hasn't itself just
        confirmed is still there);
    `file_path` resolves inside `allowed_dirs`/`project_dir` -
        requirement: "file is inside the allowed project/sandbox
        workspace" - checked with the exact, reused
        `_is_within_or_equal_allowed_dirs` helper described above;
    `validation_result` is present and its own `status` is
        `VALIDATION_VALID` - requirement: "the capability source was
        previously validated", read from the apply result, never
        recomputed;
    `test_target` - a required, caller-supplied, single, specific
        dotted test name or test file path (never `None`, never
        empty) - is present. This is the one deliberate design choice
        that makes requirement 5 ("execute only the focused tests for
        the newly created capability") actually true: this module
        never falls back to full-project `unittest discover`, which
        would run every `test_*.py` in `project_dir` - "arbitrary
        unrelated project code" requirement 6 explicitly forbids. A
        caller who wants a specific capability's own tests run must
        say exactly which ones; there is no default.
A request failing any of these is reported `STATUS_INVALID`, and no
execution is attempted.

Status vocabulary (requirement 8) - five values, each a single,
unambiguous verdict:
    `INVALID`  - `apply_result`/`test_target` failed one of the checks
                 above, or the upstream apply result's own `status`
                 was already `INVALID`/`FAILED`; OR the test runner's
                 own input validation rejected the call (a malformed
                 `path`/`target` this module's own checks did not
                 already catch); OR an unexpected environment error
                 (`OSError`, wrapped by `python_test_runner_capability`
                 as `ValueError("Could not run tests: ...")`) occurred
                 before any test could even start.
    `BLOCKED`  - the upstream apply result's own `status` was already
                 `BLOCKED`; OR `file_path` falls outside the allowed
                 workspace; OR the test runner itself refused
                 `project_dir`/`test_target` for a safety reason (path
                 outside allowed directories, target outside the
                 project directory, or a target that looks like a
                 command-line flag) - read straight off that
                 capability's own, unchanged error messages, never
                 re-checked independently here (see
                 `_classify_runner_error` below).
    `TIMEOUT`  - the test runner itself reported `timed_out: True`
                 (its own fixed, configurable execution ceiling was
                 hit; the child process was already terminated by
                 `subprocess.run` before this module ever sees the
                 result).
    `FAILED`   - the tests actually ran to completion but at least one
                 failed/errored (`success: False`, not a timeout).
    `PASSED`   - the tests ran to completion and every one passed
                 (`success: True`).

Safety requirements this module must NOT, and does not, violate
(requirement 6):
  - use the existing sandbox/test runner and its own, unchanged
    execution limits/timeouts - `timeout_seconds` is passed straight
    through to `create_python_test_runner_capability`, never widened
    or bypassed by this module;
  - never execute arbitrary unrelated project code - enforced by the
    required, specific `test_target` (see above); this module never
    calls the runner with `target=None`;
  - never access unrestricted filesystem locations - `allowed_dirs`
    is the exact same optional override the test runner itself already
    supports, passed straight through unchanged; this module never
    widens it, and independently re-checks `file_path` against it
    before ever calling the runner;
  - never access external services - this module has no network
    import of any kind; the test runner's own minimal subprocess
    environment (stripped of proxy/credential-shaped variables) is the
    only mitigation in play, unchanged;
  - never automatically retry - `run_capability_tests` is called once
    and returns once; a `FAILED`/`TIMEOUT`/`BLOCKED` result is never
    retried or re-attempted with different arguments by this module
    itself.

Never raises: a malformed `apply_result` is reported as an `INVALID`
result with every derivable field left empty/`None`, rather than
guessed - see `run_capability_tests` below.
"""

import os

from code_generation.generated_code_validator import VALIDATION_VALID
from execution.python_test_runner_capability import (
    create_python_test_runner_capability,
    DEFAULT_TIMEOUT_SECONDS,
)
from execution.project_structure_inspect_capability import _is_within_or_equal_allowed_dirs
from execution.text_file_read_capability import _resolve_allowed_dirs
from self_upgrade.capability_file_apply import (
    STATUS_APPLIED as APPLY_STATUS_APPLIED,
    STATUS_INVALID as APPLY_STATUS_INVALID,
    STATUS_BLOCKED as APPLY_STATUS_BLOCKED,
    STATUS_FAILED as APPLY_STATUS_FAILED,
    ALL_STATUSES as ALL_APPLY_STATUSES,
)

STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID"

ALL_STATUSES = (STATUS_PASSED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_BLOCKED, STATUS_INVALID)

_APPLY_RESULT_EXPECTED_KEYS = (
    "capability_name", "target_module", "status", "file_path",
    "bytes_written", "validation_result", "error",
)

# Substrings of the exact, unchanged error messages
# `python_test_runner_capability.make_python_test_runner_handler`
# already raises (see that module) - matched, never re-derived, so
# this module can tell its safety rejections (BLOCKED) apart from
# ordinary malformed-input rejections (INVALID) or an unexpected
# environment failure (also INVALID - nothing could even start).
_SAFETY_ERROR_MARKERS = (
    "is outside the allowed directories",
    "is outside the project directory",
    "must not look like a command-line option",
)


def _result(capability_name, file_path, status, tests_run, tests_passed,
            tests_failed, execution_time, output, errors, timeout_seconds):
    return {
        "capability_name": capability_name,
        "file_path": file_path,
        "status": status,
        "tests_run": tests_run,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "execution_time": execution_time,
        "output": output,
        "errors": list(errors),
        "timeout_seconds": timeout_seconds,
    }


def _invalid(capability_name, file_path, reason, timeout_seconds=None):
    return _result(
        capability_name, file_path, STATUS_INVALID,
        None, None, None, None, None, [reason], timeout_seconds,
    )


def _blocked(capability_name, file_path, reason, timeout_seconds=None):
    return _result(
        capability_name, file_path, STATUS_BLOCKED,
        None, None, None, None, None, [reason], timeout_seconds,
    )


def _classify_runner_error(error_message):
    """Read the exact, unchanged error message
    `python_test_runner_capability`'s `Capability.execute` already
    produced (`f"{type(exc).__name__}: {exc}"`, wrapping the handler's
    own `ValueError`) and classify it as BLOCKED (a safety rule the
    runner itself already enforced) or INVALID (malformed input, or an
    environment failure before any test could start) - never
    re-implements either check itself."""
    message = error_message or ""
    if any(marker in message for marker in _SAFETY_ERROR_MARKERS):
        return STATUS_BLOCKED
    return STATUS_INVALID


def run_capability_tests(
    apply_result, project_dir, test_target,
    allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Run the focused tests for a newly applied capability, via the
    existing, unmodified `python_test_runner` capability. See module
    docstring for the full status/safety rules.

    `project_dir` is the project/sandbox directory tests are run from
    (passed straight through as the test runner's own `path`); it is
    never guessed, never defaults to the real project source tree, and
    is always required.

    `test_target` is a required, specific dotted test name or test
    file path - see module docstring's "never arbitrary unrelated
    project code" rule. There is no discovery fallback.

    `allowed_dirs`, if given, is passed straight through to the test
    runner unchanged (and is also what `file_path` is independently
    checked against before execution); if omitted, defaults to
    `[project_dir]` only.

    `timeout_seconds` is passed straight through to the test runner
    unchanged; its own default is the test runner's own
    `DEFAULT_TIMEOUT_SECONDS`.

    Never mutates `apply_result`. Never executes unrelated project
    code, accesses locations outside `allowed_dirs`, accesses external
    services, retries, or bypasses the test runner's own sandboxing -
    see module docstring."""
    if not isinstance(apply_result, dict) or any(
        key not in apply_result for key in _APPLY_RESULT_EXPECTED_KEYS
    ):
        return _invalid(
            None, None,
            "apply_result must be a CapabilityFileApply result dict with "
            "all expected keys.",
            timeout_seconds=timeout_seconds,
        )

    capability_name = apply_result.get("capability_name")
    file_path = apply_result.get("file_path")
    validation_result = apply_result.get("validation_result")
    apply_status = apply_result.get("status")

    if apply_status not in ALL_APPLY_STATUSES:
        return _invalid(
            capability_name, file_path,
            f"apply_result has an unrecognized status: {apply_status!r}",
            timeout_seconds=timeout_seconds,
        )

    if apply_status == APPLY_STATUS_INVALID:
        return _invalid(
            capability_name, file_path,
            "Upstream CapabilityFileApply result is INVALID.",
            timeout_seconds=timeout_seconds,
        )

    if apply_status == APPLY_STATUS_FAILED:
        return _invalid(
            capability_name, file_path,
            "Upstream CapabilityFileApply result is FAILED - no file was "
            "actually written.",
            timeout_seconds=timeout_seconds,
        )

    if apply_status == APPLY_STATUS_BLOCKED:
        return _blocked(
            capability_name, file_path,
            "Upstream CapabilityFileApply result is BLOCKED.",
            timeout_seconds=timeout_seconds,
        )

    # apply_status == STATUS_APPLIED from here on - this module's own
    # pre-execution checks still apply (requirement 3).
    if not isinstance(file_path, str) or not file_path.strip():
        return _invalid(
            capability_name, file_path, "file_path is missing.",
            timeout_seconds=timeout_seconds,
        )

    if not os.path.isfile(file_path):
        return _invalid(
            capability_name, file_path,
            f"file_path does not exist: {file_path!r}",
            timeout_seconds=timeout_seconds,
        )

    if not isinstance(validation_result, dict) or validation_result.get("status") != VALIDATION_VALID:
        return _invalid(
            capability_name, file_path,
            "The capability source was not already validated.",
            timeout_seconds=timeout_seconds,
        )

    if not isinstance(project_dir, str) or not project_dir.strip():
        return _invalid(
            capability_name, file_path, "project_dir must be a non-empty string.",
            timeout_seconds=timeout_seconds,
        )

    if not isinstance(test_target, str) or not test_target.strip():
        return _invalid(
            capability_name, file_path,
            "test_target is required - a specific, focused test must be "
            "named; full-project discovery is never run by this stage.",
            timeout_seconds=timeout_seconds,
        )

    resolved_allowed_dirs = allowed_dirs if allowed_dirs is not None else [project_dir]
    real_file_path = os.path.realpath(file_path)
    if not _is_within_or_equal_allowed_dirs(
        real_file_path, _resolve_allowed_dirs(resolved_allowed_dirs)
    ):
        return _blocked(
            capability_name, file_path,
            f"file_path {file_path!r} is outside the allowed workspace.",
            timeout_seconds=timeout_seconds,
        )

    test_runner = create_python_test_runner_capability(
        allowed_dirs=resolved_allowed_dirs, timeout_seconds=timeout_seconds,
    )
    execution_result = test_runner.execute({"path": project_dir, "target": test_target})

    if not execution_result.success:
        status = _classify_runner_error(execution_result.error)
        result = _invalid if status == STATUS_INVALID else _blocked
        return result(
            capability_name, file_path, execution_result.error,
            timeout_seconds=timeout_seconds,
        )

    output = execution_result.output
    tests_run = output.get("tests_run")
    failures = output.get("failures")
    errors_count = output.get("errors")
    skipped = output.get("skipped")

    tests_failed = None
    if failures is not None and errors_count is not None:
        tests_failed = failures + errors_count

    tests_passed = None
    if tests_run is not None and tests_failed is not None:
        tests_passed = tests_run - tests_failed - (skipped or 0)

    stderr_text = output.get("stderr") or ""
    run_errors = [stderr_text] if stderr_text else []

    if output.get("timed_out"):
        return _result(
            capability_name, file_path, STATUS_TIMEOUT,
            tests_run, tests_passed, tests_failed,
            output.get("duration_seconds"), output.get("stdout"), run_errors,
            timeout_seconds,
        )

    status = STATUS_PASSED if output.get("success") else STATUS_FAILED
    return _result(
        capability_name, file_path, status,
        tests_run, tests_passed, tests_failed,
        output.get("duration_seconds"), output.get("stdout"), run_errors,
        timeout_seconds,
    )
