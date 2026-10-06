"""
Upgrade Sandbox Workspace (Prompt 857, Section 14 - Self-Upgrade Engine)
========================================================================
A small, deterministic, purely IN-MEMORY virtual workspace for the future
self-upgrade pipeline. It never touches the real project: no filesystem
scanning, file read or write, subprocess, code or patch execution, import of
project code, Core / Memory / AEL access, external API or network. A change set
carries no source or patch content, so applying one only records deterministic
sandbox metadata; no source code or implementation is ever invented, and no
rollback or execution exists here.

  build_sandbox_workspace(project_state)                -> build result
  validate_sandbox_workspace(workspace)                 -> validation result
  apply_change_set_to_sandbox(workspace, change_set)    -> apply result

Workspace (exactly these five keys, fixed order):

  {"version", "project_state", "applied", "execution_allowed", "executed"}

  version            exactly the string "1"
  project_state      a fresh normalized Prompt 850 project state (the declared
                     files with their path / kind / status metadata and the
                     declared capabilities); checked with validate_project_state
  applied            list, <= MAX_APPLIED records, one per applied change set:
                     {"proposal_id": text <= 64, "changes": the change set's
                     changes, unchanged, same order}; proposal ids are unique,
                     change rules are the Prompt 855 rules (reused checkers),
                     and every change must target a declared file
                     (modify_file) or capability (update_capability)
  execution_allowed  exactly the bool False
  executed           exactly the bool False

build_sandbox_workspace(project_state)
  Accepts only a project state that passes validate_project_state (Prompt 850,
  reused); `applied` starts empty. Result (fixed keys, fresh):
    {"valid", "errors", "workspace", "execution_allowed", "executed"}
  Error: invalid_project_state.

validate_sandbox_workspace(workspace)
  Structural and referential check; nothing is repaired. Result (fixed keys):
    {"valid", "errors", "execution_allowed", "executed"}

apply_change_set_to_sandbox(workspace, change_set)
  Accepts only a valid workspace and a change set that passes
  validate_change_set (Prompt 855, reused). Every change must target a declared
  file (modify_file) or capability (update_capability) of the workspace; the
  change set must not already be applied (same proposal_id) and must not repeat
  an (action, target) pair. All of it is checked before anything is recorded
  (all-or-nothing). On success the result holds a NEW workspace with one more
  `applied` record; inputs are never modified. Result (fixed keys, fresh):
    {"status", "applied", "changes", "workspace", "errors",
     "execution_allowed", "executed"}
  status "applied" (applied True, changes = the recorded changes, workspace the
  new one) or "rejected" (applied False, changes [], workspace None, errors).

errors: [{"code", "where"}], at most 16, fixed order. Codes: invalid_project_state,
invalid_workspace, invalid_change_set, unknown_target (where "changes[i].target"),
duplicate_change (where "changes[i]"), change_set_already_applied,
too_many_applied, plus workspace validation codes: missing_workspace,
workspace_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_applied, too_many_items, invalid_applied_record,
invalid_applied_field, invalid_proposal_id, duplicate_proposal_id, the Prompt 855
change codes (where prefixed "applied[i]."), unsupported_change_action,
unknown_target, invalid_execution_allowed, invalid_executed, validation_error.

`execution_allowed` and `executed` are always False in every result: a
sandbox state never implies that anything was run or may be run.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 850 / 852 / 855 modules and copy
(pure computation, no I/O).
"""

import copy

from upgrade.change_proposal import MAX_CHANGES, _check_changes
from upgrade.change_set import _check_actions, validate_change_set
from upgrade.project_state import validate_project_state
from upgrade.upgrade_plan import ACTION_CAPABILITY, ACTION_FILE
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

WORKSPACE_VERSION = "1"
MAX_APPLIED = 16

FIELDS = ("version", "project_state", "applied", "execution_allowed", "executed")
RECORD_FIELDS = ("proposal_id", "changes")

STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"

ERR_MISSING_WORKSPACE = "missing_workspace"
ERR_WORKSPACE_NOT_DICT = "workspace_not_dict"


def _known_targets(project_state):
    return {ACTION_FILE: {d["path"] for d in project_state["files"]},
            ACTION_CAPABILITY: set(project_state["capabilities"])}


def _unknown_targets(errors, changes, known, prefix=""):
    for index, change in enumerate(changes):
        if (type(change) is dict and change.get("action") in known
                and change.get("target") not in known[change["action"]]):
            _add(errors, "unknown_target", "%schanges[%d].target" % (prefix, index))


