"""
Reasoning - plan validation (Prompt 836)
========================================
A small deterministic validator for the plans produced by the Prompt 835
planner (`reasoning.reasoning_plan.build_reasoning_plan`). It only READS
the plan: it never executes, repairs, reorders or guesses anything, and it
returns a fresh, compact result.

  validate_reasoning_plan(plan)

Result (always the same keys, in this order):

  {"version", "valid", "status", "error_count", "errors", "truncated",
   "steps_checked"}

  status   "valid" | "invalid"; `valid` is True only with no error at all
  errors   [{"code", "where"}, ...] in discovery order, no duplicates, at
           most MAX_ERRORS entries (`truncated` is True when more were
           found); `where` is a field name or a path such as
           "steps[2].depends_on[0]"

Checks, in this order (all errors are collected, nothing stops early
except a plan that is not a dict):

  plan fields    plan_not_dict, missing_field, unexpected_field,
                 invalid_version, invalid_status, invalid_request_status,
                 invalid_goal, invalid_steps, invalid_step_count,
                 step_count_mismatch, invalid_truncated,
                 contradictory_truncated, executed_not_false, no_steps,
                 too_many_steps (only the first MAX_STEPS steps and
                 MAX_STEPS dependencies per step are examined)
  each step      malformed_step, missing_step_field, unexpected_step_field,
                 invalid_step_id, duplicate_step_id, invalid_step_kind,
                 unstable_step_id (id must be `kind`, or `kind.ref` for
                 clarify / need), invalid_step_ref, invalid_step_detail,
                 invalid_depends_on, too_many_dependencies,
                 executed_not_false
  dependencies   duplicate_dependency, self_dependency, missing_dependency,
                 forward_dependency (a step may only depend on EARLIER
                 steps), dependency_cycle (one error per cyclic group;
                 self-loops are reported as self_dependency only)
  plan contract  contradictory_status (ready with clarify/need steps, a
                 not-ready plan with consider / address_goal steps,
                 needs_clarification without a clarify step,
                 needs_information with one), contradictory_goal (ready
                 without a known goal), address_goal_missing,
                 address_goal_misplaced (must be exactly one, and last),
                 address_goal_dependencies (must depend on every earlier
                 step), goal_mismatch (address_goal ref / detail must equal
                 the plan goal's intent / source), step_order_violation
                 (consider_reference, consider_slots, consider_relations
                 order), unexpected_dependency (only address_goal may
                 depend on anything)
  failure        validator_error (defensive; should not occur)

Bounded work, JSON-safe, deterministic, never raises, never modifies the
plan. Pure stdlib; no Memory, AEL, Core, NLU change, execution, LLM or
network.
"""

from .reasoning_plan import (
    PLAN_VERSION, MAX_STEPS, STATUS_READY, STATUS_NEEDS_CLARIFICATION,
    STATUS_NEEDS_INFORMATION, KIND_CONSIDER_REFERENCE, KIND_CONSIDER_SLOTS,
    KIND_CONSIDER_RELATIONS, KIND_ADDRESS_GOAL, KIND_CLARIFY, KIND_NEED,
    MISSING_REQUEST_MISSING, MISSING_REQUEST_INVALID,
    _AMBIGUITY_CODES, _MISSING_CODES,
)
from .reasoning_foundation import UNRESOLVED_REFERENCE_UNRESOLVED

VALIDATION_VERSION = 1
MAX_ERRORS = 16

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"

_PLAN_FIELDS = ("version", "status", "request_status", "goal", "steps",
                "step_count", "truncated", "executed")
_STEP_FIELDS = ("id", "kind", "ref", "detail", "depends_on", "executed")
_PLAN_STATUSES = (STATUS_READY, STATUS_NEEDS_CLARIFICATION, STATUS_NEEDS_INFORMATION)
_CONSIDER_ORDER = (KIND_CONSIDER_REFERENCE, KIND_CONSIDER_SLOTS, KIND_CONSIDER_RELATIONS)
_CONSIDER_REFS = {KIND_CONSIDER_REFERENCE: "reference", KIND_CONSIDER_SLOTS: "slots",
                  KIND_CONSIDER_RELATIONS: "relations"}
_KINDS = _CONSIDER_ORDER + (KIND_ADDRESS_GOAL, KIND_CLARIFY, KIND_NEED)
_CLARIFY_REFS = tuple(_AMBIGUITY_CODES)
_NEED_REFS = ((UNRESOLVED_REFERENCE_UNRESOLVED,) + tuple(_MISSING_CODES)
              + (MISSING_REQUEST_MISSING, MISSING_REQUEST_INVALID))


