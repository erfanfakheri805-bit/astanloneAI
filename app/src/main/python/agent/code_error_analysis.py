"""
Agent - Code Error Analysis
===============================
Connects the existing `execute_generated_code` result
(code_generation/generated_code_execution.py) and its existing
evaluation (agent/generated_code_execution_evaluation.py's
`build_generated_code_execution_evaluation`) to one small, structured
"CodeErrorAnalysis" result:

    execute_generated_code() result -> build_code_error_analysis()
        -> {target_file, error_type, error_message, stderr,
            line_number, is_actionable}

Reuses, never duplicates:
  - `agent.generated_code_execution_evaluation.
    build_generated_code_execution_evaluation` is called directly,
    unchanged, to learn *whether* execution passed, failed, timed out,
    or was never run (`target_file`/`error` are also read from its
    already-computed output rather than re-read from the raw execution
    result a second, disagreeing way) - this module never re-derives
    the PASSED/FAILED/TIMEOUT/INVALID classification that function
    already computes.
  - Nothing else in this project already parses a Python traceback out
    of a subprocess's `stderr` - this module adds exactly one small,
    regex-based, read-only extraction step for that, and only for that.

Extracts only what is already, deterministically present in the
execution result (requirement: "do not guess an error that is not
present in the execution result"):
  - `error_type` is read only from the literal exception class name
    Python's own `traceback` module already prints as the last,
    unindented "ExceptionType: message" line of `stderr` - never
    inferred from message text, a return code, or anything else.
    Recognizes exactly the common failures this step is asked to
    support - `SyntaxError`, `NameError`, `TypeError`, `ImportError`,
    `RuntimeError` (each together with its own well-known standard-
    library subclasses - `IndentationError`/`TabError` are
    `SyntaxError`s, `UnboundLocalError` is a `NameError`,
    `ModuleNotFoundError` is an `ImportError`, `RecursionError`/
    `NotImplementedError` are `RuntimeError`s - see Python's own
    `exceptions` documentation) - plus the fixed `"TIMEOUT"` label for
    a timed-out execution, and the fixed `"UNKNOWN_ERROR"` fallback for
    every other outcome: a real Python exception this module simply
    doesn't (yet) recognize, or `stderr` not containing a matching line
    at all. `"UNKNOWN_ERROR"` is a deliberately honest "something
    failed, but not in a way this module can name precisely" label,
    never a guess at which specific error actually occurred.
  - `line_number` is read only from the last Python
    `File "<path>", line <N>` frame line already present in `stderr` -
    the exact frame closest to where the exception was actually
    raised, in the exact format Python's own `traceback` module always
    produces - and is `None` whenever no such line is present (e.g. a
    timeout, or `stderr` that doesn't look like a Python traceback at
    all) rather than guessed at (requirement: "line_number when it can
    be reliably detected").
  - `error_message` is read only from the exact text already following
    the recognized "ExceptionType: " line, or, when no such line is
    present, the already-computed `error` field
    `build_generated_code_execution_evaluation` itself already
    produced (e.g. `execute_generated_code`'s own fixed "timed out
    after N seconds"/"exited with return code N" message) - never
    composed or reworded here.

`is_actionable` (requirement 6: "must be deterministic") is derived
from nothing but `error_type` itself, via one fixed lookup table
(`_ACTIONABLE_ERROR_TYPES` below): `True` for any of the six supported,
named failure categories (the five recognized exception families plus
`TIMEOUT`), `False` for `"UNKNOWN_ERROR"` (nothing concrete enough is
known to act on) and for a `None` `error_type` (execution actually
succeeded, or was rejected before ever running - see
`build_generated_code_execution_evaluation`'s own PASSED/INVALID
cases). No heuristic, nothing learned, nothing randomized.

This module never modifies the generated source file, never generates
or applies a correction, and never executes or re-executes anything -
it only reads the already-produced execution result (and the
already-computed evaluation built on top of it) and reports a small,
structured analysis of what, if anything, deterministically went
wrong. `target_file`/`stderr` are always preserved, completely
unmodified, under their own keys, alongside `error_message` (itself
never invented beyond what `execute_generated_code`/the traceback
already state) - so a caller can see exactly what this analysis was
based on without a second lookup (requirement: "preserve all original
execution/evaluation results").

Never raises: any input that isn't a real `execute_generated_code`
result is reported the same safe way
`build_generated_code_execution_evaluation` itself already guarantees
- `target_file=None`, `error_type=None`, `error_message=None`,
`stderr=None`, `line_number=None`, `is_actionable=False` - never an
exception.
"""

