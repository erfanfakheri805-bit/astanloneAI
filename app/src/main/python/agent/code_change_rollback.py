"""
Agent - Code Change Rollback
================================
Prompt 353: connects an already-applied, already-tested CODE_CHANGE
to the existing Self-Upgrade rollback mechanism (self_upgrade/
version_system.py's `VersionSystem.rollback_to`, unchanged) so a
change whose test came back FAILED or TIMEOUT can be safely reverted -
never a second rollback or version system:

    test_status + target_file + version
        -> build_code_change_rollback_decision()
        -> {change_status, test_status, rollback_required,
            rollback_status, target_file}

Reuses, never duplicates:
  - `agent.test_result_evaluation.RESULT_PASSED`/`RESULT_FAILED`/
    `RESULT_TIMEOUT` - the exact same test-outcome vocabulary
    `agent.code_change_self_upgrade_validation`/`agent.code_correction_
    retest`/`agent.code_change_evaluation` already use - are imported,
    unchanged, to decide "does this outcome require a rollback"
    (requirement 2). This module never runs a test itself and never
    re-classifies a raw test result.
  - `self_upgrade.version_system.VersionSystem.rollback_to(version_id)`
    (self_upgrade/version_system.py, unchanged) is called exactly
    once, only when a rollback is required, on the `id` of the
    `version` a caller already supplies for this change (requirement
    1, 3, 4: "rollback must use the version snapshot created for that
    change") - this module never re-implements `rollback_to`'s own
    "mark this version active again" logic, never calls
    `VersionSystem.create_version` itself, and never touches
    `self_upgrade.upgrade_system.UpgradeSystem` at all (requirement 7:
    "do not create a second rollback/version system").

`version` is expected to be a version row this project's own
`VersionSystem` already produced for this exact change - typically the
`"version"` field of `agent.code_change_version_snapshot.
build_code_change_version_snapshot`'s (Prompt 352) `CREATED` result,
or any other `VersionSystem.create_version`/`rollback_to` row exposing
an `"id"` key. This module never builds that version record itself; a
caller always supplies the one already on file for this change.

This is a decision-and-rollback step, never a retry mechanism
(requirement 6): nothing here re-applies the code change, re-runs the
failed test, or proposes a new correction - a FAILED/TIMEOUT change is
only ever reverted, never automatically retried.

`change_status` is exactly one of:
    `KEPT`            - `test_status` was `PASSED`; no rollback was
                         attempted, the current state is kept as-is.
    `ROLLED_BACK`     - `test_status` was `FAILED`/`TIMEOUT` and the
                         existing `rollback_to` call succeeded.
    `ROLLBACK_FAILED` - `test_status` was `FAILED`/`TIMEOUT` but the
                         rollback attempt itself could not complete
                         (no usable `version`/`versions`, or the
                         existing `rollback_to` reported no matching
                         version).

`rollback_status` is exactly one of `NOT_REQUIRED`/`SUCCEEDED`/`FAILED`
- see `build_code_change_rollback_decision`'s own docstring below for
the exact, fixed rules each of the three follows.

Never raises: any missing or malformed input is reported as
`ROLLBACK_FAILED`/`FAILED` with `rollback_required=True`, never as an
exception - same "never raises, report what could be determined"
convention the rest of this project's CODE_CHANGE pipeline (Prompts
349-352) already follows.
"""

from .test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT

CHANGE_STATUS_KEPT = "KEPT"
CHANGE_STATUS_ROLLED_BACK = "ROLLED_BACK"
CHANGE_STATUS_ROLLBACK_FAILED = "ROLLBACK_FAILED"

ALL_CODE_CHANGE_STATUSES = (
    CHANGE_STATUS_KEPT, CHANGE_STATUS_ROLLED_BACK, CHANGE_STATUS_ROLLBACK_FAILED,
)

ROLLBACK_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
ROLLBACK_STATUS_SUCCEEDED = "SUCCEEDED"
ROLLBACK_STATUS_FAILED = "FAILED"

