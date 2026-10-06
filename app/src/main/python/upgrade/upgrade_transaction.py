"""
Upgrade Transaction Boundary (Prompt 856, Section 14 - Self-Upgrade Engine)
===========================================================================
A small, deterministic, purely DECLARATIVE record of the lifecycle of a
pending upgrade transaction for a future application process. It applies,
executes and writes nothing: it modifies no project file, creates no backup or
directory, generates no code or patch, runs no command or test, scans no
filesystem, is not connected to Core, Memory, AEL, the Capability System, LLMs
or any external service, and never modifies itself or the project. Nothing is
invented, inferred, trimmed, coerced or repaired.

  begin_upgrade_transaction(change_set)                -> begin result
  validate_upgrade_transaction(transaction)            -> validation result
  finalize_upgrade_transaction(transaction, success)   -> finalize result

Transaction (exactly these seven keys, fixed order):

  {"version", "transaction_id", "change_set_id", "status", "changes",
   "execution_allowed", "executed"}

  version            exactly the string "1"
  transaction_id     "tx_" + first 16 hex digits of the SHA-256 of the change
                     set's canonical JSON (sorted keys, compact separators,
                     ASCII) - the truncated-SHA-256 convention of
                     upgrade/change_proposal.py; depends only on the change set
  change_set_id      the change set's identity: its proposal_id
  status             "pending", "committed" or "rolled_back"
  changes            fresh copy of the change set's changes (Prompt 855 rules:
                     non-empty, <= 16, exact change dicts, unique ids,
                     supported actions)
  execution_allowed  exactly the bool False
  executed           exactly the bool False

begin_upgrade_transaction(change_set)
  The change set must pass validate_change_set (Prompt 855, reused). The new
  transaction always starts "pending". Result (fixed keys, fresh):
    {"valid", "errors", "transaction", "execution_allowed", "executed"}
  `transaction` is the fresh transaction when valid, else None.

validate_upgrade_transaction(transaction)
  Structural check: exact keys, types, version, status values, bounded ids,
  change rules, flags exactly False, and transaction_id equal to the id derived
  from the change set rebuilt from change_set_id and changes. Result:
    {"valid", "errors", "execution_allowed", "executed"}

finalize_upgrade_transaction(transaction, success=False)
  The transaction must be valid and `success` an exact bool. Only "pending" may
  be finalized: success True -> "committed", success False -> "rolled_back".
  A "committed" or "rolled_back" transaction is never changed again. The
  supplied transaction is never modified; the result holds a fresh copy:
    {"valid", "errors", "transaction", "execution_allowed", "executed"}
  Finalizing records a state only - nothing is applied or executed, and
  "executed" stays False even when committed.

errors: [{"code", "where"}], at most 16, fixed order. Begin codes:
invalid_change_set. Finalize codes: invalid_transaction, invalid_success,
transaction_already_finalized. Validation codes: missing_transaction,
transaction_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_transaction_id, invalid_change_set_id, invalid_status,
transaction_id_mismatch, the Prompt 855 change codes (invalid_changes,
empty_changes, too_many_items, invalid_change, ..., unsupported_change_action),
invalid_execution_allowed, invalid_executed, validation_error.

`execution_allowed` and `executed` are always False in every result.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 852 / 855 modules and hashlib /
json (pure computation, no I/O).
"""

import hashlib
import json

from upgrade.change_proposal import MAX_CHANGES, _check_changes
from upgrade.change_set import CHANGE_SET_VERSION, _check_actions, validate_change_set
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

TRANSACTION_VERSION = "1"
TRANSACTION_ID_PREFIX = "tx_"
TRANSACTION_ID_DIGITS = 16

STATUS_PENDING = "pending"
STATUS_COMMITTED = "committed"
STATUS_ROLLED_BACK = "rolled_back"
STATUSES = (STATUS_PENDING, STATUS_COMMITTED, STATUS_ROLLED_BACK)

