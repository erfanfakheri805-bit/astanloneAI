"""
Upgrade Audit Record (Prompt 861, Section 14 - Self-Upgrade Engine)
===================================================================
A small, deterministic, purely DECLARATIVE audit record for a FINALIZED
self-upgrade transaction. It stores, persists and executes nothing: no
filesystem or database access, no history store, no subprocess, code or patch
generation or execution, and no Core, Memory, AEL, external API or network
link. Inputs are never modified; nothing is invented, trimmed or repaired.

  build_upgrade_audit_record(transaction, finalized_commit) -> record | None
  validate_upgrade_audit_record(record)                     -> validation

Audit record (exactly these seven keys, fixed order, fresh):

  {"version", "transaction_id", "proposal_id", "status", "changes",
   "execution_allowed", "executed"}

  version            exactly the string "1"
  transaction_id     the transaction's id (identical in the finalized commit)
  proposal_id        the transaction's change_set_id (identical in the commit)
  status             "committed" or "rolled_back", identical in both inputs
  changes            fresh copy of the changes, same order, identical in both
  execution_allowed  exactly the bool False, always
  executed           exactly the bool False, always

build_upgrade_audit_record returns the fresh record, or None when ANY input is
rejected (no partial or repaired record). Checks, first failure wins:
  1. transaction    validate_upgrade_transaction (Prompt 856)
  2. finalized      its status must be "committed" or "rolled_back"
                    ("pending" is not auditable)
  3. commit         validate_finalized_commit (Prompt 860)
  4. status         finalized commit status == transaction status
  5. identity       transaction_id and proposal_id (== change_set_id) equal
  6. changes        equal, exactly and in order

validate_upgrade_audit_record(record)
  Structural check, never repairs: the Prompt 860 finalized-record rules
  (reused: exact keys, types, version, final status, bounded ids, Prompt 855
  change rules, flags exactly False, transaction_id derived from proposal_id
  and changes) plus the exact key order above. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Extra code: invalid_field_order.

Bounded work, read-only, deterministic, never raises. Imports only the
Prompt 849 / 856 / 860 modules (pure computation, no I/O).
"""

from upgrade.upgrade_commit import COMMIT_VERSION
from upgrade.upgrade_commit_finalization import FINAL_STATUSES, validate_finalized_commit
from upgrade.upgrade_request import ERR_INTERNAL, _add
from upgrade.upgrade_transaction import validate_upgrade_transaction

AUDIT_VERSION = COMMIT_VERSION

FIELDS = ("version", "transaction_id", "proposal_id", "status", "changes",
          "execution_allowed", "executed")


def _build_errors(transaction, finalized_commit):
    """Reasons an audit record cannot be built (first failing step only); [] if it can."""
    errors = []
    if not validate_upgrade_transaction(transaction)["valid"]:
        _add(errors, "invalid_transaction", "transaction")
    elif transaction["status"] not in FINAL_STATUSES:
        _add(errors, "transaction_not_finalized", "transaction.status")
    elif not validate_finalized_commit(finalized_commit)["valid"]:
        _add(errors, "invalid_finalized_commit", "finalized_commit")
    elif finalized_commit["status"] != transaction["status"]:
        _add(errors, "status_mismatch", "finalized_commit.status")
    elif finalized_commit["transaction_id"] != transaction["transaction_id"]:
        _add(errors, "transaction_id_mismatch", "finalized_commit.transaction_id")
    elif finalized_commit["proposal_id"] != transaction["change_set_id"]:
        _add(errors, "proposal_id_mismatch", "finalized_commit.proposal_id")
    elif finalized_commit["changes"] != transaction["changes"]:
        _add(errors, "changes_mismatch", "finalized_commit.changes")
    return errors


def build_upgrade_audit_record(transaction=None, finalized_commit=None):
    """Fresh audit record for a finalized transaction, or None; inputs are never modified."""
    try:
        if _build_errors(transaction, finalized_commit):
            return None
        record = {"version": AUDIT_VERSION, "transaction_id": transaction["transaction_id"],
                  "proposal_id": transaction["change_set_id"], "status": transaction["status"],
                  "changes": [dict(change) for change in transaction["changes"]],
                  "execution_allowed": False, "executed": False}
        if not validate_upgrade_audit_record(record)["valid"]:
            return None
        return record
    except Exception:
        return None


def validate_upgrade_audit_record(record=None):
    """Validation result for an audit record; nothing is repaired."""
    try:
        errors = list(validate_finalized_commit(record)["errors"])
        if not errors and list(record) != list(FIELDS):
            _add(errors, "invalid_field_order", "record")
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "record"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
