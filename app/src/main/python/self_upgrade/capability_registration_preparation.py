"""
Self-Upgrade - Capability Registration Preparation
====================================================
`prepare_capability_registration` is the stage after the approval gate
(self_upgrade.capability_approval_gate, Prompt 372): once a capability
has been explicitly APPROVED by a human, it assembles - and only
assembles - the small, structured information a *future* Capability
Registry entry would need:

    HumanApprovalRequest (Prompt 370)
        + ApprovalManager (Prompt 371, the authority on approval)
        + CapabilityBuildSpec (Prompt 361)
        -> prepare_capability_registration(...)
        -> CapabilityRegistrationPreparation{capability_name,
               interface_name, target_module, purpose, input_schema,
               output_schema, dependencies, source_version,
               approval_request_id, status, reason, errors, created_at}

ARCHITECTURAL BOUNDARY (this module exists to enforce it, not just
document it): this module only DESCRIBES a registration. It never
registers a capability, never enables or activates one, never executes
one, never installs or replaces anything, never creates a version
snapshot, never approves or rejects anything, and never reads or
writes a project file. Actual registration/activation is a separate,
future stage that will require its own explicit human approval; a
`READY_FOR_REGISTRATION` result here is input for that stage, never a
substitute for its approval. `CapabilitySystem.register`/
`set_enabled`, `CapabilityHandlerRegistry.register*`,
`VersionSystem.create_version`/`rollback_to`, and
`ApprovalManager.create_request`/`approve`/`reject` do not appear
anywhere in this module.

Reuses, never duplicates:
  - `self_upgrade.capability_approval_gate.
    evaluate_self_upgrade_approval_gate` (Prompt 372, unchanged) is the
    ONE place approval is decided here. It re-checks the request
    against `ApprovalManager.get_status` (the authoritative record) and
    never trusts a `HumanApprovalRequest`'s own, possibly-stale
    `status`. Approval is therefore never inferred: only a request the
    gate reports `READY_FOR_ACTIVATION` - i.e. `ApprovalManager`
    confirms an explicit APPROVED - can produce anything but BLOCKED/
    INVALID. (A request that merely claims `status="APPROVED"` on its
    own is not PENDING_APPROVAL, so the gate rejects it as INVALID.)
  - `self_upgrade.capability_build_spec.STATUS_READY` and the existing
    `CapabilityBuildSpec` dict shape (capability_name, interface_name,
    input_schema, output_schema, dependencies, target_module) are read
    unchanged. No second spec, registry, approval, or version system is
    introduced.
  - The gate's own `version` (the version/snapshot row recorded by
    `request_capability_human_approval` through the existing
    `VersionSystem`) is referenced as `source_version` when available.

Statuses (`status`, exactly one of `ALL_REGISTRATION_STATUSES`):
    BLOCKED                - the approval gate did not confirm an
                             explicit APPROVED: still PENDING_APPROVAL,
                             REJECTED, or the underlying request was
                             itself BLOCKED. Nothing is prepared.
    INVALID                - either the approval input itself was
                             malformed/unresolvable (the gate's own
                             INVALID: not a request dict, no
                             ApprovalManager, no matching record,
                             identity/version mismatch, or an INVALID
                             request - mirrored from the existing
                             approval model, never reinterpreted), OR
                             approval was confirmed but the registration
                             information is missing/invalid (see below).
    READY_FOR_REGISTRATION - approval was explicitly confirmed AND every
                             required registration field is valid.

Approval is always evaluated first, so a capability that is not yet
approved is BLOCKED regardless of how complete its build spec is.

Required registration information (any failure -> INVALID):
  - `build_spec` is a dict whose own `status` is READY;
  - `capability_name` and `interface_name` are non-blank strings;
  - `target_module` is a non-blank string;
  - `input_schema` and `output_schema` are dicts (an empty `{}` is the
    existing "no constraints" declaration and is valid; `None` means
    "unknown" and is not);
  - `dependencies` is a list of non-blank strings;
  - `build_spec["capability_name"]` equals the approved request's
    capability_name (an approval for one capability can never prepare
    the registration of another);
  - `purpose`, if supplied, is a string.
`purpose` is optional: `CapabilityBuildSpec` does not carry it (only
the earlier CapabilityImplementationSpec/CapabilityCreationPlan do), so
it is taken from the `purpose` argument, else from `build_spec["purpose"]`
if present, else left `None`.

Only a `READY_FOR_REGISTRATION` result carries registry-entry fields;
BLOCKED/INVALID results carry only `approval_request_id`/
`capability_name` (when known) plus `reason`/`errors`, so a non-ready
result can never be mistaken for a usable registry entry.

Never mutates its inputs (schemas/dependencies are deep-copied), never
raises: any malformed input is reported as BLOCKED/INVALID with a
non-empty `errors`.
"""

