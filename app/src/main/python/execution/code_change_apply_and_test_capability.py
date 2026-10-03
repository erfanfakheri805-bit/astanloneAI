"""
Execution - Built-in Capability: code_change_apply_and_test
=================================================================
A real, working `Capability` (execution/capability.py) that connects
the existing `code_change_apply` capability (code_change_apply_capability.py -
itself already a connection of `code_change_plan`/`text_file_edit`) to
the existing `python_test_runner` capability
(python_test_runner_capability.py) and the existing
`agent.test_result_evaluation` classifier: it applies one validated
code change and, only if that change was actually applied, runs the
project's tests and reports a consistently-classified result.

    path (string), old_text (string), new_text (string),
    test_path (string, optional), target (string, optional)
        -> Capability("code_change_apply_and_test")
        -> {change_status, test_status, test_output, error,
            change_result, test_result}

Maximal reuse, not a third file-edit/test-running system:
  - The change itself is planned and applied by calling
    `code_change_apply_capability.make_code_change_apply_handler`
    directly, unchanged - this module never re-implements the
    fragment-occurrence check, the AST-based analysis, the
    safe-path/`.py`-only validation, or the actual file write that
    `code_change_apply` (and, transitively, `code_change_plan`/
    `text_file_edit`) already perform. `code_change_apply_capability.py`
    is unmodified by this addition.
  - The tests are run by calling
    `python_test_runner_capability.make_python_test_runner_handler`
    directly, unchanged - this module never spawns a subprocess of its
    own, never imports `unittest` itself, and never re-implements the
    allowed-directory containment check, the target-resolution logic,
    or the timeout handling `python_test_runner` already performs.
    `python_test_runner_capability.py` is unmodified by this addition.
  - The test result is classified into `PASSED`/`FAILED`/`TIMEOUT`/
    `INVALID` by calling
    `agent.test_result_evaluation.classify_test_result` directly,
    unchanged - this module never re-derives that mapping from
    `success`/`timed_out` itself. `agent/test_result_evaluation.py` is
    unmodified by this addition.

"Test only after a successful change" is enforced structurally, not by
convention: `python_test_runner`'s handler is called from exactly one
branch, reached only when `code_change_apply`'s own result reports
`change_applied: True`. When the change was not applied (an unready
plan, or a write that failed), this handler returns immediately with
`test_status: None` and `test_output: None` - the test handler is
never called at all, and the change's own result (including *why* it
was not applied) is preserved unchanged under `change_result`.

Exactly one change is applied and, at most, one test run is started
per call - never a loop, never a retry, and never a second correction
or modification of any kind. A test run that itself cannot be
completed (an invalid/unsafe `test_path`, or any other error the
reused `python_test_runner` handler raises) is caught here and
reported in the small structured `error` field, with `change_result`
still preserved exactly as `code_change_apply` produced it - a test
that cannot be evaluated never erases the record of the change that
was already, successfully applied.

Strictly reuses only what already exists: no `eval()`, no `exec()`, no
shell command, no `subprocess` call of its own, no network call, and
no new dependency anywhere in this module.

Nothing in this module executes on import, registers itself into any
registry automatically, or tests/modifies any file beyond the one
`path`/`test_path` a caller explicitly asks about.
`create_code_change_apply_and_test_capability` only *builds* a
`Capability` object; `register_code_change_apply_and_test_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

import os

from .capability import Capability
from .code_change_apply_capability import make_code_change_apply_handler
from .python_test_runner_capability import (
    DEFAULT_TIMEOUT_SECONDS,
    make_python_test_runner_handler,
)
from .text_file_read_capability import DEFAULT_MAX_BYTES

# Reused, unmodified: the exact PASSED/FAILED/TIMEOUT/INVALID
# vocabulary and classification rule `agent/test_result_evaluation.py`
# already defines - never re-derived here.
from agent.test_result_evaluation import classify_test_result

CAPABILITY_NAME = "code_change_apply_and_test"

# Small, fixed change_status vocabulary - deliberately not reusing the
# PASSED/FAILED/TIMEOUT/INVALID test vocabulary, since "was the change
# applied" and "what did the tests report" are two different
# questions with two different answer sets.
CHANGE_STATUS_APPLIED = "APPLIED"
CHANGE_STATUS_NOT_APPLIED = "NOT_APPLIED"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
        "old_text": {"type": "string", "required": True},
        "new_text": {"type": "string", "required": True},
        "test_path": {"type": "string"},
        "target": {"type": "string"},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "change_status": {"type": "string"},
        "test_status": {"type": "string"},
        "test_output": {"type": "string"},
        "error": {"type": "string"},
        "change_result": {"type": "object"},
        "test_result": {"type": "object"},
    },
}


def make_code_change_apply_and_test_handler(
    allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Build the plain handler callable
    `Capability("code_change_apply_and_test")` is constructed with.
    Kept separate from `create_code_change_apply_and_test_capability`
    so a caller who only wants the bare callable can get one without
    going through `Capability` at all.

    `allowed_dirs` is forwarded unchanged into both reused handlers,
    so the change step and the test step agree on exactly the same
    set of allowed directories for a single call. `max_bytes`/
    `timeout_seconds`, if given, are forwarded unchanged into the
    reused `code_change_apply`/`python_test_runner` handlers
    respectively.
    """
    apply_handler = make_code_change_apply_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    test_handler = make_python_test_runner_handler(
        allowed_dirs=allowed_dirs, timeout_seconds=timeout_seconds
    )

    def handler(data):
        test_path = data.get("test_path") if isinstance(data, dict) else None
        target = data.get("target") if isinstance(data, dict) else None

        # Reused, unmodified: the exact same plan-then-apply flow a
        # standalone `code_change_apply` call would perform. Any
        # unsafe precondition (path outside the allowed directories,
        # non-.py file, missing file, ...) raises here exactly as it
        # already would for a direct `code_change_apply` call - before
        # any test is ever considered.
        change_result = apply_handler(data)

        if not change_result["change_applied"]:
            # "Test only after a successful modification", enforced
            # structurally: `test_handler` is simply never called on
            # this path. Reported, not raised - same "report, don't
            # crash, for a substantive judgement" convention
            # `code_change_apply`/`code_change_plan` already follow.
            return {
                "change_status": CHANGE_STATUS_NOT_APPLIED,
                "test_status": None,
                "test_output": None,
                "error": "Code change was not applied; test was not started.",
                "change_result": change_result,
                "test_result": None,
            }

        # No test_path given -> the directory the just-changed file
        # itself lives in (the file's own "project"), never a
        # separately-guessed or wider path.
        resolved_test_path = (
            test_path if isinstance(test_path, str) and test_path.strip()
            else os.path.dirname(change_result["path"])
        )

        test_data = {"path": resolved_test_path}
        if isinstance(target, str) and target.strip():
            test_data["target"] = target

        try:
            # Reused, unmodified: the exact same allowed-directory
            # containment check, target resolution, `unittest`
            # invocation, and timeout handling a standalone
            # `python_test_runner` call would perform.
            test_result = test_handler(test_data)
        except Exception as exc:
            # A test run that could not even start (e.g. an
            # invalid/unsafe test_path) never erases the change that
            # was already, successfully applied - change_result is
            # still returned, unchanged, alongside this error.
            return {
                "change_status": CHANGE_STATUS_APPLIED,
                "test_status": None,
                "test_output": None,
                "error": f"{type(exc).__name__}: {exc}",
                "change_result": change_result,
                "test_result": None,
            }

        # Reused, unmodified: the exact same PASSED/FAILED/TIMEOUT/
        # INVALID mapping `agent.test_result_evaluation` already
        # defines - never a second, differently-behaving mapping.
        test_status = classify_test_result(test_result)

        return {
            "change_status": CHANGE_STATUS_APPLIED,
            "test_status": test_status,
            "test_output": test_result.get("stdout"),
            "error": None,
            "change_result": change_result,
            "test_result": test_result,
        }

    return handler


