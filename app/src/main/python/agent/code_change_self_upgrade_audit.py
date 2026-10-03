"""
Agent - Code Change Self-Upgrade Change Audit
================================================
Prompt 351: adds a small, local, deterministic audit record for a
CODE_CHANGE Self-Upgrade readiness check that has already finished -
`agent.code_change_self_upgrade_validation.
build_code_change_self_upgrade_readiness` (Prompt 350), reused
completely unchanged - never a second validation/adapter/sandbox
system, and never a second logging or version system:

    {correction_result, original_fragment, replacement, test_status}
        -> build_code_change_self_upgrade_readiness()   (Prompt 350,
           unchanged - reused, never re-implemented)
        -> readiness_result {status, reason, target_file}
        -> build_code_change_audit_record()
        -> audit record {target_file, original_fragment, replacement,
           validation_status, test_status, result_status}
        -> CodeChangeAuditLog.record()

Reuses, never duplicates:
  - `agent.code_change_self_upgrade_validation.
    build_code_change_self_upgrade_readiness` (Prompt 350) is called
    directly, unchanged, to obtain the one, existing "is this change
    ready for Self-Upgrade" verdict (`status`/`reason`/`target_file`).
    This module never re-runs the reused Prompt-349 adapter, never
    re-runs the existing `self_upgrade.sandbox.Sandbox`, and never
    re-derives `READY`/`REJECTED` a second, disagreeing way - it only
    reads that already-computed `readiness_result` (requirement 1, 3).
  - `correction_result["validation_result"]["status"]` -
    `agent.code_correction_proposal_validation`'s own, already-computed
    `VALIDATION_STATUS_VALID`/`VALIDATION_STATUS_INVALID` verdict - is
    read as-is for the audit record's `validation_status` field; this
    module never re-validates the proposal and never invents a third
    validation vocabulary.
  - `execution.execution_event_log.ExecutionEventLog` is this
    project's existing "small, in-memory, id/order-keyed record,
    append-only, with a `latest()` reader" shape;
    `CodeChangeAuditLog` below follows that exact same shape for the
    same reasons (see that module's own docstring) rather than
    inventing a second logging convention. It is a new *store*
    because no existing store already holds this specific, small
    5-field CODE_CHANGE audit shape - `ExecutionEventLog` stores
    `ExecutionEvent` objects for the general execution pipeline, and
    `learning.learning_record_store.LearningRecordStore` stores
    correction-learning records for pattern retrieval; neither is
    reused *as* the audit store itself, since doing so would silently
    change what those two existing, already-relied-upon stores hold
    (requirement 7: "do not create duplicate logging/version
    systems" is honored by reusing their *shape*, not their
    *storage*, which would be the actual duplication/collision to
    avoid).

This is a read-only *record* of a readiness check that has already
finished, never a second decision step and never an install/activation
step (requirement 4): `build_code_change_audit_record` never calls
`build_code_change_self_upgrade_readiness` itself (a caller always
supplies its already-computed `readiness_result`), never calls
`self_upgrade.upgrade_system.UpgradeSystem.propose_upgrade`, and never
touches `self_upgrade.version_system.VersionSystem` - creating an
audit record never installs, activates, or versions anything.

Never raises: a malformed `correction_result` or `readiness_result`
simply yields `None`/`False`-shaped fields in the audit record rather
than raising, same "never raises, report what could be determined"
convention `build_code_change_self_upgrade_readiness` itself already
follows.
"""

