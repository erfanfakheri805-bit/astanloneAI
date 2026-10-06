"""
Upgrade Plan Contract (Prompt 851, Section 14 - Self-Upgrade Engine)
===================================================================
A small, deterministic, DECLARATIVE plan describing WHAT would have to change
for a requested upgrade, built only from an already validated upgrade request
(Prompt 849) and an already validated project state (Prompt 850). It generates
no source code and no patch, reads and writes no file, runs no test or
command, modifies no capability, performs no upgrade and is not connected to
Core, Memory, AEL, the Capability System, LLMs or any external service.
Nothing is invented, inferred, trimmed, coerced or repaired: invalid or
insufficient input is an error, never a guess.

  build_upgrade_plan(upgrade_request, project_state) -> build result
  validate_upgrade_plan(plan)                        -> validation result

Normalized plan (exactly these eight keys):

  {"version", "request_id", "goal", "steps", "affected_files",
   "affected_capabilities", "constraints", "execution_allowed"}

  version                 exactly the string "1"
  request_id, goal        text, <= MAX_ID_LENGTH / MAX_GOAL_LENGTH
  steps                   non-empty list, <= MAX_STEPS exact dicts with exactly
                          step_id (<= 64), action (<= 64), target (<= 200),
                          reason (<= 200), all text; step_ids are unique
  affected_files          list, <= MAX_AFFECTED items, unique text <= 200
  affected_capabilities   list, <= MAX_AFFECTED items, unique text <= 64
  constraints             list, <= MAX_ITEMS items, text <= 200
  execution_allowed       exactly the bool False

  "text" is the Prompt 849 convention (reused): exact `str`, non-empty, no
  outer whitespace, no control characters, bounded. Containers are the exact
  built-in `dict` / `list`.

build_upgrade_plan(upgrade_request, project_state)
  Both inputs must already pass validate_upgrade_request /
  validate_project_state (i.e. be normalized); nothing is repaired. Planning
  rule (the only one): each item of the request's `scope` is a target that
  must be represented in the supplied project state, either as exactly one
  file path or as exactly one capability name. One step is produced per scope
  item, in scope order:
    step_id  "step_<n>" (n = 1, 2, ...)
    action   "modify_file" (target is a project-state file path) or
             "update_capability" (target is a project-state capability)
    target   the scope item, unchanged
    reason   "Listed in scope of request <request_id>"
  affected_files / affected_capabilities list those targets, in step order;
  request_id, goal and constraints are copied from the request unchanged.
  Nothing else is added: no file or capability outside the supplied scope and
  state is ever named. Result (fixed keys, fresh on every call):
    {"valid", "errors", "plan", "execution_allowed", "executed"}
  `plan` is the fresh normalized plan when valid, else None. The plan itself
  carries no "executed" key.

validate_upgrade_plan(plan)
  Structural check of a normalized plan (all eight keys, bounds, types,
  unique step ids and unique affected entries). Result (fixed keys, fresh):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most 16, fixed order. Build codes:
invalid_upgrade_request, invalid_project_state, empty_scope,
empty_project_state, duplicate_scope_target (where "scope[i]"),
unknown_scope_target, ambiguous_scope_target, validation_error.
Validation codes: missing_plan, plan_not_dict, too_many_fields,
unexpected_field, missing_field, invalid_version, invalid_request_id,
invalid_goal, invalid_steps, empty_steps, too_many_items, invalid_item,
invalid_step, too_many_step_fields, unexpected_step_field,
missing_step_field, invalid_step_step_id / _action / _target / _reason
(where "steps[i].field"), duplicate_step_id, invalid_affected_files,
invalid_affected_capabilities, invalid_constraints, duplicate_item,
invalid_execution_allowed.

`execution_allowed` and `executed` are always False in every result: a valid
plan never implies permission to execute anything.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Only the Prompt 849 / 850 modules are imported.
"""

from upgrade.project_state import validate_project_state
from upgrade.upgrade_request import (
    ERR_INTERNAL,
    ERR_INVALID_ITEM,
    ERR_MISSING_FIELD,
    ERR_TOO_MANY_FIELDS,
    ERR_TOO_MANY_ITEMS,
    ERR_UNEXPECTED_FIELD,
    MAX_FIELDS,
    MAX_GOAL_LENGTH,
    MAX_ID_LENGTH,
    MAX_ITEM_LENGTH,
    MAX_ITEMS,
    _add,
    _is_text,
    _where,
    validate_upgrade_request,
)

PLAN_VERSION = "1"

MAX_STEPS = MAX_ITEMS
MAX_AFFECTED = MAX_ITEMS
MAX_PATH_LENGTH = MAX_ITEM_LENGTH

FIELDS = ("version", "request_id", "goal", "steps", "affected_files",
          "affected_capabilities", "constraints", "execution_allowed")
STEP_FIELDS = ("step_id", "action", "target", "reason")
_STEP_LIMITS = {"step_id": MAX_ID_LENGTH, "action": MAX_ID_LENGTH,
                "target": MAX_ITEM_LENGTH, "reason": MAX_ITEM_LENGTH}
_LIST_LIMITS = {"affected_files": (MAX_AFFECTED, MAX_PATH_LENGTH, True),
                "affected_capabilities": (MAX_AFFECTED, MAX_ID_LENGTH, True),
                "constraints": (MAX_ITEMS, MAX_ITEM_LENGTH, False)}

ACTION_FILE = "modify_file"
ACTION_CAPABILITY = "update_capability"