class _Errors:
    def __init__(self):
        self.items = []
        self._seen = set()
        self.total = 0

    def add(self, code, where):
        key = (code, where)
        if key in self._seen:
            return
        self._seen.add(key)
        self.total += 1
        if len(self.items) < MAX_ERRORS:
            self.items.append({"code": code, "where": where})


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _result(errors, steps_checked):
    return {"version": VALIDATION_VERSION, "valid": errors.total == 0,
            "status": STATUS_VALID if errors.total == 0 else STATUS_INVALID,
            "error_count": len(errors.items), "errors": list(errors.items),
            "truncated": errors.total > len(errors.items),
            "steps_checked": steps_checked}


def _check_plan_fields(plan, errs):
    for f in _PLAN_FIELDS:
        if f not in plan:
            errs.add("missing_field", f)
    for f in plan:
        if f not in _PLAN_FIELDS:
            errs.add("unexpected_field", f if isinstance(f, str) else "?")
    if "version" in plan and not (_is_int(plan["version"]) and plan["version"] == PLAN_VERSION):
        errs.add("invalid_version", "version")
    if "status" in plan and plan["status"] not in _PLAN_STATUSES:
        errs.add("invalid_status", "status")
    if "request_status" in plan and not (plan["request_status"] is None
                                         or isinstance(plan["request_status"], str)):
        errs.add("invalid_request_status", "request_status")
    if "goal" in plan:
        g = plan["goal"]
        if not (isinstance(g, dict) and set(g) == {"intent", "source", "state"}
                and (g["intent"] is None or isinstance(g["intent"], str))
                and (g["source"] is None or isinstance(g["source"], str))
                and isinstance(g["state"], str)):
            errs.add("invalid_goal", "goal")
    if "executed" in plan and plan["executed"] is not False:
        errs.add("executed_not_false", "executed")
    if "truncated" in plan and not isinstance(plan["truncated"], bool):
        errs.add("invalid_truncated", "truncated")


def _check_step(step, i, errs):
    path = f"steps[{i}]"
    if not isinstance(step, dict):
        errs.add("malformed_step", path)
        return
    for f in _STEP_FIELDS:
        if f not in step:
            errs.add("missing_step_field", f"{path}.{f}")
    for f in step:
        if f not in _STEP_FIELDS:
            errs.add("unexpected_step_field", f"{path}.{f if isinstance(f, str) else '?'}")
    sid, kind, ref = step.get("id"), step.get("kind"), step.get("ref")
    if "id" in step and not (isinstance(sid, str) and sid):
        errs.add("invalid_step_id", f"{path}.id")
    if "kind" in step and kind not in _KINDS:
        errs.add("invalid_step_kind", f"{path}.kind")
    if "ref" in step and kind in _KINDS:
        if kind in _CONSIDER_REFS:
            ok = ref == _CONSIDER_REFS[kind]
        elif kind == KIND_CLARIFY:
            ok = ref in _CLARIFY_REFS
        elif kind == KIND_NEED:
            ok = ref in _NEED_REFS
        else:
            ok = isinstance(ref, str) and bool(ref)
        if not ok:
            errs.add("invalid_step_ref", f"{path}.ref")
    if isinstance(sid, str) and sid and kind in _KINDS and "ref" in step:
        expected = f"{kind}.{ref}" if kind in (KIND_CLARIFY, KIND_NEED) else kind
        if sid != expected:
            errs.add("unstable_step_id", f"{path}.id")
    if "detail" in step and not (step["detail"] is None or isinstance(step["detail"], str)
                                 or _is_int(step["detail"])):
        errs.add("invalid_step_detail", f"{path}.detail")
    deps = step.get("depends_on")
    if "depends_on" in step:
        if not (isinstance(deps, list) and all(isinstance(d, str) for d in deps[:MAX_STEPS])):
            errs.add("invalid_depends_on", f"{path}.depends_on")
        elif len(deps) > MAX_STEPS:
            errs.add("too_many_dependencies", f"{path}.depends_on")
    if "executed" in step and step["executed"] is not False:
        errs.add("executed_not_false", f"{path}.executed")


def _check_dependencies(steps, errs):
    """Returns the cycle-graph edges {index: [index, ...]} (self-loops excluded)."""
    first = {}
    for i, s in enumerate(steps):
        sid = s.get("id") if isinstance(s, dict) else None
        if isinstance(sid, str) and sid:
            if sid in first:
                errs.add("duplicate_step_id", f"steps[{i}].id")
            else:
                first[sid] = i
    edges = {}
    for i, s in enumerate(steps):
        deps = s.get("depends_on") if isinstance(s, dict) else None
        if not isinstance(deps, list):
            continue
        sid = s.get("id")
        seen = set()
        for j, d in enumerate(deps[:MAX_STEPS]):
            where = f"steps[{i}].depends_on[{j}]"
            if not isinstance(d, str):
                continue
            if d in seen:
                errs.add("duplicate_dependency", where)
                continue
            seen.add(d)
            if d == sid:
                errs.add("self_dependency", where)
            elif d not in first:
                errs.add("missing_dependency", where)
            else:
                if first[d] > i:
                    errs.add("forward_dependency", where)
                edges.setdefault(i, []).append(first[d])
    return edges


