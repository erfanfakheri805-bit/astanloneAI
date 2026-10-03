"""
Self-Upgrade - Registration Approval Decision (READY_FOR_REGISTRATION gate)
=============================================================================
`resolve_registration_decision` is the stage right after an explicit
human decision on a `RegistrationApprovalRequest`
(self_upgrade.capability_registration_approval, Prompt 375), made via
the existing, unchanged `ApprovalManager.approve`/`.reject`
(self_upgrade.capability_approval_manager, Prompt 371):

    RegistrationApprovalRequest (PENDING_APPROVAL, stored via
        ApprovalManager.create_request, Prompt 375)
        -> ApprovalManager.approve(request_id) / .reject(request_id)
             (explicit human decision - unchanged, Prompt 371)
        -> resolve_registration_decision(request_id, approval_manager)
        -> RegistrationDecision{request_id, capability_name, status,
               registration_plan, source_version, decision_timestamp,
               errors}

THIS STEP ONLY READS an already-recorded decision and reports whether
the associated registration request is now authorized to proceed to a
future, separate registration step. It does not register the
capability, does not enable or activate it, does not execute it or any
generated code, does not install or replace anything, does not touch
the live Capability Registry, does not create a version snapshot, does
not read or write any project file, does not call `approve`/`reject`
itself (it takes their already-stored result, never a plan, a build
result, a test result, or any other capability-quality signal), and
does not continue on to registration afterwards - a later, separate
step must do that, and only after this function reports
`READY_FOR_REGISTRATION`.

Reuses, never duplicates:
  - `self_upgrade.capability_approval_manager.ApprovalManager` (Prompt
    371, unchanged) is the only place a decision is ever recorded;
    this module never approves or rejects anything itself, and the
    `PENDING_APPROVAL -> APPROVED/REJECTED` transition it enforces is
    untouched.
  - `ApprovalManager.get_stored_record` (Prompt 376's one small
    addition to that module) is the only way this function reads a
    decision - a plain, read-only getter for the complete stored
    record, not a second storage system reaching into `memory`
    directly.
  - `self_upgrade.capability_registration_approval.
    REQUEST_TYPE_CAPABILITY_REGISTRATION` (Prompt 375, unchanged) is
    the one, existing marker this module checks to tell a
    registration approval apart from the earlier capability-upgrade
    approval (Prompt 370) stored in the very same `ApprovalManager`.
  - The existing `APPROVAL_STATUS_*` vocabulary
    (self_upgrade.capability_human_approval, Prompt 370, unchanged) is
    reused for every status this module can simply pass through
    unchanged (`PENDING_APPROVAL`, `REJECTED`); no parallel status
    vocabulary is introduced for those.

Statuses (`status`):
    PENDING_APPROVAL       - the stored request is still waiting on an
                              explicit decision; reported unchanged.
    REJECTED                - the stored request was explicitly
                              rejected; reported unchanged. Can never
                              become READY_FOR_REGISTRATION.
    READY_FOR_REGISTRATION - the stored request is a
                              `capability_registration` request whose
                              recorded status is exactly `APPROVED`.
                              This is the only status this module ever
                              derives; it is never stored back onto
                              the `ApprovalManager` record (`APPROVED`
                              there stays `APPROVED` - see below).
    NOT_FOUND               - no request is stored for `request_id`
                              (never created, or the wrong id
                              entirely). Rule 5: approval is always
                              tied to the correct request_id, so a
                              lookup for one request_id never reflects
                              a decision made about a different one.
    WRONG_REQUEST_TYPE      - a request is stored for `request_id` but
                              it is not a `capability_registration`
                              request (e.g. the earlier capability
                              approval, Prompt 370, which has no
                              `request_type` at all). An `APPROVED`
                              decision on the wrong kind of request is
                              never treated as registration
                              authorization, however it was decided.
    INVALID                 - malformed input (e.g. a blank/non-string
                              `request_id`, or no usable
                              `ApprovalManager`).
`BLOCKED`/`INVALID` `RegistrationApprovalRequest`s (Prompt 375) are
never stored by `ApprovalManager.create_request` in the first place
(it refuses anything not already `PENDING_APPROVAL`), so looking one
of those up here simply reports `NOT_FOUND` - there is no stored
record to ever turn into `READY_FOR_REGISTRATION`.

This function never mutates the `ApprovalManager` record it reads:
`APPROVED` stays `APPROVED` in storage; `READY_FOR_REGISTRATION` is a
freshly computed result describing what that `APPROVED` decision
authorizes, not a fourth status spliced into `ApprovalManager`'s own
`PENDING_APPROVAL -> APPROVED/REJECTED` state machine. A repeated call
with the same `request_id` and no new decision in between reproduces
the same result - nothing here is inferred from a plan, a build, a
test, or any other state, and nothing here decides anything a human
has not already explicitly decided via `ApprovalManager`.

Never raises: any malformed input, unknown request, or wrong-typed
request is reported as a structured result with `errors`, never as an
exception.
"""

import copy

from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_registration_approval import (
    REQUEST_TYPE_CAPABILITY_REGISTRATION,
)

REGISTRATION_DECISION_STATUS_READY = "READY_FOR_REGISTRATION"
REGISTRATION_DECISION_STATUS_NOT_FOUND = "NOT_FOUND"
REGISTRATION_DECISION_STATUS_WRONG_TYPE = "WRONG_REQUEST_TYPE"

