"""
Code Generation - Generated Code Execution
==============================================
Connects an already-generated (Prompt 335), validated (Prompt 336),
and safely-written (Prompt 337) `CodeGenerationResult`
(code_generation.code_generation_result.CodeGenerationResult) to this
project's *existing* sandbox/test-execution machinery, so a newly
generated Python file can actually be run - never a second,
duplicate sandbox, and never a new, unbounded "run arbitrary code"
facility:

    CodeGenerationResult -> execute_generated_code()
        -> {status, target_file, stdout, stderr, error}

Reuses, never duplicates:
  - `code_generation.generated_code_applier.apply_generated_code` is
    called directly, unchanged, to (re)validate and write the file -
    this module never re-implements the revalidation, the create-
    only/never-overwrite write, or the allowed-directory containment
    check that step already performs.
  - `self_upgrade.sandbox.Sandbox` - the project's existing, already-
    used-elsewhere (`self_upgrade/upgrade_system.py`,
    `diagnostics/health_system.py`) static, non-executing gate - is
    reused, unchanged, as one more defense-in-depth check immediately
    before execution is attempted, exactly the same way
    `UpgradeSystem` already gates its own `install` stage on it. This
    module never modifies `self_upgrade/sandbox.py`, and never adds a
    second sandbox class.
  - `execution.python_test_runner_capability`'s own safe-execution
    primitives - `DEFAULT_TIMEOUT_SECONDS` and
    `_minimal_subprocess_environment` - are imported and used
    unchanged, rather than a second, differently-behaving timeout
    constant or environment-scrubbing routine being invented here.
    `execution.text_file_read_capability`'s `_resolve_allowed_dirs`/
    `_is_within_allowed_dirs` (the exact same allowed-directory
    containment check `python_test_runner_capability.py` itself
    reuses from that module, and `text_file_write_capability.py`
    already used to write this very file) are reused the same way, so
    the file that gets executed is independently re-checked against
    exactly the same allowed-directory rule, rather than trusting the
    write step's check alone.

    Deliberately *not* dispatched through `python_test_runner`'s own
    `python -m unittest <target>` invocation: that path is exactly
    right for *running a project's tests*, but a generated file that
    defines a plain function (the only kind `local_function_generator`
    produces today) contains no `unittest.TestCase` - `unittest`
    itself would report "no tests ran" for that file and, on the
    Python versions where that is treated as a failure, would make
    perfectly good generated code look like a failed execution. This
    module instead runs the file directly - `[sys.executable,
    target_file]`, the ordinary way to execute a Python script - using
    the same `subprocess.run(..., shell=False, capture_output=True,
    text=True, timeout=..., env=<minimal>)` shape and the same
    reused timeout/environment primitives `python_test_runner`
    already established, so a caller gets a true "did this file run
    without error" verdict rather than an artifact of test discovery.
  - `agent.test_result_evaluation.classify_test_result` is called
    directly, unchanged, against a small `{"success", "timed_out"}`
    dict built from the subprocess outcome - the exact same
    `PASSED`/`FAILED`/`TIMEOUT`/`INVALID` classification every other
    consumer of a `python_test_runner`-shaped result already uses, so
    this module never re-derives a pass/fail/timeout judgement of its
    own from a return code and a timeout flag.

Execute only files inside the allowed project/sandbox directory
(requirement 4): the file actually executed is always the exact,
already-resolved `target_file` `apply_generated_code` itself just
wrote to - a path that has, by construction, already passed that
step's own allowed-directory check - and this module independently
re-checks that same real, resolved path against `allowed_dirs` (via
`_resolve_allowed_dirs`/`_is_within_allowed_dirs`) immediately before
ever building a subprocess argv, rejecting rather than executing on
any mismatch.

Never allows arbitrary shell commands, network access, package
installation, or execution outside the allowed directory (requirement
5): the subprocess argv is always exactly `[sys.executable,
target_file]` - never a string built by concatenating caller input,
never `shell=True` anywhere in this module - and the child process
gets only the same small, explicit, minimal environment
`python_test_runner_capability._minimal_subprocess_environment`
already builds (no inherited proxy/credential variables); this module
makes no package-manager/pip call and no network call of its own.

Uses the existing timeout mechanism (requirement 7): `timeout_seconds`
(defaulting to the reused, unchanged `DEFAULT_TIMEOUT_SECONDS`) is
passed straight through to `subprocess.run(timeout=...)`, and a
`subprocess.TimeoutExpired` - which `subprocess.run` itself has
already used to terminate the child process before raising - is caught
here and reported as a safe, structured `STATUS_TIMEOUT` result, never
an unhandled exception or a runaway process.

Never modifies the generated code after execution, and never performs
a second execution of its own (requirements 8, 9): the file is opened
for writing exactly once, inside the reused `apply_generated_code`
call, before execution is even attempted; nothing after that point
opens `target_file` for writing again, and the subprocess is started
exactly once per `execute_generated_code` call - no loop, no retry, no
automatic re-run on failure or timeout.

No second sandbox or test runner (requirement 10): this module adds
exactly one, narrowly-scoped `subprocess.run` call of its own (the
same "one deliberate use of subprocess.run for a real capability, not
a general shell" convention `python_test_runner_capability.py`'s own
docstring already documents for itself) and reuses everything else -
`Sandbox`, the timeout constant, the environment builder, the
allowed-directory check, and the pass/fail/timeout classifier - rather
than building any of it a second time.
"""

