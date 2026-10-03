"""
Execution - Built-in Capability: text_file_edit
==================================================
A real, working `Capability` (execution/capability.py) that safely
performs one controlled, exact-fragment text edit on an existing file:
replace exactly one occurrence of an exact existing text fragment with
its replacement text.

    path (string), old_text (string), new_text (string)
        -> Capability("text_file_edit")
        -> {success, path, requested_path, occurrences_replaced,
            characters_removed, characters_added,
            character_count_before, character_count_after, byte_size}

This module deliberately *reuses* the same allowed-directory
validation `text_file_read_capability.py` already implements
(`_resolve_allowed_dirs`/`_is_within_allowed_dirs`), imported directly
from that module rather than re-implemented a third time here (the
requirement to "reuse the existing safe file/path validation where
possible") - `text_file_read_capability.py` and
`text_file_write_capability.py` are both left completely unmodified by
this stage; this module only ever imports from the former, never
changes it.

Safety rules (all enforced by the handler, never by the caller):
  - Only paths that resolve (via `os.path.realpath`, so symlinks and
    `..` segments cannot be used to escape) inside one of a fixed set
    of allowed directories may be edited - by default the application's
    own already-defined safe directories (`PlatformConfig`'s
    `data_dir`/`skills_dir`/`temp_dir`), or an explicit `allowed_dirs`
    override (used by tests). A path outside every allowed directory
    is rejected before the file is ever opened for anything but the
    read used to check it.
  - `old_text` must match the file's current content *exactly one
    time*. Zero matches and two-or-more matches are both rejected -
    the file is never touched in either case (same "validate first,
    only ever write on a fully valid request" rule
    `text_file_write_capability.py` already follows for its own
    overwrite check). Only when there is exactly one match is the file
    ever opened for writing.
  - Only Python standard-library file operations are used (`os`,
    built-in `open`, `str.count`/`str.replace`) - no `eval()`,
    `exec()`, shell command, `subprocess`, network call, or external
    API of any kind, and no new dependency.

Nothing in this module executes on import, registers itself into any
registry automatically, or touches any path beyond the one a caller
explicitly asks it to edit. `create_text_file_edit_capability` only
*builds* a `Capability` object; `register_text_file_edit_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

import os

from .capability import Capability
from .text_file_read_capability import _is_within_allowed_dirs, _resolve_allowed_dirs

CAPABILITY_NAME = "text_file_edit"

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
        "success": {"type": "boolean"},
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "occurrences_replaced": {"type": "integer"},
        "characters_removed": {"type": "integer"},
        "characters_added": {"type": "integer"},
        "character_count_before": {"type": "integer"},
        "character_count_after": {"type": "integer"},
        "byte_size": {"type": "integer"},
    },
}


def make_text_file_edit_handler(allowed_dirs=None):
    """Build the plain handler callable `Capability("text_file_edit")`
    is constructed with. Kept separate from
    `create_text_file_edit_capability` so a caller who only wants the
    bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`, if given, replaces the application's own default
    safe directories entirely (used by tests to point at an isolated
    temporary directory); if omitted, the handler resolves the
    application's real `data_dir`/`skills_dir`/`temp_dir` the first
    time it actually runs - never at import time (same convention
    `text_file_read_capability.py`'s `_resolve_allowed_dirs` already
    follows, reused here unchanged).
    """

    def handler(data):
        path = data.get("path") if isinstance(data, dict) else None
        old_text = data.get("old_text") if isinstance(data, dict) else None
        new_text = data.get("new_text") if isinstance(data, dict) else None

        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string.")
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string.")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string.")

        resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
        real_path = os.path.realpath(path)

        if not _is_within_allowed_dirs(real_path, resolved_allowed_dirs):
            raise ValueError(
                f"Path {path!r} is outside the allowed directories."
            )

        if not os.path.exists(real_path):
            raise ValueError(f"File does not exist: {path!r}")

        if not os.path.isfile(real_path):
            raise ValueError(f"Path is not a regular file: {path!r}")

        # Read-then-validate-then-write, in that order, and the file
        # is opened for writing only in the branch below where exactly
        # one match was found - a missing or ambiguous fragment never
        # reaches a write.
        try:
            with open(real_path, "r", encoding="utf-8") as text_file:
                original_text = text_file.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {exc}")
        except OSError as exc:
            raise ValueError(f"Could not read file: {exc}")

        occurrences = original_text.count(old_text)
        if occurrences == 0:
            raise ValueError(
                f"Fragment not found in {path!r}; no changes were made."
            )
        if occurrences > 1:
            raise ValueError(
                f"Fragment appears {occurrences} times in {path!r}; expected "
                "exactly one occurrence, so no changes were made."
            )

        updated_text = original_text.replace(old_text, new_text, 1)

        try:
            with open(real_path, "w", encoding="utf-8") as text_file:
                text_file.write(updated_text)
        except OSError as exc:
            raise ValueError(f"Could not write file: {exc}")

        byte_size = os.path.getsize(real_path)

        return {
            "success": True,
            "path": real_path,
            "requested_path": path,
            "occurrences_replaced": 1,
            "characters_removed": len(old_text),
            "characters_added": len(new_text),
            "character_count_before": len(original_text),
            "character_count_after": len(updated_text),
            "byte_size": byte_size,
        }

    return handler


def create_text_file_edit_capability(allowed_dirs=None):
    """Build (but do not register anywhere) one `Capability` instance
    for `text_file_edit`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_text_file_edit_handler(allowed_dirs=allowed_dirs)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Replace exactly one occurrence of an exact text fragment in "
            "an existing file inside an allowed project/data directory, "
            "failing safely (with no changes made) if the fragment is "
            "missing or ambiguous."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "file_output", "read_only": False, "local_only": True},
    )


def register_text_file_edit_capability(registry, allowed_dirs=None, enabled=True):
    """Build a fresh `text_file_edit` `Capability` and register it
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
    capability = create_text_file_edit_capability(allowed_dirs=allowed_dirs)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