import re

from .generated_code_execution_evaluation import build_generated_code_execution_evaluation
from .test_result_evaluation import RESULT_FAILED, RESULT_TIMEOUT

ERROR_TYPE_SYNTAX = "SyntaxError"
ERROR_TYPE_NAME = "NameError"
ERROR_TYPE_TYPE = "TypeError"
ERROR_TYPE_IMPORT = "ImportError"
ERROR_TYPE_RUNTIME = "RuntimeError"
ERROR_TYPE_TIMEOUT = "TIMEOUT"
ERROR_TYPE_UNKNOWN = "UNKNOWN_ERROR"

ALL_CODE_ERROR_TYPES = (
    ERROR_TYPE_SYNTAX, ERROR_TYPE_NAME, ERROR_TYPE_TYPE, ERROR_TYPE_IMPORT,
    ERROR_TYPE_RUNTIME, ERROR_TYPE_TIMEOUT, ERROR_TYPE_UNKNOWN,
)

# Exact, literal Python exception class names this module recognizes -
# the standard library's own well-known subclasses of each of the five
# supported families included, so a real, common failure isn't
# mislabeled UNKNOWN_ERROR merely because it's a subclass. Never a
# substring/fuzzy match - only an exact class-name lookup.
_RECOGNIZED_EXCEPTION_TYPES = {
    "SyntaxError": ERROR_TYPE_SYNTAX,
    "IndentationError": ERROR_TYPE_SYNTAX,
    "TabError": ERROR_TYPE_SYNTAX,
    "NameError": ERROR_TYPE_NAME,
    "UnboundLocalError": ERROR_TYPE_NAME,
    "TypeError": ERROR_TYPE_TYPE,
    "ImportError": ERROR_TYPE_IMPORT,
    "ModuleNotFoundError": ERROR_TYPE_IMPORT,
    "RuntimeError": ERROR_TYPE_RUNTIME,
    "RecursionError": ERROR_TYPE_RUNTIME,
    "NotImplementedError": ERROR_TYPE_RUNTIME,
}

# is_actionable (requirement 6) - a plain, fixed lookup, never a
# heuristic: every named failure category is actionable, an
# unrecognized/absent one is not.
_ACTIONABLE_ERROR_TYPES = frozenset(
    {ERROR_TYPE_SYNTAX, ERROR_TYPE_NAME, ERROR_TYPE_TYPE, ERROR_TYPE_IMPORT,
     ERROR_TYPE_RUNTIME, ERROR_TYPE_TIMEOUT}
)

# Matches exactly a Python traceback's own final "ExceptionType" or
# "ExceptionType: message" line - a bare identifier, optionally
# followed by ": " and the rest of the line. Deliberately anchored to
# the *whole* (already-stripped) line, so it never matches inside a
# longer, unrelated line of output.
_EXCEPTION_LINE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)(?::\s*(.*))?$')

# Matches Python's own 'File "<path>", line <N>' traceback frame line,
# exactly as `traceback`/the interpreter itself always formats it.
_FRAME_LINE_RE = re.compile(r'File\s+"[^"]*",\s+line\s+(\d+)')


def _extract_exception_line(stderr):
    """Return `(exception_type_name, message)` for the last
    unindented line in `stderr` that looks exactly like a Python
    "ExceptionType" or "ExceptionType: message" traceback line, or
    `(None, None)` if no such line is present.

    Only an unindented line (Python's traceback module never indents
    the exception line itself - only the "Traceback (most recent call
    last):" header, `File "...", line N` frame lines, and the quoted
    source/caret lines beneath them are indented) is ever considered a
    candidate, so a `File ...`/source/caret line, or the "Traceback"
    header itself, is never mistaken for the exception line. Reads the
    exact class name and exact trailing text already present - invents
    nothing."""
    if not stderr:
        return None, None
    for raw_line in reversed(stderr.splitlines()):
        if not raw_line.strip():
            continue
        if raw_line[:1] in (" ", "\t"):
            continue
        match = _EXCEPTION_LINE_RE.match(raw_line.strip())
        if match:
            return match.group(1), (match.group(2) or "").strip()
    return None, None


