"""
Upgrade Sandbox Verification (Prompt 858, Section 14 - Self-Upgrade Engine)
===========================================================================
A small, deterministic, read-only check that a sandbox result (Prompt 857) is
internally consistent and still represents exactly the authorized change set.
It repairs and modifies nothing, reads and writes no real file, generates no
code or patch, runs no subprocess or command, is not connected to Core, Memory,
AEL, LLMs or any external service, and never executes anything.

  verify_sandbox_result(workspace, change_set, policy_result=None) -> result
  validate_sandbox_verification(result)                            -> validation

Verification result (exactly these six keys, fixed order, fresh):

  {"valid", "status", "errors", "proposal_id", "execution_allowed", "executed"}

  valid              True only when status is "valid"
  status             one of STATUSES
  errors             [{"code", "where"}], at most 16; empty only when valid
  proposal_id        the change set's proposal_id when the change set is valid,
                     else None; always text when status is "valid"
  execution_allowed  always exactly False
  executed           always exactly False

Order of checks (the first failing step decides the status):
  1. workspace          validate_sandbox_workspace (Prompt 857, which reuses the
                        Prompt 850 project-state validation)
                        -> invalid_workspace; when every workspace error is a
                        referential / authorization one (duplicate_proposal_id,
                        unknown_target, unsupported_change_action) the
                        workspace is structurally sound but its records are not
                        authorized -> tampered
  2. change set         validate_change_set (Prompt 855)    -> invalid_change_set
  3. policy (optional)  validate_upgrade_policy_result (Prompt 854); it must be
                        status "allowed" / allowed True with the change set's
                        proposal_id (policy_not_allowed / policy_proposal_mismatch)
                                                           -> invalid_policy
  4. applied record     exactly one record with the change set's proposal_id;
                        none -> not_applied (change_set_not_applied)
  5. content            the record's changes must equal the change set's changes
                        exactly and in order -> tampered (changes_length_mismatch,
                        change_id_changed / action_changed / target_changed /
                        reason_changed with where "changes[i].field")
  6. otherwise                                               -> valid
Any unexpected internal failure -> verification_error.

validate_sandbox_verification(result)
  Structural check of a verification result: exact keys and types, known
  status, `valid` agreeing with the status, errors empty exactly when valid and
  made of exact {code, where} text dicts (<= 16), bounded proposal_id, flags
  exactly False. Never repairs. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}
  Codes: missing_result, result_not_dict, too_many_fields, unexpected_field,
  missing_field, invalid_valid, invalid_status, invalid_errors, too_many_items,
  invalid_error, invalid_proposal_id, invalid_execution_allowed, invalid_executed,
  validation_error.

`execution_allowed` and `executed` are always False in every result.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 854 / 855 / 857 modules (pure
computation, no I/O).
"""

from upgrade.change_set import validate_change_set
from upgrade.upgrade_policy import STATUS_ALLOWED, validate_upgrade_policy_result
from upgrade.upgrade_request import (
    ERR_INTERNAL,
    ERR_MISSING_FIELD,
    ERR_TOO_MANY_FIELDS,
    ERR_TOO_MANY_ITEMS,
    ERR_UNEXPECTED_FIELD,
    MAX_ERRORS,
    MAX_FIELDS,
    MAX_ID_LENGTH,
    MAX_ITEM_LENGTH,
    _add,
    _is_text,
    _where,
)
from upgrade.upgrade_sandbox import validate_sandbox_workspace

STATUS_VALID = "valid"
STATUS_INVALID_WORKSPACE = "invalid_workspace"
STATUS_INVALID_CHANGE_SET = "invalid_change_set"
STATUS_INVALID_POLICY = "invalid_policy"
STATUS_NOT_APPLIED = "not_applied"
STATUS_TAMPERED = "tampered"
STATUS_VERIFICATION_ERROR = "verification_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_WORKSPACE, STATUS_INVALID_CHANGE_SET,
            STATUS_INVALID_POLICY, STATUS_NOT_APPLIED, STATUS_TAMPERED,
            STATUS_VERIFICATION_ERROR)

FIELDS = ("valid", "status", "errors", "proposal_id", "execution_allowed", "executed")

# Workspace errors that mean "structurally sound but not authorized".
_TAMPER_CODES = ("duplicate_proposal_id", "unknown_target", "unsupported_change_action")
_CHANGE_FIELDS = ("change_id", "action", "target", "reason")
_CHANGE_FIELD_CODES = {"change_id": "change_id_changed", "action": "action_changed",
                       "target": "target_changed", "reason": "reason_changed"}


def _result(status, errors, proposal_id=None):
    return {"valid": status == STATUS_VALID, "status": status, "errors": errors,
            "proposal_id": proposal_id, "execution_allowed": False, "executed": False}


