"""
Self-Upgrade - Capability Builder
=========================================
`build_capability` is the first real **Capability Builder**: the
bridge from a `CapabilityBuildSpec`
(`self_upgrade.capability_build_spec.build_capability_build_spec`,
Prompt 361 - itself built from `CapabilityImplementationSpec`, Prompt
360, itself built from `CapabilityCreationPlan`, Prompt 359, itself
built from `AdaptivePlanAnalyzer.analyze_self_upgrade_request`, Prompt
358, itself built from `SelfUpgradeRequest`, Prompt 357) to an actual,
inspectable Python source skeleton for that capability:

    CapabilityBuildSpec (Prompt 361)
        -> build_capability(spec)
        -> {capability_name, interface_name, target_module,
            generated_source, status, validation_errors,
            code_generation_status, created_at}

Reuses, never duplicates, the existing local, deterministic code
generator (Prompt 335 - `code_generation.local_function_generator.
generate_function`, itself returning a
`code_generation.code_generation_result.CodeGenerationResult`). This
module never assembles Python source text of its own; it only ever
turns a `CapabilityBuildSpec`'s already-declared fields into the small,
structured spec dict `generate_function` already understands
(`function_name`, `parameters`, `return_expression`, `docstring`), and
reports back exactly what that existing generator produced. Same
"reuse, don't reinvent" convention already used by every earlier stage
in this chain.

Validates the minimum a spec must supply before any generation is even
attempted (requirement 3):
    `capability_name`       - non-empty string
    `interface_name`        - resolves to a valid, non-keyword Python
                               identifier (the function name a skeleton
                               would be generated under)
    `target_module`         - non-empty string (where a skeleton would
                               belong - never written there, only
                               labelled)
    `implementation_steps`  - a non-empty list (folded into the
                               generated skeleton's own docstring, as
                               plain text - never as code)
    `input_schema`/`output_schema` - required *whenever the spec itself
                               claims to be READY* (see status rules
                               below); a `BLOCKED`/`INVALID` spec is
                               never asked to supply schemas that its
                               own earlier stage already said it could
                               not determine.
A spec failing any of these is reported as `STATUS_INVALID` with every
failure reason listed in `validation_errors` - never partially built,
never guessed around (requirement: "do not bypass validation").

Status vocabulary reuses, unchanged, the exact three values
`self_upgrade.capability_build_spec` (and, transitively, every earlier
stage in this chain) already defines (requirement 6):
    `INVALID`  - `spec` isn't a dict, is missing expected keys, its own
                 `status` is already `INVALID`, this module's own
                 minimum-field validation fails, or the underlying
                 `generate_function` call itself reports
                 `STATUS_INVALID_REQUEST`.
    `BLOCKED`  - the build spec's own `status` is already `BLOCKED` -
                 this module never re-derives *why* an upstream stage
                 blocked, and never overrides that verdict with a more
                 optimistic one of its own (same rule
                 `capability_build_spec.py` already applies to the
                 implementation spec's own verdict).
    `READY`    - the build spec itself is `READY`, this module's own
                 minimum-field validation passes, *and* the underlying
                 `generate_function` call reports `STATUS_GENERATED`.

This module must NOT, and does not (requirement 7):
  - write any file - `target_module`/`generated_source` are plain
    string values only; neither is ever opened, read, or written by
    anything in this module, and there is no import of
    `execution.text_file_write_capability` or
    `execution.code_change_apply_capability` anywhere here;
  - execute generated code - the generated source is only ever handed
    back as inspectable text (via `generate_function`'s own,
    parse-only `ast`-based validation); nothing in this module calls
    `eval`/`exec`/`compile(..., mode="exec")`, and nothing runs the
    generated function;
  - install, register, or activate the capability - no import of
    `execution.capability_handlers.CapabilityHandlerRegistry` or
    `capabilities.capability_system.CapabilitySystem` anywhere in this
    module, and nothing here registers, enables, or activates
    anything;
  - modify existing project source automatically - this module only
    ever *returns* a generated skeleton for a caller to inspect; it
    never opens or edits any file on disk;
  - bypass sandboxing - no import of `self_upgrade.sandbox.Sandbox`
    anywhere in this module; sandboxed execution remains an entirely
    separate, later, not-yet-built stage;
  - bypass validation - a spec that fails this module's own minimum-
    field checks, or the build spec's own upstream verdict, is always
    reported as `INVALID`/`BLOCKED` rather than built anyway;
  - automatically retry - `build_capability` is called once and
    returns once; it never re-invokes itself, `generate_function`, or
    anything else on failure.

The generated skeleton is deliberately a *skeleton*, not a full
implementation (matching `generate_function`'s own, deliberately
narrow, single-`def`/single-`return` scope): its parameters are the
already-declared property names from `input_schema["properties"]`
(sorted, for determinism), its docstring is the capability's own
`implementation_steps` folded into plain, human-readable text (never
code), and its `return` expression is a plain dict literal built from
`output_schema["properties"]` keys, each mapped to `None` as an
explicit placeholder a later, separate stage would still need to fill
in - never a guess at real return values.

Never raises: a malformed `spec` is reported as an `INVALID` build
result with every derivable field left empty/`None`, rather than
guessed - see `build_capability` below.
"""

