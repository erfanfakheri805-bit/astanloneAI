"""
Execution - Built-in Capability: python_test_runner
=======================================================
A real, working `Capability` (execution/capability.py) that safely
runs a project's Python tests using only the Python standard library's
own test runner (`unittest`, invoked as `python -m unittest`) and
reports a structured, JSON-shaped result - never a raw shell
transcript, never an arbitrary command.

    {path, target?} -> Capability("python_test_runner")
        -> {path, requested_path, target, success, timed_out,
            return_code, stdout, stderr, tests_run, failures, errors,
            skipped, duration_seconds}

This is the execution-side sibling of `project_structure_inspect_capability.py`
and the three `text_file_*_capability.py` modules: it reuses their own
safe-path machinery unchanged (`text_file_read_capability._resolve_allowed_dirs`
for turning `allowed_dirs`/the application's own default safe
directories into a resolved, real-path list, and
`project_structure_inspect_capability._is_within_or_equal_allowed_dirs`
for containment, since a project directory - unlike a single file - is
legitimately the allowed directory itself) rather than re-implementing
either a third time. Neither of those two modules is modified by this
addition.

No equivalent capability already existed in this project before this
module: `self_upgrade/sandbox.py`'s `Sandbox.run` is an explicitly
labeled, non-executing *static* payload check (its own docstring says
so - "does not execute or apply arbitrary generated code"), and
nothing else anywhere under `execution/`, `self_upgrade/`, or
`capabilities/` runs a subprocess, imports `unittest`, or reports test
counts. This module is therefore new, not a duplicate.

Safety rules (all enforced by the handler, never by the caller):
  - Only a `path` that resolves (via `os.path.realpath`, so symlinks
    and `..` segments cannot be used to escape) to one of a fixed set
    of allowed directories, or to something inside one of them, is
    ever used as the project directory tests run in. By default those
    directories are exactly the application's own already-defined safe
    directories (`PlatformConfig`'s `data_dir`/`skills_dir`/
    `temp_dir`, via `text_file_read_capability._resolve_allowed_dirs`);
    a caller may instead pass an explicit `allowed_dirs` override
    (used by tests). A path outside every allowed directory, a path
    that doesn't exist, or a path that isn't a directory is rejected
    before any test is ever run.
  - An optional `target` - a dotted test name (e.g. `"tests.test_foo"`
    or `"tests.test_foo.TestCase.test_method"`, resolved by
    `unittest`'s own module loader against the project directory
    placed on `sys.path`) or a `.py` file path relative to the project
    directory - selects one specific test instead of the project's
    full `test_*.py` discovery. A `target` that looks like a file path
    (contains a path separator or ends in `.py`) is independently
    resolved with `os.path.realpath` and must itself land inside the
    already-validated project directory, using the same containment
    check as `path` - a `target` can never be used to point `unittest`
    at a file outside the allowed project directory. A `target`
    starting with `-` is rejected outright (never passed through to
    the `unittest` command line as something that could be mistaken
    for a flag).
  - Tests are run with a single, fixed argument list -
    `[sys.executable, "-m", "unittest", ...]` - passed to
    `subprocess.run` with `shell=False` (the default; never set to
    `True` anywhere in this module) and no string ever built by
    concatenating caller input into a command line. This is the
    project's one deliberate, narrowly-scoped use of `subprocess.run`
    for a real user-facing capability - not a general-purpose "run a
    shell command" capability: the program is always `sys.executable`,
    the first two arguments are always `"-m", "unittest"`, and the
    only caller-influenced piece is the already-validated `target`
    (or nothing, for discovery), appended as one argv element. There
    is no code path in this module that can turn caller input into an
    arbitrary shell command, a pipe, a redirection, or a second
    process.
  - A fixed, configurable execution timeout (`DEFAULT_TIMEOUT_SECONDS`,
    overridable per capability instance via `timeout_seconds=`) is
    always passed to `subprocess.run`. On `subprocess.TimeoutExpired`,
    `subprocess.run` has already terminated the child process (its own
    documented behavior) before raising; this handler catches that
    exception and reports a safe, structured `{"timed_out": True,
    "success": False, ...}` result - it never lets a hung test process
    escape unbounded, and never lets a timeout surface as an unhandled
    exception.
  - The child process's environment is a small, explicit, minimal copy
    (`_minimal_subprocess_environment`) - `PATH` (so `sys.executable`
    itself can be located) plus `SYSTEMROOT`/`COMSPEC` on Windows where
    present, with `PYTHONDONTWRITEBYTECODE=1` always set - rather than
    a full inherited `os.environ`. This is a deliberate reduction, not
    a guarantee: nothing in this module can stop test code from
    calling into the network itself (that would require a real OS-level
    sandbox/container, an external dependency this stage deliberately
    does not add - see the module-level "no external dependencies"
    rule), but this capability itself performs no network operation of
    any kind, and stripping proxy/credential-shaped environment
    variables before the child process starts means this capability
    never hands a test process any network configuration or secret
    that happened to be sitting in this process's own environment.
    `PYTHONDONTWRITEBYTECODE=1` also means a normal test run leaves no
    new `__pycache__`/`.pyc` files behind in the project directory
    (on top of `unittest` itself never writing to source files),
    satisfying "do not modify project files directly" for the common
    case without a second, separate sandboxing layer.
  - Only `subprocess`, `sys`, `os`, `re`, and `time` from the standard
    library are used - no external packages, and no dependency beyond
    what `text_file_read_capability.py`/`project_structure_inspect_capability.py`
    already import.

Nothing in this module executes on import, registers itself into any
registry automatically, or runs tests anywhere beyond the one project
directory a caller explicitly asks about.
`create_python_test_runner_capability` only *builds* a `Capability`
object; `register_python_test_runner_capability` only calls the
existing, unchanged `ExecutableCapabilityRegistry.register` (or
`CapabilityHandlerRegistry.register_capability`) with it - same "no
execution without an explicit handler, no automatic discovery" rule
the rest of execution/ already follows.
"""

