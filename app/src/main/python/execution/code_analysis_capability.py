"""
Execution - Built-in Capability: code_analysis
==================================================
A real, working `Capability` (execution/capability.py) that connects
this project's *existing* code-analysis implementation -
`code_intelligence.python_inspector.inspect_source` (AST-based,
read-only, parses but never executes source) - to the Capability
Registry / Agent execution path that `text_file_read_capability.py`,
`project_structure_inspect_capability.py`, and
`python_test_runner_capability.py` already run through.

    path (string) -> Capability("code_analysis")
        -> {path, requested_path, byte_size, analysis: {valid,
            syntax_error, functions, classes, imports}}

Before this module, `code_analysis` existed only as a *planned-
capability* row in `capabilities.capability_system.CapabilitySystem`
(the application-level, database-backed "is this capability turned on
at all" yes/no - `core/core.py`'s `_first_time_setup` already flips
that row's `status` from `"planned"` to `"active"` once
`python_inspector.py` exists) - it had no entry in
`ExecutableCapabilityRegistry`/`CapabilityHandlerRegistry` and could
not actually be run through `ExecutionEngine`. This module is that
missing connection, not a second implementation: it never re-parses
Python itself, never re-implements AST walking, and never duplicates
`inspect_source`'s own structured-result shape - it only reads a file
safely and hands the resulting text to the one existing
`inspect_source` function, unmodified, imported directly.

Maximal reuse, not a parallel safe-file-reading system: rather than
re-implementing "resolve path -> validate containment -> check
extension -> check size -> sniff for binary -> decode UTF-8" a fourth
time, this module calls `text_file_read_capability.make_text_file_read_handler`
directly - the exact same handler factory `text_file_read_capability.py`
itself uses to build the `text_file_read` capability - and reuses its
returned text unchanged as the input to `inspect_source`. Every one of
that handler's existing safety behaviors therefore applies here
automatically, with no separate copy to keep in sync:
  - only a `path` that resolves (via `os.path.realpath`) inside one of
    the allowed directories (the application's own
    `data_dir`/`skills_dir`/`temp_dir` by default, or an explicit
    `allowed_dirs` override used by tests) is ever opened;
  - a missing file, a directory, a file too large
    (`DEFAULT_MAX_BYTES`/`max_bytes=`), a binary-looking file, or a
    file that isn't valid UTF-8 text is rejected with the same
    `ValueError` messages `text_file_read` itself already raises -
    `Capability.execute` (execution/capability.py) already catches
    that `ValueError` and turns it into a safe, structured failed
    result, so this module needs no extra try/except-to-result
    plumbing of its own.
`text_file_read_capability.py` is not modified by this addition. On
top of that reused read, this module adds exactly one extra,
capability-specific check: the resolved file's extension must be
`.py` (checked on the original `path` before the read handler ever
runs) - a `.txt`/`.md`/other otherwise-readable text file is rejected
for `code_analysis` specifically, even though `text_file_read` itself
would happily read it, because "analyze this as Python source" only
makes sense for a `.py` file.

Strictly read-only: the handler never opens the target file for
writing, never creates a new file, and never calls anything from
`ast` beyond `ast.parse`/`ast.walk` (both already used, unchanged,
inside `inspect_source` itself) - source is only ever parsed into a
syntax tree, never executed, never `eval()`'d, never `exec()`'d. No
external package, no network call, no shell command, and no
`subprocess` anywhere in this module.

Nothing in this module executes on import, registers itself into any
registry automatically, or analyzes any file beyond the one path a
caller explicitly asks about. `create_code_analysis_capability` only
*builds* a `Capability` object; `register_code_analysis_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

import os

from .capability import Capability
from .text_file_read_capability import make_text_file_read_handler, DEFAULT_MAX_BYTES
from code_intelligence.python_inspector import inspect_source

CAPABILITY_NAME = "code_analysis"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "byte_size": {"type": "integer"},
        "analysis": {"type": "object"},
    },
}


def make_code_analysis_handler(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build the plain handler callable `Capability("code_analysis")`
    is constructed with. Kept separate from
    `create_code_analysis_capability` so a caller who only wants the
    bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`, if given, replaces the application's own default
    safe directories entirely (used by tests to point at an isolated
    temporary directory) and is passed straight through to the reused
    `text_file_read` handler unchanged; if omitted, that handler
    resolves the application's real `data_dir`/`skills_dir`/`temp_dir`
    the first time it actually runs - never at import time (same
    convention every sibling capability already follows).
    """
    read_handler = make_text_file_read_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)

    def handler(data):
        path = data.get("path") if isinstance(data, dict) else None

        # One extra, capability-specific check on top of the reused
        # read handler's own validation: `code_analysis` only ever
        # analyzes `.py` files. Checked on the *original* `path`
        # before the read handler runs, so an unsafe/nonexistent path
        # still surfaces the read handler's own (already safe, already
        # tested) error message rather than this one - only a
        # path that *would* otherwise be read gets rejected here for
        # having the wrong extension.
        if isinstance(path, str) and path.strip():
            _, extension = os.path.splitext(path)
            if extension.lower() != ".py":
                raise ValueError(
                    f"Unsupported file type {extension!r}; code_analysis only "
                    "analyzes Python (.py) files."
                )

        # Reused, unmodified: path resolution, allowed-directory
        # containment, existence/regular-file checks, size limit,
        # binary sniff, and UTF-8 decoding all happen exactly as they
        # already do for the `text_file_read` capability.
        read_result = read_handler(data)

        analysis = inspect_source(read_result["text"], filename=read_result["path"])

        return {
            "path": read_result["path"],
            "requested_path": read_result["requested_path"],
            "byte_size": read_result["byte_size"],
            "analysis": analysis,
        }

    return handler


def create_code_analysis_capability(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build (but do not register anywhere) one `Capability` instance
    for `code_analysis`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_code_analysis_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Read a Python (.py) file from an allowed project/data directory "
            "and return a structured, read-only AST analysis of it (validity, "
            "any syntax error, and the functions/classes/imports it declares)."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "code_analysis", "read_only": True, "local_only": True},
    )


def register_code_analysis_capability(
    registry, allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, enabled=True,
):
    """Build a fresh `code_analysis` `Capability` and register it into
    `registry` - an `ExecutableCapabilityRegistry`
    (execution/executable_registry.py) or a `CapabilityHandlerRegistry`
    (execution/capability_handlers.py), both of which already expose a
    `register`/`register_capability` method that accepts a `Capability`
    object unchanged. Never registers into any registry the caller
    didn't explicitly hand in, and never registers more than once on
    its own initiative - calling this twice against the same registry
    raises exactly the same "duplicate name" error either registry
    already raises for that case. Returns the `Capability` that was
    registered."""
    capability = create_code_analysis_capability(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