import os
import subprocess
import sys

from .code_generation_result import CodeGenerationResult
from .generated_code_applier import apply_generated_code, STATUS_APPLIED
from execution.python_test_runner_capability import (
    DEFAULT_TIMEOUT_SECONDS,
    _minimal_subprocess_environment,
)
from execution.text_file_read_capability import _resolve_allowed_dirs, _is_within_allowed_dirs
from agent.test_result_evaluation import classify_test_result
from self_upgrade.sandbox import Sandbox

STATUS_EXECUTED = "EXECUTED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_REJECTED = "REJECTED"

ALL_EXECUTION_STATUSES = (STATUS_EXECUTED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_REJECTED)

# The exact classify_test_result() vocabulary, mapped onto this
# module's own status vocabulary - reused, never re-derived. "INVALID"
# (a malformed result shape) is not reachable here - the dict handed
# to classify_test_result always carries real bool "success"/
# "timed_out" fields this module itself just built - but is still
# mapped, defensively, the same conservative way as "FAILED" rather
# than left to fall through to an unhandled label.
_CLASSIFICATION_TO_STATUS = {
    "PASSED": STATUS_EXECUTED,
    "FAILED": STATUS_FAILED,
    "TIMEOUT": STATUS_TIMEOUT,
    "INVALID": STATUS_FAILED,
}


def _rejected(error, target_file=None):
    return {
        "status": STATUS_REJECTED,
        "target_file": target_file,
        "stdout": None,
        "stderr": None,
        "error": error,
    }


