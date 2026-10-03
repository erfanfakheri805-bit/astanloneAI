"""
Self-Upgrade - Capability Lifecycle State
===========================================
`build_capability_lifecycle_state` is one small, unified, read-only view
of *where a capability currently is* in the Self-Upgrade chain. It does
not run any stage, it does not store anything, and it decides nothing:
every status it reports is derived, deterministically, from results the
existing stages already produced.

    CapabilityBuilder result            (capability_builder)
    CapabilityApplyRequest              (capability_apply_request)
    CapabilityEvaluation                (capability_evaluation)
    HumanApprovalRequest                (capability_human_approval)
    ApprovalManager records             (capability_approval_manager)
    CapabilityRegistrationPlan          (capability_registration_plan)
    RegistrationApproval decision       (capability_registration_decision)
    RegistrationResult                  (capability_registration_executor)
    RegistrationVerificationResult      (capability_registration_verifier)
    rollback decision                   (agent.code_change_rollback)
        -> build_capability_lifecycle_state(...)
        -> CapabilityLifecycleState{capability_name, current_status,
               approval_request_id, registration_request_id,
               registration_plan, registration_result,
               verification_result, source_version, reason, errors}

THIS STEP ONLY TRACKS STATE. It never activates a capability, never
executes one (or any generated code), never approves or rejects
anything, never registers or modifies anything in the live Capability
Registry, never touches project source code, never creates or rolls
back a version, never retries a failure, and never starts another
Self-Upgrade cycle. `CapabilitySystem`, `CapabilityHandlerRegistry`,
`VersionSystem`, `ApprovalManager.create_request`/`approve`/`reject`,
`execute`, `run`, and anything on `AgentLoop` do not appear anywhere in
this module. It holds no state of its own - calling it twice with the
same results always returns the same state.

Reuses, never duplicates:
  - Every status a stage can report is read from that stage's own
    result and mapped onto the lifecycle; no stage is re-run, no result
    is re-validated, and no second registry, approval, or version
    system exists here.
  - `self_upgrade.capability_approval_manager.ApprovalManager.
    get_stored_record` (read-only) and `self_upgrade.
    capability_registration_decision.resolve_registration_decision`
    (Prompt 376, unchanged) are the ONLY sources of approval status. A
    `HumanApprovalRequest` dict's own `status` is never trusted as a
    decision - exactly the rule the approval gate (Prompt 372) already
    applies - so APPROVED / READY_FOR_REGISTRATION can never be claimed
    without a real, explicit, stored human decision.
  - `self_upgrade.capability_registration_preparation._version_reference`
    (unchanged) is the one compact version/snapshot reference shape.

Lifecycle statuses (`current_status`, exactly one of
`ALL_LIFECYCLE_STATUSES`). Progress, in order (`LIFECYCLE_PROGRESS`):
    BUILT                  - the builder result is READY.
    VALIDATED              - the apply request is READY and carries a
                             VALID generated-code validation result.
    TESTED                 - the capability evaluation is SUCCESS.
    VERSIONED              - a HumanApprovalRequest exists with a version
                             snapshot but no stored approval record yet.
    PENDING_APPROVAL       - ApprovalManager holds a still-undecided
                             request (capability or registration).
    APPROVED               - ApprovalManager holds an explicit APPROVED
                             capability approval.
    READY_FOR_REGISTRATION - `resolve_registration_decision` reports
                             READY_FOR_REGISTRATION.
    REGISTERED             - the executor reported REGISTERED or
                             ALREADY_REGISTERED (a registration result
                             is required; nothing else can produce this).
    VERIFIED               - the registration verifier reported VERIFIED
                             for that same registration result.
Failure / blocking states (`LIFECYCLE_FAILURE_STATUSES`):
    INVALID      - a result is malformed or inconsistent (or no result
                   at all was supplied).
    BLOCKED      - a stage reported BLOCKED (or the approval reference is
                   the wrong kind of request).
    REJECTED     - a human explicitly rejected an approval request.
    FAILED       - a stage reported FAILED (failed tests, failed
                   registration, failed or unconfirmable verification,
                   or a rollback that itself did not complete).
    ROLLED_BACK  - a rollback completed. Always distinct from FAILED.

VERIFIED means "registered successfully and verified against the
approved registration information". It does NOT mean ACTIVE: there is
no ACTIVE lifecycle status, and nothing here can produce one.

Derivation rules (fixed, in this order):
  1. Every supplied result must describe the same capability, and the
     approval ids / registration request ids it carries must agree;
     otherwise INVALID.
  2. A completed rollback wins over everything else -> ROLLED_BACK. The
     version the other results describe was reverted, so none of them
     may still be reported as the capability's state.
  3. Otherwise, the first failure/blocking verdict, in pipeline order
     (build, validation, tests, versioning, approval, registration
     plan, registration decision, registration, verification,
     rollback), is the state. A later
     positive result never masks an earlier failure, and a FAILED
     verification stays FAILED - nothing here corrects or retries it.
  4. Otherwise, the furthest progress status any result supports.
  5. A stage that was not supplied simply contributes nothing; the
     lifecycle is derived from what exists, never from what is assumed.

Never raises: any malformed input is reported as INVALID with a
non-empty `errors`, never as an exception.
"""

