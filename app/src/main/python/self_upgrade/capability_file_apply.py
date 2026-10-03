"""
Self-Upgrade - Capability File Apply
=========================================
`apply_capability` is the next focused stage after the validated
`CapabilityApplyRequest` boundary (self_upgrade.
capability_apply_request.build_capability_apply_request, Prompt 363):
the first stage in this chain that actually touches a real file on
disk, and only ever the existing, unmodified, already-safe
`text_file_write` capability (execution.
text_file_write_capability.create_text_file_write_capability) to do
it:

    CapabilityApplyRequest (Prompt 363)
        -> apply_capability(request, output_root, ...)
        -> {capability_name, target_module, status, file_path,
            bytes_written, validation_result, error}

Reuses, never duplicates (requirement 4, 6):
  - `execution.text_file_write_capability.
    create_text_file_write_capability` is the *only* place this module
    ever opens a file for writing, creates a parent directory, checks
    whether a target path falls inside an allowed directory, or
    decides whether an already-existing file may be overwritten. This
    module builds exactly the small input dict
    (`path`/`text`/`overwrite`) that capability's own `input_schema`
    already expects and calls its own `Capability.execute` - no `os`
    import beyond `os.path.join`/`os.sep` to turn a dotted
    `target_module` into a relative file path (a pure string
    computation, not a safety check), and no second allowed-directory
    or overwrite check anywhere in this module.
  - `code_generation.generated_code_validator.VALIDATION_VALID` is
    read, never re-derived: this module trusts the exact
    `validation_result` a `CapabilityApplyRequest` already carries
    (requirement 3's own "the source has already passed the existing
    validation layer") rather than calling `validate_generated_code`
    a second time.
  - No new file-writing system, no new allowed-directory model, no new
    overwrite policy - `allowed_dirs` here is the exact same optional
    override `text_file_write_capability.make_text_file_write_handler`
    already accepts, passed straight through unchanged.

Validates, before ever attempting a write (requirement 3):
    `request` is a `CapabilityApplyRequest`-shaped dict at all;
    its own `status` is `READY` (an `INVALID`/`BLOCKED` request is
        passed through as `INVALID`/`BLOCKED` respectively - never
        re-derived, never overridden, and never written);
    `generated_source` is a non-empty string;
    `target_module` is a non-empty string;
    `capability_name` is present;
    `validation_result` is present and its own `status` is
        `VALIDATION_VALID` - requirement 3's "the source has already
        passed the existing validation layer", read from the request,
        never recomputed.
A request failing any of these is reported `STATUS_INVALID`, with an
`error` describing the first failure found - and, critically, no write
is even attempted (same "do not bypass validation" convention every
earlier stage in this chain already follows).

Status vocabulary (requirement 6) - four values, each a single,
unambiguous verdict:
    `INVALID` - `request` isn't a well-formed, `READY`
                `CapabilityApplyRequest` (see the validation list
                above), or the upstream request's own `status` was
                already `INVALID`.
    `BLOCKED` - the upstream request's own `status` was already
                `BLOCKED`; OR the resolved target path falls outside
                every allowed directory (requirement: "never write
                outside the allowed project workspace"); OR the target
                file already exists and `overwrite` was not explicitly
                requested (requirement 9: "return BLOCKED rather than
                silently replacing it"). The last two are read
                straight off `text_file_write`'s own, unchanged error
                messages - never re-checked independently here (see
                `_classify_write_error` below).
    `FAILED`  - the write was attempted (target allowed, no protected
                overwrite) but `text_file_write` itself reported a
                failure for some other reason (e.g. an OS-level I/O
                error) - never silently swallowed, never retried.
    `APPLIED` - `text_file_write` reported success; the file now
                contains exactly `generated_source`.

Safety requirements this module must NOT, and does not, violate
(requirement 7):
  - never write outside the allowed project workspace - enforced
    entirely by the unchanged `text_file_write` allowed-directory
    check; this module never widens `allowed_dirs` and never writes
    through any path other than the one built from `output_root` +
    `target_module`;
  - never overwrite a protected/existing file unless the caller
    explicitly passes `overwrite=True` - this module never defaults
    `overwrite` to `True` on its own, and passes it straight through
    to `text_file_write`, whose own default is already "protect what's
    already there" (requirement 9);
  - never execute the generated source - `generated_source` is only
    ever handed to `text_file_write` as the literal `text` to save;
    nothing in this module calls `eval`/`exec`/`compile`, and it has
    no import of `subprocess`;
  - never register or activate the capability - no import of
    `execution.capability_handlers.CapabilityHandlerRegistry` or
    `capabilities.capability_system.CapabilitySystem`;
  - never automatically retry - `apply_capability` is called once and
    returns once; a `FAILED`/`BLOCKED` result is never retried or
    re-attempted with different arguments by this module itself;
  - never bypass code validation - a request whose own
    `validation_result` is missing or not `VALIDATION_VALID` is always
    `INVALID`, never written anyway;
  - never bypass `text_file_write` itself - there is no second,
    lower-level file-write path anywhere in this module; every actual
    write goes through that one, unchanged capability.

Never raises: a malformed `request` is reported as an `INVALID` result
with every derivable field left empty/`None`, rather than guessed -
see `apply_capability` below.
"""

import os

from code_generation.generated_code_validator import VALIDATION_VALID
from execution.text_file_write_capability import create_text_file_write_capability
from self_upgrade.capability_apply_request import (
    STATUS_READY as REQUEST_STATUS_READY,
    STATUS_BLOCKED as REQUEST_STATUS_BLOCKED,
    STATUS_INVALID as REQUEST_STATUS_INVALID,
    ALL_STATUSES as ALL_REQUEST_STATUSES,
)

