"""
Self-Upgrade - Capability Registration Approval Request
=========================================================
`request_capability_registration_approval` is the stage after the
registration plan (self_upgrade.capability_registration_plan, Prompt
374): from a `READY_FOR_APPROVED_REGISTRATION` `CapabilityRegistrationPlan`
it builds one structured request asking a human to approve that
registration - and nothing more:

    CapabilityRegistrationPlan (Prompt 374, READY_FOR_APPROVED_REGISTRATION)
        -> request_capability_registration_approval(...)
        -> RegistrationApprovalRequest{request_id, request_type=
               "capability_registration", capability_name,
               interface_name, target_module, purpose, registration_plan,
               source_version, version, summary, status, errors,
               created_at}
        -> ApprovalManager.create_request(...)   (Prompt 371, unchanged)
        -> ApprovalManager.approve / .reject      (explicit human step)

THIS STEP ONLY CREATES AN APPROVAL REQUEST. It does not register the
capability, does not enable or activate it, does not execute it or any
generated code, does not install or replace anything, does not touch
the live Capability Registry, does not create a version snapshot, does
not read or write any project file, and does not continue to
registration afterwards - a later, separate step must do that, and only
after a human has explicitly approved this request. The request is
built with status `PENDING_APPROVAL` and this module has no way to set
any other decision: it takes no `ApprovalManager`, so it cannot
approve, reject, or even store anything. `APPROVED`/`REJECTED` only
ever come from `ApprovalManager.approve`/`reject`, called by whatever
surface represents an actual human decision.

No second approval system: the request IS a `HumanApprovalRequest`-shaped
dict (Prompt 370) - same `request_id`, `capability_name`, `version`,
`status`, `errors` fields, same status vocabulary (`APPROVAL_STATUS_*`
imported unchanged) - so the existing `ApprovalManager.create_request`
admits it (it only admits PENDING_APPROVAL requests with a request_id
and capability_name; an INVALID/BLOCKED one is refused and never
stored) and the existing PENDING_APPROVAL -> APPROVED/REJECTED
lifecycle applies to it unchanged. The extra fields it adds
(`request_type`, `interface_name`, `target_module`, `purpose`,
`registration_plan`, `source_version`) ride along in the stored record;
`version` repeats `source_version` under the existing key so
`ApprovalManager` results carry the snapshot reference too.

`request_type` ("capability_registration") is what tells this approval
apart from the earlier capability-upgrade approval (Prompt 370, which
has no `request_type`) in the same `ApprovalManager`: an approval of
one kind must never be accepted as an approval of the other, so any
later step that consumes an approved request must check `request_type`.
That step should also re-verify the original capability approval named
by `registration_plan["approval_request_id"]` against `ApprovalManager`
- this module preserves that reference but, being inert, does not
re-check it.

Statuses (`status`, reused from Prompt 370 - this module only ever sets
these three of `ALL_APPROVAL_STATUSES`):
    PENDING_APPROVAL - the plan is READY_FOR_APPROVED_REGISTRATION and
                       valid; a request now waits on an explicit human
                       decision.
    BLOCKED          - the plan was BLOCKED; no request is created.
    INVALID          - the plan was INVALID, malformed, unrecognized, or
                       READY but missing/inconsistent required
                       information; no request is created.
A BLOCKED/INVALID result carries no plan, no registry fields, and a
non-empty `errors`, so it can't be mistaken for a usable request (and
`ApprovalManager.create_request` refuses it).

Validity of a READY plan (any failure -> INVALID): the Prompt 373
fields checked by `registration_information_problems` (capability_name,
interface_name, target_module, input_schema, output_schema,
dependencies); a non-blank `approval_request_id`; a
`registration_preparation` reference whose status is
READY_FOR_REGISTRATION; `purpose`, if present, a string;
`source_version`, if present, a dict. `purpose` and `source_version`
are optional, exactly as in Prompts 373-374.

`registration_plan` is a deep copy of the whole plan - the human is
approving exactly what it says, and the stored request keeps that
content even if a new plan is built later. It carries the plan's own
`approval_request_id`, `registration_preparation` and `source_version`
references, so the whole chain stays traceable.

Never mutates its input and never raises: any malformed input is
reported as BLOCKED/INVALID with a non-empty `errors`.
"""

import copy
import uuid
from datetime import datetime, timezone

from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_INVALID,
    APPROVAL_STATUS_BLOCKED,
)
from self_upgrade.capability_registration_plan import (
    PLAN_STATUS_BLOCKED,
    PLAN_STATUS_INVALID,
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION as PLAN_STATUS_READY,
)
from self_upgrade.capability_registration_preparation import (
    REGISTRATION_STATUS_READY_FOR_REGISTRATION as PREPARATION_STATUS_READY,
    registration_information_problems,
    _non_blank,
)

