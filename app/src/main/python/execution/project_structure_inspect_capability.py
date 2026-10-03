"""
Execution - Built-in Capability: project_structure_inspect
==============================================================
A real, working `Capability` (execution/capability.py) that safely
lists the files and directories inside an allowed project/data
directory - a read-only structural snapshot, never a content dump
(use `text_file_read_capability.py`'s `text_file_read` for that, one
file at a time).

    path (string) -> Capability("project_structure_inspect")
        -> {path, requested_path, entries: [{path, type}, ...],
            entry_count, truncated, limit}

This module reuses `text_file_read_capability.py`'s own
`_resolve_allowed_dirs` (the requirement to "reuse the existing safe
path validation") for turning `allowed_dirs`/the application's own
default safe directories into a resolved, real-path list - imported
directly rather than re-implemented; `text_file_read_capability.py`
itself is left completely unmodified. Containment is then checked with
a small, local variant of that module's `_is_within_allowed_dirs` that
additionally accepts the allowed directory *itself* as a valid target
(unlike the file-oriented capabilities, where an allowed directory can
never be the file being read/written/edited, a project-structure
inspection is naturally often asked to start at the allowed directory
root itself) - same `os.path.realpath` + `os.path.commonpath`
containment technique, not a different one.

Safety / boundedness rules (all enforced by the handler, never by the
caller):
  - Only a `path` that resolves (via `os.path.realpath`, so symlinks
    and `..` segments cannot be used to escape) to one of a fixed set
    of allowed directories, or to something inside one of them, is
    ever inspected. By default those directories are exactly the
    application's own already-defined safe directories
    (`PlatformConfig`'s `data_dir`/`skills_dir`/`temp_dir`); a caller
    may instead pass an explicit `allowed_dirs` override (used by
    tests). A path outside every allowed directory - and a path that
    doesn't exist, or isn't a directory at all - is rejected before
    any directory is ever opened for listing.
  - `os.walk(..., followlinks=False)` is used deliberately: a
    symlinked subdirectory is reported as one entry (whatever type
    `os.path.isdir`/`os.path.isfile` says it is) but is never
    descended into, so a symlink planted inside an allowed directory
    can never be used to walk arbitrary content from elsewhere on the
    filesystem into the result.
  - The walk stops - and the result is marked `truncated: True` -
    as soon as `max_entries` entries have been collected (a fixed
    default, `DEFAULT_MAX_ENTRIES`, overridable per call via the
    `max_entries=` constructor argument, same convention
    `text_file_read_capability.py`'s own `max_bytes=` already
    follows). This bounds memory *while walking*, not just at the end
    - a directory tree far larger than the limit is never fully
    materialized in memory before being cut down.
  - This capability never creates, modifies, renames, or deletes
    anything - it only ever calls `os.walk`/`os.path.isdir`/
    `os.path.isfile`-style read-only inspection functions from the
    standard library. No `eval()`, `exec()`, shell command,
    `subprocess`, network call, or external API of any kind, and no
    new dependency.

Nothing in this module executes on import, registers itself into any
registry automatically, or inspects any path beyond the one a caller
explicitly asks it to. `create_project_structure_inspect_capability`
only *builds* a `Capability` object;
`register_project_structure_inspect_capability` only calls the
existing, unchanged `ExecutableCapabilityRegistry.register` (or
`CapabilityHandlerRegistry.register_capability`) with it - same "no
execution without an explicit handler, no automatic discovery" rule
the rest of execution/ already follows.
"""

import os

from .capability import Capability
from .text_file_read_capability import _resolve_allowed_dirs

CAPABILITY_NAME = "project_structure_inspect"

# A reasonable, fixed default cap on how many entries one inspection
# call will ever collect - keeps a single call bounded regardless of
# how large the actual directory tree turns out to be. Overridable per
# capability instance via `max_entries=` (see
# `create_project_structure_inspect_capability`), never widened on its
# own initiative.
DEFAULT_MAX_ENTRIES = 2000

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
        "entries": {"type": "array"},
        "entry_count": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "limit": {"type": "integer"},
    },
}


