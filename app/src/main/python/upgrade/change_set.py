"""
Sandboxed Change Set (Prompt 855, Section 14 - Self-Upgrade Engine)
===================================================================
A small, deterministic, purely DECLARATIVE layer that turns an ALLOWED change
proposal (Prompt 852, gated by the Prompt 854 policy) into an isolated change
set: a structured description of intended changes for a future sandboxed
application stage. It is NOT a sandbox and not an executor: it creates no
directory or file, copies no project file, applies and generates no patch,
diff or source code, runs no command or test, reads and scans no filesystem,
registers or modifies no capability, is not connected to Core, Memory, AEL,
LLMs or any external service, and never touches the real project. Nothing is
added, removed, inferred, trimmed, coerced or repaired.

  build_change_set(change_proposal, policy_result) -> build result
  validate_change_set(change_set)                  -> validation result

Normalized change set (exactly these four keys):

  {"version", "proposal_id", "changes", "execution_allowed"}

  version            exactly the string "1"
  proposal_id        text <= MAX_ID_LENGTH, the proposal's plan_id
  changes            non-empty list, <= MAX_CHANGES exact dicts with exactly
                     change_id (<= 64), action (<= 64), target (<= 200),
                     reason (<= 200), all non-empty text; change ids unique;
                     action is one of ACTIONS (modify_file / update_capability,
                     the only actions a Prompt 851 plan can contain)
  execution_allowed  exactly the bool False

build_change_set(change_proposal, policy_result)
  The proposal must pass validate_change_proposal (Prompt 852, reused) and the
  policy result must pass validate_upgrade_policy_result (Prompt 854, reused).
  The policy result must have status "allowed" and allowed True, and must
  correspond to the proposal: its proposal_id equals the proposal's plan_id and
  it equals what evaluate_upgrade_policy (Prompt 854, reused) returns for that
  proposal, so a forged or stale "allowed" result is refused. Then:
    proposal_id  the proposal's plan_id
    changes      fresh copies of the proposal's changes, same order, unchanged
  Result (fixed keys, fresh):
    {"valid", "errors", "change_set", "execution_allowed", "executed"}
  `change_set` is the fresh normalized change set when valid, else None. The
  change set itself carries no "executed" key.

validate_change_set(change_set)
  Structural check of a normalized change set. Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most 16, fixed order. Build codes:
invalid_change_proposal, invalid_policy_result, policy_not_allowed,
policy_proposal_mismatch, plus the validation codes of the produced change set.
Validation codes: missing_change_set, change_set_not_dict, too_many_fields,
unexpected_field, missing_field, invalid_version, invalid_proposal_id,
invalid_changes, empty_changes, too_many_items, invalid_change,
too_many_change_fields, unexpected_change_field, missing_change_field,
invalid_change_change_id / _action / _target / _reason (where
"changes[i].field"), duplicate_change_id, unsupported_change_action,
invalid_execution_allowed, validation_error.

`execution_allowed` and `executed` are always False in every result: a change
set never implies permission to apply or execute anything.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 851 / 852 / 854 modules (pure
computation, no I/O).
"""

from upgrade.change_proposal import MAX_CHANGES, _check_changes, validate_change_proposal
from upgrade.upgrade_plan import ACTION_CAPABILITY, ACTION_FILE
from upgrade.upgrade_policy import (
    STATUS_ALLOWED,
    evaluate_upgrade_policy,
    validate_upgrade_policy_result,
)
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

CHANGE_SET_VERSION = "1"

FIELDS = ("version", "proposal_id", "changes", "execution_allowed")
ACTIONS = (ACTION_FILE, ACTION_CAPABILITY)

ERR_MISSING_CHANGE_SET = "missing_change_set"
ERR_CHANGE_SET_NOT_DICT = "change_set_not_dict"


def _check_actions(errors, changes):
    for index, change in enumerate(changes):
        if (type(change) is dict and type(change.get("action")) is str
                and _is_text(change["action"], MAX_ID_LENGTH) and change["action"] not in ACTIONS):
            _add(errors, "unsupported_change_action", "changes[%d].action" % index)


def _change_set_errors(change_set):
    errors = []
    if type(change_set) is not dict:
        _add(errors, ERR_MISSING_CHANGE_SET if change_set is None else ERR_CHANGE_SET_NOT_DICT,
             "change_set")
        return errors
    if len(change_set) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "change_set")
        return errors
    for key in change_set:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in change_set:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = change_set[field]
        if field == "version":
            if type(value) is not str or value != CHANGE_SET_VERSION:
                _add(errors, "invalid_version", field)
        elif field == "proposal_id":
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_proposal_id", field)
        elif field == "changes":
            _check_changes(errors, value)
            if type(value) is list and len(value) <= MAX_CHANGES:
                _check_actions(errors, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_change_set(change_set=None):
    """Validation result for a normalized change set; nothing is repaired."""
    try:
        return _validation(_change_set_errors(change_set))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "change_set"}])


def _failure(errors):
    return {"valid": False, "errors": errors, "change_set": None,
            "execution_allowed": False, "executed": False}


def _gate_errors(errors, change_proposal, policy_result):
    proposal_ok = validate_change_proposal(change_proposal)["valid"]
    policy_ok = validate_upgrade_policy_result(policy_result)["valid"]
    if not proposal_ok:
        _add(errors, "invalid_change_proposal", "change_proposal")
    if not policy_ok:
        _add(errors, "invalid_policy_result", "policy_result")
    if errors:
        return
    if policy_result["status"] != STATUS_ALLOWED or policy_result["allowed"] is not True:
        _add(errors, "policy_not_allowed", "policy_result")
    elif (policy_result["proposal_id"] != change_proposal["plan_id"]
          or policy_result != evaluate_upgrade_policy(change_proposal)):
        _add(errors, "policy_proposal_mismatch", "policy_result")


def build_change_set(change_proposal=None, policy_result=None):
    """Build a fresh declarative change set, or report why it is impossible."""
    try:
        errors = []
        _gate_errors(errors, change_proposal, policy_result)
        if errors:
            return _failure(errors)
        change_set = {"version": CHANGE_SET_VERSION, "proposal_id": change_proposal["plan_id"],
                      "changes": [dict(change) for change in change_proposal["changes"]],
                      "execution_allowed": False}
        problems = _change_set_errors(change_set)
        if problems:
            return _failure(problems)
        return {"valid": True, "errors": [], "change_set": change_set,
                "execution_allowed": False, "executed": False}
    except Exception:
        return _failure([{"code": ERR_INTERNAL, "where": "change_set"}])
