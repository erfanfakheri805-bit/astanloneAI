"""
Plan Validation (Prompt 680)
==============================
Deterministic, read-only structural validation of an EXISTING `Plan` (planning/plan.py):

    Plan -> validate_plan() -> PlanValidationResult(valid, issues, execution_eligible, ordered_step_ids)

Checks: empty goal, empty plan, duplicate step ids, invalid dependencies (unknown id, self-dependency,
non-list), dependency cycles, unknown capabilities (not registered at all), missing capabilities
(registered but disabled), and impossible execution eligibility (a caller claiming eligibility for a plan
that cannot be eligible). Invalid plans are REPORTED, never repaired: the plan is never modified, no step
status is touched, nothing is registered/enabled and nothing is executed.

Capability semantics match `PlanManager.check_plan_capabilities`: a capability is available only when it
is registered AND enabled in the (read-only) `capability_system.all()` lookup. Without a capability_system
the capability checks are skipped; a plan that requires capabilities is then structurally valid but NOT
execution-eligible (`CAPABILITIES_UNCHECKED` warning) - eligibility is never assumed.
"""

from planning.plan import Plan

EMPTY_GOAL = "EMPTY_GOAL"
INVALID_PLAN_OBJECT = "INVALID_PLAN_OBJECT"
EMPTY_PLAN = "EMPTY_PLAN"
INVALID_STEP_ID = "INVALID_STEP_ID"
EMPTY_STEP_DESCRIPTION = "EMPTY_STEP_DESCRIPTION"
DUPLICATE_STEP_ID = "DUPLICATE_STEP_ID"
INVALID_DEPENDENCY = "INVALID_DEPENDENCY"
DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
MISSING_CAPABILITY = "MISSING_CAPABILITY"
IMPOSSIBLE_EXECUTION_ELIGIBILITY = "IMPOSSIBLE_EXECUTION_ELIGIBILITY"
CAPABILITIES_UNCHECKED = "CAPABILITIES_UNCHECKED"  # warning only


def _issue(code, message, **details):
    item = {"code": code, "message": message}
    item.update(details)
    return item


class PlanValidationResult:
    __slots__ = ("plan_id", "valid", "issues", "warnings", "capabilities_checked",
                 "execution_eligible", "ordered_step_ids")

    def __init__(self, plan_id):
        self.plan_id = plan_id
        self.valid = False
        self.issues = []
        self.warnings = []
        self.capabilities_checked = False
        self.execution_eligible = False
        self.ordered_step_ids = []

    def codes(self):
        return [i["code"] for i in self.issues]

    def has(self, code):
        return code in self.codes()

    def to_dict(self):
        return {
            "plan_id": self.plan_id,
            "valid": self.valid,
            "issues": [dict(i) for i in self.issues],
            "warnings": [dict(w) for w in self.warnings],
            "capabilities_checked": self.capabilities_checked,
            "execution_eligible": self.execution_eligible,
            "ordered_step_ids": list(self.ordered_step_ids),
        }


def _goal_text(goal):
    if goal is None:
        return None
    if isinstance(goal, str):
        return goal
    return getattr(goal, "normalized_text", None) or getattr(goal, "original_text", None) or ""


