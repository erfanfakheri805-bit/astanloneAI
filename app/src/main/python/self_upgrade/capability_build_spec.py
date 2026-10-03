"""
Self-Upgrade - Capability Build Spec
=========================================
`build_capability_build_spec` connects the existing
`CapabilityImplementationSpec`
(self_upgrade.capability_implementation_spec.
build_capability_implementation_spec, Prompt 360 - itself built from
`CapabilityCreationPlan`, Prompt 359, itself built from
`AdaptivePlanAnalyzer.analyze_self_upgrade_request`, Prompt 358, itself
built from `SelfUpgradeRequest`, Prompt 357) to one small, structured
`CapabilityBuildSpec` - the last, most concrete stage before an actual
future Capability Builder would exist:

    CapabilityImplementationSpec (Prompt 360)
        -> build_capability_build_spec()
        -> {capability_name, interface_name, input_schema,
            output_schema, dependencies, implementation_steps,
            validation_requirements, test_requirements, target_module,
            status}

Same small *adapter* shape already used by every prior stage in this
chain (`self_upgrade.capability_creation_plan.
build_capability_creation_plan`,
`self_upgrade.capability_implementation_spec.
build_capability_implementation_spec`,
`agent.code_change_self_upgrade_adapter.
build_self_upgrade_input_from_code_correction`) - never a duplicate
planning, capability, or registry system (requirement: "do not create
duplicate planning, capability, or registry systems"). Every field
except `target_module` is read straight off the implementation spec,
unchanged, under (in two cases) a renamed key:
    `capability_name`            <- spec["capability_name"]
    `interface_name`              <- spec["interface_name"]
    `input_schema`                <- spec["inputs"]
    `output_schema`               <- spec["outputs"]
    `dependencies`                <- spec["dependencies"]
    `implementation_steps`        <- spec["implementation_steps"]
    `validation_requirements`     <- spec["validation_requirements"]
    `test_requirements`           <- spec["test_requirements"]
This module never re-derives *why* the implementation spec reached its
own status, and never overrides a `BLOCKED`/`INVALID` spec's verdict
with a more optimistic one of its own (requirement 5).

`target_module` (requirement 3: "describe exactly what a future
Capability Builder should create") is the one thing this module adds:
the single existing module `dependencies` (== the implementation
spec's own `affected_systems`, itself already read off already-
registered handler modules - see capability_implementation_spec.py's
own docstring) names as where this capability's implementation
already lives or would belong. It is only ever set when `dependencies`
names *exactly one* module - a `CapabilityBuilder`, when it exists,
needs one unambiguous file to work in, and this project's own records
never name more than one "affected system" per capability without
this module inventing a way to pick among them. Zero or more-than-one
entries in `dependencies` therefore means `target_module` can't be
determined without guessing, and requirement 5 ("if required
information is missing, return BLOCKED instead of guessing") applies:
`target_module` is `None` and `status` is `BLOCKED`.

Status vocabulary reuses, unchanged, the exact three values
`self_upgrade.capability_implementation_spec` (and, transitively,
`self_upgrade.capability_creation_plan`) already define
(`STATUS_READY`/`STATUS_BLOCKED`/`STATUS_INVALID`) - never a fourth,
disagreeing vocabulary:
    `INVALID`  - `spec` isn't a dict, is missing expected keys, or its
                 own `status` is already `INVALID`.
    `BLOCKED`  - the implementation spec's own `status` is `BLOCKED`,
                 OR the spec is `READY` but `target_module` still can't
                 be determined (zero or multiple `dependencies`) -
                 requirement 5 applies equally to this module's own
                 added field, not only the spec's.
    `READY`    - the implementation spec itself is `READY` *and*
                 `target_module` was actually determined.

This module never generates source code, never modifies a project
file, and never executes, installs, sandboxes, or versions anything
(requirements 6, 7, 8): no file I/O, no `eval`/`exec`/`subprocess`,
and no import of `self_upgrade.upgrade_system.UpgradeSystem`,
`self_upgrade.sandbox.Sandbox`, or `self_upgrade.version_system.
VersionSystem` anywhere in this module. `implementation_steps`/
`validation_requirements`/`test_requirements` are carried through
exactly as the implementation spec already built them - plain,
human-readable strings, never code (see
capability_implementation_spec.py's own docstring for how those were
built).

Never raises: a malformed `spec` is reported as an `INVALID` build
spec with every derivable field left empty/`None`, rather than
guessed - see `build_capability_build_spec` below.
"""

