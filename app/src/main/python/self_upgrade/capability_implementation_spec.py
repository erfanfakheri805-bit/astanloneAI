"""
Self-Upgrade - Capability Implementation Spec
==================================================
`build_capability_implementation_spec` connects the existing
`CapabilityCreationPlan` (self_upgrade.capability_creation_plan.
build_capability_creation_plan, Prompt 359 - itself built from
`AdaptivePlanAnalyzer.analyze_self_upgrade_request`, Prompt 358, itself
built from `SelfUpgradeRequest`, Prompt 357) to one small, structured
`CapabilityImplementationSpec`:

    CapabilityCreationPlan (Prompt 359)
        -> build_capability_implementation_spec()
        -> {capability_name, purpose, inputs, outputs,
            required_capabilities, dependencies, interface_name,
            implementation_steps, validation_requirements,
            test_requirements, status}

Same small *adapter* shape already used by
`self_upgrade.capability_creation_plan.build_capability_creation_plan`
and `agent.code_change_self_upgrade_adapter.
build_self_upgrade_input_from_code_correction` - never a second,
general-purpose planning or capability-registry system (requirement 8:
"do not create a duplicate capability registry or planning system").
`capability_name`, `purpose`, `required_capabilities`, and
`implementation_steps` are read straight off the plan, unchanged
(requirement 3: "derive the specification only from available plan
information"); this module never re-derives *why* a plan reached its
own status, and never overrides a `BLOCKED`/`INVALID` plan's verdict
with a more optimistic one of its own.

`inputs`/`outputs` (requirement 3, 4 - "only from available plan
information", "never guess") are the one thing this module can add
that the plan itself doesn't carry - and only when that information is
already recorded somewhere in this project, never invented:
  - when the optional `capability_handlers` collaborator
    (`execution.capability_handlers.CapabilityHandlerRegistry` - the
    exact same, already-existing registry
    `AdaptivePlanAnalyzer.analyze_self_upgrade_request` already reads
    for `affected_systems`/`BLOCKER_MISSING_HANDLER`) has a
    `Capability` (execution/capability.py) object registered under
    `plan["capability_name"]`, its own already-declared
    `input_schema`/`output_schema` are reused, unmodified, as
    `inputs`/`outputs` - real, already-declared facts, not a guess
    (an empty `{}` schema is itself a real, already-declared "no
    constraints" fact, distinct from "unknown" below);
  - otherwise (no `capability_handlers` supplied, no handler
    registered for the name, or a handler registered that isn't a
    `Capability` object and therefore carries no schema at all)
    `inputs`/`outputs` are `None` - "unknown", never guessed at.

`interface_name` is always exactly `plan["capability_name"]` - the one
identifier this project's own `capabilities.capability_system.
CapabilitySystem` and `execution.capability_handlers.
CapabilityHandlerRegistry` already use to refer to this capability
everywhere; never a new, invented name.

`dependencies` is always exactly `plan["affected_systems"]`, unchanged
- the already-recorded modules this capability's implementation would
live in/touch, the only "what this depends on existing" information
this project's own registries already expose for a not-yet-built
capability (there is no separate module-dependency graph anywhere in
this project to draw a richer answer from).

Status vocabulary reuses, unchanged, the exact three values
`self_upgrade.capability_creation_plan` already defines
(`STATUS_READY`/`STATUS_BLOCKED`/`STATUS_INVALID`) - never a fourth,
disagreeing vocabulary:
    `INVALID`  - `plan` isn't a dict, is missing expected keys, or its
                 own `status` is already `INVALID` - this module never
                 builds a spec on top of a plan it can't trust.
    `BLOCKED`  - the plan's own `status` is `BLOCKED` (requirement 4 -
                 nothing here overrides that), OR the plan is `READY`
                 but `inputs`/`outputs` still can't be determined (no
                 `Capability` object on record for this name) -
                 requirement 4's "if required information is missing,
                 return BLOCKED instead of guessing" applies equally to
                 this module's own added fields, not only the plan's.
    `READY`    - the plan itself is `READY` *and* both `inputs` and
                 `outputs` were actually found on record.

`validation_requirements`/`test_requirements` (requirement 3) are, like
`implementation_steps` in Prompt 359, a small, fixed set of
deterministic, plain-English strings built from `capability_name` -
never source code, never a diff, and only ever populated for a `READY`
spec (requirements 5, 6: "do not generate source code yet"; an
incomplete spec has nothing safe to require validation/tests of yet).

Never modifies a project file, never registers/enables/disables a
capability or a handler, never calls a handler, and never executes,
installs, sandboxes, or versions anything (requirements 6, 7): no file
I/O, no `eval`/`exec`/`subprocess`, and no import of
`self_upgrade.upgrade_system.UpgradeSystem`,
`self_upgrade.sandbox.Sandbox`, or `self_upgrade.version_system.
VersionSystem` anywhere in this module.

Never raises: a malformed `plan` is reported as an `INVALID` spec with
an explanatory blocker-shaped note under `validation_requirements`
being left empty rather than guessed - see
`build_capability_implementation_spec` below.
"""

from datetime import datetime, timezone

