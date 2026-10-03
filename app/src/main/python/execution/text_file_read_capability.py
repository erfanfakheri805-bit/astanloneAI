"""
Execution - Built-in Capability: text_file_read
==================================================
A real, working `Capability` (execution/capability.py) that safely
reads a text file from disk and returns its content plus basic
metadata. This is the project's first *executable* built-in capability
- everything else under execution/capability.py,
execution/executable_registry.py, and execution/capability_handlers.py
is infrastructure for *hosting* a capability; this module is one
actual capability built on top of that infrastructure.

    path (string) -> Capability("text_file_read") -> {path, text,
        character_count, line_count, byte_size}

Distinct from `capabilities.capability_system.CapabilitySystem`'s
`"file_input"` planned-capability placeholder (capabilities/
capability_system.py) - that is a database-backed, disabled-by-default
row describing an *intended future* capability at the application
level; this module is a small, real, standard-library-only handler
that can actually be registered and executed today through the
existing `Capability` / `ExecutableCapabilityRegistry` /
`ExecutionEngine.execute_registered_capability` machinery. Neither
reads nor writes the other.

Safety rules (all enforced by the handler, never by the caller):
  - Only paths that resolve (via `os.path.realpath`, so symlinks and
    `..` segments cannot be used to escape) inside one of a fixed set
    of allowed directories may be read. By default those directories
    are exactly the ones the application itself already defines for
    its own data - `PlatformConfig.from_adapter()`'s `data_dir`,
    `skills_dir`, and `temp_dir` (core/config.py, backed by
    `platform_layer.get_platform()`) - never an arbitrary path on the
    filesystem. A caller may instead pass an explicit `allowed_dirs`
    list (e.g. for tests, or a future stage that wants a narrower
    allow-list); nothing here ever widens that list on its own.
  - A missing file, a path outside every allowed directory, a
    directory (not a file), an unrecognized/binary file, and a file
    that isn't valid UTF-8 text are all rejected the same way this
    project already rejects a bad handler input elsewhere (see
    execution/capability.py's module docstring): the handler raises a
    plain `ValueError` describing the problem, which `Capability.execute`
    (and `ExecutionEngine.execute_registered_capability`, when this
    capability is run through it) already catches and turns into a
    safe, structured failed result - this module never needs its own
    try/except-to-result plumbing.
  - Only Python standard-library file operations are used (`os`,
    built-in `open`) - no external packages, no network calls, no
    shell commands, and no `subprocess`.

Nothing in this module executes on import, registers itself into any
registry automatically, or scans the filesystem beyond the one path a
caller asks about. `create_text_file_read_capability` only *builds* a
`Capability` object; `register_text_file_read_capability` only calls
the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

import os

from .capability import Capability

CAPABILITY_NAME = "text_file_read"

# Recognized text-file extensions. Deliberately a fixed allow-list
# (rather than "anything that isn't binary") - matches the project's
# general "never surprise a caller with something broader than they
# asked for" style, and gives a second, independent line of defense
# alongside the binary-content sniff below (an extension that lies
# about its content still gets caught by that sniff).
TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py",
    ".yaml", ".yml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm",
    ".css", ".js", ".tsv",
})

# How many bytes to inspect up front for a binary-content sniff test,
# before ever attempting a full UTF-8 decode of the whole file.
_SNIFF_BYTES = 8192

# A generous, but not unbounded, default size ceiling - keeps a single
# capability call from reading an unexpectedly huge file into memory.
# A caller may override this (e.g. in tests) via `max_bytes=`.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

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
        "text": {"type": "string"},
        "character_count": {"type": "integer"},
        "line_count": {"type": "integer"},
        "byte_size": {"type": "integer"},
    },
}


def _default_allowed_dirs():
    """The application's own already-defined safe directories - never
    computed independently here. Imported lazily (rather than at
    module load time) so importing this module never has a side
    effect on, or a hard import-order dependency with,
    `platform_layer`/`core.config` - the same "no import-time
    surprises" caution `executable_registry.py`'s own lazy `Capability`
    import already follows."""
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
            continue  # an allowed directory itself is not a readable file
        try:
            if os.path.commonpath([allowed, real_path]) == allowed:
                return True
        except ValueError:
            # Different drives/roots (e.g. on Windows) - never a match,
            # never a crash.
            continue
    return False


def _looks_binary(sample_bytes):
    """A deterministic, standard-library-only binary sniff: a NUL byte
    essentially never appears in legitimate text, so its presence is
    treated as a reliable "this is not a text file" signal - the same
    heuristic most text editors and `git` itself use."""
    return b"\x00" in sample_bytes


def make_text_file_read_handler(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build the plain handler callable `Capability("text_file_read")`
    is constructed with. Kept separate from
    `create_text_file_read_capability` so a caller who only wants the
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
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string.")

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

        _, extension = os.path.splitext(real_path)
        if extension.lower() not in TEXT_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type {extension!r}; only text files are readable."
            )

        try:
            byte_size = os.path.getsize(real_path)
        except OSError as exc:
            raise ValueError(f"Could not read file metadata: {exc}")

        if byte_size > max_bytes:
            raise ValueError(
                f"File is too large to read ({byte_size} bytes; limit is {max_bytes})."
            )

        try:
            with open(real_path, "rb") as binary_file:
                sample = binary_file.read(_SNIFF_BYTES)
        except OSError as exc:
            raise ValueError(f"Could not read file: {exc}")

        if _looks_binary(sample):
            raise ValueError(f"File appears to be binary, not text: {path!r}")

        try:
            with open(real_path, "r", encoding="utf-8") as text_file:
                text = text_file.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {exc}")
        except OSError as exc:
            raise ValueError(f"Could not read file: {exc}")

        return {
            "path": real_path,
            "requested_path": path,
            "text": text,
            "character_count": len(text),
            "line_count": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            "byte_size": byte_size,
        }

    return handler


def create_text_file_read_capability(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build (but do not register anywhere) one `Capability` instance
    for `text_file_read`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_text_file_read_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Read a text file from an allowed project/data directory and "
            "return its contents and basic metadata."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={"category": "file_input", "read_only": True, "local_only": True},
    )


def register_text_file_read_capability(
    registry, allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, enabled=True,
):
    """Build a fresh `text_file_read` `Capability` and register it into
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
    capability = create_text_file_read_capability(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
