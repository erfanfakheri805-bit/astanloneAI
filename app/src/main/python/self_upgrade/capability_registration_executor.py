"""
Self-Upgrade - Capability Registration Executor (READY_FOR_REGISTRATION -> REGISTERED)
=========================================================================================
`register_approved_capability` is the first stage that actually writes
to the live Capability Registry (`capabilities.capability_system.
CapabilitySystem`, unchanged): from a `request_id` whose registration
decision (self_upgrade.capability_registration_decision, Prompt 376)
is `READY_FOR_REGISTRATION`, it registers exactly one row describing
the approved capability - and nothing more:

    RegistrationApprovalRequest, APPROVED (Prompt 375/376)
        -> resolve_registration_decision(...)        (Prompt 376, unchanged)
        -> READY_FOR_REGISTRATION{registration_plan, source_version}
        -> register_approved_capability(request_id, approval_manager,
                                        capability_system)
        -> RegistrationResult{status=REGISTERED, capability, ...}
        -> CapabilitySystem.register(name, description, enabled=False,
                                     status="registered")   (unchanged)

THIS STEP ONLY REGISTERS. It writes one inert row to the existing
`capabilities` table (via `CapabilitySystem.register`, never a second
registry) with `enabled=False` - it never enables it, never activates
it, never executes it or any generated code, never adds it to
`execution.capability_handlers.CapabilityHandlerRegistry` (the
separate, execution-time handler map - see that module's own
docstring), never touches `AgentLoop` or any execution path, never
starts another self-upgrade cycle, and never creates another
capability. `REGISTERED` and `ACTIVE` remain two separate, later,
independently-decided stages; nothing in this module can produce
`ACTIVE`, and there is nothing here for a future caller to invoke to
skip that separate step.

Reuses, never duplicates:
  - `self_upgrade.capability_registration_decision.
    resolve_registration_decision` (Prompt 376, unchanged) is the only
    place an approval decision is ever read - this module never calls
    `ApprovalManager.approve`/`.reject`/`.create_request` itself, never
    inspects a stored record directly, and never infers approval from
    a plan, a build, or any other signal. A decision that is not
    `READY_FOR_REGISTRATION` (still pending, rejected, the wrong
    request type, or simply not found) is never registered.
  - `self_upgrade.capability_registration_preparation.
    registration_information_problems`/`_non_blank` (Prompt 373,
    unchanged) is the one, existing "is this complete registration
    information" check - re-run here (defense in depth) exactly as
    Prompts 373-375 already run it, rather than a second, possibly-
    diverging validator.
  - `self_upgrade.capability_registration_plan.
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION` (Prompt 374,
    unchanged) is the one status a plan must still carry.
  - `capabilities.capability_system.CapabilitySystem.register`/`.all`
    (unchanged) is the one, existing live Capability Registry - a
    single `capabilities` table row keyed by `name`. No new table, no
    new schema, no second registry.

Pre-registration checks (all must pass; the module docstring's numbered
list from the task, in order - any failure short-circuits and nothing
is registered):
    1. the approval request exists           -> resolve_registration_decision
                                                  is not NOT_FOUND
    2. the approval state is explicitly
       APPROVED (of the right request_type)   -> resolve_registration_decision
                                                  reports READY_FOR_REGISTRATION
    3. the registration plan exists           -> decision["registration_plan"]
                                                  is a dict
    4. the registration plan is valid         -> its own status is
                                                  PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION
    5-8. capability_name / interface_name /
         target_module / required
         registration information present     -> registration_information_problems

Statuses (`status`):
    INVALID           - malformed input to this function itself (bad
                         request_id, no usable ApprovalManager/
                         CapabilitySystem), or a registration_plan that
                         is missing, not the right status, or missing
                         required registration information (checks
                         3-8 above).
    BLOCKED           - checks 1-2 failed: no approval request exists
                         for request_id, it is still PENDING_APPROVAL,
                         it was explicitly REJECTED, or it exists but
                         is not a capability_registration request.
                         Never registers anything.
    REGISTERED        - every check passed and no capability was
                         previously registered under this name; one
                         new, disabled row was written.
    ALREADY_REGISTERED - a capability is already registered under this
                         exact name with the exact same registration
                         information (idempotent replay of a request
                         that was already successfully registered
                         before) - no duplicate row is written, no
                         existing row is touched.
    FAILED            - a *different*, conflicting capability is
                         already registered under this name (same name,
                         different interface/module/purpose) - never
                         silently overwritten; or the registry write
                         itself did not produce the row this call
                         intended (e.g. a race with a conflicting
                         concurrent registration).

Idempotency: registering the same approved request twice - or two
independently-approved requests that happen to describe the exact same
capability the exact same way - never creates a second row and never
mutates the first; it is reported as `ALREADY_REGISTERED`. A second,
*different* description under the same `capability_name` is refused
(`FAILED`) rather than silently replacing the first row -
`CapabilitySystem.register` itself already never overwrites an
existing row, and this module's own pre-check makes that refusal
visible and structured instead of a silent no-op.

Never raises: any missing/malformed input, a non-ready decision, an
invalid plan, or a registry conflict is reported as a structured
result with `errors`, never as an exception. Never calls
`approve`/`reject`/`create_request`, `set_enabled`,
`register_capability`/`replace_capability`/`unregister`, `execute`,
`run`, or anything on `AgentLoop`.
"""