def build_code_change_audit_record(
    correction_result, original_fragment, replacement, test_status, readiness_result,
):
    """Build the small, structured audit record for one already-
    finished CODE_CHANGE Self-Upgrade readiness check.

    `correction_result` is the same `{proposal, validation_result,
    application}` dict `build_code_change_self_upgrade_readiness`
    (Prompt 350) itself accepts - reused here only to read its own
    already-computed `validation_result["status"]`, never to
    re-validate anything.

    `original_fragment`/`replacement`/`test_status` are the same
    values already supplied to `build_code_change_self_upgrade_
    readiness` for this check - recorded here as-is, unchanged.

    `readiness_result` is the `{status, reason, target_file}` dict
    `build_code_change_self_upgrade_readiness` (Prompt 350) already
    returned for this exact check (requirement: "record an audit
    entry only after the CODE_CHANGE validation flow finishes") - its
    `status` becomes this record's `result_status`, and its
    `target_file` becomes this record's `target_file`; both reused
    verbatim, never re-derived.

    Always returns a plain dict with exactly these six keys:
        {
            "target_file": <readiness_result["target_file"], or None>,
            "original_fragment": <the value supplied, as-is>,
            "replacement": <the value supplied, as-is>,
            "validation_status": <correction_result["validation_result"]
                ["status"], or None if unavailable>,
            "test_status": <the value supplied, as-is>,
            "result_status": <readiness_result["status"] - one of
                agent.code_change_self_upgrade_validation.
                ALL_SELF_UPGRADE_READINESS_STATUSES - or None if
                `readiness_result` itself is malformed>,
        }

    Never raises: a non-dict `correction_result` or `readiness_result`
    simply yields `None` for the fields that would have come from it,
    rather than raising - same convention
    `build_code_change_self_upgrade_readiness` itself already follows.
    """
    is_correction_dict = isinstance(correction_result, dict)
    validation_result = (
        correction_result.get("validation_result") if is_correction_dict else None
    )
    validation_status = (
        validation_result.get("status") if isinstance(validation_result, dict) else None
    )

    is_readiness_dict = isinstance(readiness_result, dict)
    target_file = readiness_result.get("target_file") if is_readiness_dict else None
    result_status = readiness_result.get("status") if is_readiness_dict else None

    return {
        "target_file": target_file,
        "original_fragment": original_fragment,
        "replacement": replacement,
        "validation_status": validation_status,
        "test_status": test_status,
        "result_status": result_status,
    }


class CodeChangeAuditLog:
    """A small, in-memory, append-only, ordered record of CODE_CHANGE
    Self-Upgrade audit records built by `build_code_change_audit_
    record` above - same "list in insertion order, `latest()` never
    raises on an empty log" shape as
    `execution.execution_event_log.ExecutionEventLog` (see that
    module's own docstring).

    Deliberately independent from persistent storage (requirement 6:
    "keep the audit system deterministic and local"), same as
    `ExecutionEventLog`/`execution.execution_history.ExecutionHistory`:
    this log lives only in this process's RAM and is cleared on
    process restart, or via an explicit `clear()` call.

    Not thread-safe (matches the rest of the project - see
    `ExecutionEventLog`'s own note).
    """

    def __init__(self):
        self._records = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(
        self, correction_result, original_fragment, replacement, test_status, readiness_result,
    ):
        """Build (via `build_code_change_audit_record` above, unchanged)
        and store one audit record for an already-finished CODE_CHANGE
        Self-Upgrade readiness check (requirement 3), then return it.

        Requirement 2: an entry is stored for a rejected change exactly
        the same way as for a successful one - `readiness_result`
        already carries whichever `status` the reused Prompt-350
        readiness check produced (`READY` or `REJECTED`), and this
        method never filters, skips, or special-cases either case.

        Never installs, activates, or versions anything (requirement
        4) - this is storage only. Never raises: malformed inputs are
        handled the same way `build_code_change_audit_record` itself
        handles them (see that function's own docstring).
        """
        audit_record = build_code_change_audit_record(
            correction_result, original_fragment, replacement, test_status, readiness_result,
        )
        self._records.append(audit_record)
        return audit_record

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def latest(self):
        """The most recently recorded audit record, or `None` if
        nothing has been recorded yet (requirement 5: "a simple way to
        retrieve the latest audit record"). Never raises on an empty
        log - same convention as `ExecutionEventLog.latest`."""
        return self._records[-1] if self._records else None

    def list_all(self):
        """Every audit record ever recorded, oldest-first (insertion
        order) - a safe copy of the internal list, so mutating the
        returned list can never reach back into this log's own
        storage. Never raises."""
        return list(self._records)

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def clear(self):
        """Discard every recorded audit record, resetting this log
        back to empty. Never raises; a no-op on an already-empty log."""
        self._records.clear()

    def __len__(self):
        return len(self._records)
