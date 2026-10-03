"""
Agent - Code Change Upgrade Result
======================================
Prompt 354: a small, structured result that summarizes the complete
CODE_CHANGE self-upgrade flow already built by Prompts 349-353 - never
a second CODE_CHANGE, audit, validation, testing, version, or rollback
system:

    correction_result (Prompt 343)
        + readiness_result   (agent.code_change_self_upgrade_validation.
                               build_code_change_self_upgrade_readiness,
                               Prompt 350, unchanged)
        + snapshot_result    (agent.code_change_version_snapshot.
                               build_code_change_version_snapshot,
                               Prompt 352, unchanged)
        + rollback_result    (agent.code_change_rollback.
                               build_code_change_rollback_decision,
                               Prompt 353, unchanged)
        -> build_code_change_upgrade_result()
        -> {target_file, validation_status, change_status, test_status,
            version_status, rollback_required, rollback_status,
            final_status}

Reuses, never duplicates:
  - `correction_result["validation_result"]["status"]` -
    `agent.code_correction_proposal_validation`'s own, already-computed
    verdict - is read as-is for this result's `validation_status`,
    exactly the same field `agent.code_change_self_upgrade_audit.
    build_code_change_audit_record` (Prompt 351) already reads the
    same way. This module never re-validates anything.
  - `readiness_result["status"]` - `agent.code_change_self_upgrade_
    validation.build_code_change_self_upgrade_readiness`'s (Prompt
    350) own `READY`/`REJECTED` verdict, itself already gating on the
    existing adapter (Prompt 349), the existing test-outcome
    vocabulary, and the existing `Sandbox` - is read as-is; this
    module never re-runs the readiness check and never re-derives
    `READY`/`REJECTED` a second, disagreeing way.
  - `snapshot_result["status"]` - `agent.code_change_version_snapshot.
    build_code_change_version_snapshot`'s (Prompt 352) own
    `CREATED`/`SKIPPED` verdict against the existing `VersionSystem` -
    is read as-is for this result's `version_status`; this module
    never calls `VersionSystem.create_version` itself.
  - `rollback_result` - `agent.code_change_rollback.build_code_change_
    rollback_decision`'s (Prompt 353) own already-computed
    `{change_status, test_status, rollback_required, rollback_status,
    target_file}` against the existing `VersionSystem.rollback_to` -
    is read as-is, field for field, for four of this result's eight
    fields (`change_status`, `test_status`, `rollback_required`,
    `rollback_status`, and, as the first-available choice,
    `target_file`); this module never calls `VersionSystem.
    rollback_to` itself and never re-derives whether a rollback was
    required or whether it succeeded.

`correction_result`/`readiness_result`/`snapshot_result`/
`rollback_result` are each expected to already be the finished result
of the correspondingly-named existing step above, run once, by a
caller, in that fixed order (typically via the existing
`AgentLoop.apply_code_correction` -> `AgentLoop.evaluate_self_upgrade_
readiness` -> `AgentLoop.snapshot_self_upgrade_version` ->
`AgentLoop.decide_code_change_rollback` sequence, all unchanged) -
this module never runs, re-runs, or reorders any of those steps
itself; it only reads the four already-computed dicts it is handed
and reports one small, combined summary of what they already say
(requirement 1: "reuse existing CODE_CHANGE, audit, validation,
testing, version, and rollback systems").

`final_status` (requirement 3) is derived from nothing but the three
already-computed verdicts above (`readiness_result["status"]`,
`rollback_result["change_status"]`, `snapshot_result["status"]`),
checked in this fixed order, and is exactly one of:

    `ROLLED_BACK` - `rollback_result["change_status"]` was already
                    `ROLLED_BACK` (the relevant test came back
                    FAILED/TIMEOUT and the existing `rollback_to` call
                    already succeeded, using the version supplied for
                    this change).
    `FAILED`      - `rollback_result["change_status"]` was already
                    `ROLLBACK_FAILED` (a rollback was required but the
                    existing rollback attempt could not complete); OR
                    the change was `KEPT` (the relevant test passed,
                    no rollback needed) *and* `readiness_result
                    ["status"]` was already `READY`, but
                    `snapshot_result["status"]` was not `CREATED`
                    (e.g. no `VersionSystem` was available to record
                    the successful change); OR any of the three inputs
                    this depends on is malformed/missing (a safe,
                    conservative default - never guessed as SUCCESS,
                    REJECTED, or ROLLED_BACK without evidence for one
                    of those).
    `REJECTED`    - the change was `KEPT` (the relevant test passed,
                    no rollback needed) but `readiness_result
                    ["status"]` was not already `READY` (validation,
                    safe application, or the existing sandbox check
                    did not all pass, per Prompt 350's own, unchanged
                    gate).
    `SUCCESS`     - the change was `KEPT`, `readiness_result["status"]`
                    was already `READY`, *and* `snapshot_result
                    ["status"]` was already `CREATED` - every existing
                    stage this flow depends on already reported
                    success.

Never re-derives, and never runs, retries, or reverses anything of its
own (requirements 5, 6): this module contains no call to any
correction, validation, sandbox, version, or rollback method - it only
reads four already-finished dicts' own fields and combines them into
one small, structured, inert summary. In particular, a `FAILED`
`final_status` is only ever *reported* here - this module never
automatically retries the failed change and never automatically starts
another upgrade (requirements 5, 6 restated for this specific,
terminal step).

Serializable and small (requirement 7): the returned dict's eight
values are always plain strings, `None`, or a single `bool` - never a
nested object, so it is trivially safe for `Core`/`AgentLoop` (or a
JSON boundary) to consume directly.

Never raises: any of the four inputs that is missing or not a dict
yields `None`/`False`-shaped fields for whatever could not be
determined from it, and `final_status` falls back to `FAILED` rather
than raising - same "never raises, report what could be determined"
convention every other module in this project's CODE_CHANGE pipeline
(Prompts 349-353) already follows.
"""