def _reach(start, edges):
    seen, stack = set(), list(edges.get(start, ()))
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(edges.get(n, ()))
    return seen


def _check_cycles(steps, edges, errs):
    reach = {i: _reach(i, edges) for i in range(len(steps))}
    done = set()
    for i in range(len(steps)):
        if i in done or i not in reach[i]:
            continue
        group = {k for k in reach[i] if i in reach[k]} | {i}
        done |= group
        errs.add("dependency_cycle", f"steps[{i}]")


def _check_contract(plan, steps, errs):
    kinds = [s.get("kind") for s in steps if isinstance(s, dict)]
    status = plan.get("status")
    has_block = any(k in (KIND_CLARIFY, KIND_NEED) for k in kinds)
    has_work = any(k in _CONSIDER_ORDER or k == KIND_ADDRESS_GOAL for k in kinds)
    if status == STATUS_READY:
        if has_block:
            errs.add("contradictory_status", "status")
        g = plan.get("goal")
        if isinstance(g, dict) and not (g.get("state") == "known" and isinstance(g.get("intent"), str)
                                        and g["intent"] not in ("", "unknown")):
            errs.add("contradictory_goal", "goal")
    elif status in _PLAN_STATUSES:
        if has_work:
            errs.add("contradictory_status", "status")
        if (status == STATUS_NEEDS_CLARIFICATION) != (KIND_CLARIFY in kinds):
            errs.add("contradictory_status", "status")

    goal_idx = [i for i, s in enumerate(steps)
                if isinstance(s, dict) and s.get("kind") == KIND_ADDRESS_GOAL]
    if status == STATUS_READY and not goal_idx:
        errs.add("address_goal_missing", "steps")
    if goal_idx and (len(goal_idx) != 1 or goal_idx[0] != len(steps) - 1):
        errs.add("address_goal_misplaced", f"steps[{goal_idx[-1]}]")
    if len(goal_idx) == 1:
        i = goal_idx[0]
        s = steps[i]
        earlier = [e.get("id") for e in steps[:i] if isinstance(e, dict)]
        if isinstance(s.get("depends_on"), list) and s["depends_on"] != earlier:
            errs.add("address_goal_dependencies", f"steps[{i}].depends_on")
        g = plan.get("goal")
        if isinstance(g, dict) and (s.get("ref") != g.get("intent")
                                    or s.get("detail") != g.get("source")):
            errs.add("goal_mismatch", f"steps[{i}]")

    order = [(i, _CONSIDER_ORDER.index(s["kind"])) for i, s in enumerate(steps)
             if isinstance(s, dict) and s.get("kind") in _CONSIDER_ORDER]
    for (_a, ra), (b, rb) in zip(order, order[1:]):
        if rb <= ra:
            errs.add("step_order_violation", f"steps[{b}]")
    for i, s in enumerate(steps):
        if (isinstance(s, dict) and s.get("kind") in _KINDS and s.get("kind") != KIND_ADDRESS_GOAL
                and isinstance(s.get("depends_on"), list) and s["depends_on"]):
            errs.add("unexpected_dependency", f"steps[{i}].depends_on")


def validate_reasoning_plan(plan):
    """Validate `plan` (see module docstring). Never raises, never modifies."""
    errs = _Errors()
    checked = 0
    try:
        if not isinstance(plan, dict):
            errs.add("plan_not_dict", "plan")
            return _result(errs, 0)
        _check_plan_fields(plan, errs)
        steps = plan.get("steps")
        if "steps" in plan and not isinstance(steps, list):
            errs.add("invalid_steps", "steps")
            steps = None
        if steps is not None:
            if not steps:
                errs.add("no_steps", "steps")
            if len(steps) > MAX_STEPS:
                errs.add("too_many_steps", "steps")
            if "step_count" in plan:
                if not _is_int(plan["step_count"]):
                    errs.add("invalid_step_count", "step_count")
                elif plan["step_count"] != len(steps):
                    errs.add("step_count_mismatch", "step_count")
            if plan.get("truncated") is True and len(steps) != MAX_STEPS:
                errs.add("contradictory_truncated", "truncated")
            steps = steps[:MAX_STEPS]
            checked = len(steps)
            for i, s in enumerate(steps):
                _check_step(s, i, errs)
            edges = _check_dependencies(steps, errs)
            _check_cycles(steps, edges, errs)
            _check_contract(plan, steps, errs)
        elif "step_count" in plan and not _is_int(plan["step_count"]):
            errs.add("invalid_step_count", "step_count")
        return _result(errs, checked)
    except Exception:  # pragma: no cover - defensive: the validator is optional
        errs = _Errors()
        errs.add("validator_error", "plan")
        return _result(errs, 0)