from datetime import datetime, timezone

from self_upgrade.capability_implementation_spec import (
    STATUS_READY as SPEC_STATUS_READY,
    STATUS_BLOCKED as SPEC_STATUS_BLOCKED,
    STATUS_INVALID as SPEC_STATUS_INVALID,
    ALL_STATUSES as ALL_SPEC_STATUSES,
)

STATUS_READY = SPEC_STATUS_READY
STATUS_BLOCKED = SPEC_STATUS_BLOCKED
STATUS_INVALID = SPEC_STATUS_INVALID

ALL_STATUSES = (STATUS_READY, STATUS_BLOCKED, STATUS_INVALID)

_SPEC_EXPECTED_KEYS = (
    "capability_name", "interface_name", "inputs", "outputs",
    "dependencies", "implementation_steps", "validation_requirements",
    "test_requirements", "status",
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _target_module(dependencies):
    """The single existing module `dependencies` names, or `None` if
    that isn't unambiguous - never a guess (requirement 5). Read-only:
    inspects the already-supplied list, nothing else."""
    if len(dependencies) == 1:
        return dependencies[0]
    return None


def _build_spec(
    capability_name, interface_name, input_schema, output_schema,
    dependencies, implementation_steps, validation_requirements,
    test_requirements, target_module, status,
):
    return {
        "capability_name": capability_name,
        "interface_name": interface_name,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "dependencies": list(dependencies),
        "implementation_steps": list(implementation_steps),
        "validation_requirements": list(validation_requirements),
        "test_requirements": list(test_requirements),
        "target_module": target_module,
        "status": status,
        "created_at": _now_iso(),
    }


def build_capability_build_spec(spec):
    """Build one `CapabilityBuildSpec` dict from `spec` - the exact
    dict `build_capability_implementation_spec` already returns
    (Prompt 360). See module docstring for the full status/field
    rules.

    Never mutates `spec`. Never generates source code, never modifies
    a project file, and never executes, installs, sandboxes, or
    versions anything - see module docstring."""
    if not isinstance(spec, dict) or any(key not in spec for key in _SPEC_EXPECTED_KEYS):
        return _build_spec(None, None, None, None, [], [], [], [], None, STATUS_INVALID)

    capability_name = spec.get("capability_name")
    interface_name = spec.get("interface_name")
    dependencies = list(spec.get("dependencies") or [])
    implementation_steps = list(spec.get("implementation_steps") or [])
    spec_status = spec.get("status")

    if spec_status == STATUS_INVALID or spec_status not in ALL_SPEC_STATUSES:
        return _build_spec(
            capability_name, interface_name, None, None, dependencies,
            [], [], [], None, STATUS_INVALID,
        )

    if spec_status == STATUS_BLOCKED:
        return _build_spec(
            capability_name, interface_name, None, None, dependencies,
            [], [], [], None, STATUS_BLOCKED,
        )

    # spec_status == STATUS_READY from here on.
    input_schema = spec.get("inputs")
    output_schema = spec.get("outputs")
    validation_requirements = list(spec.get("validation_requirements") or [])
    test_requirements = list(spec.get("test_requirements") or [])
    target_module = _target_module(dependencies)

    if input_schema is None or output_schema is None or target_module is None:
        # Requirement 5: the implementation spec was READY, but this
        # module's own required information (an unambiguous
        # target_module, or the schemas themselves) is still missing -
        # BLOCKED, never guessed.
        return _build_spec(
            capability_name, interface_name, None, None, dependencies,
            [], [], [], None, STATUS_BLOCKED,
        )

    return _build_spec(
        capability_name, interface_name, input_schema, output_schema,
        dependencies, implementation_steps, validation_requirements,
        test_requirements, target_module, STATUS_READY,
    )