FIELDS = ("version", "transaction_id", "change_set_id", "status", "changes",
          "execution_allowed", "executed")

ERR_MISSING_TRANSACTION = "missing_transaction"
ERR_TRANSACTION_NOT_DICT = "transaction_not_dict"


def derive_transaction_id(change_set):
    """Deterministic bounded id from a (validated) change set's content only."""
    text = json.dumps(change_set, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return (TRANSACTION_ID_PREFIX
            + hashlib.sha256(text.encode("ascii")).hexdigest()[:TRANSACTION_ID_DIGITS])


def _rebuilt_change_set(transaction):
    return {"version": CHANGE_SET_VERSION, "proposal_id": transaction["change_set_id"],
            "changes": transaction["changes"], "execution_allowed": False}


def _transaction_errors(transaction):
    errors = []
    if type(transaction) is not dict:
        _add(errors, ERR_MISSING_TRANSACTION if transaction is None else ERR_TRANSACTION_NOT_DICT,
             "transaction")
        return errors
    if len(transaction) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "transaction")
        return errors
    for key in transaction:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in transaction:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = transaction[field]
        if field == "version":
            if type(value) is not str or value != TRANSACTION_VERSION:
                _add(errors, "invalid_version", field)
        elif field in ("transaction_id", "change_set_id"):
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_" + field, field)
        elif field == "status":
            if type(value) is not str or value not in STATUSES:
                _add(errors, "invalid_status", field)
        elif field == "changes":
            _check_changes(errors, value)
            if type(value) is list and len(value) <= MAX_CHANGES:
                _check_actions(errors, value)
        elif value is not False:
            _add(errors, "invalid_" + field, field)
    if not errors and transaction["transaction_id"] != derive_transaction_id(
            _rebuilt_change_set(transaction)):
        _add(errors, "transaction_id_mismatch", "transaction_id")
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_upgrade_transaction(transaction=None):
    """Validation result for a transaction; nothing is repaired."""
    try:
        return _validation(_transaction_errors(transaction))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "transaction"}])


def _result(errors, transaction=None):
    return {"valid": not errors, "errors": errors, "transaction": None if errors else transaction,
            "execution_allowed": False, "executed": False}


def _transaction(change_set_id, transaction_id, status, changes):
    return {"version": TRANSACTION_VERSION, "transaction_id": transaction_id,
            "change_set_id": change_set_id, "status": status,
            "changes": [dict(change) for change in changes],
            "execution_allowed": False, "executed": False}


def begin_upgrade_transaction(change_set=None):
    """Fresh pending transaction for a valid change set, or the reason it is impossible."""
    try:
        errors = []
        if not validate_change_set(change_set)["valid"]:
            _add(errors, "invalid_change_set", "change_set")
            return _result(errors)
        transaction = _transaction(change_set["proposal_id"], derive_transaction_id(change_set),
                                   STATUS_PENDING, change_set["changes"])
        if _transaction_errors(transaction):
            return _result([{"code": ERR_INTERNAL, "where": "transaction"}])
        return _result(errors, transaction)
    except Exception:
        return _result([{"code": ERR_INTERNAL, "where": "transaction"}])


def finalize_upgrade_transaction(transaction=None, success=False):
    """Fresh finalized copy of a pending transaction; the input is never modified."""
    try:
        errors = []
        if not validate_upgrade_transaction(transaction)["valid"]:
            _add(errors, "invalid_transaction", "transaction")
        if type(success) is not bool:
            _add(errors, "invalid_success", "success")
        if not errors and transaction["status"] != STATUS_PENDING:
            _add(errors, "transaction_already_finalized", "status")
        if errors:
            return _result(errors)
        final = _transaction(transaction["change_set_id"], transaction["transaction_id"],
                             STATUS_COMMITTED if success else STATUS_ROLLED_BACK,
                             transaction["changes"])
        return _result(errors, final)
    except Exception:
        return _result([{"code": ERR_INTERNAL, "where": "transaction"}])