def _workspace_failure(errors):
    status = STATUS_INVALID_WORKSPACE
    if errors and all(e["code"] in _TAMPER_CODES for e in errors):
        status = STATUS_TAMPERED
    out = []
    for error in errors:
        _add(out, error["code"], "workspace." + error["where"])
    return status, out


def _policy_errors(policy_result, change_set):
    errors = []
    if not validate_upgrade_policy_result(policy_result)["valid"]:
        _add(errors, "invalid_policy_result", "policy_result")
    elif policy_result["status"] != STATUS_ALLOWED or policy_result["allowed"] is not True:
        _add(errors, "policy_not_allowed", "policy_result")
    elif policy_result["proposal_id"] != change_set["proposal_id"]:
        _add(errors, "policy_proposal_mismatch", "policy_result")
    return errors


def _content_errors(record_changes, changes):
    errors = []
    if len(record_changes) != len(changes):
        _add(errors, "changes_length_mismatch", "changes")
        return errors
    for index, (recorded, expected) in enumerate(zip(record_changes, changes)):
        for field in _CHANGE_FIELDS:
            if recorded[field] != expected[field]:
                _add(errors, _CHANGE_FIELD_CODES[field], "changes[%d].%s" % (index, field))
    return errors


def _verify(workspace, change_set, policy_result):
    cs_ok = validate_change_set(change_set)["valid"]
    proposal_id = change_set["proposal_id"] if cs_ok else None
    workspace_check = validate_sandbox_workspace(workspace)
    if not workspace_check["valid"]:
        status, errors = _workspace_failure(workspace_check["errors"])
        return _result(status, errors, proposal_id)
    if not cs_ok:
        return _result(STATUS_INVALID_CHANGE_SET,
                       [{"code": "invalid_change_set", "where": "change_set"}])
    if policy_result is not None:
        errors = _policy_errors(policy_result, change_set)
        if errors:
            return _result(STATUS_INVALID_POLICY, errors, proposal_id)
    records = [r for r in workspace["applied"] if r["proposal_id"] == proposal_id]
    if not records:
        return _result(STATUS_NOT_APPLIED,
                       [{"code": "change_set_not_applied", "where": "workspace.applied"}], proposal_id)
    if len(records) > 1:
        return _result(STATUS_TAMPERED,
                       [{"code": "duplicate_application_record", "where": "workspace.applied"}],
                       proposal_id)
    errors = _content_errors(records[0]["changes"], change_set["changes"])
    if errors:
        return _result(STATUS_TAMPERED, errors, proposal_id)
    return _result(STATUS_VALID, [], proposal_id)


def verify_sandbox_result(workspace=None, change_set=None, policy_result=None):
    """Fresh verification result; inputs are never modified or repaired."""
    try:
        return _verify(workspace, change_set, policy_result)
    except Exception:
        return _result(STATUS_VERIFICATION_ERROR, [{"code": ERR_INTERNAL, "where": "verification"}])


def _error_items(errors, value):
    if type(value) is not list:
        _add(errors, "invalid_errors", "errors")
    elif len(value) > MAX_ERRORS:
        _add(errors, ERR_TOO_MANY_ITEMS, "errors")
    else:
        for index, item in enumerate(value):
            if not (type(item) is dict and list(item) == ["code", "where"]
                    and _is_text(item["code"], MAX_ID_LENGTH)
                    and _is_text(item["where"], MAX_ITEM_LENGTH)):
                _add(errors, "invalid_error", "errors[%d]" % index)


def _result_errors(result):
    errors = []
    if type(result) is not dict:
        _add(errors, "missing_result" if result is None else "result_not_dict", "result")
        return errors
    if len(result) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "result")
        return errors
    for key in result:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in result:
            _add(errors, ERR_MISSING_FIELD, field)
    if errors:
        return errors
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        _add(errors, "invalid_status", "status")
    if type(result["valid"]) is not bool or (status_ok and result["valid"] != (status == STATUS_VALID)):
        _add(errors, "invalid_valid", "valid")
    _error_items(errors, result["errors"])
    if type(result["errors"]) is list and status_ok and bool(result["errors"]) == (status == STATUS_VALID):
        _add(errors, "invalid_errors", "errors")
    proposal_id = result["proposal_id"]
    if not ((proposal_id is None and status != STATUS_VALID) or _is_text(proposal_id, MAX_ID_LENGTH)):
        _add(errors, "invalid_proposal_id", "proposal_id")
    for field in ("execution_allowed", "executed"):
        if result[field] is not False:
            _add(errors, "invalid_" + field, field)
    return errors


def validate_sandbox_verification(result=None):
    """Validation result for a verification result; nothing is repaired."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
