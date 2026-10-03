"""
Agent - Code Change Version Snapshot
========================================
Prompt 352: connects an already-validated, already-applied,
already-passing CODE_CHANGE Self-Upgrade readiness check (agent/
code_change_self_upgrade_validation.py's `build_code_change_self_
upgrade_readiness`, Prompt 350, unchanged) to the existing Self-Upgrade
Version System (self_upgrade/version_system.py's `VersionSystem`,
unchanged) by creating one version snapshot BEFORE any future
installation/activation step - never a second version-management
system, and never `self_upgrade.upgrade_system.UpgradeSystem.
propose_upgrade`'s own install stage:

    readiness_result (Prompt 350, unchanged)
        + correction_result / test_status / audit_record (Prompt 351)
        -> build_code_change_version_snapshot()
        -> {status, reason, target_file, version}

Reuses, never duplicates:
  - `agent.code_change_self_upgrade_validation.STATUS_READY` (Prompt
    350) is the one, existing "validation passed, the change was
    safely applied, and the relevant test passed" gate this module
    reads - it never re-runs the reused Prompt-349 adapter, never
    re-runs the existing `self_upgrade.sandbox.Sandbox`, and never
    re-derives READY/REJECTED a second, disagreeing way (requirements
    2, 8: a version snapshot is only ever created for an already-
    computed `READY` result; anything else, including a `REJECTED`
    result caused by failed validation or a failed test, never reaches
    `VersionSystem.create_version` at all).
  - `correction_result["validation_result"]["status"]` -
    `agent.code_correction_proposal_validation`'s own, already-
    computed verdict - is read as-is for the snapshot's
    `validation_status` metadata; this module never re-validates
    anything.
  - `agent.code_change_self_upgrade_audit.build_code_change_audit_
    record`'s own, already-built audit record (Prompt 351) is embedded
    in the snapshot as-is, as the "audit record/reference" metadata
    (requirement 3) - this module never rebuilds, re-derives, or
    stores a second copy of that record anywhere else.
  - `self_upgrade.version_system.VersionSystem.create_version(
    upgrade_id, version_label, snapshot=None)` (requirement 1, 6: "no
    new version-management system") is called directly, exactly once,
    completely unchanged, with `upgrade_id=None` - this CODE_CHANGE
    snapshot is not the product of `UpgradeSystem.propose_upgrade`'s
    own upgrade-record lifecycle (no `upgrades` row is created, no
    `stage`/`status` is ever advanced to `install`/`installed` for it -
    requirements 4, 5), so there is no existing upgrade id to attach
    it to; `versions.upgrade_id` already allows this (see
    self_upgrade/version_system.py's schema - `upgrade_id INTEGER`,
    nullable). `VersionSystem.rollback_to`/`history`/`current_version`
    are left completely untouched by this module (requirement 7) -
    it only ever calls `create_version`, exactly the same single
    existing method `UpgradeSystem.propose_upgrade` itself already
    calls for its own, separate install pipeline.

This is a snapshot *step*, never an install/activation step
(requirements 4, 5): nothing in this module calls
`self_upgrade.upgrade_system.UpgradeSystem.propose_upgrade`,
`UpgradeSystem._advance`, or any other method that would mark a
CODE_CHANGE as "installed" - the version record this module creates
exists purely as the already-existing Version System's own record of
what *could* be installed, exactly the same "snapshot now, activate
later, separately, explicitly" shape `agent.code_change_self_upgrade_
validation.build_code_change_self_upgrade_readiness` (Prompt 350)
and `agent.code_change_self_upgrade_adapter.build_self_upgrade_input_
from_code_correction` (Prompt 349) already established for the steps
before this one.

`status` is exactly one of:
    `CREATED` - `readiness_result["status"]` was `READY`; a version
                snapshot was created via `VersionSystem.create_version`
                and is returned under `version`.
    `SKIPPED` - `readiness_result` was not `READY` (missing metadata,
                failed validation, a failed test, or a failed sandbox
                check - requirement 8: "if validation or testing
                fails, do not create a successful version snapshot");
                `version` is `None` and `reason` explains why, reusing
                the reused Prompt-350 `readiness_result["reason"]`
                verbatim rather than inventing a second explanation.

Never raises: a malformed `readiness_result`/`correction_result` is
always reported as `status=SKIPPED` with an explanatory `reason`,
never as an exception - same convention `build_code_change_self_
upgrade_readiness` and `build_code_change_audit_record` themselves
already follow.
"""

from .code_change_self_upgrade_validation import STATUS_READY

CHANGE_TYPE_CODE_CHANGE = "CODE_CHANGE"

SNAPSHOT_STATUS_CREATED = "CREATED"
SNAPSHOT_STATUS_SKIPPED = "SKIPPED"

ALL_CODE_CHANGE_SNAPSHOT_STATUSES = (SNAPSHOT_STATUS_CREATED, SNAPSHOT_STATUS_SKIPPED)

_REASON_NOT_READY = (
    "The code change is not READY for Self-Upgrade (validation, safe "
    "application, the relevant test, or the sandbox check did not all "
    "pass); no version snapshot was created."
)
_REASON_MISSING_VERSION_SYSTEM = (
    "No VersionSystem was supplied; no version snapshot was created."
)