import os
import re
import subprocess
import sys
import time

from .capability import Capability
from .text_file_read_capability import _resolve_allowed_dirs
from .project_structure_inspect_capability import _is_within_or_equal_allowed_dirs

CAPABILITY_NAME = "python_test_runner"

# A reasonable, fixed default execution ceiling - keeps one test run
# bounded regardless of what the tests themselves do (an infinite
# loop, a hang waiting on a socket that will never answer, etc.).
# Overridable per capability instance via `timeout_seconds=` (same
# `max_entries=`/`max_bytes=` convention the sibling capabilities
# already follow).
DEFAULT_TIMEOUT_SECONDS = 30

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
        "target": {"type": "string"},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "target": {"type": "string"},
        "success": {"type": "boolean"},
        "timed_out": {"type": "boolean"},
        "return_code": {"type": "integer"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "tests_run": {"type": "integer"},
        "failures": {"type": "integer"},
        "errors": {"type": "integer"},
        "skipped": {"type": "integer"},
        "duration_seconds": {"type": "number"},
    },
}

# `unittest`'s own summary line, e.g. "Ran 3 tests in 0.001s" -
# printed exactly once per run, regardless of verbosity or outcome.
_RAN_PATTERN = re.compile(r"Ran (\d+) tests? in")

# `unittest`'s own final status line, e.g. "OK", "OK (skipped=1)",
# "FAILED (failures=1)", or "FAILED (failures=1, errors=2, skipped=1)".
_STATUS_PATTERN = re.compile(r"^(OK|FAILED)(?:\s*\(([^)]*)\))?\s*$", re.MULTILINE)