# Every status resolve_registration_decision can return. Only
# REGISTRATION_DECISION_STATUS_READY authorizes a future registration
# step; every other value here never does.
ALL_REGISTRATION_DECISION_STATUSES = (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_INVALID,
    REGISTRATION_DECISION_STATUS_READY,
    REGISTRATION_DECISION_STATUS_NOT_FOUND,
    REGISTRATION_DECISION_STATUS_WRONG_TYPE,
)


def _decision(status, request_id=None, capability_name=None, registration_plan=None,
              source_version=None, decision_timestamp=None, errors=None):
    return {
        "request_id": request_id,
        "capability_name": capability_name,
        "status": status,
        "registration_plan": registration_plan,
        "source_version": source_version,
        "decision_timestamp": decision_timestamp,
        "errors": list(errors or []),
    }


def resolve_registration_decision(request_id, approval_manager):
    """Read the already-recorded decision for a `RegistrationApprovalRequest`
    (Prompt 375, `request_id`) off the existing `ApprovalManager`
    (Prompt 371, `approval_manager`) and report whether it is now
    `READY_FOR_REGISTRATION`. See module docstring. Never approves,
    rejects, registers, activates, executes, installs, or modifies
    anything; never calls `approve`/`reject` itself; never raises.

    `approval_manager` must be a real `ApprovalManager` (or a
    compatible object exposing `get_stored_record`) - the only source
    of truth for what a human actually decided. This function performs
    no lookup of its own kind; without one, the result is `INVALID`.

    Always returns a dict with exactly: request_id, capability_name,
    status (one of `ALL_REGISTRATION_DECISION_STATUSES`),
    registration_plan, source_version, decision_timestamp, errors.
    `registration_plan`/`source_version` are populated only when
    `status == READY_FOR_REGISTRATION`; `None` otherwise.
    """
    try:
        return _resolve(request_id, approval_manager)
    except Exception as exc:  # pragma: no cover - defensive
        return _decision(APPROVAL_STATUS_INVALID, request_id,
                          errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _resolve(request_id, approval_manager):
    if not isinstance(request_id, str) or not request_id.strip():
        return _decision(APPROVAL_STATUS_INVALID, request_id,
                          errors=["request_id must be a non-blank string."])

    if approval_manager is None or not hasattr(approval_manager, "get_stored_record"):
        return _decision(APPROVAL_STATUS_INVALID, request_id,
                          errors=["A real ApprovalManager (self_upgrade."
                                  "capability_approval_manager, Prompt 371) exposing "
                                  "get_stored_record is required."])

    record = approval_manager.get_stored_record(request_id)
    if record is None:
        return _decision(REGISTRATION_DECISION_STATUS_NOT_FOUND, request_id,
                          errors=[f"No approval request found for "
                                  f"request_id={request_id!r}."])

    # Rule 5 - approval is always tied to the correct request_id: the
    # record this ApprovalManager stored under this exact key must
    # itself carry the same id (defensive; ApprovalManager already
    # keys/stores by request_id, so this can't diverge in practice).
    if record.get("request_id") != request_id:
        return _decision(APPROVAL_STATUS_INVALID, request_id,
                          errors=[f"Stored record for request_id={request_id!r} does not "
                                  "match the requested id; refusing to resolve it."])

    capability_name = record.get("capability_name")
    decision_timestamp = record.get("decision_timestamp")

    if record.get("request_type") != REQUEST_TYPE_CAPABILITY_REGISTRATION:
        return _decision(
            REGISTRATION_DECISION_STATUS_WRONG_TYPE, request_id, capability_name,
            decision_timestamp=decision_timestamp,
            errors=[f"request_id={request_id!r} is not a "
                    f"{REQUEST_TYPE_CAPABILITY_REGISTRATION!r} request "
                    f"(request_type={record.get('request_type')!r}); it can never become "
                    f"{REGISTRATION_DECISION_STATUS_READY!r}."])

    stored_status = record.get("status")

    if stored_status == APPROVAL_STATUS_APPROVED:
        return _decision(
            REGISTRATION_DECISION_STATUS_READY, request_id, capability_name,
            registration_plan=copy.deepcopy(record.get("registration_plan")),
            source_version=copy.deepcopy(record.get("source_version")),
            decision_timestamp=decision_timestamp,
        )

    if stored_status == APPROVAL_STATUS_PENDING:
        return _decision(APPROVAL_STATUS_PENDING, request_id, capability_name,
                          decision_timestamp=decision_timestamp)

    if stored_status == APPROVAL_STATUS_REJECTED:
        return _decision(APPROVAL_STATUS_REJECTED, request_id, capability_name,
                          decision_timestamp=decision_timestamp,
                          errors=[f"request_id={request_id!r} was rejected; it can never "
                                  f"become {REGISTRATION_DECISION_STATUS_READY!r}."])

    # Any other/unrecognized stored status (should not occur given
    # ApprovalManager's own state machine) - reported as-is, never as
    # READY_FOR_REGISTRATION.
    return _decision(
        stored_status, request_id, capability_name, decision_timestamp=decision_timestamp,
        errors=[f"request_id={request_id!r} has status {stored_status!r}, not APPROVED; "
                f"it cannot become {REGISTRATION_DECISION_STATUS_READY!r}."])