ALL_ROLLBACK_STATUSES = (
    ROLLBACK_STATUS_NOT_REQUIRED, ROLLBACK_STATUS_SUCCEEDED, ROLLBACK_STATUS_FAILED,
)

# Requirement 2: exactly these two outcomes require a rollback -
# fixed, never guessed at from any other field.
_ROLLBACK_REQUIRED_TEST_STATUSES = (RESULT_FAILED, RESULT_TIMEOUT)


def build_code_change_rollback_decision(test_status, target_file, version, versions=None):
    """Decide whether an already-applied, already-tested CODE_CHANGE
    must be rolled back, and - only when it must - perform that
    rollback via the existing, reused `VersionSystem.rollback_to`.

    `test_status` is an already-classified test outcome - typically
    `agent.code_correction_retest.build_code_correction_retest(...)
    ["retest_evaluation"]["classification"]`, or `agent.test_result_
    evaluation.classify_test_result(...)` - one of
    `agent.test_result_evaluation.ALL_TEST_RESULT_CLASSIFICATIONS`.
    This function never runs a test itself.

    `target_file` is the file the CODE_CHANGE targeted - recorded in
    the result as-is, never re-derived.

    `version` is the version row `VersionSystem.create_version`
    already produced for this exact change (requirement 4) -
    typically `agent.code_change_version_snapshot.
    build_code_change_version_snapshot(...)["version"]` (Prompt 352).
    Only its `"id"` is read, and only when a rollback is required.

    `versions`, if given, must be a `self_upgrade.version_system.
    VersionSystem` instance (or a compatible object exposing
    `rollback_to(version_id)`) - reused exactly as provided, same
    "caller may inject a collaborator" convention
    `build_code_change_self_upgrade_readiness` (Prompt 350) already
    follows for its own `sandbox=` parameter. Omitted (`None`) on a
    change that needs a rollback, this function reports
    `ROLLBACK_FAILED`/`FAILED` rather than fabricating a version
    system of its own (requirement 7).

    Always returns a plain dict with exactly these five keys
    (requirement 5):
        {
            "change_status": <"KEPT", "ROLLED_BACK", or
                "ROLLBACK_FAILED" - see module docstring>,
            "test_status": <the value supplied, as-is>,
            "rollback_required": <True for FAILED/TIMEOUT, else
                False - requirement 2>,
            "rollback_status": <"NOT_REQUIRED", "SUCCEEDED", or
                "FAILED">,
            "target_file": <the value supplied, as-is>,
        }

    Never retries the change itself (requirement 6) - this function
    never re-applies a correction, never re-runs a test, and never
    proposes a new one. Never raises: a missing/malformed `version`
    or `versions` on a change that needs a rollback is reported as
    `ROLLBACK_FAILED`/`FAILED`, never as an exception.
    """
    rollback_required = test_status in _ROLLBACK_REQUIRED_TEST_STATUSES

    if not rollback_required:
        return {
            "change_status": CHANGE_STATUS_KEPT,
            "test_status": test_status,
            "rollback_required": False,
            "rollback_status": ROLLBACK_STATUS_NOT_REQUIRED,
            "target_file": target_file,
        }

    # Requirement 4: rollback must use the version snapshot already
    # created for this change - never a freshly-built or guessed id.
    version_id = version.get("id") if isinstance(version, dict) else None

    rolled_back = None
    if versions is not None and version_id is not None:
        rolled_back = versions.rollback_to(version_id)

    if rolled_back is not None:
        return {
            "change_status": CHANGE_STATUS_ROLLED_BACK,
            "test_status": test_status,
            "rollback_required": True,
            "rollback_status": ROLLBACK_STATUS_SUCCEEDED,
            "target_file": target_file,
        }

    return {
        "change_status": CHANGE_STATUS_ROLLBACK_FAILED,
        "test_status": test_status,
        "rollback_required": True,
        "rollback_status": ROLLBACK_STATUS_FAILED,
        "target_file": target_file,
    }