def _check_record(errors, index, record, seen_ids, known):
    where = "applied[%d]" % index
    if type(record) is not dict:
        _add(errors, "invalid_applied_record", where)
        return
    if len(record) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, where)
        return
    for key in record:
        if type(key) is not str or key not in RECORD_FIELDS:
            _add(errors, "invalid_applied_field", "%s.%s" % (where, _where(key)))
    for field in RECORD_FIELDS:
        if field not in record:
            _add(errors, ERR_MISSING_FIELD, "%s.%s" % (where, field))
    proposal_id = record.get("proposal_id")
    if "proposal_id" in record:
        if not _is_text(proposal_id, MAX_ID_LENGTH):
            _add(errors, "invalid_proposal_id", where + ".proposal_id")
        elif proposal_id in seen_ids:
            _add(errors, "duplicate_proposal_id", where + ".proposal_id")
        else:
            seen_ids.add(proposal_id)
    if "changes" in record:
        inner = []
        _check_changes(inner, record["changes"])
        if type(record["changes"]) is list and len(record["changes"]) <= MAX_CHANGES:
            _check_actions(inner, record["changes"])
            _unknown_targets(inner, record["changes"], known)
        for item in inner:
            _add(errors, item["code"], "%s.%s" % (where, item["where"]))


def _workspace_errors(workspace):
    errors = []
    if type(workspace) is not dict:
        _add(errors, ERR_MISSING_WORKSPACE if workspace is None else ERR_WORKSPACE_NOT_DICT,
             "workspace")
        return errors
    if len(workspace) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "workspace")
        return errors
    for key in workspace:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in workspace:
            _add(errors, ERR_MISSING_FIELD, field)
    if errors:
        return errors
    if type(workspace["version"]) is not str or workspace["version"] != WORKSPACE_VERSION:
        _add(errors, "invalid_version", "version")
    state_ok = validate_project_state(workspace["project_state"])["valid"]
    if not state_ok:
        _add(errors, "invalid_project_state", "project_state")
    applied = workspace["applied"]
    if type(applied) is not list:
        _add(errors, "invalid_applied", "applied")
    elif len(applied) > MAX_APPLIED:
        _add(errors, "too_many_items", "applied")
    elif state_ok:
        known, seen = _known_targets(workspace["project_state"]), set()
        for index, record in enumerate(applied):
            _check_record(errors, index, record, seen, known)
    for field in ("execution_allowed", "executed"):
        if workspace[field] is not False:
            _add(errors, "invalid_" + field, field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_sandbox_workspace(workspace=None):
    """Validation result for a sandbox workspace; nothing is repaired."""
    try:
        return _validation(_workspace_errors(workspace))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "workspace"}])


def _build_result(errors, workspace=None):
    return {"valid": not errors, "errors": errors, "workspace": None if errors else workspace,
            "execution_allowed": False, "executed": False}


def build_sandbox_workspace(project_state=None):
    """Fresh empty in-memory workspace for a valid project state."""
    try:
        if not validate_project_state(project_state)["valid"]:
            return _build_result([{"code": "invalid_project_state", "where": "project_state"}])
        workspace = {"version": WORKSPACE_VERSION, "project_state": copy.deepcopy(project_state),
                     "applied": [], "execution_allowed": False, "executed": False}
        if _workspace_errors(workspace):
            return _build_result([{"code": ERR_INTERNAL, "where": "workspace"}])
        return _build_result([], workspace)
    except Exception:
        return _build_result([{"code": ERR_INTERNAL, "where": "workspace"}])


def _apply_result(errors, changes=None, workspace=None):
    return {"status": STATUS_REJECTED if errors else STATUS_APPLIED, "applied": not errors,
            "changes": [] if errors else changes, "workspace": None if errors else workspace,
            "errors": errors, "execution_allowed": False, "executed": False}


def _apply_errors(errors, workspace, change_set):
    if not validate_sandbox_workspace(workspace)["valid"]:
        _add(errors, "invalid_workspace", "workspace")
    if not validate_change_set(change_set)["valid"]:
        _add(errors, "invalid_change_set", "change_set")
    if errors:
        return
    if len(workspace["applied"]) >= MAX_APPLIED:
        _add(errors, "too_many_applied", "applied")
    if any(r["proposal_id"] == change_set["proposal_id"] for r in workspace["applied"]):
        _add(errors, "change_set_already_applied", "change_set.proposal_id")
    _unknown_targets(errors, change_set["changes"], _known_targets(workspace["project_state"]))
    seen = set()
    for index, change in enumerate(change_set["changes"]):
        pair = (change["action"], change["target"])
        if pair in seen:
            _add(errors, "duplicate_change", "changes[%d]" % index)
        seen.add(pair)


def apply_change_set_to_sandbox(workspace=None, change_set=None):
    """Record a valid change set in a NEW workspace; inputs are never modified."""
    try:
        errors = []
        _apply_errors(errors, workspace, change_set)
        if errors:
            return _apply_result(errors)
        changes = [dict(change) for change in change_set["changes"]]
        new = copy.deepcopy(workspace)
        new["applied"].append({"proposal_id": change_set["proposal_id"],
                               "changes": [dict(change) for change in changes]})
        if _workspace_errors(new):
            return _apply_result([{"code": ERR_INTERNAL, "where": "workspace"}])
        return _apply_result([], changes, new)
    except Exception:
        return _apply_result([{"code": ERR_INTERNAL, "where": "workspace"}])