STATUS_APPLIED = "APPLIED"
STATUS_INVALID = "INVALID"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"

ALL_STATUSES = (STATUS_APPLIED, STATUS_INVALID, STATUS_BLOCKED, STATUS_FAILED)

_APPLY_REQUEST_EXPECTED_KEYS = (
    "capability_name", "interface_name", "target_module", "generated_source",
    "status", "validation_errors", "validation_result", "created_at",
)

# Substrings of the exact, unchanged error messages
# `text_file_write_capability.make_text_file_write_handler` already
# raises (see that module) - matched, never re-derived, purely so
# this module can tell those two specific, already-safe rejections
# apart from any other failure (requirement: BLOCKED, not FAILED, for
# either).
_OUTSIDE_ALLOWED_DIRS_MARKER = "outside the allowed directories"
_ALREADY_EXISTS_MARKER = "already exists and overwrite was not explicitly enabled"


def _result(capability_name, target_module, status, file_path, bytes_written,
            validation_result, error):
    return {
        "capability_name": capability_name,
        "target_module": target_module,
        "status": status,
        "file_path": file_path,
        "bytes_written": bytes_written,
        "validation_result": validation_result,
        "error": error,
    }


def _target_module_to_relative_path(target_module):
    """Pure string computation only - never a safety check. Whether
    the resulting path is actually writable is decided entirely by
    `text_file_write`'s own allowed-directory check, not here."""
    return target_module.replace(".", os.sep) + ".py"


def _classify_write_error(error_message):
    """Read the exact, unchanged error message `text_file_write`'s
    `Capability.execute` already produced (`f"{type(exc).__name__}:
    {exc}"`, wrapping the handler's own `ValueError`) and classify it
    as BLOCKED (a safety rule the write capability itself already
    enforced) or FAILED (anything else) - never re-implements either
    check itself."""
    message = error_message or ""
    if _OUTSIDE_ALLOWED_DIRS_MARKER in message or _ALREADY_EXISTS_MARKER in message:
        return STATUS_BLOCKED
    return STATUS_FAILED


def apply_capability(request, output_root, allowed_dirs=None, overwrite=False):
    """Apply a validated `CapabilityApplyRequest` (Prompt 363) to a
    real file under `output_root`, via the existing, unmodified
    `text_file_write` capability. See module docstring for the full
    status/safety rules.

    `output_root` is the directory `target_module`'s dotted path is
    resolved relative to (e.g. a project source root, or - in tests -
    an isolated temporary directory); it is never guessed, never
    defaults to the real project source tree, and is always required.

    `allowed_dirs`, if given, is passed straight through to
    `text_file_write` unchanged (same override `text_file_write_
    capability.py` itself already supports, e.g. for tests); if
    omitted, defaults to `[output_root]` only - never any wider
    default of its own.

    `overwrite` is passed straight through to `text_file_write`
    unchanged; its own default here is `False` - same "protect what's
    already there" default `text_file_write` itself already applies
    (requirement 9).

    Never mutates `request`. Never writes outside `allowed_dirs`,
    executes the generated source, registers/activates the capability,
    retries, or bypasses validation/`text_file_write` itself - see
    module docstring."""
    if not isinstance(request, dict) or any(
        key not in request for key in _APPLY_REQUEST_EXPECTED_KEYS
    ):
        return _result(
            None, None, STATUS_INVALID, None, None, None,
            "request must be a CapabilityApplyRequest dict with all expected keys.",
        )

    capability_name = request.get("capability_name")
    target_module = request.get("target_module")
    generated_source = request.get("generated_source")
    validation_result = request.get("validation_result")
    request_status = request.get("status")

    if request_status not in ALL_REQUEST_STATUSES:
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, f"request has an unrecognized status: {request_status!r}",
        )

    if request_status == REQUEST_STATUS_INVALID:
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, "Upstream CapabilityApplyRequest is INVALID.",
        )

    if request_status == REQUEST_STATUS_BLOCKED:
        return _result(
            capability_name, target_module, STATUS_BLOCKED, None, None,
            validation_result, "Upstream CapabilityApplyRequest is BLOCKED.",
        )

    # request_status == STATUS_READY from here on - this module's own
    # minimum-field/validation-layer check still applies (same "do not
    # bypass validation" convention every earlier stage already
    # follows).
    if not isinstance(capability_name, str) or not capability_name.strip():
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, "capability_name must be a non-empty string.",
        )

    if not isinstance(target_module, str) or not target_module.strip():
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, "target_module must be a non-empty string.",
        )

    if not isinstance(generated_source, str) or not generated_source.strip():
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, "generated_source is empty.",
        )

    if not isinstance(validation_result, dict) or validation_result.get("status") != VALIDATION_VALID:
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result,
            "generated_source has not already passed the existing validation layer.",
        )

    if not isinstance(output_root, str) or not output_root.strip():
        return _result(
            capability_name, target_module, STATUS_INVALID, None, None,
            validation_result, "output_root must be a non-empty string.",
        )

    relative_path = _target_module_to_relative_path(target_module)
    file_path = os.path.join(output_root, relative_path)
    resolved_allowed_dirs = allowed_dirs if allowed_dirs is not None else [output_root]

    write_capability = create_text_file_write_capability(allowed_dirs=resolved_allowed_dirs)
    execution_result = write_capability.execute(
        {"path": file_path, "text": generated_source, "overwrite": bool(overwrite)}
    )

    if not execution_result.success:
        status = _classify_write_error(execution_result.error)
        return _result(
            capability_name, target_module, status, None, None,
            validation_result, execution_result.error,
        )

    output = execution_result.output
    return _result(
        capability_name, target_module, STATUS_APPLIED,
        output["path"], output["byte_size"], validation_result, None,
    )