def create_code_change_apply_and_test_capability(
    allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Build (but do not register anywhere) one `Capability` instance
    for `code_change_apply_and_test`. Never calls the handler; same
    "construct, don't execute" convention `Capability.__init__` itself
    already follows."""
    handler = make_code_change_apply_and_test_handler(
        allowed_dirs=allowed_dirs, max_bytes=max_bytes, timeout_seconds=timeout_seconds,
    )
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Apply one exact-fragment text change to an existing Python "
            "(.py) file using the existing code_change_apply capability, "
            "then - only if that change was actually applied - run the "
            "affected project's tests using the existing "
            "python_test_runner capability and classify the result with "
            "the existing PASSED/FAILED/TIMEOUT/INVALID vocabulary; never "
            "starts a test after a failed/not-applied change, and never "
            "performs a second change or correction of its own."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={
            "category": "file_output",
            "read_only": False,
            "local_only": True,
            "composes": ("code_change_apply", "python_test_runner"),
        },
    )


def register_code_change_apply_and_test_capability(
    registry, allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS, enabled=True,
):
    """Build a fresh `code_change_apply_and_test` `Capability` and
    register it into `registry` - an `ExecutableCapabilityRegistry`
    (execution/executable_registry.py) or a `CapabilityHandlerRegistry`
    (execution/capability_handlers.py), both of which already expose a
    `register`/`register_capability` method that accepts a `Capability`
    object unchanged. Never registers into any registry the caller
    didn't explicitly hand in, and never registers more than once on
    its own initiative. Returns the `Capability` that was registered."""
    capability = create_code_change_apply_and_test_capability(
        allowed_dirs=allowed_dirs, max_bytes=max_bytes, timeout_seconds=timeout_seconds,
    )
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
