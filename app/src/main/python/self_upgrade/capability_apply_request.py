"""
Self-Upgrade - Capability Apply Request
=========================================
`build_capability_apply_request` is the next focused stage after the
`CapabilityBuilder` (self_upgrade.capability_builder.build_capability,
Prompt 362): the bridge from a successful builder result's already-
generated, in-memory `generated_source` to a validated
`CapabilityApplyRequest` - a safe boundary a caller can inspect before
any file write is ever attempted:

    CapabilityBuilder result (Prompt 362)
        -> build_capability_apply_request(result)
        -> {capability_name, interface_name, target_module,
            generated_source, status, validation_errors,
            validation_result, created_at}

    (a future, separate, not-yet-built stage would read a READY
     CapabilityApplyRequest and actually write target_module - see
     requirement 5 below; nothing in this module gets anywhere near
     that)

Reuses, never duplicates (requirement 6):
  - `code_generation.generated_code_validator.validate_generated_code`
    is the *only* place this module ever checks whether
    `generated_source` is syntactically valid Python. This module
    builds a `code_generation.code_generation_result.
    CodeGenerationResult` from the builder result's own already-
    produced `generated_source`/`target_module` (exactly the values
    that already came out of `generate_function` in Prompt 362 - never
    re-generated, never re-derived) purely so it can hand that object
    to the existing, unmodified `validate_generated_code`, and returns
    that call's own verdict unchanged as `validation_result`. No `ast`
    import, no second parser, no re-implementation of
    `code_intelligence.python_inspector.inspect_source` anywhere here.
  - Status vocabulary reuses, unchanged, the exact same three values
    `self_upgrade.capability_builder` (and, transitively, every
    earlier stage in this chain back to `capability_build_spec`)
    already defines - never a fourth, disagreeing vocabulary.
  - No new code-analysis logic, no second code generator, and no
    duplicated allowed-directory/overwrite logic from
    `execution.text_file_write_capability` or
    `execution.code_change_apply_capability` - this module never
    imports either of those, since it never writes anything (see
    requirement 5).

Validates, before ever building an apply request (requirement 2):
    the input is a `CapabilityBuilder`-shaped dict at all;
    its own `status` is `READY` (an `INVALID`/`BLOCKED` builder result
        is passed through as `INVALID`/`BLOCKED` respectively - never
        re-derived, never overridden with a more optimistic verdict);
    `generated_source` is a non-empty, non-whitespace-only string;
    `target_module` is a non-empty string (the "valid non-empty
        path/module target" this stage would eventually apply to -
        this module only checks it is a real, non-empty string; it
        never resolves it against a filesystem or an allowed-
        directories list, since that check belongs entirely to the
        later, not-yet-built write stage, exactly the way
        `text_file_write_capability`'s own allowed-directory check
        already only ever runs inside that capability's handler);
    `capability_name` and `interface_name` are both present, and
        `interface_name` is a valid, non-keyword Python identifier
        (same check `capability_builder.py` already applies, kept
        local for the same reason that module already gives: never
        depend on another module's private helper);
    `generated_source` passes the existing
        `validate_generated_code` check (requirement 2's own "existing
        code-analysis / generated-code validation infrastructure").
A builder result failing any `READY`-path check is reported as
`STATUS_INVALID` with every failure reason listed in
`validation_errors` - never partially built, never guessed around
(same "do not bypass validation" convention every earlier stage in
this chain already follows).

This module must NOT, and does not (requirement 5):
  - write the file yet, or modify any existing project file - no
    import of `execution.text_file_write_capability` or
    `execution.code_change_apply_capability`, and nothing here opens
    any file for writing;
  - execute generated code - `generated_source` is only ever handed to
    `validate_generated_code`, itself only ever calling the parse-only
    `inspect_source`; nothing in this module calls
    `eval`/`exec`/`compile(..., mode="exec")`;
  - register or activate the capability - no import of
    `execution.capability_handlers.CapabilityHandlerRegistry` or
    `capabilities.capability_system.CapabilitySystem`;
  - install anything - this module only ever returns a plain dict for
    a caller to inspect;
  - bypass the existing validation system - a builder result whose own
    generated source fails `validate_generated_code` is always
    reported `INVALID`, never applied anyway;
  - automatically retry - `build_capability_apply_request` is called
    once and returns once; it never re-invokes itself,
    `validate_generated_code`, or anything else on failure.

Never raises: a malformed `builder_result` is reported as an `INVALID`
apply request with every derivable field left empty/`None`, rather
than guessed - see `build_capability_apply_request` below.
"""

from datetime import datetime, timezone

