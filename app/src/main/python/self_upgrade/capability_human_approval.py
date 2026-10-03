"""
Self-Upgrade - Capability Version Snapshot + Human Approval Request
====================================================================
`request_capability_human_approval` is the stage after controlled
correction retesting (self_upgrade.capability_correction_verification,
Prompt 369): a capability whose correction is VERIFIED gets one version
snapshot recorded via the existing, reused Version System, and one
structured `HumanApprovalRequest` describing it - never anything more:

    CapabilityCorrectionVerificationResult (Prompt 369, VERIFIED)
        + VersionSystem (self_upgrade.version_system, unchanged)
        -> request_capability_human_approval(...)
        -> HumanApprovalRequest{request_id, capability_name,
               target_file, version, verification_status, summary,
               tests_passed, tests_failed, rollback_available, status}

ARCHITECTURAL BOUNDARY (this module exists to enforce it, not just
document it): this project is meant to become a general-purpose local
AI with many self-authored capabilities, but PERMANENT changes to the
AI's own project always require an explicit human decision. This
module may create a recovery-point snapshot automatically (a snapshot
is inert - it changes nothing about what is currently running), but it
never activates a capability, never registers one as active, and never
marks a Self-Upgrade as complete. Those three actions do not exist
anywhere in this module; there is nothing here for a future caller to
invoke to skip the approval step.

Reuses, never duplicates:
  - `self_upgrade.capability_correction_verification.STATUS_VERIFIED`
    is the one, existing "this correction is confirmed good" gate read
    here - this module never re-runs a test, never re-evaluates a
    result, and never accepts anything but an already-VERIFIED result.
  - `self_upgrade.version_system.VersionSystem.create_version` is
    called exactly once, completely unchanged, with `upgrade_id=None`
    (same convention `agent.code_change_version_snapshot` already
    established for a capability/change that is not part of an
    `UpgradeSystem`-managed upgrade record). No second version or
    rollback system is created; `rollback_to`/`history`/
    `current_version` are never touched by this module.
  - `execution.project_structure_inspect_capability.
    _is_within_or_equal_allowed_dirs` and `execution.
    text_file_read_capability._resolve_allowed_dirs` are the exact,
    already-existing workspace-containment check `self_upgrade.
    capability_test_execution` itself already reuses - imported here
    unchanged rather than a third copy of the same containment logic.

Verification (before any snapshot is created):
  - `verification_result["status"]` must be `STATUS_VERIFIED` (an
    unverified, failed, timed-out, blocked, or invalid correction can
    never reach a snapshot or an approval request);
  - `capability_name` must be a non-blank string;
  - `file_path` must be a non-blank string that exists on disk;
  - when `allowed_dirs` is given, `file_path` must resolve inside it.
Any failure here is `INVALID` (bad/missing input) or `BLOCKED` (a real
target outside the allowed workspace) - no snapshot, no version, no
approval request is created either way.

Approval states (`status`, exactly one of `ALL_APPROVAL_STATUSES`):
    PENDING_APPROVAL - a snapshot was created and a HumanApprovalRequest
                        is now waiting on an explicit human decision.
                        This module never sets any other status here;
                        `APPROVED`/`REJECTED` only ever come from a
                        separate, later, explicitly human-triggered
                        step that does not exist in this module.
    INVALID          - `verification_result` was not VERIFIED, or was
                        malformed/missing required fields.
    BLOCKED          - inputs were otherwise valid but the target file
                        does not exist, or resolves outside
                        `allowed_dirs`.

`rollback_available` is True exactly when a snapshot was created
(`status == PENDING_APPROVAL`) and `VersionSystem.create_version`
returned a usable version row (i.e. `version["id"]` is present) - the
same version id `self_upgrade.version_system.VersionSystem.
rollback_to` (already existing, unchanged) already accepts.

Never activates, never registers, never marks Self-Upgrade complete,
never approves or rejects anything itself, never rolls back anything.
Never raises: any missing/malformed input, or an unverified
correction, is reported as `INVALID`/`BLOCKED`, never as an exception.
"""

import os
import uuid

from execution.project_structure_inspect_capability import _is_within_or_equal_allowed_dirs
from execution.text_file_read_capability import _resolve_allowed_dirs
from self_upgrade.capability_correction_verification import STATUS_VERIFIED

APPROVAL_STATUS_PENDING = "PENDING_APPROVAL"
APPROVAL_STATUS_APPROVED = "APPROVED"
APPROVAL_STATUS_REJECTED = "REJECTED"
APPROVAL_STATUS_INVALID = "INVALID"
APPROVAL_STATUS_BLOCKED = "BLOCKED"

# APPROVED/REJECTED are listed for a HumanApprovalRequest's own
# lifecycle (what a *later*, separate, human-triggered step may set
# this to) - this module itself only ever produces PENDING_APPROVAL,
# INVALID, or BLOCKED. Nothing in this module sets APPROVED/REJECTED.
ALL_APPROVAL_STATUSES = (
    APPROVAL_STATUS_PENDING, APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED, APPROVAL_STATUS_INVALID, APPROVAL_STATUS_BLOCKED,
)

_REASON_NOT_VERIFIED = (
    "Only a VERIFIED capability correction (self_upgrade."
    "capability_correction_verification.STATUS_VERIFIED) may proceed "
    "to a version snapshot / human approval request."
)


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


