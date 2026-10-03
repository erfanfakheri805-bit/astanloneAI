"""
Self-Upgrade - Capability Registration Plan
=============================================
`build_capability_registration_plan` is the stage after registration
preparation (self_upgrade.capability_registration_preparation, Prompt
373): it turns a `READY_FOR_REGISTRATION` `CapabilityRegistrationPreparation`
into one structured `CapabilityRegistrationPlan` - the complete,
self-contained description of what a *future, explicitly approved*
registration action would register:

    CapabilityRegistrationPreparation (Prompt 373, READY_FOR_REGISTRATION)
        [+ ApprovalManager (Prompt 371), optional authoritative re-check]
        -> build_capability_registration_plan(...)
        -> CapabilityRegistrationPlan{capability_name, interface_name,
               target_module, purpose, input_schema, output_schema,
               dependencies, source_version, approval_request_id,
               registration_preparation, status, reason, errors,
               created_at}

THIS IS A PLANNING STEP ONLY. Building a plan is never permission to
register anything: it does not register the capability in the live
Capability Registry, does not enable or activate it, does not execute
it or any generated code, does not install or replace anything, does
not create a version snapshot, does not approve or reject anything,
and does not read or write any project file. The actual registration
remains a separate, future step that needs its own explicit human
approval. `READY_FOR_APPROVED_REGISTRATION` only says "the information
for that later, explicitly approved step is complete and consistent" -
nothing here, and no field of the plan (there is deliberately no
`registration_allowed`/`activation_allowed` flag), authorizes it.
`CapabilitySystem.register`/`set_enabled`, `CapabilityHandlerRegistry.
register*`, `VersionSystem`, and `ApprovalManager.create_request`/
`approve`/`reject` do not appear anywhere in this module.

Reuses, never duplicates:
  - The status vocabulary and the "what is a valid registry field"
    rules of Prompt 373: `REGISTRATION_STATUS_*` and
    `registration_information_problems` (the one shared validator) are
    imported unchanged, so this stage cannot disagree with the stage
    that produced its input.
  - `self_upgrade.capability_human_approval.APPROVAL_STATUS_APPROVED`
    and `ApprovalManager.get_status` (Prompt 371, called read-only and
    only when an `approval_manager` is supplied - see below).

Statuses (`status`, exactly one of `ALL_PLAN_STATUSES`):
    BLOCKED                       - the preparation was BLOCKED (approval
                                    pending/rejected/blocked), or - when
                                    an `approval_manager` re-check is
                                    requested - `ApprovalManager` does
                                    not confirm an explicit APPROVED.
                                    Stays blocked; nothing is planned.
    INVALID                       - the preparation was INVALID, is
                                    malformed, has an unrecognized
                                    status, or is READY_FOR_REGISTRATION
                                    but its registration information or
                                    approval reference is missing/
                                    invalid/inconsistent.
    READY_FOR_APPROVED_REGISTRATION - the preparation is
                                    READY_FOR_REGISTRATION and every
                                    required field is valid.
Only a `READY_FOR_REGISTRATION` preparation can ever yield a
`READY_FOR_APPROVED_REGISTRATION` plan; a BLOCKED preparation always
yields a BLOCKED plan and an INVALID one an INVALID plan.

Approval is preserved, never inferred: `approval_request_id` (required)
and `source_version` (the version/snapshot reference, when the
preparation carries one) are copied through unchanged, and
`registration_preparation` records which preparation the plan was built
from (its status, approval_request_id and created_at).

Optional authoritative re-check: a preparation is a snapshot of an
earlier moment, and a plain dict can claim any status. When the caller
supplies `approval_manager`, the plan is only built if
`ApprovalManager.get_status(approval_request_id)` (the one authority on
human decisions) confirms APPROVED for the same capability and version;
a request that is not APPROVED is BLOCKED, and a missing record or an
identity/version mismatch is INVALID. Without `approval_manager` the
preparation's own (already gate-verified) status is what is relied on;
either way the later registration step must still obtain its own
explicit human approval.

Required information (any failure in a READY_FOR_REGISTRATION
preparation -> INVALID): a non-blank `approval_request_id`; the
Prompt 373 fields checked by `registration_information_problems`
(capability_name, interface_name, target_module, input_schema,
output_schema, dependencies); `purpose`, if present, a string;
`source_version`, if present, a dict. `purpose` and `source_version`
are optional, exactly as in Prompt 373.

Only a `READY_FOR_APPROVED_REGISTRATION` plan carries registry-entry
fields; BLOCKED/INVALID plans carry only `approval_request_id`/
`capability_name`/`registration_preparation` (when known) plus
`reason`/`errors`, so a non-ready plan can never be mistaken for a
usable one.

Never mutates its input (schemas/dependencies are deep-copied) and
never raises: any malformed input is reported as BLOCKED/INVALID with a
non-empty `errors`.
"""

import copy
from datetime import datetime, timezone

from self_upgrade.capability_human_approval import APPROVAL_STATUS_APPROVED
from self_upgrade.capability_registration_preparation import (
    REGISTRATION_STATUS_BLOCKED as PREPARATION_STATUS_BLOCKED,
    REGISTRATION_STATUS_INVALID as PREPARATION_STATUS_INVALID,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION as PREPARATION_STATUS_READY,
    registration_information_problems,
    _non_blank,
)

PLAN_STATUS_BLOCKED = "BLOCKED"
PLAN_STATUS_INVALID = "INVALID"
PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION = "READY_FOR_APPROVED_REGISTRATION"

