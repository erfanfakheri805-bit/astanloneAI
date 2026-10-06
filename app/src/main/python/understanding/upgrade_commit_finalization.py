"""
Upgrade Commit Finalization (Prompt 860, Section 14 - Self-Upgrade Engine)
==========================================================================
A small, deterministic, purely DECLARATIVE record of the final outcome of a
controlled upgrade transaction. It applies, writes, deletes, restores and
executes nothing: it never modifies the real project, the transaction or the
commit result, performs no filesystem I/O, subprocess, code or patch
generation or execution, and has no Core, Memory, AEL, external API or network
link. Nothing is invented, trimmed or repaired.

  finalize_upgrade_commit(transaction, commit_result, success=False) -> final | None
  validate_finalized_commit(result)                                   -> validation

Finalized record (exactly these seven keys, fixed order, fresh):

  {"version", "transaction_id", "proposal_id", "changes", "status",
   "execution_allowed", "executed"}

  version            exactly the string "1"
  transaction_id     the transaction's / commit's id (identical in both)
  proposal_id        the transaction's change_set_id / commit's proposal_id
  changes            fresh copy of the changes, same order
  status             "committed" (success True) or "rolled_back" (success False)
  execution_allowed  exactly the bool False, always
  executed           exactly the bool False, always

finalize_upgrade_commit returns the fresh record, or None when ANY input is
rejected (no partial or repaired record). Checks, first failure wins:
  1. transaction    validate_upgrade_transaction (Prompt 856)
  2. pending        transaction status must be "pending" (a committed or
                    rolled_back transaction is already finalized)
  3. commit         validate_upgrade_commit (Prompt 859); status is necessarily
                    "ready_to_commit"
  4. success        an exact bool (True / False)
  5. identity       commit transaction_id == transaction transaction_id and
                    commit proposal_id == transaction change_set_id
  6. changes        commit changes == transaction changes, exactly and in order
The status comes from finalize_upgrade_transaction (Prompt 856), reused.
Finalizing records a state only: "executed" stays False even when committed.

validate_finalized_commit(result)
  Structural check, never repairs: exact keys and types, version, status in
  {"committed", "rolled_back"} ("ready_to_commit" / "pending" are not final),
  bounded ids, Prompt 855 change rules, flags exactly False, and transaction_id
  equal to the id derived (Prompt 856) from the change set rebuilt from
  proposal_id and changes (the Prompt 859 record check, reused). Result:
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: those of validate_upgrade_commit, with invalid_status for a status
  that is not final.

Bounded work, read-only, deterministic, never raises. Imports only the
Prompt 849 / 856 / 859 modules (pure computation, no I/O).
"""

from upgrade.upgrade_commit import (
    COMMIT_VERSION,
    STATUS_READY_TO_COMMIT,
    validate_upgrade_commit,
)
from upgrade.upgrade_request import ERR_INTERNAL, _add
from upgrade.upgrade_transaction import (
    STATUS_COMMITTED,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    finalize_upgrade_transaction,
    validate_upgrade_transaction,
)

FINAL_STATUSES = (STATUS_COMMITTED, STATUS_ROLLED_BACK)


def _finalize_errors(transaction, commit_result, success):
    """Reasons finalization is impossible (first failing step only); [] if possible."""
    errors = []
    if not validate_upgrade_transaction(transaction)["valid"]:
        _add(errors, "invalid_transaction", "transaction")
    elif transaction["status"] != STATUS_PENDING:
        _add(errors, "transaction_already_finalized", "transaction.status")
    elif not validate_upgrade_commit(commit_result)["valid"]:
        _add(errors, "invalid_commit", "commit_result")
    elif type(success) is not bool:
        _add(errors, "invalid_success", "success")
    elif commit_result["transaction_id"] != transaction["transaction_id"]:
        _add(errors, "transaction_id_mismatch", "commit_result.transaction_id")
    elif commit_result["proposal_id"] != transaction["change_set_id"]:
        _add(errors, "proposal_id_mismatch", "commit_result.proposal_id")
    elif commit_result["changes"] != transaction["changes"]:
        _add(errors, "changes_mismatch", "commit_result.changes")
    return errors


def finalize_upgrade_commit(transaction=None, commit_result=None, success=False):
    """Fresh committed / rolled_back record, or None; nothing is applied or modified."""
    try:
        if _finalize_errors(transaction, commit_result, success):
            return None
        final_tx = finalize_upgrade_transaction(transaction, success)
        if not final_tx["valid"]:
            return None
        tx = final_tx["transaction"]
        result = {"version": COMMIT_VERSION, "transaction_id": tx["transaction_id"],
                  "proposal_id": tx["change_set_id"],
                  "changes": [dict(change) for change in commit_result["changes"]],
                  "status": tx["status"],
                  "execution_allowed": False, "executed": False}
        if not validate_finalized_commit(result)["valid"]:
            return None
        return result
    except Exception:
        return None


def validate_finalized_commit(result=None):
    """Validation result for a finalized record; nothing is repaired."""
    try:
        probe = result
        status_error = False
        if type(result) is dict and "status" in result:
            status = result["status"]
            if not (type(status) is str and status in FINAL_STATUSES):
                status_error = True
            # Same record rules as Prompt 859: check the rest with the status swapped
            # on a throw-away copy (the supplied result itself is never touched).
            probe = dict(result, status=STATUS_READY_TO_COMMIT)
        errors = list(validate_upgrade_commit(probe)["errors"])
        if status_error:
            _add(errors, "invalid_status", "status")
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