import copy
from datetime import datetime, timezone

from self_upgrade.capability_registration_decision import (
    resolve_registration_decision,
    REGISTRATION_DECISION_STATUS_READY,
)
from self_upgrade.capability_registration_plan import (
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
)
from self_upgrade.capability_registration_preparation import (
    registration_information_problems,
    _non_blank,
)

REGISTRATION_RESULT_INVALID = "INVALID"
REGISTRATION_RESULT_BLOCKED = "BLOCKED"
REGISTRATION_RESULT_REGISTERED = "REGISTERED"
REGISTRATION_RESULT_ALREADY_REGISTERED = "ALREADY_REGISTERED"
REGISTRATION_RESULT_FAILED = "FAILED"

ALL_REGISTRATION_RESULT_STATUSES = (
    REGISTRATION_RESULT_INVALID,
    REGISTRATION_RESULT_BLOCKED,
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
    REGISTRATION_RESULT_FAILED,
)

# The CapabilitySystem `status` value written for a capability this
# executor registers - distinct from the existing "planned" (never
# reviewed) and "active" (enabled and in use) values a capability can
# already carry (capabilities.capability_system.PLANNED_CAPABILITIES,
# core.core.Core), so a registered-but-not-yet-active capability is
# never confused with either. `enabled` is always written as False -
# this module never writes True.
CAPABILITY_REGISTRY_STATUS = "registered"