from agent.code_change_rollback import (
    CHANGE_STATUS_KEPT,
    CHANGE_STATUS_ROLLED_BACK,
    CHANGE_STATUS_ROLLBACK_FAILED,
    ROLLBACK_STATUS_SUCCEEDED,
)
from code_generation.generated_code_validator import VALIDATION_VALID
from self_upgrade.capability_build_spec import (
    STATUS_READY as SPEC_STATUS_READY,
    STATUS_BLOCKED as SPEC_STATUS_BLOCKED,
)
from self_upgrade.capability_evaluation import (
    EVAL_SUCCESS,
    EVAL_FAILED,
    EVAL_TIMEOUT,
    EVAL_BLOCKED,
    EVAL_INVALID,
    EVAL_NEEDS_CORRECTION,
)
from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_registration_approval import (
    REQUEST_TYPE_CAPABILITY_REGISTRATION,
)
from self_upgrade.capability_registration_decision import (
    resolve_registration_decision,
    REGISTRATION_DECISION_STATUS_READY,
    REGISTRATION_DECISION_STATUS_NOT_FOUND,
    REGISTRATION_DECISION_STATUS_WRONG_TYPE,
)
from self_upgrade.capability_registration_executor import (
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
    REGISTRATION_RESULT_BLOCKED,
    REGISTRATION_RESULT_FAILED,
)
from self_upgrade.capability_registration_plan import (
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
    PLAN_STATUS_BLOCKED,
)
from self_upgrade.capability_registration_preparation import (
    _non_blank,
    _version_reference,
)
from self_upgrade.capability_registration_verifier import (
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_FAILED,
    VERIFICATION_STATUS_NOT_REGISTERED,
)

LIFECYCLE_BUILT = "BUILT"
LIFECYCLE_VALIDATED = "VALIDATED"
LIFECYCLE_TESTED = "TESTED"
LIFECYCLE_VERSIONED = "VERSIONED"
LIFECYCLE_PENDING_APPROVAL = "PENDING_APPROVAL"
LIFECYCLE_APPROVED = "APPROVED"
LIFECYCLE_READY_FOR_REGISTRATION = "READY_FOR_REGISTRATION"
LIFECYCLE_REGISTERED = "REGISTERED"
LIFECYCLE_VERIFIED = "VERIFIED"

LIFECYCLE_INVALID = "INVALID"
LIFECYCLE_BLOCKED = "BLOCKED"
LIFECYCLE_REJECTED = "REJECTED"
LIFECYCLE_FAILED = "FAILED"
LIFECYCLE_ROLLED_BACK = "ROLLED_BACK"

LIFECYCLE_PROGRESS = (
    LIFECYCLE_BUILT,
    LIFECYCLE_VALIDATED,
    LIFECYCLE_TESTED,
    LIFECYCLE_VERSIONED,
    LIFECYCLE_PENDING_APPROVAL,
    LIFECYCLE_APPROVED,
    LIFECYCLE_READY_FOR_REGISTRATION,
    LIFECYCLE_REGISTERED,
    LIFECYCLE_VERIFIED,
)

LIFECYCLE_FAILURE_STATUSES = (
    LIFECYCLE_INVALID,
    LIFECYCLE_BLOCKED,
    LIFECYCLE_REJECTED,
    LIFECYCLE_FAILED,
    LIFECYCLE_ROLLED_BACK,
)

ALL_LIFECYCLE_STATUSES = LIFECYCLE_PROGRESS + LIFECYCLE_FAILURE_STATUSES