def _find_cycle(step_ids, deps_by_id):
    """Deterministic cycle search over known-step edges (step -> its dependencies). Returns one cycle as
    a list of step ids (first-found in step order, closing id repeated at the end) or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {sid: WHITE for sid in step_ids}
    for root in step_ids:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(deps_by_id.get(root, ())))]
        path = [root]
        color[root] = GREY
        while stack:
            node, it = stack[-1]
            advanced = False
            for dep in it:
                if dep not in color:
                    continue
                if color[dep] == GREY:
                    return path[path.index(dep):] + [dep]
                if color[dep] == WHITE:
                    color[dep] = GREY
                    path.append(dep)
                    stack.append((dep, iter(deps_by_id.get(dep, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return None


def _topological_order(step_ids, deps_by_id):
    """Kahn ordering, ties broken by original step order (deterministic). Assumes acyclic."""
    remaining = {sid: set(d for d in deps_by_id.get(sid, ()) if d in deps_by_id) for sid in step_ids}
    order = []
    while remaining:
        ready = [sid for sid in step_ids if sid in remaining and not remaining[sid]]
        if not ready:
            break
        nxt = ready[0]
        order.append(nxt)
        del remaining[nxt]
        for deps in remaining.values():
            deps.discard(nxt)
    return order


def validate_plan(plan, goal=None, capability_system=None, claimed_execution_eligible=None):
    """Validate `plan` (a planning.plan.Plan). `goal` may be a Goal, a goal string, or None (then only
    `plan.goal_id` is checked for being non-empty). `capability_system` is anything exposing `.all()` rows
    with `name`/`enabled` (the project's CapabilitySystem); `claimed_execution_eligible=True` asks
    "is a claim of execution eligibility possible for this plan?". Never raises for any input, never
    mutates anything."""
    if not isinstance(plan, Plan):
        res = PlanValidationResult(None)
        res.issues.append(_issue(INVALID_PLAN_OBJECT, "Not a Plan; nothing to validate."))
        return res

    res = PlanValidationResult(plan.plan_id)
    issues = res.issues

    # --- goal --------------------------------------------------------------------------------------
    text = _goal_text(goal)
    if text is not None:
        if not str(text).strip():
            issues.append(_issue(EMPTY_GOAL, "The goal is empty."))
    elif not isinstance(plan.goal_id, str) or not plan.goal_id.strip():
        issues.append(_issue(EMPTY_GOAL, "The plan has no goal."))

    # --- steps ---------------------------------------------------------------------------------------
    if not plan.steps:
        issues.append(_issue(EMPTY_PLAN, "The plan has no steps."))

    seen, dupes, ids_in_order = set(), set(), []
    for idx, step in enumerate(plan.steps):
        sid = getattr(step, "step_id", None)
        if not isinstance(sid, str) or not sid.strip():
            issues.append(_issue(INVALID_STEP_ID, "A step has an empty or non-string id.", index=idx))
            continue
        if sid in seen:
            if sid not in dupes:
                dupes.add(sid)
                issues.append(_issue(DUPLICATE_STEP_ID, f"Duplicate step id: {sid}.", step_id=sid))
        else:
            seen.add(sid)
            ids_in_order.append(sid)
        desc = getattr(step, "description", None)
        if not isinstance(desc, str) or not desc.strip():
            issues.append(_issue(EMPTY_STEP_DESCRIPTION, f"Step {sid} has no description.", step_id=sid))

    # --- dependencies ---------------------------------------------------------------------------------
    deps_by_id = {}
    for step in plan.steps:
        sid = getattr(step, "step_id", None)
        if sid not in seen or sid in deps_by_id:
            continue
        deps = step.dependencies if isinstance(step.dependencies, list) else None
        if deps is None:
            issues.append(_issue(INVALID_DEPENDENCY, f"Step {sid} dependencies are not a list.", step_id=sid))
            deps_by_id[sid] = []
            continue
        clean = []
        for dep in deps:
            if dep == sid:
                issues.append(_issue(INVALID_DEPENDENCY, f"Step {sid} depends on itself.",
                                     step_id=sid, dependency=dep))
            elif dep not in seen:
                issues.append(_issue(INVALID_DEPENDENCY, f"Step {sid} depends on unknown step {dep!r}.",
                                     step_id=sid, dependency=dep))
            else:
                clean.append(dep)
        deps_by_id[sid] = clean

    cycle = _find_cycle(ids_in_order, deps_by_id)
    if cycle:
        issues.append(_issue(DEPENDENCY_CYCLE, "Dependency cycle: " + " -> ".join(cycle) + ".", cycle=cycle))
    elif ids_in_order and not dupes:
        res.ordered_step_ids = _topological_order(ids_in_order, deps_by_id)

    # --- capabilities ---------------------------------------------------------------------------------
    required = []
    for step in plan.steps:
        for cap in step.required_capabilities:
            if cap not in required:
                required.append(cap)
    if capability_system is not None:
        res.capabilities_checked = True
        registered = {row["name"]: row for row in capability_system.all()}
        for step in plan.steps:
            for cap in step.required_capabilities:
                row = registered.get(cap) if isinstance(cap, str) else None
                if row is None:
                    issues.append(_issue(UNKNOWN_CAPABILITY,
                                         f"Step {step.step_id} requires unknown capability {cap!r}.",
                                         step_id=step.step_id, capability=cap))
                elif not bool(row["enabled"]):
                    issues.append(_issue(MISSING_CAPABILITY,
                                         f"Step {step.step_id} requires capability {cap!r}, which is not enabled.",
                                         step_id=step.step_id, capability=cap))
    elif required:
        res.warnings.append(_issue(CAPABILITIES_UNCHECKED,
                                   "Required capabilities were not checked (no capability system given)."))

    # --- eligibility ------------------------------------------------------------------------------------
    res.valid = not issues
    res.execution_eligible = res.valid and (res.capabilities_checked or not required)
    if claimed_execution_eligible and not res.execution_eligible:
        issues.append(_issue(IMPOSSIBLE_EXECUTION_ELIGIBILITY,
                             "Execution eligibility was claimed for a plan that cannot be eligible."))
        res.valid = False
        res.execution_eligible = False
    if not res.valid:
        res.ordered_step_ids = []
    return res