from code_generation.code_generation_result import CodeGenerationResult, STATUS_GENERATED
from code_generation.generated_code_validator import (
    validate_generated_code,
    VALIDATION_VALID,
)
from self_upgrade.capability_builder import (
    STATUS_READY as BUILDER_STATUS_READY,
    STATUS_BLOCKED as BUILDER_STATUS_BLOCKED,
    STATUS_INVALID as BUILDER_STATUS_INVALID,
    ALL_STATUSES as ALL_BUILDER_STATUSES,
)

STATUS_READY = BUILDER_STATUS_READY
STATUS_BLOCKED = BUILDER_STATUS_BLOCKED
STATUS_INVALID = BUILDER_STATUS_INVALID

ALL_STATUSES = (STATUS_READY, STATUS_BLOCKED, STATUS_INVALID)

_BUILDER_RESULT_EXPECTED_KEYS = (
    "capability_name", "interface_name", "target_module", "generated_source",
    "status", "validation_errors", "code_generation_status", "created_at",
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _is_valid_identifier(value):
    """Same independent, local check `capability_builder.py` already
    applies (and gives the same reason for keeping local rather than
    importing a private helper from another module)."""
    import keyword
    if not isinstance(value, str) or not value.isidentifier():
        return False
    if keyword.iskeyword(value):
        return False
    if hasattr(keyword, "issoftkeyword") and keyword.issoftkeyword(value):
        return False
    return True


def _result(
    capability_name, interface_name, target_module, generated_source,
    status, validation_errors, validation_result=None,
):
    return {
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "generated_source": generated_source,
        "status": status,
        "validation_errors": list(validation_errors),
        "validation_result": validation_result,
        "created_at": _now_iso(),
    }


def build_capability_apply_request(builder_result):
    """Build one `CapabilityApplyRequest` dict from `builder_result` -
    the exact dict `capability_builder.build_capability` already
    returns (Prompt 362). See module docstring for the full
    status/field rules.

    Never mutates `builder_result`. Never writes a file, executes
    generated code, registers/activates a capability, installs
    anything, bypasses the existing validation system, or retries -
    see module docstring."""
    if not isinstance(builder_result, dict) or any(
        key not in builder_result for key in _BUILDER_RESULT_EXPECTED_KEYS
    ):
        return _result(
            None, None, None, None, STATUS_INVALID,
            ["builder_result must be a CapabilityBuilder result dict "
             "with all expected keys."],
        )

    capability_name = builder_result.get("capability_name")
    interface_name = builder_result.get("interface_name")
    target_module = builder_result.get("target_module")
    generated_source = builder_result.get("generated_source")
    builder_status = builder_result.get("status")

    if builder_status not in ALL_BUILDER_STATUSES:
        return _result(
            capability_name, interface_name, target_module, generated_source,
            STATUS_INVALID,
            [f"builder_result has an unrecognized status: {builder_status!r}"],
        )

    if builder_status == BUILDER_STATUS_INVALID:
        return _result(
            capability_name, interface_name, target_module, generated_source,
            STATUS_INVALID, ["Upstream CapabilityBuilder result is INVALID."],
        )

    if builder_status == BUILDER_STATUS_BLOCKED:
        return _result(
            capability_name, interface_name, target_module, generated_source,
            STATUS_BLOCKED, ["Upstream CapabilityBuilder result is BLOCKED."],
        )

    # builder_status == STATUS_READY from here on - this module's own
    # minimum-field/generated-source validation still applies (same
    # "do not bypass validation" convention every earlier stage
    # already follows).
    errors = []

    if not isinstance(capability_name, str) or not capability_name.strip():
        errors.append("capability_name must be a non-empty string.")

    if not _is_valid_identifier(interface_name):
        errors.append(
            f"interface_name must be a valid, non-keyword Python "
            f"identifier: {interface_name!r}"
        )

    if not isinstance(target_module, str) or not target_module.strip():
        errors.append("target_module must be a non-empty string.")

    if not isinstance(generated_source, str) or not generated_source.strip():
        errors.append("generated_source is empty.")

    if errors:
        return _result(
            capability_name, interface_name, target_module, generated_source,
            STATUS_INVALID, errors,
        )

    code_generation_result = CodeGenerationResult(
        request=None,
        target_file=target_module,
        generated_code=generated_source,
        status=STATUS_GENERATED,
    )
    validation_result = validate_generated_code(code_generation_result)

    if validation_result["status"] != VALIDATION_VALID:
        return _result(
            capability_name, interface_name, target_module, generated_source,
            STATUS_INVALID,
            [f"generated_source failed validation: {validation_result['error']}"],
            validation_result=validation_result,
        )

    return _result(
        capability_name, interface_name, target_module, generated_source,
        STATUS_READY, [], validation_result=validation_result,
    )