_REGISTRATION_SUCCESS_STATUSES = (
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
)

_PLAN_REFERENCE_KEYS = ("status", "capability_name", "approval_request_id", "created_at")
_REGISTRATION_REFERENCE_KEYS = ("status", "request_id", "capability_name", "approval_request_id")
_VERIFICATION_REFERENCE_KEYS = (
    "status", "request_id", "capability_name", "approval_request_id", "verified_at")


def _state(capability_name, status, reason, errors=None, approval_request_id=None,
           registration_request_id=None, registration_plan=None,
           registration_result=None, verification_result=None, source_version=None):
    return {
        "capability_name": capability_name,
        "current_status": status,
        "approval_request_id": approval_request_id,
        "registration_request_id": registration_request_id,
        "registration_plan": registration_plan,
        "registration_result": registration_result,
        "verification_result": verification_result,
        "source_version": source_version,
        "reason": reason,
        "errors": list(errors or []),
    }


def _reference(result, keys):
    """A compact, read-only reference to an existing result (its status
    plus the ids that identify it) - never a copy of the whole result."""
    if not isinstance(result, dict):
        return None
    return {key: result.get(key) for key in keys}


def _get(result, key):
    return result.get(key) if isinstance(result, dict) else None


def _first_non_blank(*values):
    return next((v for v in values if _non_blank(v)), None)


def build_capability_lifecycle_state(
        capability_name, build_result=None, apply_request=None, test_evaluation=None,
        human_approval_request=None, approval_manager=None, approval_request_id=None,
        registration_request_id=None, registration_plan=None, registration_result=None,
        verification_result=None, rollback_result=None):
    """Derive the current `CapabilityLifecycleState` of `capability_name`
    from the results the existing Self-Upgrade stages already produced.
    See module docstring for the status vocabulary, derivation rules,
    and safety boundary. Read-only: never activates, executes,
    approves, registers, retries, or modifies anything; never raises.

    Every argument except `capability_name` is optional - a stage that
    was not supplied contributes nothing:
      build_result             - `capability_builder.build_capability` result
      apply_request            - `capability_apply_request.
                                  build_capability_apply_request` result
      test_evaluation          - `capability_evaluation.
                                  evaluate_capability_test_result` result
      human_approval_request   - `capability_human_approval.
                                  request_capability_human_approval` result
      approval_manager         - the real `ApprovalManager`; the only
                                  authority on approval decisions. Needed
                                  for any PENDING_APPROVAL / APPROVED /
                                  READY_FOR_REGISTRATION / REJECTED state.
      approval_request_id      - the capability approval's request id
                                  (else taken from the results above)
      registration_request_id  - the registration approval's request id
                                  (else taken from the registration /
                                  verification results)
      registration_plan        - `capability_registration_plan.
                                  build_capability_registration_plan` result
      registration_result      - `capability_registration_executor.
                                  register_approved_capability` result
      verification_result      - `capability_registration_verifier.
                                  verify_registered_capability` result
      rollback_result          - `agent.code_change_rollback.
                                  build_code_change_rollback_decision` result

    Always returns a dict with exactly: capability_name,
    current_status (one of `ALL_LIFECYCLE_STATUSES`),
    approval_request_id, registration_request_id, registration_plan,
    registration_result, verification_result, source_version, reason,
    errors. The three `registration_*`/`verification_result` fields are
    compact references (status + ids), or `None` when not available.
    """
    try:
        return _derive(
            capability_name, build_result, apply_request, test_evaluation,
            human_approval_request, approval_manager, approval_request_id,
            registration_request_id, registration_plan, registration_result,
            verification_result, rollback_result)
    except Exception as exc:  # pragma: no cover - defensive
        return _state(
            capability_name if isinstance(capability_name, str) else None,
            LIFECYCLE_INVALID, "Unexpected error while deriving the lifecycle state.",
            [f"Unexpected error: {type(exc).__name__}: {exc}"])


# --------------------------------------------------------------------
# Per-stage verdicts. Each returns None (nothing to say), or a
# (lifecycle_status, errors) pair read straight off the stage's result.
# --------------------------------------------------------------------
def _bad_shape(label):
    return (LIFECYCLE_INVALID, [f"{label} must be a result dict."])