from datetime import datetime, timezone

from code_generation.local_function_generator import generate_function
from code_generation.code_generation_result import STATUS_GENERATED
from self_upgrade.capability_build_spec import (
    STATUS_READY as SPEC_STATUS_READY,
    STATUS_BLOCKED as SPEC_STATUS_BLOCKED,
    STATUS_INVALID as SPEC_STATUS_INVALID,
    ALL_STATUSES as ALL_SPEC_STATUSES,
)

STATUS_READY = SPEC_STATUS_READY
STATUS_BLOCKED = SPEC_STATUS_BLOCKED
STATUS_INVALID = SPEC_STATUS_INVALID

ALL_STATUSES = (STATUS_READY, STATUS_BLOCKED, STATUS_INVALID)

_BUILD_SPEC_EXPECTED_KEYS = (
    "capability_name", "interface_name", "input_schema", "output_schema",
    "dependencies", "implementation_steps", "validation_requirements",
    "test_requirements", "target_module", "status",
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _is_valid_identifier(value):
    """Same two standard-library checks `code_generation.
    local_function_generator._is_valid_identifier` already applies -
    kept as an independent, local check (rather than importing a
    private helper from another module) so this module's own
    validation never depends on another module's private surface."""
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
    status, validation_errors, code_generation_status=None,
):
    return {
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "generated_source": generated_source,
        "status": status,
        "validation_errors": list(validation_errors),
        "code_generation_status": code_generation_status,
        "created_at": _now_iso(),
    }


def _validate_minimum_fields(spec):
    """Structural validation only (requirement 3) - every check here
    inspects the already-structured `spec` dict's own fields. Returns
    a list of human-readable error strings; empty means `spec` carries
    the minimum a `CapabilityBuilder` needs to attempt generation.
    Only ever called on a `spec` whose own `status` is already
    `STATUS_READY` - a `BLOCKED`/`INVALID` spec is never asked to
    supply fields its own earlier stage already said it could not
    determine."""
    errors = []

    capability_name = spec.get("capability_name")
    if not isinstance(capability_name, str) or not capability_name.strip():
        errors.append("capability_name must be a non-empty string.")

    interface_name = spec.get("interface_name")
    if not _is_valid_identifier(interface_name):
        errors.append(
            f"interface_name must be a valid, non-keyword Python "
            f"identifier: {interface_name!r}"
        )

    target_module = spec.get("target_module")
    if not isinstance(target_module, str) or not target_module.strip():
        errors.append("target_module must be a non-empty string.")

    implementation_steps = spec.get("implementation_steps")
    if not isinstance(implementation_steps, list) or not implementation_steps:
        errors.append("implementation_steps must be a non-empty list.")

    input_schema = spec.get("input_schema")
    if not isinstance(input_schema, dict):
        errors.append("input_schema is required and must be a dict.")

    output_schema = spec.get("output_schema")
    if not isinstance(output_schema, dict):
        errors.append("output_schema is required and must be a dict.")

    return errors


