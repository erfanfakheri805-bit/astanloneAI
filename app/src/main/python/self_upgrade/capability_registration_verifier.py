"""
Self-Upgrade - Capability Registration Verification (REGISTERED -> VERIFIED / FAILED)
=========================================================================================
`verify_registered_capability` is the stage right after registration
(self_upgrade.capability_registration_executor, Prompt 377): given the
`RegistrationResult` a REGISTERED capability produced, it checks -
never repairs - that the capability still matches the approved
registration information:

    RegistrationResult (Prompt 377, REGISTERED/ALREADY_REGISTERED)
        + ApprovalManager (Prompt 371, re-read only)
        + CapabilitySystem (unchanged, re-read only)
        -> verify_registered_capability(...)
        -> CapabilityRegistrationVerificationResult{request_id,
               capability_name, interface_name, target_module,
               approval_request_id, source_version, status,
               mismatches, errors, verified_at}

THIS STEP ONLY VERIFIES. It never activates the capability, never
executes it or any generated code, never installs anything, never
modifies source code, never modifies the registered capability, never
bypasses human approval, never auto-repairs a mismatch, never
auto-retries a failed registration, and never starts another
self-upgrade cycle. `CapabilitySystem.set_enabled`/`register`,
`execution.capability_handlers.CapabilityHandlerRegistry.register*`,
`ApprovalManager.approve`/`reject`/`create_request`, `execute`, `run`,
and anything on `AgentLoop` do not appear anywhere in this module.

Reuses, never duplicates:
  - `self_upgrade.capability_registration_decision.
    resolve_registration_decision` (Prompt 376, unchanged) is
    re-consulted, read-only, to obtain the *current* stored approval
    decision/plan for `request_id` - the one authority on what is
    currently approved. This module never approves/rejects anything
    itself and never trusts a caller-supplied plan over it.
  - `self_upgrade.capability_registration_preparation.
    registration_information_problems`/`_non_blank` (Prompt 373,
    unchanged) is the one, existing "is this complete registration
    information" check, reused rather than a second validator.
  - `self_upgrade.capability_registration_plan.
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION` and
    `self_upgrade.capability_registration_executor._describe`/
    `REGISTRATION_RESULT_REGISTERED`/`REGISTRATION_RESULT_ALREADY_REGISTERED`
    (Prompt 374/377, unchanged) are the exact, existing "what a valid
    plan/registry description looks like" rules - reused unchanged so
    this stage can never disagree with the stage that produced its
    input.
  - `capabilities.capability_system.CapabilitySystem.all` (unchanged)
    is read, never written.

What is verified (Prompt 378's required field list, where applicable):
capability_name, interface_name, target_module, purpose, input_schema,
output_schema, dependencies, source_version (snapshot/version
reference), and approval_request_id.

Two independent sources are compared, and both must agree with the
live registry row:
  1. `registration_result["registration_plan"]` - the plan that was
     actually used at registration time (the caller's own record of
     what it registered).
  2. `resolve_registration_decision(request_id, approval_manager)` -
     the *current* stored decision, re-read fresh from the one
     authoritative store. Ordinarily this is identical to (1)
     (ApprovalManager records are immutable outside `approve`/
     `reject`), so an untouched registration verifies cleanly; any
     divergence between them, or between either of them and the live
     registry row's own description, means something has drifted
     since registration and is reported as FAILED rather than
     silently trusted.

Statuses (`status`, exactly one of `ALL_VERIFICATION_STATUSES`):
    NOT_REGISTERED - no registry entry currently exists for the
                     capability name (rule 2). Nothing to verify
                     against.
    INVALID        - `registration_result` is malformed, is not a
                     REGISTERED/ALREADY_REGISTERED result, or its own
                     recorded `registration_plan` is missing/invalid
                     required registration information (rule 3).
    VERIFIED       - every checked field agrees across the recorded
                     plan, the freshly re-read approval decision, and
                     the live registry entry's description (rule 4).
    FAILED         - the current approval decision can no longer be
                     confirmed READY_FOR_REGISTRATION (rejected,
                     pending, not found, or wrong request type), or
                     any checked field disagrees between the recorded
                     plan, the current decision, or the live registry
                     row (rule 5).

Never activates, never executes, never installs, never modifies the
registry or any project file, never approves/rejects/repairs/retries
anything, never starts another upgrade or registration cycle. Never
raises: any malformed input is reported as INVALID/FAILED with a
non-empty `errors`, never as an exception.
"""

