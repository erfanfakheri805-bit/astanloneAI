"""
Upgrade Commit Boundary (Prompt 859, Section 14 - Self-Upgrade Engine)
======================================================================
A small, deterministic, purely DECLARATIVE "ready to commit" record built from
a valid pending Upgrade Transaction (Prompt 856) and a verified sandbox result
(Prompt 857 / 858). It commits nothing: it never modifies the real project,
the transaction or the workspace, performs no filesystem I/O, backup,
subprocess, code or patch generation or execution, and has no Core, Memory,
AEL, external API or network link. Nothing is invented, trimmed or repaired.

  prepare_upgrade_commit(transaction, workspace, verification_result) -> commit | None
  validate_upgrade_commit(commit_result)                              -> validation

Commit record (exactly these seven keys, fixed order, fresh):

  {"version", "transaction_id", "proposal_id", "changes", "status",
   "execution_allowed", "executed"}

  version            exactly the string "1"
  transaction_id     the transaction's id ("tx_" + 16 hex digits)
  proposal_id        the verified change set's proposal_id (the transaction's
                     change_set_id)
  changes            fresh copy of the verified change set's changes, same order
  status             exactly "ready_to_commit"
  execution_allowed  exactly the bool False, always
  executed           exactly the bool False, always

prepare_upgrade_commit returns the fresh record, or None when ANY input is
rejected (there is no partial or repaired record). Checks, first failure wins:
  1. transaction        validate_upgrade_transaction (Prompt 856)
  2. pending            status must be "pending" (committed / rolled_back
                        transactions are already finalized)
  3. workspace          validate_sandbox_workspace (Prompt 857)
  4. verification       validate_sandbox_verification (Prompt 858), and it must
                        be status "valid" / valid True
  5. identity           verification proposal_id == transaction change_set_id
  6. applied            exactly one workspace record for that proposal_id, and
                        its changes equal the transaction's changes exactly,
                        in order
  7. freshness          verify_sandbox_result (Prompt 858) re-run against the
                        change set rebuilt from the transaction must equal the
                        supplied verification result exactly (rejects stale or
                        forged verification results)

validate_upgrade_commit(commit_result)
  Structural check, never repairs: exact keys, exact types, version, status,
  bounded text ids, Prompt 855 change rules, flags exactly False, and
  transaction_id equal to the id derived (Prompt 856) from the change set
  rebuilt from proposal_id and changes. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_commit, commit_not_dict, too_many_fields, unexpected_field,
  missing_field, invalid_version, invalid_transaction_id, invalid_proposal_id,
  invalid_status, the Prompt 855 change codes, invalid_execution_allowed,
  invalid_executed, transaction_id_mismatch, validation_error.

Bounded work, read-only, deterministic, never raises. Imports only the
Prompt 849 / 852 / 855 / 856 / 857 / 858 modules (pure computation, no I/O).
"""

from upgrade.change_proposal import MAX_CHANGES, _check_changes
from upgrade.change_set import CHANGE_SET_VERSION, _check_actions
from upgrade.upgrade_request import (
    ERR_INTERNAL,
    ERR_MISSING_FIELD,
    ERR_TOO_MANY_FIELDS,
    ERR_UNEXPECTED_FIELD,
    MAX_FIELDS,
    MAX_ID_LENGTH,
    _add,
    _is_text,
    _where,
)
from upgrade.upgrade_sandbox import validate_sandbox_workspace
from upgrade.upgrade_transaction import (
    STATUS_PENDING,
    derive_transaction_id,
    validate_upgrade_transaction,
)
from upgrade.upgrade_verification import (
    STATUS_VALID,
    validate_sandbox_verification,
    verify_sandbox_result,
)

COMMIT_VERSION = "1"
STATUS_READY_TO_COMMIT = "ready_to_commit"

FIELDS = ("version", "transaction_id", "proposal_id", "changes", "status",
          "execution_allowed", "executed")

ERR_MISSING_COMMIT = "missing_commit"
ERR_COMMIT_NOT_DICT = "commit_not_dict"


def _rebuilt_change_set(proposal_id, changes):
    return {"version": CHANGE_SET_VERSION, "proposal_id": proposal_id,
            "changes": changes, "execution_allowed": False}


def _prepare_errors(transaction, workspace, verification_result):
    """Reasons a commit cannot be prepared (first failing step only); [] if it can."""
    errors = []
    if not validate_upgrade_transaction(transaction)["valid"]:
        _add(errors, "invalid_transaction", "transaction")
    elif transaction["status"] != STATUS_PENDING:
        _add(errors, "transaction_not_pending", "transaction.status")
    elif not validate_sandbox_workspace(workspace)["valid"]:
        _add(errors, "invalid_workspace", "workspace")
    elif not validate_sandbox_verification(verification_result)["valid"]:
        _add(errors, "invalid_verification", "verification_result")
    elif verification_result["status"] != STATUS_VALID or verification_result["valid"] is not True:
        _add(errors, "verification_not_valid", "verification_result")
    elif verification_result["proposal_id"] != transaction["change_set_id"]:
        _add(errors, "verification_mismatch", "verification_result.proposal_id")
    else:
        proposal_id = transaction["change_set_id"]
        records = [r for r in workspace["applied"] if r["proposal_id"] == proposal_id]
        if len(records) != 1:
            _add(errors, "change_set_not_applied", "workspace.applied")
        elif records[0]["changes"] != transaction["changes"]:
            _add(errors, "applied_changes_mismatch", "workspace.applied")
        elif verify_sandbox_result(
                workspace, _rebuilt_change_set(proposal_id, transaction["changes"])
        ) != verification_result:
            _add(errors, "verification_stale", "verification_result")
    return errors


def prepare_upgrade_commit(transaction=None, workspace=None, verification_result=None):
    """Fresh ready_to_commit record, or None; no input is modified, nothing is committed."""
    try:
        if _prepare_errors(transaction, workspace, verification_result):
            return None
        commit = {"version": COMMIT_VERSION, "transaction_id": transaction["transaction_id"],
                  "proposal_id": transaction["change_set_id"],
                  "changes": [dict(change) for change in transaction["changes"]],
                  "status": STATUS_READY_TO_COMMIT,
                  "execution_allowed": False, "executed": False}
        if _commit_errors(commit):
            return None
        return commit
    except Exception:
        return None


def _commit_errors(commit):
    errors = []
    if type(commit) is not dict:
        _add(errors, ERR_MISSING_COMMIT if commit is None else ERR_COMMIT_NOT_DICT, "commit")
        return errors
    if len(commit) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "commit")
        return errors
    for key in commit:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in commit:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = commit[field]
        if field == "version":
            if type(value) is not str or value != COMMIT_VERSION:
                _add(errors, "invalid_version", field)
        elif field in ("transaction_id", "proposal_id"):
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_" + field, field)
        elif field == "status":
            if type(value) is not str or value != STATUS_READY_TO_COMMIT:
                _add(errors, "invalid_status", field)
        elif field == "changes":
            _check_changes(errors, value)
            if type(value) is list and len(value) <= MAX_CHANGES:
                _check_actions(errors, value)
        elif value is not False:
            _add(errors, "invalid_" + field, field)
    if not errors and commit["transaction_id"] != derive_transaction_id(
            _rebuilt_change_set(commit["proposal_id"], commit["changes"])):
        _add(errors, "transaction_id_mismatch", "transaction_id")
    return errors


def validate_upgrade_commit(commit_result=None):
    """Validation result for a commit record; nothing is repaired."""
    try:
        errors = _commit_errors(commit_result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "commit"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