_NON_READY_TO_RESULT_STATUS = {
    "NOT_FOUND": REGISTRATION_RESULT_BLOCKED,
    "PENDING_APPROVAL": REGISTRATION_RESULT_BLOCKED,
    "REJECTED": REGISTRATION_RESULT_BLOCKED,
    "WRONG_REQUEST_TYPE": REGISTRATION_RESULT_BLOCKED,
    "INVALID": REGISTRATION_RESULT_INVALID,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _result(status, request_id=None, capability_name=None, interface_name=None,
            target_module=None, approval_request_id=None, registration_plan=None,
            source_version=None, capability=None, errors=None):
    return {
        "request_id": request_id,
        "capability_name": capability_name,
        "interface_name": interface_name,
        "target_module": target_module,
        "approval_request_id": approval_request_id,
        "registration_plan": registration_plan,
        "source_version": source_version,
        "capability": capability,
        "status": status,
        "errors": list(errors or []),
    }


def _describe(capability_name, interface_name, target_module, purpose):
    """The one, deterministic description written to the Capability
    Registry for a given (capability_name, interface_name,
    target_module, purpose) - same inputs always produce the exact
    same string, so re-registering the same approved capability can be
    recognized as identical (ALREADY_REGISTERED) rather than compared
    field-by-field against a registry row that only ever stores a
    single description column."""
    base = f"Capability {capability_name!r} (interface {interface_name!r}, module {target_module!r})."
    if _non_blank(purpose):
        base += f" Purpose: {purpose}"
    return base


def register_approved_capability(request_id, approval_manager, capability_system):
    """Register the capability named by an already-`READY_FOR_REGISTRATION`
    registration decision (Prompt 376, `request_id` + `approval_manager`)
    into the existing, unchanged `CapabilitySystem` (`capability_system`).
    See module docstring for the full precondition list, status
    vocabulary, and idempotency contract. Never approves, rejects,
    activates, executes, or installs anything; never raises.

    Always returns a dict with exactly: request_id, capability_name,
    interface_name, target_module, approval_request_id,
    registration_plan, source_version, capability, status (one of
    `ALL_REGISTRATION_RESULT_STATUSES`), errors.
    """
    try:
        return _register(request_id, approval_manager, capability_system)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(REGISTRATION_RESULT_INVALID, request_id,
                        errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _register(request_id, approval_manager, capability_system):
    if not isinstance(request_id, str) or not request_id.strip():
        return _result(REGISTRATION_RESULT_INVALID, request_id,
                        errors=["request_id must be a non-blank string."])

    if approval_manager is None or not hasattr(approval_manager, "get_stored_record"):
        return _result(REGISTRATION_RESULT_INVALID, request_id,
                        errors=["A real ApprovalManager (self_upgrade."
                                "capability_approval_manager, Prompt 371) is required."])

    if (capability_system is None
            or not hasattr(capability_system, "register")
            or not hasattr(capability_system, "all")):
        return _result(REGISTRATION_RESULT_INVALID, request_id,
                        errors=["A real CapabilitySystem (capabilities."
                                "capability_system, unchanged) is required."])

    # Checks 1-2: the approval request exists and is explicitly
    # APPROVED, of the correct (capability_registration) request_type -
    # entirely delegated to the existing, unchanged Prompt 376 gate.
    decision = resolve_registration_decision(request_id, approval_manager)
    if decision["status"] != REGISTRATION_DECISION_STATUS_READY:
        mapped_status = _NON_READY_TO_RESULT_STATUS.get(
            decision["status"], REGISTRATION_RESULT_BLOCKED)
        errors = list(decision.get("errors") or [])
        if not errors:
            errors = [f"Registration approval decision for request_id={request_id!r} is "
                      f"{decision['status']!r}, not {REGISTRATION_DECISION_STATUS_READY!r}."]
        return _result(mapped_status, request_id, decision.get("capability_name"),
                        errors=errors)

    plan = decision.get("registration_plan")
    source_version = decision.get("source_version")

    # Check 3: the registration plan exists.
    if not isinstance(plan, dict):
        return _result(REGISTRATION_RESULT_INVALID, request_id,
                        decision.get("capability_name"), source_version=source_version,
                        errors=["The approved decision has no registration_plan; "
                                "nothing to register."])

    # Check 4: the registration plan is valid (still the exact status
    # a READY_FOR_APPROVED_REGISTRATION CapabilityRegistrationPlan, Prompt
    # 374, must carry).
    if plan.get("status") != PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION:
        return _result(
            REGISTRATION_RESULT_INVALID, request_id, plan.get("capability_name"),
            plan.get("interface_name"), plan.get("target_module"),
            plan.get("approval_request_id"), registration_plan=copy.deepcopy(plan),
            source_version=copy.deepcopy(source_version),
            errors=[f"registration_plan status is {plan.get('status')!r}, not "
                    f"{PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION!r}."])

    capability_name = plan.get("capability_name")
    interface_name = plan.get("interface_name")
    target_module = plan.get("target_module")
    purpose = plan.get("purpose")
    approval_request_id = plan.get("approval_request_id")

    # Checks 5-8: capability_name / interface_name / target_module /
    # required registration information (input_schema, output_schema,
    # dependencies) - the exact, existing check Prompts 373-375 already
    # run, re-run here rather than trusted blindly.
    problems = registration_information_problems(
        capability_name, interface_name, target_module,
        plan.get("input_schema"), plan.get("output_schema"), plan.get("dependencies"))
    if problems:
        return _result(
            REGISTRATION_RESULT_INVALID, request_id, capability_name, interface_name,
            target_module, approval_request_id, registration_plan=copy.deepcopy(plan),
            source_version=copy.deepcopy(source_version), errors=problems)

    description = _describe(capability_name, interface_name, target_module, purpose)

    existing = next(
        (row for row in capability_system.all() if row.get("name") == capability_name), None)

    if existing is not None:
        if existing.get("description") == description:
            # Idempotent replay: same capability, same information,
            # already registered - no duplicate row, nothing touched.
            return _result(
                REGISTRATION_RESULT_ALREADY_REGISTERED, request_id, capability_name,
                interface_name, target_module, approval_request_id,
                registration_plan=copy.deepcopy(plan),
                source_version=copy.deepcopy(source_version), capability=existing)
        # A capability already exists under this name with different
        # information (e.g. a seeded placeholder, or an earlier,
        # differently-described registration) - never silently
        # overwritten.
        return _result(
            REGISTRATION_RESULT_FAILED, request_id, capability_name, interface_name,
            target_module, approval_request_id, registration_plan=copy.deepcopy(plan),
            source_version=copy.deepcopy(source_version), capability=existing,
            errors=[f"A different capability is already registered under the name "
                    f"{capability_name!r}; refusing to overwrite it."])

    row = capability_system.register(
        capability_name, description, enabled=False, status=CAPABILITY_REGISTRY_STATUS)

    if not isinstance(row, dict) or row.get("description") != description:
        # Defensive: CapabilitySystem.register never overwrites an
        # existing row, so a description mismatch here means a
        # conflicting registration landed between our own check above
        # and this call.
        return _result(
            REGISTRATION_RESULT_FAILED, request_id, capability_name, interface_name,
            target_module, approval_request_id, registration_plan=copy.deepcopy(plan),
            source_version=copy.deepcopy(source_version), capability=row,
            errors=[f"Registering {capability_name!r} did not produce the intended "
                    "registry entry (a conflicting registration may have occurred "
                    "concurrently); refusing to treat this as a successful registration."])

    return _result(
        REGISTRATION_RESULT_REGISTERED, request_id, capability_name, interface_name,
        target_module, approval_request_id, registration_plan=copy.deepcopy(plan),
        source_version=copy.deepcopy(source_version), capability=row)