def _schema_property_names(schema):
    """Already-declared property names from a `Capability`-style
    schema (see execution/capability.py's own schema-vocabulary
    docstring), sorted for determinism - never a guess at fields the
    schema does not actually declare. Read-only: inspects the
    already-supplied dict, nothing else."""
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    return sorted(name for name in properties if _is_valid_identifier(name))


def _build_docstring(capability_name, target_module, implementation_steps):
    lines = [
        f"Skeleton for capability {capability_name!r}.",
        "",
        f"Intended target_module: {target_module}.",
        "Implementation steps (from CapabilityBuildSpec):",
    ]
    lines.extend(f"  - {step}" for step in implementation_steps)
    lines.append("")
    lines.append(
        "This is a generated skeleton only - it is not written to "
        "target_module, not executed, and not registered/activated."
    )
    return "\n".join(lines)


def _build_return_expression(output_schema):
    output_fields = _schema_property_names(output_schema)
    if not output_fields:
        return "None"
    body = ", ".join(f"{name!r}: None" for name in output_fields)
    return "{" + body + "}"


def build_capability(spec):
    """Build one `CapabilityBuilder` result dict from `spec` - the
    exact dict `build_capability_build_spec` already returns (Prompt
    361). See module docstring for the full status/field rules.

    Never mutates `spec`. Never writes a file, executes generated
    code, installs/registers/activates a capability, modifies existing
    project source, bypasses sandboxing/validation, or retries - see
    module docstring."""
    if not isinstance(spec, dict) or any(
        key not in spec for key in _BUILD_SPEC_EXPECTED_KEYS
    ):
        return _result(
            None, None, None, None, STATUS_INVALID,
            ["spec must be a CapabilityBuildSpec dict with all expected keys."],
        )

    capability_name = spec.get("capability_name")
    interface_name = spec.get("interface_name")
    target_module = spec.get("target_module")
    spec_status = spec.get("status")

    if spec_status not in ALL_SPEC_STATUSES:
        return _result(
            capability_name, interface_name, target_module, None,
            STATUS_INVALID, [f"spec has an unrecognized status: {spec_status!r}"],
        )

    if spec_status == STATUS_INVALID:
        return _result(
            capability_name, interface_name, target_module, None,
            STATUS_INVALID, ["Upstream CapabilityBuildSpec is INVALID."],
        )

    if spec_status == STATUS_BLOCKED:
        return _result(
            capability_name, interface_name, target_module, None,
            STATUS_BLOCKED, ["Upstream CapabilityBuildSpec is BLOCKED."],
        )

    # spec_status == STATUS_READY from here on - this module's own
    # minimum-field validation still applies (requirement: "do not
    # bypass validation").
    field_errors = _validate_minimum_fields(spec)
    if field_errors:
        return _result(
            capability_name, interface_name, target_module, None,
            STATUS_INVALID, field_errors,
        )

    implementation_steps = list(spec.get("implementation_steps") or [])
    input_schema = spec.get("input_schema")
    output_schema = spec.get("output_schema")

    generation_spec = {
        "function_name": interface_name,
        "parameters": _schema_property_names(input_schema),
        "return_expression": _build_return_expression(output_schema),
        "docstring": _build_docstring(
            capability_name, target_module, implementation_steps
        ),
    }

    generation_result = generate_function(generation_spec, target_file=target_module)

    if generation_result.status != STATUS_GENERATED:
        return _result(
            capability_name, interface_name, target_module,
            generation_result.generated_code, STATUS_INVALID,
            [f"Code generation failed: {generation_result.error}"],
            code_generation_status=generation_result.status,
        )

    return _result(
        capability_name, interface_name, target_module,
        generation_result.generated_code, STATUS_READY, [],
        code_generation_status=generation_result.status,
    )
