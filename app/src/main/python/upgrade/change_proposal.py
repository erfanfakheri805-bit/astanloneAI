"""
Upgrade Change Proposal (Prompt 852, Section 14 - Self-Upgrade Engine)
======================================================================
A small, deterministic, DECLARATIVE change proposal derived from an already
validated upgrade plan (Prompt 851) and project state (Prompt 850). It
describes the intended changes one-to-one with the plan's steps and nothing
more: it generates no source code, diff or patch, reads and writes no file,
inspects no filesystem, runs no test or command, modifies no capability,
performs no upgrade and is not connected to Core, Memory, AEL, the Capability
System, LLMs or any external service. Nothing is invented, inferred, trimmed,
coerced or repaired: invalid or inconsistent input is an error.

  build_change_proposal(upgrade_plan, project_state) -> build result
  validate_change_proposal(proposal)                 -> validation result

Normalized proposal (exactly these seven keys):

  {"version", "plan_id", "changes", "affected_files", "affected_capabilities",
   "constraints", "execution_allowed"}

  version                 exactly the string "1"
  plan_id                 text <= MAX_ID_LENGTH
  changes                 non-empty list, <= MAX_CHANGES exact dicts with exactly
                          change_id (<= 64), action (<= 64), target (<= 200),
                          reason (<= 200), all text; change_ids are unique
  affected_files          list, <= 16, unique text <= 200   (Prompt 851 rules)
  affected_capabilities   list, <= 16, unique text <= 64    (Prompt 851 rules)
  constraints             list, <= 16, text <= 200          (Prompt 851 rules)
  execution_allowed       exactly the bool False

build_change_proposal(upgrade_plan, project_state)
  Both inputs must already pass validate_upgrade_plan /
  validate_project_state; nothing is repaired. They must also be consistent:
  every step's action must be "modify_file" (target is a project-state file
  path) or "update_capability" (target is a project-state capability), and the
  plan's affected_files / affected_capabilities must be exactly the targets of
  its file / capability steps in step order. Then:
    plan_id   "plan_" + the first 16 hex digits of the SHA-256 of the plan's
              canonical JSON (sorted keys, compact separators, ASCII) - the
              same truncated-SHA-256 convention planning/plan_builder.py uses;
              it depends only on the supplied plan
    changes   one per step, same order: change_id "change_<n>" (n = position
              from 1), action / target / reason copied unchanged
    affected_files, affected_capabilities, constraints  copied unchanged
  No target outside the plan is ever added. Result (fixed keys, fresh):
    {"valid", "errors", "proposal", "execution_allowed", "executed"}
  `proposal` is the fresh normalized proposal when valid, else None. The
  proposal itself carries no "executed" key.

validate_change_proposal(proposal)
  Structural check of a normalized proposal (all seven keys, exact types,
  bounds, exact change keys, unique change ids). Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most 16, fixed order. Build codes:
invalid_upgrade_plan, invalid_project_state, unsupported_step_action,
step_target_not_in_project_state (where "steps[i]"), affected_files_mismatch,
affected_capabilities_mismatch, validation_error. Validation codes:
missing_proposal, proposal_not_dict, too_many_fields, unexpected_field,
missing_field, invalid_version, invalid_plan_id, invalid_changes,
empty_changes, too_many_items, invalid_item, invalid_change,
too_many_change_fields, unexpected_change_field, missing_change_field,
invalid_change_change_id / _action / _target / _reason (where
"changes[i].field"), duplicate_change_id, invalid_affected_files,
invalid_affected_capabilities, invalid_constraints, duplicate_item,
invalid_execution_allowed.

`execution_allowed` and `executed` are always False in every result: a valid
proposal never implies permission to execute anything.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Imports only the Prompt 849 / 850 / 851 modules and hashlib /
json (pure computation, no I/O).
"""

import hashlib
import json

from upgrade.project_state import validate_project_state
from upgrade.upgrade_plan import (
    ACTION_CAPABILITY,
    ACTION_FILE,
    MAX_STEPS,
    _check_list,
    validate_upgrade_plan,
)
from upgrade.upgrade_request import (
    ERR_INTERNAL,
    ERR_MISSING_FIELD,
    ERR_TOO_MANY_FIELDS,
    ERR_TOO_MANY_ITEMS,
    ERR_UNEXPECTED_FIELD,
    MAX_FIELDS,
    MAX_ID_LENGTH,
    MAX_ITEM_LENGTH,
    _add,
    _is_text,
    _where,
)

PROPOSAL_VERSION = "1"

MAX_CHANGES = MAX_STEPS
PLAN_ID_PREFIX = "plan_"
PLAN_ID_DIGITS = 16

FIELDS = ("version", "plan_id", "changes", "affected_files",
          "affected_capabilities", "constraints", "execution_allowed")
CHANGE_FIELDS = ("change_id", "action", "target", "reason")
_CHANGE_LIMITS = {"change_id": MAX_ID_LENGTH, "action": MAX_ID_LENGTH,
                  "target": MAX_ITEM_LENGTH, "reason": MAX_ITEM_LENGTH}