def _judge_build(result):
    if not isinstance(result, dict):
        return _bad_shape("build_result")
    status = result.get("status")
    if status == SPEC_STATUS_READY:
        return (LIFECYCLE_BUILT, [])
    detail = list(result.get("validation_errors") or [])
    if status == SPEC_STATUS_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["build_result is BLOCKED."] + detail)
    return (LIFECYCLE_INVALID, [f"build_result status is {status!r}, not READY."] + detail)


def _judge_apply_request(result):
    if not isinstance(result, dict):
        return _bad_shape("apply_request")
    status = result.get("status")
    detail = list(result.get("validation_errors") or [])
    if status == SPEC_STATUS_READY:
        validation = result.get("validation_result")
        if isinstance(validation, dict) and validation.get("status") == VALIDATION_VALID:
            return (LIFECYCLE_VALIDATED, [])
        return (LIFECYCLE_INVALID, ["apply_request is READY but carries no VALID "
                                    "validation_result."] + detail)
    if status == SPEC_STATUS_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["apply_request is BLOCKED."] + detail)
    return (LIFECYCLE_INVALID, [f"apply_request status is {status!r}, not READY."] + detail)


def _judge_test_evaluation(result):
    if not isinstance(result, dict):
        return _bad_shape("test_evaluation")
    status = result.get("evaluation_status")
    if status == EVAL_SUCCESS:
        return (LIFECYCLE_TESTED, [])
    detail = [result.get("failure_reason")] if _non_blank(result.get("failure_reason")) else []
    detail += list(result.get("errors") or [])
    if status == EVAL_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["test_evaluation is BLOCKED."] + detail)
    if status == EVAL_INVALID:
        return (LIFECYCLE_INVALID, ["test_evaluation is INVALID."] + detail)
    # FAILED / NEEDS_CORRECTION / TIMEOUT: the tests did not pass.
    if status in (EVAL_FAILED, EVAL_NEEDS_CORRECTION, EVAL_TIMEOUT):
        return (LIFECYCLE_FAILED,
                [f"test_evaluation status is {status!r}; the tests did not pass."] + detail)
    return (LIFECYCLE_INVALID, [f"test_evaluation status {status!r} is not recognized."])


def _judge_human_approval_request(request):
    """The request dict is evidence of a version snapshot only. Its own
    `status` is never read as a decision (approval comes from
    ApprovalManager alone), so anything other than PENDING_APPROVAL /
    BLOCKED / INVALID is refused, as the approval gate (Prompt 372)
    already does."""
    if not isinstance(request, dict):
        return _bad_shape("human_approval_request")
    status = request.get("status")
    detail = list(request.get("errors") or [])
    if status == APPROVAL_STATUS_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["human_approval_request is BLOCKED."] + detail)
    if status == APPROVAL_STATUS_INVALID:
        return (LIFECYCLE_INVALID, ["human_approval_request is INVALID."] + detail)
    if status != APPROVAL_STATUS_PENDING:
        return (LIFECYCLE_INVALID,
                [f"human_approval_request status is {status!r}; a decision is only "
                 "ever read from ApprovalManager, never from the request itself."])
    if _version_reference(request.get("version")) is None:
        return (LIFECYCLE_INVALID, ["human_approval_request carries no version snapshot."])
    return (LIFECYCLE_VERSIONED, [])


def _judge_capability_approval(request_id, approval_manager, explicit):
    """Returns (verdict_or_None, stored_capability_name)."""
    record = approval_manager.get_stored_record(request_id)
    if record is None:
        if explicit:
            return ((LIFECYCLE_INVALID,
                     [f"No approval request is stored for approval_request_id={request_id!r}."]),
                    None)
        return (None, None)  # not submitted for a decision yet
    name = record.get("capability_name")
    if record.get("request_id") != request_id:
        return ((LIFECYCLE_INVALID, [f"The stored record for {request_id!r} does not "
                                     "match the requested id."]), name)
    if record.get("request_type") == REQUEST_TYPE_CAPABILITY_REGISTRATION:
        return ((LIFECYCLE_INVALID, [f"approval_request_id={request_id!r} refers to a "
                                     "registration approval request, not a capability "
                                     "approval."]), name)
    status = record.get("status")
    if status == APPROVAL_STATUS_APPROVED:
        return ((LIFECYCLE_APPROVED, []), name)
    if status == APPROVAL_STATUS_PENDING:
        return ((LIFECYCLE_PENDING_APPROVAL, []), name)
    if status == APPROVAL_STATUS_REJECTED:
        return ((LIFECYCLE_REJECTED, [f"approval request {request_id!r} was rejected by a "
                                      "human; it can never become APPROVED."]), name)
    return ((LIFECYCLE_INVALID, [f"approval request {request_id!r} has unrecognized status "
                                 f"{status!r}."]), name)