def build_code_change_version_snapshot(
    correction_result, test_status, readiness_result, audit_record, versions,
):
    """Build the version-snapshot metadata for an already-finished
    CODE_CHANGE Self-Upgrade readiness check, and - only when that
    check is `READY` - record it into the existing, reused
    `VersionSystem` (requirement 1) via its own, unchanged
    `create_version` method.

    `correction_result` is the same `{proposal, validation_result,
    application}` dict `build_code_change_self_upgrade_readiness`
    (Prompt 350) itself accepts - reused here only to read its own
    already-computed `validation_result["status"]`, never to
    re-validate anything.

    `test_status` is the same already-classified test outcome already
    supplied to the Prompt-350 readiness check for this exact change -
    recorded here as-is, unchanged.

    `readiness_result` is the `{status, reason, target_file}` dict
    `build_code_change_self_upgrade_readiness` (Prompt 350) already
    returned for this exact check - this function never calls that
    readiness check itself; a caller always supplies its already-
    computed result (requirement: "when a CODE_CHANGE passes
    validation, safe application, and the relevant test" - i.e. is
    already `READY`).

    `audit_record` is the already-built `{target_file,
    original_fragment, replacement, validation_status, test_status,
    result_status}` dict `agent.code_change_self_upgrade_audit.
    build_code_change_audit_record` (Prompt 351) already produced for
    this exact change - embedded in the snapshot as-is, as the "audit
    record/reference" metadata (requirement 3). May be `None` if no
    audit record is available; the snapshot then simply carries `None`
    for that field rather than raising.

    `versions` must be a `self_upgrade.version_system.VersionSystem`
    instance (or a compatible object exposing `create_version`) - the
    exact same collaborator `UpgradeSystem.__init__` itself already
    builds one of, reused here rather than a second version system.
    Required for a `CREATED` result; if omitted (`None`) on an
    otherwise-`READY` change, this function reports `SKIPPED` rather
    than raising or silently fabricating a version record.

    Always returns:
        {
            "status": <"CREATED" or "SKIPPED" - see module
                docstring>,
            "reason": <str explaining the verdict>,
            "target_file": <the target file this snapshot is for, or
                None when it could not be determined>,
            "version": <the version row `VersionSystem.create_version`
                returned, for "CREATED"; None for "SKIPPED">,
        }

    Never installs or activates the change itself (requirements 4, 5)
    - see module docstring. Never raises: any malformed input is
    reported as `status=SKIPPED` with an explanatory `reason`, exactly
    like `build_code_change_self_upgrade_readiness` and
    `build_code_change_audit_record` already guarantee for themselves.
    """
    is_readiness_dict = isinstance(readiness_result, dict)
    target_file = readiness_result.get("target_file") if is_readiness_dict else None

    # Requirement 2, 8: only an already-READY change (validation
    # passed, safely applied, relevant test passed, and the existing
    # sandbox check passed - see Prompt 350) is ever snapshotted; a
    # REJECTED or malformed readiness_result never creates a
    # successful version snapshot.
    if not is_readiness_dict or readiness_result.get("status") != STATUS_READY:
        reason = (
            readiness_result.get("reason")
            if is_readiness_dict and readiness_result.get("reason")
            else _REASON_NOT_READY
        )
        return {
            "status": SNAPSHOT_STATUS_SKIPPED,
            "reason": reason,
            "target_file": target_file,
            "version": None,
        }

    if versions is None:
        return {
            "status": SNAPSHOT_STATUS_SKIPPED,
            "reason": _REASON_MISSING_VERSION_SYSTEM,
            "target_file": target_file,
            "version": None,
        }

    is_correction_dict = isinstance(correction_result, dict)
    validation_result = (
        correction_result.get("validation_result") if is_correction_dict else None
    )
    validation_status = (
        validation_result.get("status") if isinstance(validation_result, dict) else None
    )

    # Requirement 3: enough metadata to identify target_file, change
    # type, test status, validation status, and the audit record this
    # snapshot corresponds to - nothing more is stored here, and none
    # of it is re-derived (all of it is read from already-computed
    # results supplied by the caller).
    snapshot_metadata = {
        "target_file": target_file,
        "change_type": CHANGE_TYPE_CODE_CHANGE,
        "test_status": test_status,
        "validation_status": validation_status,
        "audit_record": audit_record if isinstance(audit_record, dict) else None,
    }

    # Requirement 4, 5: only `VersionSystem.create_version` is called -
    # never `UpgradeSystem.propose_upgrade` and never any method that
    # would mark a CODE_CHANGE upgrade record as installed. `upgrade_id`
    # is None because this snapshot does not belong to an
    # UpgradeSystem-managed upgrade lifecycle (see module docstring).
    version = versions.create_version(
        upgrade_id=None,
        version_label=f"code_change:{target_file}",
        snapshot=snapshot_metadata,
    )

    return {
        "status": SNAPSHOT_STATUS_CREATED,
        "reason": (
            f"Version snapshot created for the CODE_CHANGE to {target_file!r}; "
            "not installed or activated."
        ),
        "target_file": target_file,
        "version": version,
    }
