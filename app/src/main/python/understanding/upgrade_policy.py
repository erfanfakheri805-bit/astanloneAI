"""
Upgrade Policy Gate (Prompt 854, Section 14 - Self-Upgrade Engine)
==================================================================
A small, deterministic, purely DECLARATIVE policy gate between the change
proposal (Prompt 852) and any future, separate change-application stage. It
only answers one question - may this validated proposal proceed to a future
controlled application stage? - and nothing else. It applies, generates,
modifies and executes nothing, reads and writes no file, scans no filesystem,
runs no test or command, registers or modifies no capability and is not
connected to Core, Memory, AEL, the Capability System, LLMs or any external
service. Permission is never inferred from action names, file names,
capability names, purposes or the trustworthiness of the caller, and invalid
or incomplete input is never repaired or approved.

  evaluate_upgrade_policy(change_proposal, project_state=None) -> policy result
  validate_upgrade_policy_result(result)                      -> validation result

Policy result (exactly these seven keys, fixed order, fresh on every call):

  {"version", "status", "allowed", "reason", "proposal_id",
   "execution_allowed", "executed"}

  version             exactly "1"
  status              one of STATUSES
  allowed             bool; True only when status is "allowed"
  reason              the one fixed reason of the status (REASONS)
  proposal_id         the proposal's plan_id (text <= 64) when the proposal is
                      structurally valid (or empty_proposal with a valid
                      plan_id), else None; always text when allowed
  execution_allowed   always exactly False
  executed            always exactly False

Evaluation order (the first failing step decides; nothing is repaired):
  1. change_proposal must be a dict                -> invalid_input
  2. validate_change_proposal (Prompt 852, reused) -> empty_proposal when its
     only error is empty_changes, else invalid_proposal. It also rejects any
     execution permission and any malformed change.
  3. project_state, when not None, must pass validate_project_state (Prompt 850,
     reused)                                       -> invalid_project_state
  4. every change target must be listed in the proposal's affected_files or
     affected_capabilities and every affected entry must be a change target;
     the proposal must represent its own targets    -> policy_denied
  5. otherwise                                      -> allowed
project_state is only validated; it never widens or grants permission. The
`allowed` status is a permission to proceed to a future stage, not an
execution: execution_allowed and executed stay False in every result.

validate_upgrade_policy_result(result)
  Structural check of a policy result: exact dict with the seven keys, exact
  types, version "1", a known status, a bool `allowed` that agrees with the
  status, the fixed reason for that status, a bounded proposal_id (None for
  invalid_input / invalid_proposal, text for allowed / policy_denied /
  invalid_project_state), and execution_allowed / executed exactly False.
  Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most 16, fixed order. Codes: missing_result,
result_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_status, invalid_allowed, invalid_reason,
invalid_proposal_id, invalid_execution_allowed, invalid_executed,
validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 850 / 852 modules (pure
computation, no I/O).
"""

from upgrade.change_proposal import validate_change_proposal
from upgrade.project_state import validate_project_state
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

POLICY_VERSION = "1"

FIELDS = ("version", "status", "allowed", "reason", "proposal_id",
          "execution_allowed", "executed")

STATUS_INVALID_INPUT = "invalid_input"
STATUS_INVALID_PROPOSAL = "invalid_proposal"
STATUS_INVALID_PROJECT_STATE = "invalid_project_state"
STATUS_EMPTY_PROPOSAL = "empty_proposal"
STATUS_POLICY_DENIED = "policy_denied"
STATUS_ALLOWED = "allowed"

STATUSES = (STATUS_INVALID_INPUT, STATUS_INVALID_PROPOSAL, STATUS_INVALID_PROJECT_STATE,
            STATUS_EMPTY_PROPOSAL, STATUS_POLICY_DENIED, STATUS_ALLOWED)

REASON_MISSING_PROPOSAL = "change_proposal_missing"
REASON_PROPOSAL_NOT_DICT = "change_proposal_not_dict"
REASON_INTERNAL = "policy_evaluation_error"

# Every status has fixed reasons; invalid_input is the only one with several.
REASONS = {
    STATUS_INVALID_INPUT: (REASON_MISSING_PROPOSAL, REASON_PROPOSAL_NOT_DICT, REASON_INTERNAL),
    STATUS_INVALID_PROPOSAL: ("change_proposal_invalid",),
    STATUS_INVALID_PROJECT_STATE: ("project_state_invalid",),
    STATUS_EMPTY_PROPOSAL: ("change_proposal_has_no_changes",),
    STATUS_POLICY_DENIED: ("affected_targets_not_represented_by_changes",),
    STATUS_ALLOWED: ("proposal_is_valid_and_represents_its_own_targets",),
}

