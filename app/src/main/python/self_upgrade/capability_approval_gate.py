"""
Self-Upgrade - Capability Approval Gate
=========================================
`evaluate_self_upgrade_approval_gate` is the stage after
`ApprovalManager` (self_upgrade.capability_approval_manager, Prompt
371): a small, read-only check that turns a capability's approval
state into the one signal any later activation/registration stage is
allowed to look at - `activation_allowed`/`registration_allowed` - and
nothing else. This module performs no activation or registration
itself; those stages do not exist yet (see Prompt 371's own closing
note and requirements 10-11 below).

    HumanApprovalRequest (Prompt 370)
        + ApprovalManager (Prompt 371, the *authority* on current status)
        -> evaluate_self_upgrade_approval_gate(...)
        -> ApprovalGateResult{request_id, capability_name,
               approval_status, gate_status, version,
               activation_allowed, registration_allowed, reason, errors}

THE CENTRAL RULE THIS MODULE EXISTS TO ENFORCE: a `HumanApprovalRequest`
is a snapshot taken at the moment it was built - it can go stale the
instant a human actually decides it. So this gate never trusts a
`HumanApprovalRequest`'s own `status` field for the actual decision; a
`PENDING_APPROVAL` request is always re-checked against
`ApprovalManager.get_status(request_id)` (Prompt 371, unchanged) - the
one place a real APPROVED/REJECTED decision is durably recorded - and
only that authoritative answer is ever mapped to `READY_FOR_ACTIVATION`
or `UPGRADE_REJECTED`. (A `HumanApprovalRequest` that was never
`PENDING_APPROVAL` to begin with - Prompt 370's own `INVALID`/`BLOCKED`
- never had anything to check against `ApprovalManager` in the first
place; those two statuses pass straight through unchanged, see below.)

Reuses, never duplicates:
  - `self_upgrade.capability_human_approval.APPROVAL_STATUS_PENDING/
    APPROVED/REJECTED/INVALID/BLOCKED` (Prompt 370) - the exact status
    vocabulary a `HumanApprovalRequest` and `ApprovalManager` record
    already use - imported unchanged.
  - `self_upgrade.capability_approval_manager.ApprovalManager.
    get_status` (Prompt 371, unchanged) is called at most once, purely
    to read the current stored record - never to create, approve, or
    reject one. No other `ApprovalManager` method is ever called here.

Gate status (`gate_status`, exactly one of `ALL_GATE_STATUSES`):
    READY_FOR_ACTIVATION - `ApprovalManager` confirms APPROVED, and the
                            capability identity and version/snapshot
                            match between the request and that record.
    UPGRADE_REJECTED     - `ApprovalManager` confirms REJECTED.
    WAITING_FOR_APPROVAL - `ApprovalManager` confirms still
                            PENDING_APPROVAL.
    INVALID              - the `HumanApprovalRequest` was malformed, or
                            was itself already `INVALID` (Prompt 370),
                            or `ApprovalManager` has no matching record,
                            or the capability name / version identifier
                            do not match between the request and the
                            authoritative `ApprovalManager` record.
    BLOCKED              - the `HumanApprovalRequest` was itself already
                            `BLOCKED` (Prompt 370: target file missing
                            or outside the allowed workspace).

Safety rules (requirement 7 - `activation_allowed`/`registration_allowed`
are computed from `gate_status` alone, by this exact fixed table, never
inferred from a test result, a confidence score, or a prior decision):
    READY_FOR_ACTIVATION -> True,  True
    everything else      -> False, False

This module never activates a capability, never registers one, never
executes generated code, never modifies project source, never creates
another version snapshot, and never calls `ApprovalManager.
create_request`/`approve`/`reject` - it only ever calls `get_status`.
Never raises: any malformed input, or the absence of a matching
`ApprovalManager` record, is reported as `gate_status=INVALID` with a
non-empty `errors`, never as an exception.
"""

from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_INVALID,
    APPROVAL_STATUS_BLOCKED,
)

GATE_STATUS_READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION"
GATE_STATUS_UPGRADE_REJECTED = "UPGRADE_REJECTED"
GATE_STATUS_WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
GATE_STATUS_INVALID = "INVALID"
GATE_STATUS_BLOCKED = "BLOCKED"

ALL_GATE_STATUSES = (
    GATE_STATUS_READY_FOR_ACTIVATION, GATE_STATUS_UPGRADE_REJECTED,
    GATE_STATUS_WAITING_FOR_APPROVAL, GATE_STATUS_INVALID, GATE_STATUS_BLOCKED,
)

# Requirement 7: activation/registration are a pure, fixed function of
# gate_status alone - nothing else may ever influence these two flags.
_ACTIVATION_ALLOWED = {GATE_STATUS_READY_FOR_ACTIVATION}


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _version_id(version):
    return version.get("id") if isinstance(version, dict) else None


def _result(gate_status, request_id=None, capability_name=None, approval_status=None,
            version=None, reason="", errors=None):
    allowed = gate_status in _ACTIVATION_ALLOWED
    return {
        "request_id": request_id,
        "capability_name": capability_name,
        "approval_status": approval_status,
        "gate_status": gate_status,
        "version": version,
        "activation_allowed": allowed,
        "registration_allowed": allowed,
        "reason": reason,
        "errors": list(errors or []),
    }