def _judge_plan(plan):
    if not isinstance(plan, dict):
        return _bad_shape("registration_plan")
    status = plan.get("status")
    # A READY plan is only a description; it is never approval, so it
    # adds a reference but no progress of its own.
    if status == PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION:
        return None
    detail = list(plan.get("errors") or [])
    if status == PLAN_STATUS_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["registration_plan is BLOCKED."] + detail)
    return (LIFECYCLE_INVALID, [f"registration_plan status is {status!r}."] + detail)


def _judge_registration_decision(decision):
    status = decision.get("status")
    detail = list(decision.get("errors") or [])
    if status == REGISTRATION_DECISION_STATUS_READY:
        return (LIFECYCLE_READY_FOR_REGISTRATION, [])
    if status == APPROVAL_STATUS_PENDING:
        return (LIFECYCLE_PENDING_APPROVAL, [])
    if status == APPROVAL_STATUS_REJECTED:
        return (LIFECYCLE_REJECTED, ["The registration approval was rejected by a human; "
                                     "it can never become READY_FOR_REGISTRATION."])
    if status == REGISTRATION_DECISION_STATUS_WRONG_TYPE:
        return (LIFECYCLE_BLOCKED, ["The registration request id refers to a request that is "
                                    "not a capability_registration request."] + detail)
    return (LIFECYCLE_INVALID, [f"Registration decision status is {status!r}."] + detail)


def _judge_registration_result(result):
    if not isinstance(result, dict):
        return _bad_shape("registration_result")
    status = result.get("status")
    detail = list(result.get("errors") or [])
    if status in _REGISTRATION_SUCCESS_STATUSES:
        return (LIFECYCLE_REGISTERED, [])
    if status == REGISTRATION_RESULT_BLOCKED:
        return (LIFECYCLE_BLOCKED, ["registration_result is BLOCKED; nothing was registered."]
                + detail)
    if status == REGISTRATION_RESULT_FAILED:
        return (LIFECYCLE_FAILED, ["registration_result is FAILED."] + detail)
    return (LIFECYCLE_INVALID, [f"registration_result status is {status!r}; it is not a "
                                "successful registration."] + detail)


def _judge_verification(verification, registration_result):
    if not isinstance(verification, dict):
        return _bad_shape("verification_result")
    status = verification.get("status")
    detail = list(verification.get("errors") or [])
    if status == VERIFICATION_STATUS_VERIFIED:
        # Only a verifier VERIFIED for a real, successful registration
        # of that same request can ever produce VERIFIED here.
        if not isinstance(registration_result, dict) \
                or registration_result.get("status") not in _REGISTRATION_SUCCESS_STATUSES:
            return (LIFECYCLE_INVALID, ["verification_result is VERIFIED but there is no "
                                        "successful registration_result to verify."])
        if verification.get("request_id") != registration_result.get("request_id"):
            return (LIFECYCLE_INVALID, ["verification_result verified a different "
                                        "registration request than registration_result."])
        if verification.get("mismatches") or detail:
            return (LIFECYCLE_INVALID, ["verification_result is VERIFIED but reports "
                                        "mismatches or errors."])
        return (LIFECYCLE_VERIFIED, [])
    mismatches = list(verification.get("mismatches") or [])
    if status == VERIFICATION_STATUS_FAILED:
        return (LIFECYCLE_FAILED, ["verification_result is FAILED; the registration no "
                                   "longer matches the approved registration information."]
                + mismatches + [d for d in detail if d not in mismatches])
    if status == VERIFICATION_STATUS_NOT_REGISTERED:
        return (LIFECYCLE_FAILED, ["verification_result is NOT_REGISTERED; the registration "
                                   "could not be confirmed."] + detail)
    return (LIFECYCLE_INVALID, [f"verification_result status is {status!r}."] + detail)