# proposal_id rule per status: None required, text required, or either.
_ID_NONE, _ID_TEXT, _ID_EITHER = "none", "text", "either"
_ID_RULES = {
    STATUS_INVALID_INPUT: _ID_NONE,
    STATUS_INVALID_PROPOSAL: _ID_NONE,
    STATUS_INVALID_PROJECT_STATE: _ID_TEXT,
    STATUS_EMPTY_PROPOSAL: _ID_EITHER,
    STATUS_POLICY_DENIED: _ID_TEXT,
    STATUS_ALLOWED: _ID_TEXT,
}

ERR_MISSING_RESULT = "missing_result"
ERR_RESULT_NOT_DICT = "result_not_dict"


def _result(status, reason, proposal_id=None):
    return {"version": POLICY_VERSION, "status": status,
            "allowed": status == STATUS_ALLOWED, "reason": reason,
            "proposal_id": proposal_id, "execution_allowed": False, "executed": False}


def _result_errors(result):
    errors = []
    if type(result) is not dict:
        _add(errors, ERR_MISSING_RESULT if result is None else ERR_RESULT_NOT_DICT, "result")
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
    if type(result["version"]) is not str or result["version"] != POLICY_VERSION:
        _add(errors, "invalid_version", "version")
    if not status_ok:
        _add(errors, "invalid_status", "status")
    if type(result["allowed"]) is not bool or (status_ok and result["allowed"] != (status == STATUS_ALLOWED)):
        _add(errors, "invalid_allowed", "allowed")
    reason = result["reason"]
    if type(reason) is not str or (status_ok and reason not in REASONS[status]):
        _add(errors, "invalid_reason", "reason")
    proposal_id = result["proposal_id"]
    rule = _ID_RULES[status] if status_ok else _ID_EITHER
    id_text = _is_text(proposal_id, MAX_ID_LENGTH)
    if not ((proposal_id is None and rule != _ID_TEXT) or (id_text and rule != _ID_NONE)):
        _add(errors, "invalid_proposal_id", "proposal_id")
    if result["execution_allowed"] is not False:
        _add(errors, "invalid_execution_allowed", "execution_allowed")
    if result["executed"] is not False:
        _add(errors, "invalid_executed", "executed")
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_upgrade_policy_result(result=None):
    """Validation result for a policy result; nothing is repaired."""
    try:
        return _validation(_result_errors(result))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "result"}])


def _represents_own_targets(proposal):
    targets = {change["target"] for change in proposal["changes"]}
    affected = set(proposal["affected_files"]) | set(proposal["affected_capabilities"])
    return targets == affected


def _evaluate(change_proposal, project_state):
    if type(change_proposal) is not dict:
        return _result(STATUS_INVALID_INPUT, REASON_MISSING_PROPOSAL if change_proposal is None
                       else REASON_PROPOSAL_NOT_DICT)
    proposal_errors = validate_change_proposal(change_proposal)["errors"]
    plan_id = change_proposal.get("plan_id")
    proposal_id = plan_id if _is_text(plan_id, MAX_ID_LENGTH) else None
    if proposal_errors:
        if [e["code"] for e in proposal_errors] == ["empty_changes"]:
            return _result(STATUS_EMPTY_PROPOSAL, REASONS[STATUS_EMPTY_PROPOSAL][0], proposal_id)
        return _result(STATUS_INVALID_PROPOSAL, REASONS[STATUS_INVALID_PROPOSAL][0])
    if project_state is not None and not validate_project_state(project_state)["valid"]:
        return _result(STATUS_INVALID_PROJECT_STATE, REASONS[STATUS_INVALID_PROJECT_STATE][0],
                       proposal_id)
    if not _represents_own_targets(change_proposal):
        return _result(STATUS_POLICY_DENIED, REASONS[STATUS_POLICY_DENIED][0], proposal_id)
    return _result(STATUS_ALLOWED, REASONS[STATUS_ALLOWED][0], proposal_id)


def evaluate_upgrade_policy(change_proposal=None, project_state=None):
    """Fresh policy result: may this proposal proceed to a future application stage?"""
    try:
        result = _evaluate(change_proposal, project_state)
        if _result_errors(result):
            return _result(STATUS_INVALID_INPUT, REASON_INTERNAL)
        return result
    except Exception:
        return _result(STATUS_INVALID_INPUT, REASON_INTERNAL)