def evaluate_self_upgrade_approval_gate(human_approval_request, approval_manager):
    """Evaluate whether a capability's approval state authorizes a
    later activation/registration stage to proceed. Never performs
    that activation/registration itself - see module docstring. Never
    raises.

    `human_approval_request` must be the `HumanApprovalRequest` dict
    `self_upgrade.capability_human_approval.
    request_capability_human_approval` (Prompt 370) already produced -
    reused only to read its own `request_id`, `capability_name`,
    `version`, and `status`; this function never rebuilds or
    re-verifies any of it.

    `approval_manager` must be a `self_upgrade.
    capability_approval_manager.ApprovalManager` instance (or a
    compatible object exposing `get_status(request_id)`) - the single
    source of truth this gate re-checks a `PENDING_APPROVAL` request
    against. Required whenever `human_approval_request["status"]` is
    `PENDING_APPROVAL`; if omitted (`None`) in that case, this is
    reported as `INVALID` rather than trusting the request's own,
    possibly-stale status.

    Always returns an `ApprovalGateResult` dict with exactly:
        {
            "request_id": <str or None>,
            "capability_name": <str or None>,
            "approval_status": <the authoritative APPROVAL_STATUS_*
                this gate_status was derived from, or None for a
                malformed/mismatched request that was never resolved
                against ApprovalManager at all>,
            "gate_status": <one of ALL_GATE_STATUSES>,
            "version": <the version/snapshot dict this request or the
                matching ApprovalManager record carries, or None>,
            "activation_allowed": <bool - see module docstring>,
            "registration_allowed": <bool - always equal to
                activation_allowed, per requirement 7>,
            "reason": <short human-readable explanation>,
            "errors": <list of str>,
        }
    """
    try:
        return _evaluate(human_approval_request, approval_manager)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(GATE_STATUS_INVALID,
                        errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _evaluate(request, approval_manager):
    if not isinstance(request, dict):
        return _result(GATE_STATUS_INVALID,
                        errors=["human_approval_request must be a "
                                "HumanApprovalRequest dict."])

    request_id = request.get("request_id")
    capability_name = request.get("capability_name")
    request_status = request.get("status")
    request_version = request.get("version")

    if not _non_blank(request_id):
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        errors=["human_approval_request is missing a request_id."])
    if not _non_blank(capability_name):
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        errors=["human_approval_request is missing a capability_name."])

    # A HumanApprovalRequest that Prompt 370 itself already marked
    # BLOCKED/INVALID never reached ApprovalManager (Prompt 371's
    # create_request only admits PENDING_APPROVAL requests) - there is
    # nothing to re-check, so it passes straight through unchanged.
    if request_status == APPROVAL_STATUS_BLOCKED:
        return _result(GATE_STATUS_BLOCKED, request_id, capability_name,
                        version=request_version,
                        reason="The underlying HumanApprovalRequest was BLOCKED "
                               "(Prompt 370); it was never eligible for approval.",
                        errors=list(request.get("errors") or []))
    if request_status == APPROVAL_STATUS_INVALID:
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        reason="The underlying HumanApprovalRequest was INVALID "
                               "(Prompt 370); it was never eligible for approval.",
                        errors=list(request.get("errors") or []))
    if request_status != APPROVAL_STATUS_PENDING:
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        errors=[f"Unrecognized HumanApprovalRequest status: "
                                f"{request_status!r}."])

    # Requirement 3: the current approval state MUST come from
    # ApprovalManager, never from this (possibly stale) request's own
    # status field.
    if approval_manager is None:
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        errors=["No ApprovalManager was supplied; the authoritative "
                                "approval state could not be verified."])

    record = approval_manager.get_status(request_id)
    if not isinstance(record, dict) or record.get("errors"):
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        reason="No matching approval record was found in ApprovalManager.",
                        errors=list((record or {}).get("errors")
                                    or ["No ApprovalManager record for this request_id."]))

    # Requirement 3: capability identity and snapshot/version identity
    # must match between the request and the authoritative record -
    # a mismatch means this request no longer corresponds to what
    # ApprovalManager actually decided on, and is never trusted.
    if record.get("capability_name") != capability_name:
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        reason="capability_name does not match the ApprovalManager record.",
                        errors=["Capability identity mismatch between the "
                                "HumanApprovalRequest and the ApprovalManager record."])

    if _version_id(record.get("version")) != _version_id(request_version):
        return _result(GATE_STATUS_INVALID, request_id, capability_name,
                        version=request_version,
                        reason="version/snapshot identifier does not match the "
                               "ApprovalManager record.",
                        errors=["Snapshot/version mismatch between the "
                                "HumanApprovalRequest and the ApprovalManager record."])

    authoritative_status = record.get("status")
    resolved_version = record.get("version")

    if authoritative_status == APPROVAL_STATUS_APPROVED:
        return _result(GATE_STATUS_READY_FOR_ACTIVATION, request_id, capability_name,
                        authoritative_status, resolved_version,
                        reason="ApprovalManager confirms this capability was explicitly "
                               "APPROVED; activation/registration may proceed.")

    if authoritative_status == APPROVAL_STATUS_REJECTED:
        return _result(GATE_STATUS_UPGRADE_REJECTED, request_id, capability_name,
                        authoritative_status, resolved_version,
                        reason="ApprovalManager confirms this capability was explicitly "
                               "REJECTED; it has not been rejected or invalidated by "
                               "this gate - the rejection has not been reversed.")

    if authoritative_status == APPROVAL_STATUS_PENDING:
        return _result(GATE_STATUS_WAITING_FOR_APPROVAL, request_id, capability_name,
                        authoritative_status, resolved_version,
                        reason="Still PENDING_APPROVAL in ApprovalManager; waiting on "
                               "an explicit human decision.")

    return _result(GATE_STATUS_INVALID, request_id, capability_name,
                    version=resolved_version,
                    errors=[f"Unrecognized ApprovalManager status: {authoritative_status!r}."])