from self_upgrade.capability_creation_plan import (
    STATUS_READY as PLAN_STATUS_READY,
    STATUS_BLOCKED as PLAN_STATUS_BLOCKED,
    STATUS_INVALID as PLAN_STATUS_INVALID,
    ALL_STATUSES as ALL_PLAN_STATUSES,
)

STATUS_READY = PLAN_STATUS_READY
STATUS_BLOCKED = PLAN_STATUS_BLOCKED
STATUS_INVALID = PLAN_STATUS_INVALID

ALL_STATUSES = (STATUS_READY, STATUS_BLOCKED, STATUS_INVALID)

_PLAN_EXPECTED_KEYS = (
    "capability_name", "purpose", "required_capabilities",
    "affected_systems", "implementation_steps", "status",
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _capability_schemas(capability_name, capability_handlers):
    """Returns `(inputs, outputs)` already-declared on a registered
    `Capability` object for `capability_name`, or `(None, None)` if no
    such object is on record - never a guess. Read-only: never calls
    `get`/`get_capability` for any purpose other than this lookup,
    never registers/replaces/unregisters anything."""
    if capability_handlers is None or capability_name is None:
        return None, None

    from execution.capability import Capability
    handler = capability_handlers.get(capability_name)
    if not isinstance(handler, Capability):
        return None, None

    return dict(handler.input_schema), dict(handler.output_schema)


def _validation_requirements(capability_name):
    return [
        f"Validate every input to {capability_name!r} against its declared "
        "input_schema before execution.",
        f"Validate the result of {capability_name!r} against its declared "
        "output_schema after execution.",
        f"Confirm {capability_name!r} is registered and enabled in "
        "capability_system before it is invoked.",
        f"Confirm a handler for {capability_name!r} is registered in "
        "capability_handlers before it is invoked.",
    ]


def _test_requirements(capability_name):
    return [
        f"Add a unit test that {capability_name!r} is registered and "
        "enabled in capability_system.",
        f"Add a unit test that a handler for {capability_name!r} is "
        "registered in capability_handlers.",
        f"Add a unit test covering valid input handled by {capability_name!r}.",
        f"Add a unit test covering invalid/missing input rejected by "
        f"{capability_name!r}.",
        f"Add a unit test asserting the output shape of {capability_name!r} "
        "matches its declared output_schema.",
    ]


def _spec(
    capability_name, purpose, inputs, outputs, required_capabilities,
    dependencies, interface_name, implementation_steps,
    validation_requirements, test_requirements, status,
):
    return {
        "capability_name": capability_name,
        "purpose": purpose,
        "inputs": inputs,
        "outputs": outputs,
        "required_capabilities": list(required_capabilities),
        "dependencies": list(dependencies),
        "interface_name": interface_name,
        "implementation_steps": list(implementation_steps),
        "validation_requirements": list(validation_requirements),
        "test_requirements": list(test_requirements),
        "status": status,
        "created_at": _now_iso(),
    }


def build_capability_implementation_spec(plan, capability_handlers=None):
    """Build one `CapabilityImplementationSpec` dict from `plan` - the
    exact dict `build_capability_creation_plan` already returns
    (Prompt 359). See module docstring for the full status/field
    rules.

    `capability_handlers` is optional - the same
    `execution.capability_handlers.CapabilityHandlerRegistry` a caller
    would already have on hand (e.g. the one passed to
    `AdaptivePlanAnalyzer`) - and is only ever used to look up an
    already-registered `Capability`'s own `input_schema`/
    `output_schema`; nothing is registered, replaced, or called on it.

    Never mutates `plan`. Never generates source code, never modifies
    a project file, and never executes, installs, sandboxes, or
    versions anything - see module docstring."""
    if not isinstance(plan, dict) or any(key not in plan for key in _PLAN_EXPECTED_KEYS):
        return _spec(
            None, None, None, None, [], [], None, [], [], [], STATUS_INVALID,
        )

    capability_name = plan.get("capability_name")
    purpose = plan.get("purpose")
    required_capabilities = list(plan.get("required_capabilities") or [])
    dependencies = list(plan.get("affected_systems") or [])
    implementation_steps = list(plan.get("implementation_steps") or [])
    plan_status = plan.get("status")

    if plan_status == STATUS_INVALID or plan_status not in ALL_PLAN_STATUSES:
        return _spec(
            capability_name, purpose, None, None, required_capabilities,
            dependencies, capability_name, [], [], [], STATUS_INVALID,
        )

    interface_name = capability_name

    if plan_status == STATUS_BLOCKED:
        return _spec(
            capability_name, purpose, None, None, required_capabilities,
            dependencies, interface_name, [], [], [], STATUS_BLOCKED,
        )

    # plan_status == STATUS_READY from here on.
    inputs, outputs = _capability_schemas(capability_name, capability_handlers)

    if inputs is None or outputs is None:
        # Requirement 4: the plan itself was READY, but this module's
        # own required information (declared input/output schemas) is
        # still missing - BLOCKED, never guessed.
        return _spec(
            capability_name, purpose, None, None, required_capabilities,
            dependencies, interface_name, [], [], [], STATUS_BLOCKED,
        )

    return _spec(
        capability_name, purpose, inputs, outputs, required_capabilities,
        dependencies, interface_name, implementation_steps,
        _validation_requirements(capability_name),
        _test_requirements(capability_name),
        STATUS_READY,
    )