from .code_change_self_upgrade_validation import STATUS_READY
from .code_change_version_snapshot import SNAPSHOT_STATUS_CREATED
from .code_change_rollback import (
    CHANGE_STATUS_KEPT,
    CHANGE_STATUS_ROLLED_BACK,
    CHANGE_STATUS_ROLLBACK_FAILED,
)

FINAL_STATUS_SUCCESS = "SUCCESS"
FINAL_STATUS_FAILED = "FAILED"
FINAL_STATUS_ROLLED_BACK = "ROLLED_BACK"
FINAL_STATUS_REJECTED = "REJECTED"

ALL_CODE_CHANGE_UPGRADE_FINAL_STATUSES = (
    FINAL_STATUS_SUCCESS,
    FINAL_STATUS_FAILED,
    FINAL_STATUS_ROLLED_BACK,
    FINAL_STATUS_REJECTED,
)


def _determine_final_status(readiness_status, change_status, version_status):
    """The one, fixed decision table `final_status` follows - see
    module docstring for the full rationale for each branch. Checked
    in this exact order; never raises."""
    if change_status == CHANGE_STATUS_ROLLED_BACK:
        return FINAL_STATUS_ROLLED_BACK
    if change_status == CHANGE_STATUS_ROLLBACK_FAILED:
        return FINAL_STATUS_FAILED
    if change_status == CHANGE_STATUS_KEPT:
        if readiness_status != STATUS_READY:
            return FINAL_STATUS_REJECTED
        if version_status == SNAPSHOT_STATUS_CREATED:
            return FINAL_STATUS_SUCCESS
        return FINAL_STATUS_FAILED
    # Requirement: never raise - an unrecognized/missing change_status
    # (a malformed rollback_result) is reported as FAILED, the same
    # conservative default a broken/incomplete flow already earns
    # above, never guessed as one of the other three.
    return FINAL_STATUS_FAILED