def _extract_line_number(stderr):
    """Return the line number from the last Python
    `File "<path>", line <N>` frame already present in `stderr` - the
    frame closest to where the exception was actually raised - or
    `None` when no such frame is present (requirement: "line_number
    when it can be reliably detected"). Never guesses a location from
    anything else."""
    if not stderr:
        return None
    matches = _FRAME_LINE_RE.findall(stderr)
    return int(matches[-1]) if matches else None


def build_code_error_analysis(execution_result):
    """Build the small, structured `CodeErrorAnalysis`
    `AgentLoop.analyze_generated_code_error` (agent/agent_loop.py)
    exposes, on top of - and without duplicating - the existing
    `execute_generated_code` result and its existing evaluation.

    Always returns:
        {
            "target_file": <the evaluation's own target_file, or None>,
            "error_type": <one of ALL_CODE_ERROR_TYPES, or None when
                           execution actually succeeded or was
                           rejected before ever running>,
            "error_message": <the exact traceback message already
                              present in stderr, or the existing
                              evaluation's own "error" text when no
                              traceback line was found, or None>,
            "stderr": <execution_result["stderr"] unchanged, or None>,
            "line_number": <int or None - see _extract_line_number>,
            "is_actionable": <bool - see module docstring>,
        }

    A `TIMEOUT` execution (requirement: support "timeout") is reported
    with `error_type=ERROR_TYPE_TIMEOUT`, the existing evaluation's own
    already-fixed timeout message as `error_message`, and no
    `line_number` (a timeout has no traceback location to read).

    A `FAILED` execution (requirement: support "unknown execution
    error" alongside the five named exception families) has `stderr`
    parsed via `_extract_exception_line`/`_extract_line_number`;
    an unrecognized (or altogether absent) exception line is reported
    as `ERROR_TYPE_UNKNOWN_ERROR` - never guessed at as one of the
    five named families it doesn't actually match.

    A `PASSED` (execution succeeded) or `INVALID` (rejected before
    ever running, or not a real `execute_generated_code` result at
    all) evaluation has nothing to analyze - `error_type=None`,
    `line_number=None`, `is_actionable=False` - since no error is
    actually present to extract (requirement: "do not guess an error
    that is not present in the execution result").

    Purely a read-only extraction step: never modifies
    `execution_result`, the generated source file, or anything else,
    never generates or applies a correction, and never executes or
    re-executes anything. Never raises - delegates every input-shape
    decision to `build_generated_code_execution_evaluation`, so a
    malformed `execution_result` becomes the same safe, structured
    "nothing to analyze" result described above."""
    evaluation = build_generated_code_execution_evaluation(execution_result)
    target_file = evaluation["target_file"]
    stderr = execution_result.get("stderr") if isinstance(execution_result, dict) else None

    if evaluation["status"] == RESULT_TIMEOUT:
        return {
            "target_file": target_file,
            "error_type": ERROR_TYPE_TIMEOUT,
            "error_message": evaluation["error"],
            "stderr": stderr,
            "line_number": None,
            "is_actionable": True,
        }

    if evaluation["status"] != RESULT_FAILED:
        # PASSED (execution succeeded) or INVALID (never ran, or not a
        # real execution result at all) - nothing failed, so nothing
        # is analyzed or invented.
        return {
            "target_file": target_file,
            "error_type": None,
            "error_message": evaluation["error"],
            "stderr": stderr,
            "line_number": None,
            "is_actionable": False,
        }

    exception_name, message = _extract_exception_line(stderr)
    error_type = (
        _RECOGNIZED_EXCEPTION_TYPES.get(exception_name, ERROR_TYPE_UNKNOWN)
        if exception_name else ERROR_TYPE_UNKNOWN
    )

    return {
        "target_file": target_file,
        "error_type": error_type,
        "error_message": message if exception_name else evaluation["error"],
        "stderr": stderr,
        "line_number": _extract_line_number(stderr),
        "is_actionable": error_type in _ACTIONABLE_ERROR_TYPES,
    }