import copy
from datetime import datetime, timezone

from self_upgrade.capability_approval_gate import (
    evaluate_self_upgrade_approval_gate,
    GATE_STATUS_READY_FOR_ACTIVATION,
    GATE_STATUS_INVALID,
)
from self_upgrade.capability_build_spec import STATUS_READY as BUILD_SPEC_STATUS_READY
from self_upgrade.capability_human_approval import APPROVAL_STATUS_APPROVED

REGISTRATION_STATUS_BLOCKED = "BLOCKED"
REGISTRATION_STATUS_INVALID = "INVALID"
REGISTRATION_STATUS_READY_FOR_REGISTRATION = "READY_FOR_REGISTRATION"

ALL_REGISTRATION_STATUSES = (
    REGISTRATION_STATUS_BLOCKED,
    REGISTRATION_STATUS_INVALID,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def registration_information_problems(capability_name, interface_name, target_module,
                                      input_schema, output_schema, dependencies):
    """The one place the required registry-entry fields are validated:
    returns a list of problem strings (empty when everything is valid).
    Used by `prepare_capability_registration` here and reused unchanged
    by `self_upgrade.capability_registration_plan` (Prompt 374), so the
    two stages can never disagree about what "complete registration
    information" means. Pure: reads its arguments, nothing else."""
    problems = []
    if not _non_blank(capability_name):
        problems.append("capability_name is missing.")
    if not _non_blank(interface_name):
        problems.append("interface_name (interface information) is missing.")
    if not _non_blank(target_module):
        problems.append("target_module is missing.")
    if not isinstance(input_schema, dict):
        problems.append("input_schema is missing or not a dict.")
    if not isinstance(output_schema, dict):
        problems.append("output_schema is missing or not a dict.")
    if not isinstance(dependencies, list) or not all(_non_blank(d) for d in dependencies):
        problems.append("dependencies must be a list of non-blank module names.")
    return problems


def _preparation(status, approval_request_id=None, capability_name=None,
                 interface_name=None, target_module=None, purpose=None,
                 input_schema=None, output_schema=None, dependencies=None,
                 source_version=None, reason="", errors=None):
    return {
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "purpose": purpose,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "dependencies": list(dependencies or []),
        "source_version": source_version,
        "approval_request_id": approval_request_id,
        "status": status,
        "reason": reason,
        "errors": list(errors or []),
        "created_at": _now_iso(),
    }


def _version_reference(version):
    """A compact, JSON-friendly reference to the version/snapshot row
    the approval carries (id + label), or `None` if none is available.
    Read-only: never creates or touches a version."""
    if not isinstance(version, dict) or version.get("id") is None:
        return None
    return {"id": version.get("id"), "version_label": version.get("version_label")}


def prepare_capability_registration(human_approval_request, approval_manager,
                                    build_spec, purpose=None):
    """Prepare - never perform - the registry entry for a capability
    whose human approval was explicitly confirmed. See module
    docstring. Never registers, activates, executes, or modifies
    anything; never raises.

    `human_approval_request` is the `HumanApprovalRequest` dict
    `self_upgrade.capability_human_approval.
    request_capability_human_approval` (Prompt 370) produced, and
    `approval_manager` the `self_upgrade.capability_approval_manager.
    ApprovalManager` (Prompt 371) that holds the authoritative,
    explicitly human-made decision - both are only handed to the
    existing approval gate (Prompt 372), which is the sole authority on
    whether approval exists.

    `build_spec` is the `CapabilityBuildSpec` dict
    `self_upgrade.capability_build_spec.build_capability_build_spec`
    (Prompt 361) already produced. `purpose` is optional (see module
    docstring).

    Always returns a `CapabilityRegistrationPreparation` dict with
    exactly: capability_name, interface_name, target_module, purpose,
    input_schema, output_schema, dependencies, source_version,
    approval_request_id, status (one of `ALL_REGISTRATION_STATUSES`),
    reason, errors, created_at.
    """
    try:
        return _prepare(human_approval_request, approval_manager, build_spec, purpose)
    except Exception as exc:  # pragma: no cover - defensive
        return _preparation(
            REGISTRATION_STATUS_INVALID,
            reason="Unexpected error during registration preparation.",
            errors=[f"Unexpected error: {type(exc).__name__}: {exc}"],
        )


def _prepare(human_approval_request, approval_manager, build_spec, purpose):
    # Step 1 - approval. Decided only by the existing gate, which
    # consults the authoritative ApprovalManager record. Nothing about
    # the build spec is even looked at unless approval is explicit.
    gate = evaluate_self_upgrade_approval_gate(human_approval_request, approval_manager)
    request_id = gate.get("request_id")
    approved_name = gate.get("capability_name")
    gate_status = gate.get("gate_status")

    explicitly_approved = (
        gate_status == GATE_STATUS_READY_FOR_ACTIVATION
        and gate.get("registration_allowed") is True
        and gate.get("approval_status") == APPROVAL_STATUS_APPROVED
    )
    if not explicitly_approved:
        # Mirror the existing approval model: a malformed/unresolvable
        # approval is INVALID; a well-formed approval that is simply not
        # (yet) APPROVED - pending, rejected, blocked - is BLOCKED.
        status = (REGISTRATION_STATUS_INVALID if gate_status == GATE_STATUS_INVALID
                  else REGISTRATION_STATUS_BLOCKED)
        reason = (f"Registration preparation refused: approval gate status is "
                  f"{gate_status!r}, not an explicit APPROVED.")
        return _preparation(
            status, request_id, approved_name, reason=reason,
            errors=[reason] + list(gate.get("errors") or []),
        )

    # Step 2 - registration information. Approval is explicit; now
    # every required field must be present and valid.
    problems = []
    if not isinstance(build_spec, dict):
        problems.append("build_spec must be a CapabilityBuildSpec dict.")
        build_spec = {}
    elif build_spec.get("status") != BUILD_SPEC_STATUS_READY:
        problems.append(
            f"build_spec status must be {BUILD_SPEC_STATUS_READY!r} "
            f"(got {build_spec.get('status')!r}).")

    capability_name = build_spec.get("capability_name")
    interface_name = build_spec.get("interface_name")
    target_module = build_spec.get("target_module")
    input_schema = build_spec.get("input_schema")
    output_schema = build_spec.get("output_schema")
    dependencies = build_spec.get("dependencies")

    problems.extend(registration_information_problems(
        capability_name, interface_name, target_module,
        input_schema, output_schema, dependencies))
    if _non_blank(capability_name) and capability_name != approved_name:
        problems.append(
            f"capability_name {capability_name!r} does not match the approved "
            f"capability {approved_name!r}.")

    if purpose is None:
        purpose = build_spec.get("purpose")
    if purpose is not None and not isinstance(purpose, str):
        problems.append("purpose must be a string when supplied.")
    elif isinstance(purpose, str) and not purpose.strip():
        purpose = None

    if problems:
        reason = "Registration information is missing or invalid."
        return _preparation(
            REGISTRATION_STATUS_INVALID, request_id, approved_name,
            reason=reason, errors=problems,
        )

    return _preparation(
        REGISTRATION_STATUS_READY_FOR_REGISTRATION,
        approval_request_id=request_id,
        capability_name=capability_name,
        interface_name=interface_name,
        target_module=target_module,
        purpose=purpose,
        input_schema=copy.deepcopy(input_schema),
        output_schema=copy.deepcopy(output_schema),
        dependencies=copy.deepcopy(dependencies),
        source_version=_version_reference(gate.get("version")),
        reason=("Explicit human APPROVAL confirmed and all registration information "
                "is valid. Registration has NOT been performed; it remains a separate "
                "step requiring explicit human approval."),
    )
