"""
Execution - Built-in Capability: code_change_plan
=====================================================
A real, working `Capability` (execution/capability.py) that plans -
but never applies - one controlled, exact-fragment text change to an
existing Python (`.py`) file: it validates the change is safe to
propose and reports a structured "change plan" a caller can review
(or later hand to the existing `text_file_edit` capability to
actually apply) - never a second, differently-behaving edit system.

    path (string), old_text (string), new_text (string)
        -> Capability("code_change_plan")
        -> {path, requested_path, target_fragment, replacement,
            validation_status, analysis_summary, ready_to_apply,
            apply_capability}

Maximal reuse, not a fourth copy of file-safety/analysis logic:
  - `code_analysis_capability.make_code_analysis_handler` is called
    directly, unchanged, to (a) enforce the exact same allowed-
    directory / existence / size / binary / UTF-8 safety rules
    `text_file_read_capability.py` already enforces, (b) enforce the
    exact same ".py files only" rule `code_analysis_capability.py`
    already enforces, and (c) produce the exact same AST-based
    `inspect_source` analysis that capability already returns - this
    module never re-implements path validation, the `.py` check, or
    source analysis a second time. `code_analysis_capability.py`
    (and, transitively, `text_file_read_capability.py`,
    `python_inspector.py`) are unmodified by this addition.
  - `text_file_read_capability.make_text_file_read_handler` is called
    directly, unchanged, a second time only to obtain the file's
    current text (needed to count `old_text` occurrences) - the exact
    same safely-read text `text_file_edit_capability.py` itself reads
    before it ever writes. Calling the *read* handler again (rather
    than reusing `code_analysis`'s own already-read text, which it
    does not expose) never touches the file for writing and never
    duplicates the allowed-directory logic itself - both handlers
    delegate that to the same `_resolve_allowed_dirs`/
    `_is_within_allowed_dirs` functions `text_file_read_capability.py`
    already implements once.
  - The occurrence-count rule itself - `old_text` must appear in the
    file's current text *exactly one time*, otherwise the change is
    not ready to apply - is the exact same rule
    `text_file_edit_capability.py`'s own handler already enforces
    (`text.count(old_text)`, zero or more-than-one both rejected).
    This module never calls `text_file_edit`'s handler, though -
    doing so would actually write the file, which this planning
    capability must never do - so that one small, standard-library
    `str.count` rule is applied here directly, read-only, rather than
    invoking a capability whose whole contract is "make the change".
    `text_file_edit_capability.py` is unmodified by this addition, and
    its own `CAPABILITY_NAME` is reused (imported, not duplicated) as
    the `"apply_capability"` field of the returned plan - naming the
    exact existing capability a caller would invoke next to actually
    perform the edit this plan describes.

This is a planning/validation step, not an edit: the handler never
opens the target file for writing, never creates a new file, and
never calls `text_file_edit`'s write path. Unlike `text_file_edit`
(which raises for a missing/ambiguous fragment, since it can't safely
write in either case), an unparseable file or a missing/ambiguous
fragment is reported *inside* the returned plan
(`validation_status`/`analysis_summary`/`ready_to_apply`) rather than
raised - same "report, don't crash, for a substantive judgement"
convention `code_analysis_capability.py` already follows for a
syntax error (`analysis.valid=False` is a successful capability
result, not a failure). Only the underlying safety preconditions
`code_analysis`/`text_file_read` already raise for (an unsafe path, a
non-`.py` file, a missing file, ...) are still raised here, unchanged
- this module adds no new raising behavior of its own.

Strictly read-only, exactly like `code_analysis_capability.py`: no
`eval()`, no `exec()`, no shell command, no `subprocess`, no network
call, no external API, and no new dependency anywhere in this module.

Nothing in this module executes on import, registers itself into any
registry automatically, or plans a change for any file beyond the one
path a caller explicitly asks about. `create_code_change_plan_capability`
only *builds* a `Capability` object; `register_code_change_plan_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

from .capability import Capability
from .code_analysis_capability import make_code_analysis_handler
from .text_file_read_capability import make_text_file_read_handler, DEFAULT_MAX_BYTES
from .text_file_edit_capability import CAPABILITY_NAME as _TEXT_FILE_EDIT_CAPABILITY_NAME

CAPABILITY_NAME = "code_change_plan"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
        "old_text": {"type": "string", "required": True},
        "new_text": {"type": "string", "required": True},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "target_fragment": {"type": "string"},
        "replacement": {"type": "string"},
        "validation_status": {"type": "object"},
        "analysis_summary": {"type": "object"},
        "ready_to_apply": {"type": "boolean"},
        "apply_capability": {"type": "string"},
    },
}


def make_code_change_plan_handler(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build the plain handler callable `Capability("code_change_plan")`
    is constructed with. Kept separate from
    `create_code_change_plan_capability` so a caller who only wants the
    bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`/`max_bytes`, if given, are forwarded unchanged into
    both reused handlers below (`make_code_analysis_handler`,
    `make_text_file_read_handler`) - same "resolve the application's
    real safe directories the first time it actually runs, never at
    import time" convention every sibling capability already follows.
    """
    analysis_handler = make_code_analysis_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    read_handler = make_text_file_read_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)

    def handler(data):
        old_text = data.get("old_text") if isinstance(data, dict) else None
        new_text = data.get("new_text") if isinstance(data, dict) else None

        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string.")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string.")

        # Reused, unmodified: path resolution, allowed-directory
        # containment, ".py files only", existence/regular-file
        # checks, size limit, binary sniff, UTF-8 decoding, and the
        # AST-based analysis itself all happen exactly as they already
        # do for the standalone `code_analysis` capability. Any of
        # those safety preconditions failing raises here exactly as it
        # already would for a direct `code_analysis` call - this
        # capability never turns a hard precondition failure into a
        # "not ready" plan; a plan can only be built for a file that
        # was actually safe and valid to read as Python source.
        analysis_result = analysis_handler(data)

        # Second, independent reuse of the same safe-read machinery
        # (not the write path) to obtain the file's current text, so
        # the exact-fragment occurrence rule `text_file_edit` itself
        # enforces can be checked here without ever writing anything.
        read_result = read_handler(data)
        occurrences = read_result["text"].count(old_text)

        fragment_errors = []
        if occurrences == 0:
            fragment_errors.append(
                f"Fragment not found in {read_result['path']!r}."
            )
        elif occurrences > 1:
            fragment_errors.append(
                f"Fragment appears {occurrences} times in {read_result['path']!r}; "
                "expected exactly one occurrence."
            )

        validation_status = {
            "valid": not fragment_errors,
            "occurrences": occurrences,
            "errors": fragment_errors,
        }

        analysis = analysis_result["analysis"]
        analysis_summary = {
            "valid": analysis["valid"],
            "syntax_error": analysis["syntax_error"],
            "function_count": len(analysis["functions"]),
            "class_count": len(analysis["classes"]),
            "import_count": len(analysis["imports"]),
        }

        # Ready only when both existing evaluators agree: the
        # fragment resolves unambiguously (validation_status) *and*
        # the file the change would land in is currently valid,
        # parseable Python (analysis_summary) - never approved on
        # only one of the two.
        ready_to_apply = validation_status["valid"] and analysis_summary["valid"]

        return {
            "path": analysis_result["path"],
            "requested_path": analysis_result["requested_path"],
            "target_fragment": old_text,
            "replacement": new_text,
            "validation_status": validation_status,
            "analysis_summary": analysis_summary,
            "ready_to_apply": ready_to_apply,
            # Names the exact existing capability that would actually
            # perform this plan's edit - never invoked by this
            # capability itself (see module docstring).
            "apply_capability": _TEXT_FILE_EDIT_CAPABILITY_NAME,
        }

    return handler


def create_code_change_plan_capability(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build (but do not register anywhere) one `Capability` instance
    for `code_change_plan`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_code_change_plan_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Plan (but never apply) one exact-fragment text change to an "
            "existing Python (.py) file inside an allowed project/data "
            "directory: validate the fragment resolves unambiguously, "
            "analyze the file with the existing code_analysis capability, "
            "and report a structured, read-only change plan with a "
            "ready_to_apply verdict."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "code_analysis", "read_only": True, "local_only": True},
    )


def register_code_change_plan_capability(
    registry, allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, enabled=True,
):
    """Build a fresh `code_change_plan` `Capability` and register it
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
    capability = create_code_change_plan_capability(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