from datetime import datetime, timezone

from self_upgrade.capability_registration_decision import (
    resolve_registration_decision,
    REGISTRATION_DECISION_STATUS_READY,
)
from self_upgrade.capability_registration_executor import (
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
    _describe,
)
from self_upgrade.capability_registration_plan import (
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
)
from self_upgrade.capability_registration_preparation import (
    registration_information_problems,
    _non_blank,
)

VERIFICATION_STATUS_VERIFIED = "VERIFIED"
VERIFICATION_STATUS_FAILED = "FAILED"
VERIFICATION_STATUS_INVALID = "INVALID"
VERIFICATION_STATUS_NOT_REGISTERED = "NOT_REGISTERED"

ALL_VERIFICATION_STATUSES = (
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_FAILED,
    VERIFICATION_STATUS_INVALID,
    VERIFICATION_STATUS_NOT_REGISTERED,
)

# The Prompt 378 field list, checked wherever both sides carry it.
_COMPARED_PLAN_FIELDS = (
    "capability_name", "interface_name", "target_module", "purpose",
    "input_schema", "output_schema", "dependencies",
    "source_version", "approval_request_id",
)

_VALID_EXECUTOR_STATUSES = (
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _result(status, request_id=None, capability_name=None, interface_name=None,
            target_module=None, approval_request_id=None, source_version=None,
            mismatches=None, errors=None):
    return {
        "request_id": request_id,
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "approval_request_id": approval_request_id,
        "source_version": source_version,
        "status": status,
        "mismatches": list(mismatches or []),
        "errors": list(errors or []),
        "verified_at": _now_iso(),
    }


def verify_registered_capability(registration_result, approval_manager, capability_system):
    """Verify - never repair, activate, or execute - that a REGISTERED
    capability (`registration_result`, the `RegistrationResult` dict
    `self_upgrade.capability_registration_executor.
    register_approved_capability` (Prompt 377) already produced)
    still matches its approved registration information. See module
    docstring for the full field list, status vocabulary, and safety
    boundary. Never raises.

    `approval_manager` must be a real `ApprovalManager` (self_upgrade.
    capability_approval_manager, Prompt 371) exposing
    `get_stored_record`, and `capability_system` a real
    `CapabilitySystem` (capabilities.capability_system, unchanged)
    exposing `all` - both are read-only inputs; neither is ever
    written to by this function.

    Always returns a `CapabilityRegistrationVerificationResult` dict
    with exactly: request_id, capability_name, interface_name,
    target_module, approval_request_id, source_version, status (one of
    `ALL_VERIFICATION_STATUSES`), mismatches, errors, verified_at.
    """
    try:
        return _verify(registration_result, approval_manager, capability_system)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(VERIFICATION_STATUS_INVALID,
                        errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _verify(registration_result, approval_manager, capability_system):
    if not isinstance(registration_result, dict):
        return _result(VERIFICATION_STATUS_INVALID,
                        errors=["registration_result must be a RegistrationResult dict."])

    request_id = registration_result.get("request_id")
    executor_status = registration_result.get("status")
    if executor_status not in _VALID_EXECUTOR_STATUSES:
        return _result(
            VERIFICATION_STATUS_INVALID, request_id,
            registration_result.get("capability_name"),
            errors=[f"registration_result status is {executor_status!r}; only a "
                    f"{REGISTRATION_RESULT_REGISTERED!r} or "
                    f"{REGISTRATION_RESULT_ALREADY_REGISTERED!r} result can be verified."])

    plan = registration_result.get("registration_plan")
    if (not isinstance(plan, dict)
            or plan.get("status") != PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION):
        return _result(
            VERIFICATION_STATUS_INVALID, request_id,
            registration_result.get("capability_name"),
            errors=["registration_result carries no valid "
                    f"{PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION!r} registration_plan."])

    capability_name = plan.get("capability_name")
    interface_name = plan.get("interface_name")
    target_module = plan.get("target_module")
    approval_request_id = plan.get("approval_request_id")
    source_version = plan.get("source_version")

    # Required registration information must still be complete and
    # valid before anything is compared against it (rule 3).
    problems = registration_information_problems(
        capability_name, interface_name, target_module,
        plan.get("input_schema"), plan.get("output_schema"), plan.get("dependencies"))
    if not _non_blank(approval_request_id):
        problems.append("approval_request_id is missing from the recorded registration_plan.")
    if problems:
        return _result(
            VERIFICATION_STATUS_INVALID, request_id, capability_name, interface_name,
            target_module, approval_request_id, source_version, errors=problems)

    if approval_manager is None or not hasattr(approval_manager, "get_stored_record"):
        return _result(
            VERIFICATION_STATUS_INVALID, request_id, capability_name, interface_name,
            target_module, approval_request_id, source_version,
            errors=["A real ApprovalManager (self_upgrade.capability_approval_manager, "
                    "Prompt 371) is required."])

    if capability_system is None or not hasattr(capability_system, "all"):
        return _result(
            VERIFICATION_STATUS_INVALID, request_id, capability_name, interface_name,
            target_module, approval_request_id, source_version,
            errors=["A real CapabilitySystem (capabilities.capability_system, "
                    "unchanged) is required."])

    # Rule 2 - the registry entry must actually exist (read-only lookup;
    # never registers, replaces, or removes anything).
    existing = next(
        (row for row in capability_system.all() if row.get("name") == capability_name), None)
    if existing is None:
        return _result(
            VERIFICATION_STATUS_NOT_REGISTERED, request_id, capability_name, interface_name,
            target_module, approval_request_id, source_version,
            errors=[f"No capability is currently registered under {capability_name!r}."])

    mismatches = []

    # Re-read the *current* approved decision fresh from the one
    # authoritative store - never trust the recorded plan alone, since
    # the underlying approval record could have changed since
    # registration (rules 4-5).
    decision = resolve_registration_decision(request_id, approval_manager)
    if decision["status"] != REGISTRATION_DECISION_STATUS_READY:
        mismatches.append(
            f"The current approval decision for request_id={request_id!r} is "
            f"{decision['status']!r}, not {REGISTRATION_DECISION_STATUS_READY!r}; the "
            "registration can no longer be confirmed as approved.")
    else:
        current_plan = decision.get("registration_plan") or {}
        for field in _COMPARED_PLAN_FIELDS:
            if plan.get(field) != current_plan.get(field):
                mismatches.append(
                    f"{field} in the recorded registration ({plan.get(field)!r}) does not "
                    f"match the currently approved value ({current_plan.get(field)!r}).")

    # The live registry row's own description must still match what
    # the recorded, valid registration information would produce.
    expected_description = _describe(
        capability_name, interface_name, target_module, plan.get("purpose"))
    if existing.get("description") != expected_description:
        mismatches.append(
            "The live registry entry's description does not match the approved "
            "registration information.")
    if existing.get("enabled"):
        # Defensive, read-only observation only: Prompt 377's executor
        # always writes enabled=False, so an enabled row here means the
        # capability was activated by something outside this chain -
        # this module reports it, it never disables or otherwise
        # touches the row.
        mismatches.append("The registered capability is unexpectedly enabled/active.")

    if mismatches:
        return _result(
            VERIFICATION_STATUS_FAILED, request_id, capability_name, interface_name,
            target_module, approval_request_id, source_version,
            mismatches=mismatches, errors=list(mismatches))

    return _result(
        VERIFICATION_STATUS_VERIFIED, request_id, capability_name, interface_name,
        target_module, approval_request_id, source_version)