def execute_generated_code(result, allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """Safely execute an already-generated `CodeGenerationResult`
    (Prompt 335), the single, small "controlled execution step" this
    module adds (requirement 2).

    `allowed_dirs`, if given, is forwarded unchanged into
    `apply_generated_code`'s write step and used again, unchanged, for
    this module's own pre-execution containment check, so the file
    that gets written and the file that gets executed always agree on
    exactly the same set of allowed directories. `timeout_seconds`, if
    given, replaces the reused `DEFAULT_TIMEOUT_SECONDS` default
    (requirement 7).

    Always returns:
        {
            "status": one of ALL_EXECUTION_STATUSES,
            "target_file": <str or None - see below>,
            "stdout": <str, or None when execution was never
                       attempted>,
            "stderr": <str, or None when execution was never
                       attempted>,
            "error": <str, or None only for STATUS_EXECUTED>,
        }

    Execution is allowed only when all three of these hold
    (requirement 3), checked in this fixed order, the first failure
    short-circuiting the rest - never executed otherwise:
      1. `result` is actually a `CodeGenerationResult` whose own
         generation `status` is `STATUS_GENERATED` (`result.success`) -
         "code generation succeeded".
      2. Revalidating and writing it via the existing, unchanged
         `apply_generated_code` reports `STATUS_APPLIED` - this alone
         already covers both "validation status is VALID"
         (`apply_generated_code` itself revalidates before writing)
         and "file creation succeeded" (nothing is ever executed from
         a file that was not actually just written to disk).
      3. The existing, unchanged `self_upgrade.sandbox.Sandbox` static
         gate passes for the file about to be executed - one more
         defense-in-depth check, the same one `UpgradeSystem` already
         requires to pass before its own `install` stage.

    Any failure of 1-3, or of this module's own independent
    allowed-directory recheck on the file `apply_generated_code`
    reported, is `STATUS_REJECTED`, with `target_file` set to whatever
    is already known at that point and `stdout`/`stderr` left `None` -
    nothing was ever executed.

    Once a subprocess is actually started, the outcome is classified
    with the existing, unchanged `classify_test_result` into
    `STATUS_EXECUTED` (exited with return code 0), `STATUS_FAILED`
    (ran, but exited non-zero), or `STATUS_TIMEOUT` (the existing
    timeout mechanism cut it off) - `stdout`/`stderr` are always the
    exact strings the subprocess itself produced.

    Never raises: an `OSError` starting the subprocess (e.g. the
    interpreter could not be launched) is caught and reported as a
    structured `STATUS_REJECTED` failure rather than propagated, same
    "report, don't crash, for a substantive judgement" convention this
    project's other reused-capability call sites already follow."""
    if not isinstance(result, CodeGenerationResult):
        return _rejected(f"Expected a CodeGenerationResult, got {type(result).__name__}.")

    if not result.success:
        return _rejected(
            f"Code generation did not succeed (status={result.status!r}); "
            f"refusing to execute it.",
            target_file=result.target_file,
        )

    # Reused, unmodified: revalidates (VALIDATION_VALID) and writes
    # (create-only) the file exactly as a standalone apply_generated_code
    # call would. Covers requirement 3's remaining two conditions.
    application = apply_generated_code(result, allowed_dirs=allowed_dirs)
    if application["status"] != STATUS_APPLIED:
        return _rejected(application["error"], target_file=application["target_file"])

    target_file = application["target_file"]

    # Reused, unmodified: the same static, non-executing gate
    # `self_upgrade/upgrade_system.py` and `diagnostics/health_system.py`
    # already require to pass before their own real actions.
    sandbox_result = Sandbox().run(
        {"name": os.path.basename(target_file), "description": f"Execute generated code at {target_file}"}
    )
    if not sandbox_result.passed:
        return _rejected(sandbox_result.details, target_file=target_file)

    # Reused, unmodified: the exact same allowed-directory containment
    # check `python_test_runner_capability.py` itself already reuses
    # from this same module - an independent recheck of the path
    # apply_generated_code just wrote to, never trusted blindly.
    resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
    real_target = os.path.realpath(target_file)
    if not _is_within_allowed_dirs(real_target, resolved_allowed_dirs):
        return _rejected(
            f"Path {target_file!r} is outside the allowed directories.",
            target_file=target_file,
        )
    if not os.path.isfile(real_target):
        return _rejected(f"Generated file does not exist: {target_file!r}", target_file=target_file)

    argv = [sys.executable, real_target]
    env = _minimal_subprocess_environment()

    try:
        completed = subprocess.run(
            argv,
            cwd=os.path.dirname(real_target),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        classification = classify_test_result({"success": False, "timed_out": True})
        return {
            "status": _CLASSIFICATION_TO_STATUS.get(classification, STATUS_TIMEOUT),
            "target_file": target_file,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "error": f"Execution of {target_file!r} timed out after {timeout_seconds} seconds.",
        }
    except OSError as exc:
        return _rejected(f"Could not execute file: {exc}", target_file=target_file)

    classification = classify_test_result(
        {"success": completed.returncode == 0, "timed_out": False}
    )
    status = _CLASSIFICATION_TO_STATUS.get(classification, STATUS_FAILED)
    error = (
        None if status == STATUS_EXECUTED
        else f"Execution of {target_file!r} exited with return code {completed.returncode}."
    )

    return {
        "status": status,
        "target_file": target_file,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "error": error,
    }