def _is_within_or_equal_allowed_dirs(real_path, resolved_allowed_dirs):
    """Same `os.path.realpath` + `os.path.commonpath` containment
    technique as `text_file_read_capability._is_within_allowed_dirs`,
    except an allowed directory matching `real_path` exactly counts as
    contained here (a project-structure inspection legitimately starts
    "at" an allowed directory itself, unlike a file read/write/edit
    target, which never is one)."""
    for allowed in resolved_allowed_dirs:
        if real_path == allowed:
            return True
        try:
            if os.path.commonpath([allowed, real_path]) == allowed:
                return True
        except ValueError:
            # Different drives/roots (e.g. on Windows) - never a match,
            # never a crash.
            continue
    return False


def make_project_structure_inspect_handler(allowed_dirs=None, max_entries=DEFAULT_MAX_ENTRIES):
    """Build the plain handler callable
    `Capability("project_structure_inspect")` is constructed with.
    Kept separate from `create_project_structure_inspect_capability`
    so a caller who only wants the bare callable (e.g. to register
    directly with `CapabilityHandlerRegistry`, no `Capability` wrapper
    involved) can get one without going through `Capability` at all.

    `allowed_dirs`, if given, replaces the application's own default
    safe directories entirely (used by tests to point at an isolated
    temporary directory); if omitted, the handler resolves the
    application's real `data_dir`/`skills_dir`/`temp_dir` the first
    time it actually runs - never at import time (same convention
    `text_file_read_capability.py`'s own `_resolve_allowed_dirs`
    already follows, reused here unchanged).
    """

    def handler(data):
        path = data.get("path") if isinstance(data, dict) else None
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string.")

        resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
        real_path = os.path.realpath(path)

        if not _is_within_or_equal_allowed_dirs(real_path, resolved_allowed_dirs):
            raise ValueError(
                f"Path {path!r} is outside the allowed directories."
            )

        if not os.path.exists(real_path):
            raise ValueError(f"Directory does not exist: {path!r}")

        if not os.path.isdir(real_path):
            raise ValueError(f"Path is not a directory: {path!r}")

        entries = []
        truncated = False

        for current_dir, dir_names, file_names in os.walk(real_path, followlinks=False):
            if truncated:
                break

            dir_names.sort()
            file_names.sort()

            for dir_name in dir_names:
                if len(entries) >= max_entries:
                    truncated = True
                    break
                full_path = os.path.join(current_dir, dir_name)
                relative_path = os.path.relpath(full_path, real_path)
                entries.append({"path": relative_path, "type": "directory"})

            if truncated:
                break

            for file_name in file_names:
                if len(entries) >= max_entries:
                    truncated = True
                    break
                full_path = os.path.join(current_dir, file_name)
                relative_path = os.path.relpath(full_path, real_path)
                entries.append({"path": relative_path, "type": "file"})

            if truncated:
                break

        entries.sort(key=lambda entry: entry["path"])

        return {
            "path": real_path,
            "requested_path": path,
            "entries": entries,
            "entry_count": len(entries),
            "truncated": truncated,
            "limit": max_entries,
        }

    return handler


def create_project_structure_inspect_capability(allowed_dirs=None, max_entries=DEFAULT_MAX_ENTRIES):
    """Build (but do not register anywhere) one `Capability` instance
    for `project_structure_inspect`. Never calls the handler; same
    "construct, don't execute" convention `Capability.__init__` itself
    already follows."""
    handler = make_project_structure_inspect_handler(
        allowed_dirs=allowed_dirs, max_entries=max_entries
    )
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "List the files and directories inside an allowed project/data "
            "directory, with relative paths and file-or-directory type "
            "information, bounded to a fixed maximum number of entries."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "introspection", "read_only": True, "local_only": True},
    )


def register_project_structure_inspect_capability(
    registry, allowed_dirs=None, max_entries=DEFAULT_MAX_ENTRIES, enabled=True,
):
    """Build a fresh `project_structure_inspect` `Capability` and
    register it into `registry` - an `ExecutableCapabilityRegistry`
    (execution/executable_registry.py) or a `CapabilityHandlerRegistry`
    (execution/capability_handlers.py), both of which already expose a
    `register`/`register_capability` method that accepts a `Capability`
    object unchanged. Never registers into any registry the caller
    didn't explicitly hand in, and never registers more than once on
    its own initiative - calling this twice against the same registry
    raises exactly the same "duplicate name" error either registry
    already raises for that case. Returns the `Capability` that was
    registered."""
    capability = create_project_structure_inspect_capability(
        allowed_dirs=allowed_dirs, max_entries=max_entries
    )
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