ERR_MISSING_PLAN = "missing_plan"
ERR_PLAN_NOT_DICT = "plan_not_dict"


def _check_step(errors, index, step, seen_ids):
    where = "steps[%d]" % index
    if type(step) is not dict:
        _add(errors, "invalid_step", where)
        return
    if len(step) > MAX_FIELDS:
        _add(errors, "too_many_step_fields", where)
        return
    for key in step:
        if type(key) is not str or key not in STEP_FIELDS:
            _add(errors, "unexpected_step_field", "%s.%s" % (where, _where(key)))
    for field in STEP_FIELDS:
        if field not in step:
            _add(errors, "missing_step_field", "%s.%s" % (where, field))
        elif not _is_text(step[field], _STEP_LIMITS[field]):
            _add(errors, "invalid_step_" + field, "%s.%s" % (where, field))
    step_id = step.get("step_id")
    if _is_text(step_id, MAX_ID_LENGTH):
        if step_id in seen_ids:
            _add(errors, "duplicate_step_id", where + ".step_id")
        seen_ids.add(step_id)


def _check_steps(errors, value):
    if type(value) is not list:
        _add(errors, "invalid_steps", "steps")
    elif len(value) > MAX_STEPS:
        _add(errors, ERR_TOO_MANY_ITEMS, "steps")
    elif not value:
        _add(errors, "empty_steps", "steps")
    else:
        seen = set()
        for index, step in enumerate(value):
            _check_step(errors, index, step, seen)


def _check_list(errors, field, value):
    max_items, max_length, unique = _LIST_LIMITS[field]
    if type(value) is not list:
        _add(errors, "invalid_" + field, field)
    elif len(value) > max_items:
        _add(errors, ERR_TOO_MANY_ITEMS, field)
    else:
        seen = set()
        for index, item in enumerate(value):
            where = "%s[%d]" % (field, index)
            if not _is_text(item, max_length):
                _add(errors, ERR_INVALID_ITEM, where)
            elif unique:
                if item in seen:
                    _add(errors, "duplicate_item", where)
                seen.add(item)


def _plan_errors(plan):
    errors = []
    if type(plan) is not dict:
        _add(errors, ERR_MISSING_PLAN if plan is None else ERR_PLAN_NOT_DICT, "plan")
        return errors
    if len(plan) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "plan")
        return errors
    for key in plan:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in plan:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = plan[field]
        if field == "version":
            if type(value) is not str or value != PLAN_VERSION:
                _add(errors, "invalid_version", field)
        elif field == "request_id":
            if not _is_text(value, MAX_ID_LENGTH):
                _add(errors, "invalid_request_id", field)
        elif field == "goal":
            if not _is_text(value, MAX_GOAL_LENGTH):
                _add(errors, "invalid_goal", field)
        elif field == "steps":
            _check_steps(errors, value)
        elif field in _LIST_LIMITS:
            _check_list(errors, field, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_upgrade_plan(plan=None):
    """Validation result for a normalized upgrade plan."""
    try:
        return _validation(_plan_errors(plan))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "plan"}])


def _plan_steps(errors, scope, project_state):
    """Steps, affected files and capabilities for `scope`, or errors added."""
    files = {d["path"] for d in project_state["files"]}
    capabilities = set(project_state["capabilities"])
    if not scope:
        _add(errors, "empty_scope", "upgrade_request.scope")
        return None
    if not files and not capabilities:
        _add(errors, "empty_project_state", "project_state")
        return None
    steps, affected_files, affected_capabilities, seen = [], [], [], set()
    for index, target in enumerate(scope):
        where = "scope[%d]" % index
        if target in seen:
            _add(errors, "duplicate_scope_target", where)
        seen.add(target)
        is_file, is_capability = target in files, target in capabilities
        if is_file and is_capability:
            _add(errors, "ambiguous_scope_target", where)
        elif not is_file and not is_capability:
            _add(errors, "unknown_scope_target", where)
        else:
            (affected_files if is_file else affected_capabilities).append(target)
            steps.append({"step_id": "step_%d" % (index + 1),
                          "action": ACTION_FILE if is_file else ACTION_CAPABILITY,
                          "target": target, "reason": ""})
    return steps, affected_files, affected_capabilities


def build_upgrade_plan(upgrade_request=None, project_state=None):
    """Build a fresh declarative plan, or report why planning is impossible."""
    try:
        errors, plan = [], None
        if not validate_upgrade_request(upgrade_request)["valid"]:
            _add(errors, "invalid_upgrade_request", "upgrade_request")
        if not validate_project_state(project_state)["valid"]:
            _add(errors, "invalid_project_state", "project_state")
        if not errors:
            planned = _plan_steps(errors, upgrade_request["scope"], project_state)
            if not errors:
                steps, files, capabilities = planned
                reason = "Listed in scope of request " + upgrade_request["request_id"]
                for step in steps:
                    step["reason"] = reason
                plan = {"version": PLAN_VERSION,
                        "request_id": upgrade_request["request_id"],
                        "goal": upgrade_request["goal"], "steps": steps,
                        "affected_files": files, "affected_capabilities": capabilities,
                        "constraints": list(upgrade_request["constraints"]),
                        "execution_allowed": False}
                if _plan_errors(plan):
                    errors, plan = [{"code": ERR_INTERNAL, "where": "plan"}], None
        return {"valid": not errors, "errors": errors, "plan": plan,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "plan"}],
                "plan": None, "execution_allowed": False, "executed": False}
