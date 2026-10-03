"""
Execution - Built-in Capability: text_file_write
===================================================
A real, working `Capability` (execution/capability.py) that safely
writes text content to a file on disk and returns basic metadata about
what was written. Sibling of `text_file_read_capability.py` - same
allowed-directory safety model, same "handler raises ValueError,
`Capability.execute` turns that into a safe failed result" convention
- but deliberately its own, independent module (not sharing helper
functions with the read capability) so this stage never has to modify
or risk regressing `text_file_read_capability.py` to add writing.

    path (string), text (string), overwrite (boolean, optional)
        -> Capability("text_file_write")
        -> {path, requested_path, character_count, byte_size,
            created, overwritten}

Safety rules (all enforced by the handler, never by the caller):
  - Only paths that resolve (via `os.path.realpath`, so symlinks and
    `..` segments cannot be used to escape) inside one of a fixed set
    of allowed directories may be written to. By default those
    directories are exactly the ones the application itself already
    defines for its own data - `PlatformConfig.from_adapter()`'s
    `data_dir`, `skills_dir`, and `temp_dir` (core/config.py, backed by
    `platform_layer.get_platform()`) - never an arbitrary path on the
    filesystem. A caller may instead pass an explicit `allowed_dirs`
    list (e.g. for tests); nothing here ever widens that list on its
    own.
  - A parent directory is only ever created (via `os.makedirs`) when
    it falls inside one of those same allowed directories - which is
    always true once the target file path itself has already passed
    the allowed-directory check below, since every parent of a path
    inside an allowed directory is itself either that allowed
    directory or a directory nested inside it. A target path outside
    every allowed directory is rejected before any directory is ever
    created or any byte is ever written.
  - A file that already exists at the resolved path is never
    overwritten unless the caller explicitly passes `overwrite: True`
    - the default is always "protect what's already there". A target
    that is an existing directory is always rejected, `overwrite` or
    not (this capability only ever writes one file, never touches a
    directory itself).
  - Only Python standard-library file operations are used (`os`,
    built-in `open`) - no external packages, no network calls, no
    shell commands, and no `subprocess`.

Nothing in this module executes on import, registers itself into any
registry automatically, or writes to any path beyond the one a caller
explicitly asks it to. `create_text_file_write_capability` only
*builds* a `Capability` object; `register_text_file_write_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

import os

from .capability import Capability

CAPABILITY_NAME = "text_file_write"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
        "text": {"type": "string", "required": True},
        "overwrite": {"type": "boolean"},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "character_count": {"type": "integer"},
        "byte_size": {"type": "integer"},
        "created": {"type": "boolean"},
        "overwritten": {"type": "boolean"},
    },
}


def _default_allowed_dirs():
    """The application's own already-defined safe directories - never
    computed independently here. Imported lazily (rather than at
    module load time) so importing this module never has a side
    effect on, or a hard import-order dependency with,
    `platform_layer`/`core.config` - same "no import-time surprises"
    caution `text_file_read_capability.py` already follows."""
    from platform_layer import get_platform
    from core.config import PlatformConfig

    platform_config = PlatformConfig.from_adapter(get_platform())
    return [
        platform_config.data_dir,
        platform_config.skills_dir,
        platform_config.temp_dir,
    ]


def _resolve_allowed_dirs(allowed_dirs):
    dirs = allowed_dirs if allowed_dirs is not None else _default_allowed_dirs()
    return [os.path.realpath(directory) for directory in dirs]


def _is_within_allowed_dirs(real_path, resolved_allowed_dirs):
    for allowed in resolved_allowed_dirs:
        if real_path == allowed:
            continue  # an allowed directory itself is not a writable file target
        try:
            if os.path.commonpath([allowed, real_path]) == allowed:
                return True
        except ValueError:
            # Different drives/roots (e.g. on Windows) - never a match,
            # never a crash.
            continue
    return False


def make_text_file_write_handler(allowed_dirs=None):
    """Build the plain handler callable `Capability("text_file_write")`
    is constructed with. Kept separate from
    `create_text_file_write_capability` so a caller who only wants the
    bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`, if given, replaces the application's own default
    safe directories entirely (used by tests to point at an isolated
    temporary directory); if omitted, the handler resolves the
    application's real `data_dir`/`skills_dir`/`temp_dir` the first
    time it actually runs - never at import time.
    """

    def handler(data):
        path = data.get("path") if isinstance(data, dict) else None
        text = data.get("text") if isinstance(data, dict) else None
        overwrite = bool(data.get("overwrite", False)) if isinstance(data, dict) else False

        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string.")
        if not isinstance(text, str):
            raise ValueError("text must be a string.")

        resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
        real_path = os.path.realpath(path)

        if not _is_within_allowed_dirs(real_path, resolved_allowed_dirs):
            raise ValueError(
                f"Path {path!r} is outside the allowed directories."
            )

        if os.path.isdir(real_path):
            raise ValueError(f"Path is a directory, not a file: {path!r}")

        already_exists = os.path.exists(real_path)
        if already_exists and not overwrite:
            raise ValueError(
                f"File already exists and overwrite was not explicitly "
                f"enabled: {path!r}"
            )

        # Every parent of `real_path` is, by construction, either an
        # allowed directory itself or a directory nested inside one
        # (the containment check above already guarantees this) - so
        # it is always safe to create it here.
        parent_dir = os.path.dirname(real_path)
        if parent_dir and not os.path.isdir(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"Could not create parent directory: {exc}")

        try:
            with open(real_path, "w", encoding="utf-8") as text_file:
                text_file.write(text)
        except OSError as exc:
            raise ValueError(f"Could not write file: {exc}")

        byte_size = os.path.getsize(real_path)

        return {
            "path": real_path,
            "requested_path": path,
            "character_count": len(text),
            "byte_size": byte_size,
            "created": not already_exists,
            "overwritten": bool(already_exists and overwrite),
        }

    return handler


def create_text_file_write_capability(allowed_dirs=None):
    """Build (but do not register anywhere) one `Capability` instance
    for `text_file_write`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_text_file_write_handler(allowed_dirs=allowed_dirs)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Write text content to a file inside an allowed project/data "
            "directory and return basic metadata about what was written."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "file_output", "read_only": False, "local_only": True},
    )


def register_text_file_write_capability(registry, allowed_dirs=None, enabled=True):
    """Build a fresh `text_file_write` `Capability` and register it
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
    capability = create_text_file_write_capability(allowed_dirs=allowed_dirs)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