ALL_PLAN_STATUSES = (
    PLAN_STATUS_BLOCKED,
    PLAN_STATUS_INVALID,
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _plan(status, approval_request_id=None, capability_name=None,
          registration_preparation=None, interface_name=None, target_module=None,
          purpose=None, input_schema=None, output_schema=None, dependencies=None,
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
        "registration_preparation": registration_preparation,
        "status": status,
        "reason": reason,
        "errors": list(errors or []),
        "created_at": _now_iso(),
    }


def _version_id(version):
    return version.get("id") if isinstance(version, dict) else None


def build_capability_registration_plan(registration_preparation, approval_manager=None):
    """Build one `CapabilityRegistrationPlan` from a
    `CapabilityRegistrationPreparation` dict (Prompt 373). See module
    docstring. Planning only: never registers, activates, executes, or
    modifies anything, and is never itself permission to register.
    Never raises.

    `approval_manager` is optional; when given, it is used read-only
    (`get_status`) to re-confirm the explicit APPROVED decision - see
    module docstring.

    Always returns a `CapabilityRegistrationPlan` dict with exactly:
    capability_name, interface_name, target_module, purpose,
    input_schema, output_schema, dependencies, source_version,
    approval_request_id, registration_preparation, status (one of
    `ALL_PLAN_STATUSES`), reason, errors, created_at.
    """
    try:
        return _build(registration_preparation, approval_manager)
    except Exception as exc:  # pragma: no cover - defensive
        return _plan(
            PLAN_STATUS_INVALID,
            reason="Unexpected error while building the registration plan.",
            errors=[f"Unexpected error: {type(exc).__name__}: {exc}"],
        )


def _build(preparation, approval_manager):
    if not isinstance(preparation, dict):
        reason = "registration_preparation must be a CapabilityRegistrationPreparation dict."
        return _plan(PLAN_STATUS_INVALID, reason=reason, errors=[reason])

    prep_status = preparation.get("status")
    request_id = preparation.get("approval_request_id")
    capability_name = preparation.get("capability_name")
    reference = {
        "status": prep_status,
        "approval_request_id": request_id,
        "created_at": preparation.get("created_at"),
    }

    # Rules 1-2: only a READY_FOR_REGISTRATION preparation can proceed;
    # a BLOCKED one stays BLOCKED, an INVALID one stays INVALID.
    if prep_status == PREPARATION_STATUS_BLOCKED:
        reason = "The registration preparation is BLOCKED; no registration plan was made."
        return _plan(PLAN_STATUS_BLOCKED, request_id, capability_name, reference,
                     reason=reason,
                     errors=[reason] + list(preparation.get("errors") or []))
    if prep_status == PREPARATION_STATUS_INVALID:
        reason = "The registration preparation is INVALID; no registration plan was made."
        return _plan(PLAN_STATUS_INVALID, request_id, capability_name, reference,
                     reason=reason,
                     errors=[reason] + list(preparation.get("errors") or []))
    if prep_status != PREPARATION_STATUS_READY:
        reason = (f"Unrecognized registration preparation status {prep_status!r}; "
                  f"only {PREPARATION_STATUS_READY!r} can be planned.")
        return _plan(PLAN_STATUS_INVALID, request_id, capability_name, reference,
                     reason=reason, errors=[reason])

    # Rule 4: the explicit human approval reference must be present.
    if not _non_blank(request_id):
        reason = "The preparation carries no approval_request_id (approval reference)."
        return _plan(PLAN_STATUS_INVALID, None, capability_name, reference,
                     reason=reason, errors=[reason])

    # Optional authoritative re-check (read-only): approval is never
    # inferred from the preparation dict's own claim.
    record = None
    if approval_manager is not None:
        record = approval_manager.get_status(request_id)
        if not isinstance(record, dict) or record.get("errors"):
            reason = "No matching approval record was found in ApprovalManager."
            return _plan(PLAN_STATUS_INVALID, request_id, capability_name, reference,
                         reason=reason,
                         errors=[reason] + list((record or {}).get("errors") or []))
        if record.get("status") != APPROVAL_STATUS_APPROVED:
            reason = (f"ApprovalManager reports {record.get('status')!r}, not an explicit "
                      f"APPROVED; the registration plan stays blocked.")
            return _plan(PLAN_STATUS_BLOCKED, request_id, capability_name, reference,
                         reason=reason, errors=[reason])

    # Rule 3: required registration information (shared validator).
    interface_name = preparation.get("interface_name")
    target_module = preparation.get("target_module")
    input_schema = preparation.get("input_schema")
    output_schema = preparation.get("output_schema")
    dependencies = preparation.get("dependencies")
    purpose = preparation.get("purpose")
    source_version = preparation.get("source_version")

    problems = registration_information_problems(
        capability_name, interface_name, target_module,
        input_schema, output_schema, dependencies)
    if purpose is not None and not isinstance(purpose, str):
        problems.append("purpose must be a string when present.")
    if source_version is not None and not isinstance(source_version, dict):
        problems.append("source_version must be a version reference dict when present.")
    if record is not None:
        if record.get("capability_name") != capability_name:
            problems.append("capability_name does not match the ApprovalManager record.")
        if _version_id(record.get("version")) != _version_id(source_version):
            problems.append("source_version does not match the ApprovalManager record.")

    if problems:
        reason = "Registration information is missing or invalid."
        return _plan(PLAN_STATUS_INVALID, request_id, capability_name, reference,
                     reason=reason, errors=problems)

    return _plan(
        PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
        approval_request_id=request_id,
        capability_name=capability_name,
        registration_preparation=reference,
        interface_name=interface_name,
        target_module=target_module,
        purpose=purpose,
        input_schema=copy.deepcopy(input_schema),
        output_schema=copy.deepcopy(output_schema),
        dependencies=copy.deepcopy(dependencies),
        source_version=copy.deepcopy(source_version),
        reason=("Plan complete. This is a description only: nothing has been registered, "
                "activated, or executed, and registration still requires its own "
                "explicit human approval."),
    )