def _parse_unittest_summary(text):
    """Best-effort, regex-only parse of `unittest`'s own plain-text
    summary (never a second test run, never an import of the tests
    themselves - just reading the text the child process already
    printed). Returns a plain `{"tests_run", "failures", "errors",
    "skipped"}` dict; any field `unittest` didn't report stays `None`
    rather than being guessed at (e.g. a crash before the summary ever
    printed leaves all four as `None`, an honest "unknown", not a
    fabricated zero)."""
    text = text or ""

    ran_match = _RAN_PATTERN.search(text)
    tests_run = int(ran_match.group(1)) if ran_match else None

    failures = errors = skipped = None
    status_match = _STATUS_PATTERN.search(text)
    if status_match:
        failures = errors = skipped = 0
        details = status_match.group(2) or ""
        for part in details.split(","):
            part = part.strip()
            if not part:
                continue
            key, _, value = part.partition("=")
            key = key.strip()
            value = value.strip()
            if not value.isdigit():
                continue
            if key == "failures":
                failures = int(value)
            elif key == "errors":
                errors = int(value)
            elif key == "skipped":
                skipped = int(value)

    return {
        "tests_run": tests_run,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _minimal_subprocess_environment():
    """A small, explicit environment for the child test process -
    never the full, inherited `os.environ` (see module docstring).
    Only what's needed to locate and run `sys.executable` itself is
    carried over; `PYTHONDONTWRITEBYTECODE` is always forced on."""
    env = {}
    for key in ("PATH", "SYSTEMROOT", "COMSPEC"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _looks_like_file_target(target):
    return target.endswith(".py") or (os.sep in target) or (os.altsep and os.altsep in target)


def _resolve_target(target, real_project_dir):
    """Validate and normalize an optional `target`. Returns `None` for
    no target (full discovery), or the exact string to append to the
    `unittest` argv - either a dotted test name, unchanged, or a
    project-relative file path whose real, resolved location has
    already been proven to sit inside `real_project_dir`. Raises
    `ValueError` - and never touches the filesystem beyond a single
    `os.path.realpath`/existence check - for anything unsafe or
    malformed."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must be a non-empty string when provided.")
    target = target.strip()

    if target.startswith("-"):
        raise ValueError(
            f"target {target!r} must not look like a command-line option."
        )

    if not _looks_like_file_target(target):
        # A dotted test name (e.g. "tests.test_foo" or
        # "tests.test_foo.TestCase.test_method") - left exactly as
        # given; `unittest` itself resolves it against the project
        # directory once that directory is both the child process's
        # cwd and, via `-m`, prepended to its own sys.path.
        return target

    candidate = target if os.path.isabs(target) else os.path.join(real_project_dir, target)
    real_target = os.path.realpath(candidate)

    if not _is_within_or_equal_allowed_dirs(real_target, [real_project_dir]) or real_target == real_project_dir:
        raise ValueError(
            f"target {target!r} is outside the project directory."
        )

    if not os.path.isfile(real_target):
        raise ValueError(f"target file does not exist: {target!r}")

    return os.path.relpath(real_target, real_project_dir)


def make_python_test_runner_handler(allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """Build the plain handler callable
    `Capability("python_test_runner")` is constructed with. Kept
    separate from `create_python_test_runner_capability` so a caller
    who only wants the bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`, if given, replaces the application's own default
    safe directories entirely (used by tests to point at an isolated
    temporary directory); if omitted, the handler resolves the
    application's real `data_dir`/`skills_dir`/`temp_dir` the first
    time it actually runs - never at import time (same convention the
    sibling capabilities already follow).
    """

    def handler(data):
        path = data.get("path") if isinstance(data, dict) else None
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string.")

        raw_target = data.get("target") if isinstance(data, dict) else None

        resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
        real_path = os.path.realpath(path)

        if not _is_within_or_equal_allowed_dirs(real_path, resolved_allowed_dirs):
            raise ValueError(f"Path {path!r} is outside the allowed directories.")

        if not os.path.exists(real_path):
            raise ValueError(f"Directory does not exist: {path!r}")

        if not os.path.isdir(real_path):
            raise ValueError(f"Path is not a directory: {path!r}")

        argv_target = None
        if raw_target is not None:
            argv_target = _resolve_target(raw_target, real_path)

        argv = [sys.executable, "-m", "unittest"]
        if argv_target is not None:
            argv.append(argv_target)
        else:
            argv.extend(["discover", "-s", real_path, "-p", "test_*.py"])

        env = _minimal_subprocess_environment()
        started_at = time.monotonic()

        try:
            completed = subprocess.run(
                argv,
                cwd=real_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_seconds = time.monotonic() - started_at
            return {
                "path": real_path,
                "requested_path": path,
                "target": raw_target,
                "success": False,
                "timed_out": True,
                "return_code": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "tests_run": None,
                "failures": None,
                "errors": None,
                "skipped": None,
                "duration_seconds": duration_seconds,
            }
        except OSError as exc:
            raise ValueError(f"Could not run tests: {exc}")

        duration_seconds = time.monotonic() - started_at
        counts = _parse_unittest_summary(completed.stderr)

        return {
            "path": real_path,
            "requested_path": path,
            "target": raw_target,
            "success": completed.returncode == 0,
            "timed_out": False,
            "return_code": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "tests_run": counts["tests_run"],
            "failures": counts["failures"],
            "errors": counts["errors"],
            "skipped": counts["skipped"],
            "duration_seconds": duration_seconds,
        }

    return handler


def create_python_test_runner_capability(allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    """Build (but do not register anywhere) one `Capability` instance
    for `python_test_runner`. Never calls the handler; same
    "construct, don't execute" convention `Capability.__init__` itself
    already follows."""
    handler = make_python_test_runner_handler(
        allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds
    )
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Run a project's Python tests, inside an allowed project directory "
            "only, using the standard library's own unittest runner, and "
            "return a structured pass/fail result with captured output and "
            "basic test counts."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={
            "category": "testing",
            "modifies_project": False,
            "local_only": True,
            "network_access": False,
        },
    )


def register_python_test_runner_capability(
    registry, allowed_dirs=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, enabled=True,
):
    """Build a fresh `python_test_runner` `Capability` and register it
    into `registry` - an `ExecutableCapabilityRegistry`
    (execution/executable_registry.py) or a `CapabilityHandlerRegistry`
    (execution/capability_handlers.py), both of which already expose a
    `register`/`register_capability` method that accepts a `Capability`
    object unchanged. Never registers into any registry the caller
    didn't explicitly hand in, and never registers more than once on
    its own initiative - calling this twice against the same registry
    raises exactly the same "duplicate name" error either registry
    already raises for that case. Returns the `Capability` that was
    registered."""
    capability = create_python_test_runner_capability(
        allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds
    )
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