def _judge_rollback(result):
    if not isinstance(result, dict):
        return _bad_shape("rollback_result")
    change_status = result.get("change_status")
    if change_status == CHANGE_STATUS_ROLLED_BACK:
        if result.get("rollback_status") != ROLLBACK_STATUS_SUCCEEDED:
            return (LIFECYCLE_INVALID, ["rollback_result is ROLLED_BACK but its "
                                        "rollback_status is not SUCCEEDED."])
        return (LIFECYCLE_ROLLED_BACK, ["The change was rolled back to its previous version."])
    if change_status == CHANGE_STATUS_ROLLBACK_FAILED:
        return (LIFECYCLE_FAILED, ["A rollback was required but did not complete."])
    if change_status == CHANGE_STATUS_KEPT:
        return None  # no rollback happened; nothing to add
    return (LIFECYCLE_INVALID, [f"rollback_result change_status {change_status!r} "
                                "is not recognized."])


# --------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------
def _derive(capability_name, build_result, apply_request, test_evaluation,
            human_approval_request, approval_manager, approval_request_id,
            registration_request_id, registration_plan, registration_result,
            verification_result, rollback_result):
    if not _non_blank(capability_name):
        return _state(None, LIFECYCLE_INVALID, "capability_name must be a non-blank string.",
                      ["capability_name must be a non-blank string."])

    # Compact references, resolved from whatever results exist. A plan /
    # source_version embedded in a later result stands in for one that
    # was not passed separately.
    embedded_plan = _get(registration_result, "registration_plan")
    ids = {
        "approval_request_id": {
            "approval_request_id": approval_request_id,
            "human_approval_request": _get(human_approval_request, "request_id"),
            "registration_plan": _get(registration_plan, "approval_request_id"),
            "registration_result": _get(registration_result, "approval_request_id"),
            "verification_result": _get(verification_result, "approval_request_id"),
        },
        "registration_request_id": {
            "registration_request_id": registration_request_id,
            "registration_result": _get(registration_result, "request_id"),
            "verification_result": _get(verification_result, "request_id"),
        },
    }
    approval_id = _first_non_blank(*ids["approval_request_id"].values())
    registration_id = _first_non_blank(*ids["registration_request_id"].values())

    plan_source = registration_plan if isinstance(registration_plan, dict) else embedded_plan
    refs = {
        "approval_request_id": approval_id,
        "registration_request_id": registration_id,
        "registration_plan": _reference(plan_source, _PLAN_REFERENCE_KEYS),
        "registration_result": _reference(registration_result, _REGISTRATION_REFERENCE_KEYS),
        "verification_result": _reference(verification_result, _VERIFICATION_REFERENCE_KEYS),
        "source_version": None,
    }
    for candidate in (_get(verification_result, "source_version"),
                      _get(registration_result, "source_version"),
                      _get(plan_source, "source_version"),
                      _get(human_approval_request, "version")):
        refs["source_version"] = _version_reference(candidate)
        if refs["source_version"] is not None:
            break

    def finish(status, reason, errors=None):
        return _state(capability_name, status, reason, errors, **refs)

    # Rule 1 (part): identifiers the results carry must agree.
    for label, values in ids.items():
        distinct = {v for v in values.values() if _non_blank(v)}
        if len(distinct) > 1:
            return finish(LIFECYCLE_INVALID, f"The supplied results disagree on {label}.",
                          [f"{label} differs between results: {sorted(distinct)!r}."])

    if approval_manager is not None and not hasattr(approval_manager, "get_stored_record"):
        return finish(LIFECYCLE_INVALID, "approval_manager is not a usable ApprovalManager.",
                      ["approval_manager must be a real ApprovalManager exposing "
                       "get_stored_record."])
    explicit_ids_need_manager = (_non_blank(approval_request_id)
                                 or _non_blank(registration_request_id))
    if approval_manager is None and explicit_ids_need_manager:
        return finish(LIFECYCLE_INVALID, "An approval id was given without an ApprovalManager.",
                      ["A real ApprovalManager is required to read an approval decision."])

    # Gather (stage, status, errors) verdicts in pipeline order, and the
    # capability names the results carry.
    verdicts = []
    names = {}

    def add(stage, verdict):
        if verdict is not None:
            verdicts.append((stage, verdict[0], verdict[1]))

    if build_result is not None:
        add("build", _judge_build(build_result))
        names["build_result"] = _get(build_result, "capability_name")
    if apply_request is not None:
        add("validation", _judge_apply_request(apply_request))
        names["apply_request"] = _get(apply_request, "capability_name")
    if test_evaluation is not None:
        add("tests", _judge_test_evaluation(test_evaluation))
        names["test_evaluation"] = _get(test_evaluation, "capability_name")
    if human_approval_request is not None:
        add("versioning", _judge_human_approval_request(human_approval_request))
        names["human_approval_request"] = _get(human_approval_request, "capability_name")

    if approval_manager is not None and _non_blank(approval_id):
        verdict, stored_name = _judge_capability_approval(
            approval_id, approval_manager, explicit=_non_blank(approval_request_id))
        add("approval", verdict)
        names["approval record"] = stored_name

    if registration_plan is not None:
        add("registration plan", _judge_plan(registration_plan))
        names["registration_plan"] = _get(registration_plan, "capability_name")

    if approval_manager is not None and _non_blank(registration_id):
        decision = resolve_registration_decision(registration_id, approval_manager)
        names["registration decision"] = decision.get("capability_name")
        if decision.get("status") == REGISTRATION_DECISION_STATUS_NOT_FOUND:
            # A derived id that was never stored is simply "no decision
            # yet"; an id the caller explicitly named must exist.
            if _non_blank(registration_request_id):
                add("registration decision",
                    (LIFECYCLE_INVALID, [f"No registration approval request is stored for "
                                         f"registration_request_id={registration_request_id!r}."]))
        else:
            add("registration decision", _judge_registration_decision(decision))
            if refs["registration_plan"] is None:
                refs["registration_plan"] = _reference(
                    decision.get("registration_plan"), _PLAN_REFERENCE_KEYS)
            if refs["source_version"] is None:
                refs["source_version"] = _version_reference(decision.get("source_version"))

    if registration_result is not None:
        add("registration", _judge_registration_result(registration_result))
        names["registration_result"] = _get(registration_result, "capability_name")
    if verification_result is not None:
        add("verification", _judge_verification(verification_result, registration_result))
        names["verification_result"] = _get(verification_result, "capability_name")
    if rollback_result is not None:
        add("rollback", _judge_rollback(rollback_result))

    # Rule 1: every result must describe this capability.
    wrong = {label: name for label, name in names.items()
             if _non_blank(name) and name != capability_name}
    if wrong:
        return finish(
            LIFECYCLE_INVALID, "A supplied result describes a different capability.",
            [f"{label} is for {name!r}, not {capability_name!r}."
             for label, name in sorted(wrong.items())])

    # Rule 2: a completed rollback wins over everything else.
    for stage, status, errors in verdicts:
        if status == LIFECYCLE_ROLLED_BACK:
            return finish(LIFECYCLE_ROLLED_BACK, errors[0], [])

    # Rule 3: the first failure/blocking verdict, in pipeline order.
    for stage, status, errors in verdicts:
        if status in LIFECYCLE_FAILURE_STATUSES:
            return finish(status, f"Stopped at the {stage} stage: {status}.",
                          [f"{stage}: {message}" for message in errors])

    # Rule 4: the furthest progress any result supports.
    reached = [status for _, status, _ in verdicts if status in LIFECYCLE_PROGRESS]
    if not reached:
        return finish(LIFECYCLE_INVALID, "No result supports any lifecycle status.",
                      ["No lifecycle evidence was supplied; nothing to derive a status from."])
    current = max(reached, key=LIFECYCLE_PROGRESS.index)
    return finish(current, _PROGRESS_REASONS[current], [])


_PROGRESS_REASONS = {
    LIFECYCLE_BUILT: "The capability was built; nothing further is confirmed.",
    LIFECYCLE_VALIDATED: "The generated capability source passed validation.",
    LIFECYCLE_TESTED: "The capability's tests passed.",
    LIFECYCLE_VERSIONED: "A version snapshot exists; no approval decision is stored yet.",
    LIFECYCLE_PENDING_APPROVAL: "An approval request is waiting on an explicit human decision.",
    LIFECYCLE_APPROVED: "A human explicitly approved the capability; it is not registered.",
    LIFECYCLE_READY_FOR_REGISTRATION: ("Registration was explicitly approved; the "
                                       "capability is not registered yet."),
    LIFECYCLE_REGISTERED: ("The capability was registered (disabled); registration is not "
                           "verified and the capability is not active."),
    LIFECYCLE_VERIFIED: ("The registration was verified against the approved registration "
                         "information. This does not mean the capability is active."),
}