def _request(status, capability_name=None, file_path=None, version=None,
             verification_status=None, summary=None, tests_passed=None,
             tests_failed=None, errors=None):
    return {
        "request_id": f"approval-{uuid.uuid4().hex}",
        "capability_name": capability_name,
        "target_file": file_path,
        "version": version,
        "verification_status": verification_status,
        "summary": summary,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "rollback_available": bool(
            status == APPROVAL_STATUS_PENDING
            and isinstance(version, dict)
            and version.get("id") is not None
        ),
        "status": status,
        "errors": list(errors or []),
    }


def request_capability_human_approval(verification_result, versions, allowed_dirs=None):
    """Build a PENDING_APPROVAL `HumanApprovalRequest` for an already-
    VERIFIED capability correction, recording exactly one version
    snapshot via the existing, reused `VersionSystem`. See module
    docstring. Never raises, never activates, registers, approves, or
    rejects anything.

    `verification_result` must be the `CapabilityCorrectionVerificationResult`
    dict `self_upgrade.capability_correction_verification.
    verify_capability_correction` (Prompt 369) already produced -
    reused only to read its own already-computed `status`,
    `capability_name`, `file_path`, `retest_result`, and
    `retest_evaluation`; this function never re-verifies or re-tests
    anything itself.

    `versions` must be a `self_upgrade.version_system.VersionSystem`
    instance (or a compatible object exposing `create_version`) -
    required to produce a `PENDING_APPROVAL` result; if omitted
    (`None`) this is reported as `INVALID` rather than fabricating a
    version system of its own.

    `allowed_dirs`, if given, is the same optional workspace allowlist
    `self_upgrade.capability_test_execution.run_capability_tests`
    already accepts; when omitted, only file existence is checked (no
    workspace-containment check is possible without an allowlist).

    Always returns a `HumanApprovalRequest` dict with exactly:
        {
            "request_id": <fresh uuid4-based id>,
            "capability_name": <str or None>,
            "target_file": <str or None>,
            "version": <the version row `VersionSystem.create_version`
                returned, for PENDING_APPROVAL; None otherwise>,
            "verification_status": <verification_result["status"]>,
            "summary": <short human-readable description, or None>,
            "tests_passed": <int or None, from the retest>,
            "tests_failed": <int or None, from the retest>,
            "rollback_available": <bool - see module docstring>,
            "status": <one of ALL_APPROVAL_STATUSES - this module only
                ever sets PENDING_APPROVAL, INVALID, or BLOCKED>,
            "errors": <list of str>,
        }
    """
    try:
        return _build(verification_result, versions, allowed_dirs)
    except Exception as exc:  # pragma: no cover - defensive
        return _request(APPROVAL_STATUS_INVALID,
                         errors=[f"Unexpected error: {type(exc).__name__}: {exc}"])


def _build(verification_result, versions, allowed_dirs):
    if not isinstance(verification_result, dict):
        return _request(APPROVAL_STATUS_INVALID,
                         errors=["verification_result must be a "
                                 "CapabilityCorrectionVerificationResult dict."])

    verification_status = verification_result.get("status")
    capability_name = verification_result.get("capability_name")
    file_path = verification_result.get("file_path")

    if verification_status != STATUS_VERIFIED:
        return _request(APPROVAL_STATUS_INVALID, capability_name, file_path,
                         verification_status=verification_status,
                         errors=[_REASON_NOT_VERIFIED])

    if not _non_blank(capability_name):
        return _request(APPROVAL_STATUS_INVALID, capability_name, file_path,
                         verification_status=verification_status,
                         errors=["capability_name is missing."])

    if not _non_blank(file_path):
        return _request(APPROVAL_STATUS_INVALID, capability_name, file_path,
                         verification_status=verification_status,
                         errors=["target file/path is missing."])

    real_path = os.path.realpath(file_path)
    if not os.path.isfile(real_path):
        return _request(APPROVAL_STATUS_BLOCKED, capability_name, file_path,
                         verification_status=verification_status,
                         errors=[f"Target file does not exist: {file_path!r}"])

    if allowed_dirs is not None:
        resolved_allowed_dirs = _resolve_allowed_dirs(allowed_dirs)
        if not _is_within_or_equal_allowed_dirs(real_path, resolved_allowed_dirs):
            return _request(APPROVAL_STATUS_BLOCKED, capability_name, file_path,
                             verification_status=verification_status,
                             errors=[f"Target file is outside the allowed "
                                     f"project workspace: {file_path!r}"])

    if versions is None:
        return _request(APPROVAL_STATUS_INVALID, capability_name, file_path,
                         verification_status=verification_status,
                         errors=["No VersionSystem was supplied; no version "
                                 "snapshot was created."])

    retest = verification_result.get("retest_result")
    retest = retest if isinstance(retest, dict) else {}
    tests_passed = retest.get("tests_passed")
    tests_failed = retest.get("tests_failed")

    snapshot_metadata = {
        "capability_name": capability_name,
        "target_file": file_path,
        "verification_status": verification_status,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "related_request": None,  # filled in below once request_id exists
    }

    request_id = f"approval-{uuid.uuid4().hex}"
    snapshot_metadata["related_request"] = request_id

    version = versions.create_version(
        upgrade_id=None,
        version_label=f"capability:{capability_name}",
        snapshot=snapshot_metadata,
    )

    summary = (
        f"Capability {capability_name!r} ({file_path}) passed correction "
        f"verification (retest {tests_passed if tests_passed is not None else '?'} "
        f"passed / {tests_failed if tests_failed is not None else '?'} failed) "
        "and is pending human approval before activation."
    )

    result = _request(
        APPROVAL_STATUS_PENDING, capability_name, file_path, version,
        verification_status, summary, tests_passed, tests_failed,
    )
    # Preserve the exact request_id embedded in the snapshot metadata.
    result["request_id"] = request_id
    return result