def build_code_change_upgrade_result(
    correction_result, readiness_result, snapshot_result, rollback_result,
):
    """Build the small, structured, serializable result that
    summarizes the complete CODE_CHANGE self-upgrade flow already run
    by the existing, unchanged Prompts 349-353 pipeline. See module
    docstring for the full field-by-field reuse and `final_status`
    rules.

    `correction_result` is the same `{proposal, validation_result,
    application}` dict `AgentLoop.apply_code_correction` (Prompt 343)
    already returns - read here only for its own already-computed
    `validation_result["status"]`, never re-validated.

    `readiness_result` is the `{status, reason, target_file}` dict
    `AgentLoop.evaluate_self_upgrade_readiness` (Prompt 350) already
    returned for this exact change.

    `snapshot_result` is the `{status, reason, target_file, version}`
    dict `AgentLoop.snapshot_self_upgrade_version` (Prompt 352) already
    returned for this exact change.

    `rollback_result` is the `{change_status, test_status,
    rollback_required, rollback_status, target_file}` dict
    `AgentLoop.decide_code_change_rollback` (Prompt 353) already
    returned for this exact change.

    None of the four steps above is re-run, re-ordered, or
    re-derived a second way by this function - it only reads each
    one's own, already-computed fields.

    Always returns a plain, serializable dict with exactly these eight
    keys (requirement 2, 7):
        {
            "target_file": <str or None - rollback_result
                ["target_file"] if available, else readiness_result
                ["target_file"], else snapshot_result["target_file"]>,
            "validation_status": <correction_result["validation_result"]
                ["status"], or None if unavailable>,
            "change_status": <rollback_result["change_status"] -
                "KEPT"/"ROLLED_BACK"/"ROLLBACK_FAILED" - or None if
                unavailable>,
            "test_status": <rollback_result["test_status"], or None if
                unavailable>,
            "version_status": <snapshot_result["status"] -
                "CREATED"/"SKIPPED" - or None if unavailable>,
            "rollback_required": <rollback_result["rollback_required"],
                or None if unavailable>,
            "rollback_status": <rollback_result["rollback_status"], or
                None if unavailable>,
            "final_status": <one of ALL_CODE_CHANGE_UPGRADE_FINAL_
                STATUSES - see module docstring>,
        }

    Never retries the change and never starts another upgrade
    (requirements 5, 6) - this function contains no call to any
    correction, validation, sandbox, version, or rollback method.
    Never raises: any malformed input yields `None` for the fields
    that would have come from it, and `final_status` falls back to
    `FAILED` - never an exception.
    """
    is_correction_dict = isinstance(correction_result, dict)
    validation_result = (
        correction_result.get("validation_result") if is_correction_dict else None
    )
    validation_status = (
        validation_result.get("status") if isinstance(validation_result, dict) else None
    )

    is_readiness_dict = isinstance(readiness_result, dict)
    readiness_status = readiness_result.get("status") if is_readiness_dict else None
    readiness_target_file = readiness_result.get("target_file") if is_readiness_dict else None

    is_snapshot_dict = isinstance(snapshot_result, dict)
    version_status = snapshot_result.get("status") if is_snapshot_dict else None
    snapshot_target_file = snapshot_result.get("target_file") if is_snapshot_dict else None

    is_rollback_dict = isinstance(rollback_result, dict)
    change_status = rollback_result.get("change_status") if is_rollback_dict else None
    test_status = rollback_result.get("test_status") if is_rollback_dict else None
    rollback_required = rollback_result.get("rollback_required") if is_rollback_dict else None
    rollback_status = rollback_result.get("rollback_status") if is_rollback_dict else None
    rollback_target_file = rollback_result.get("target_file") if is_rollback_dict else None

    # requirement: a single target_file, preferring whichever of the
    # three already-computed steps actually determined one - never a
    # second, independently-derived path.
    target_file = rollback_target_file or readiness_target_file or snapshot_target_file

    final_status = _determine_final_status(readiness_status, change_status, version_status)

    return {
        "target_file": target_file,
        "validation_status": validation_status,
        "change_status": change_status,
        "test_status": test_status,
        "version_status": version_status,
        "rollback_required": rollback_required,
        "rollback_status": rollback_status,
        "final_status": final_status,
    }