_LIST_FIELDS = ("affected_files", "affected_capabilities", "constraints")

ERR_MISSING_PROPOSAL = "missing_proposal"
ERR_PROPOSAL_NOT_DICT = "proposal_not_dict"


def _check_change(errors, index, change, seen_ids):
    where = "changes[%d]" % index
    if type(change) is not dict:
        _add(errors, "invalid_change", where)
        return
    if len(change) > MAX_FIELDS:
        _add(errors, "too_many_change_fields", where)
        return
    for key in change:
        if type(key) is not str or key not in CHANGE_FIELDS:
            _add(errors, "unexpected_change_field", "%s.%s" % (where, _where(key)))
    for field in CHANGE_FIELDS:
        if field not in change:
            _add(errors, "missing_change_field", "%s.%s" % (where, field))
        elif not _is_text(change[field], _CHANGE_LIMITS[field]):
            _add(errors, "invalid_change_" + field, "%s.%s" % (where, field))
    change_id = change.get("change_id")
    if _is_text(change_id, MAX_ID_LENGTH):
        if change_id in seen_ids:
            _add(errors, "duplicate_change_id", where + ".change_id")
        seen_ids.add(change_id)


def _check_changes(errors, value):
    if type(value) is not list:
        _add(errors, "invalid_changes", "changes")
    elif len(value) > MAX_CHANGES:
        _add(errors, ERR_TOO_MANY_ITEMS, "changes")
    elif not value:
        _add(errors, "empty_changes", "changes")
    else:
        seen = set()
        for index, change in enumerate(value):
            _check_change(errors, index, change, seen)


def _proposal_errors(proposal):
    errors = []
    if type(proposal) is not dict:
        _add(errors, ERR_MISSING_PROPOSAL if proposal is None else ERR_PROPOSAL_NOT_DICT,
             "proposal")
        return errors
    if len(proposal) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "proposal")
        return errors
    for key in proposal:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in proposal:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = proposal[field]
        if field == "version":
            if type(value) is not str or value != PROPOSAL_VERSION:
                _add(errors, "invalid_version", field)
        elif field == "plan_id":
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_plan_id", field)
        elif field == "changes":
            _check_changes(errors, value)
        elif field in _LIST_FIELDS:
            _check_list(errors, field, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_change_proposal(proposal=None):
    """Validation result for a normalized change proposal."""
    try:
        return _validation(_proposal_errors(proposal))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "proposal"}])


def derive_plan_id(upgrade_plan):
    """Deterministic bounded id from a (validated) plan's content only."""
    text = json.dumps(upgrade_plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return PLAN_ID_PREFIX + hashlib.sha256(text.encode("ascii")).hexdigest()[:PLAN_ID_DIGITS]


def _consistency_errors(errors, plan, project_state):
    files = {d["path"] for d in project_state["files"]}
    capabilities = set(project_state["capabilities"])
    plan_files, plan_capabilities = [], []
    for index, step in enumerate(plan["steps"]):
        where = "steps[%d]" % index
        if step["action"] == ACTION_FILE:
            known, bucket = step["target"] in files, plan_files
        elif step["action"] == ACTION_CAPABILITY:
            known, bucket = step["target"] in capabilities, plan_capabilities
        else:
            _add(errors, "unsupported_step_action", where)
            continue
        if not known:
            _add(errors, "step_target_not_in_project_state", where)
        bucket.append(step["target"])
    if plan_files != plan["affected_files"]:
        _add(errors, "affected_files_mismatch", "affected_files")
    if plan_capabilities != plan["affected_capabilities"]:
        _add(errors, "affected_capabilities_mismatch", "affected_capabilities")


def build_change_proposal(upgrade_plan=None, project_state=None):
    """Build a fresh declarative change proposal, or report why it is impossible."""
    try:
        errors, proposal = [], None
        if not validate_upgrade_plan(upgrade_plan)["valid"]:
            _add(errors, "invalid_upgrade_plan", "upgrade_plan")
        if not validate_project_state(project_state)["valid"]:
            _add(errors, "invalid_project_state", "project_state")
        if not errors:
            _consistency_errors(errors, upgrade_plan, project_state)
        if not errors:
            proposal = {
                "version": PROPOSAL_VERSION, "plan_id": derive_plan_id(upgrade_plan),
                "changes": [{"change_id": "change_%d" % (index + 1),
                             "action": step["action"], "target": step["target"],
                             "reason": step["reason"]}
                            for index, step in enumerate(upgrade_plan["steps"])],
                "affected_files": list(upgrade_plan["affected_files"]),
                "affected_capabilities": list(upgrade_plan["affected_capabilities"]),
                "constraints": list(upgrade_plan["constraints"]),
                "execution_allowed": False}
            if _proposal_errors(proposal):
                errors, proposal = [{"code": ERR_INTERNAL, "where": "proposal"}], None
        return {"valid": not errors, "errors": errors, "proposal": proposal,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "proposal"}],
                "proposal": None, "execution_allowed": False, "executed": False}