REQUEST_TYPE_CAPABILITY_REGISTRATION = "capability_registration"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _request(status, capability_name=None, errors=None, interface_name=None,
             target_module=None, purpose=None, registration_plan=None,
             source_version=None, summary=None, request_id=None):
    return {
        "request_id": request_id or f"registration-approval-{uuid.uuid4().hex}",
        "request_type": REQUEST_TYPE_CAPABILITY_REGISTRATION,
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "purpose": purpose,
        "registration_plan": registration_plan,
        "source_version": source_version,
        # Same snapshot reference under HumanApprovalRequest's own key,
        # so ApprovalManager results carry it too.
        "version": copy.deepcopy(source_version),
        "summary": summary,
        "status": status,
        "errors": list(errors or []),
        "created_at": _now_iso(),
    }


def request_capability_registration_approval(registration_plan):
    """Build a `PENDING_APPROVAL` `RegistrationApprovalRequest` for a
    `READY_FOR_APPROVED_REGISTRATION` `CapabilityRegistrationPlan`
    (Prompt 374). See module docstring. Creating the request is never
    permission to register anything; never registers, activates,
    executes, stores, approves, or rejects anything; never raises.

    Always returns a dict with exactly: request_id, request_type,
    capability_name, interface_name, target_module, purpose,
    registration_plan, source_version, version, summary, status (one of
    PENDING_APPROVAL / BLOCKED / INVALID), errors, created_at.
    """
    try:
        return _build(registration_plan)
    except Exception as exc:  # pragma: no cover - defensive
        return _request(APPROVAL_STATUS_INVALID,
                        errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _build(plan):
    if not isinstance(plan, dict):
        return _request(APPROVAL_STATUS_INVALID,
                        errors=["registration_plan must be a CapabilityRegistrationPlan dict."])

    plan_status = plan.get("status")
    capability_name = plan.get("capability_name")

    # Rules 1-2: only a READY_FOR_APPROVED_REGISTRATION plan can create a
    # request; BLOCKED/INVALID plans never do.
    if plan_status == PLAN_STATUS_BLOCKED:
        return _request(APPROVAL_STATUS_BLOCKED, capability_name, errors=[
            "The registration plan is BLOCKED; no registration approval request was created."
        ] + list(plan.get("errors") or []))
    if plan_status == PLAN_STATUS_INVALID:
        return _request(APPROVAL_STATUS_INVALID, capability_name, errors=[
            "The registration plan is INVALID; no registration approval request was created."
        ] + list(plan.get("errors") or []))
    if plan_status != PLAN_STATUS_READY:
        return _request(APPROVAL_STATUS_INVALID, capability_name, errors=[
            f"Unrecognized registration plan status {plan_status!r}; only "
            f"{PLAN_STATUS_READY!r} can request registration approval."])

    interface_name = plan.get("interface_name")
    target_module = plan.get("target_module")
    purpose = plan.get("purpose")
    source_version = plan.get("source_version")
    preparation_ref = plan.get("registration_preparation")

    problems = registration_information_problems(
        capability_name, interface_name, target_module,
        plan.get("input_schema"), plan.get("output_schema"), plan.get("dependencies"))
    if not _non_blank(plan.get("approval_request_id")):
        problems.append("approval_request_id (the earlier human approval reference) is missing.")
    if (not isinstance(preparation_ref, dict)
            or preparation_ref.get("status") != PREPARATION_STATUS_READY):
        problems.append("registration_preparation reference is missing or not "
                        f"{PREPARATION_STATUS_READY!r}.")
    if purpose is not None and not isinstance(purpose, str):
        problems.append("purpose must be a string when present.")
    if source_version is not None and not isinstance(source_version, dict):
        problems.append("source_version must be a version reference dict when present.")
    if problems:
        return _request(APPROVAL_STATUS_INVALID, capability_name, errors=problems)

    summary = (
        f"Registration of capability {capability_name!r} (interface "
        f"{interface_name!r}, module {target_module!r}) is pending explicit human "
        "approval. Approving records a decision only; registration and activation "
        "remain separate steps."
    )
    return _request(
        APPROVAL_STATUS_PENDING, capability_name,
        interface_name=interface_name, target_module=target_module, purpose=purpose,
        registration_plan=copy.deepcopy(plan),
        source_version=copy.deepcopy(source_version),
        summary=summary,
    )
