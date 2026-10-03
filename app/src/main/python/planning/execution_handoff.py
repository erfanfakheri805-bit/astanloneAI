"""
Inert Execution Handoff (Prompt 680)
======================================
A plain, JSON-shaped RECORD describing what a FUTURE executor would be handed for a validated plan:

    Plan + PlanValidationResult (+ RequestContext gaps) -> prepare_execution_handoff() -> ExecutionHandoff

EXECUTION BOUNDARY: this module executes nothing. It imports no execution/engine/handler code, no
subprocess/os/socket/network module, holds no callables, has no run/execute method, never changes a plan
or step status, never touches a capability registry, and its handoff is always `executed=False`,
`inert=True`, `execution_authorized=False`. A handoff is a snapshot (steps are copied as plain data), so
mutating the plan afterwards never alters it. An invalid, ineligible or gap-blocked plan yields a
`rejected` handoff carrying the reasons - never a silently repaired one. Actually running anything
requires a future, explicitly approved executor, which is out of scope here.
"""

from planning.plan import Plan, ensure_structured_data

STATUS_READY_FOR_EXECUTOR = "ready_for_executor"
STATUS_REJECTED = "rejected"

BOUNDARY_NOTICE = (
    "Inert handoff record only. Nothing has been executed and nothing here is authorized to execute; "
    "a future executor must validate and explicitly approve before running any step."
)


class ExecutionHandoff:
    __slots__ = ("handoff_id", "plan_id", "goal_id", "goal", "status", "steps", "required_capabilities",
                 "rejection_reasons", "blocking_gaps", "executed", "inert", "execution_authorized",
                 "boundary")

    def __init__(self, handoff_id, plan_id, goal_id, goal):
        self.handoff_id = handoff_id
        self.plan_id = plan_id
        self.goal_id = goal_id
        self.goal = goal
        self.status = STATUS_REJECTED
        self.steps = []
        self.required_capabilities = []
        self.rejection_reasons = []
        self.blocking_gaps = []
        self.executed = False
        self.inert = True
        self.execution_authorized = False
        self.boundary = BOUNDARY_NOTICE

    @property
    def ready(self):
        return self.status == STATUS_READY_FOR_EXECUTOR

    def to_dict(self):
        return ensure_structured_data({
            "handoff_id": self.handoff_id,
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "goal": self.goal,
            "status": self.status,
            "steps": self.steps,
            "required_capabilities": self.required_capabilities,
            "rejection_reasons": self.rejection_reasons,
            "blocking_gaps": self.blocking_gaps,
            "executed": self.executed,
            "inert": self.inert,
            "execution_authorized": self.execution_authorized,
            "boundary": self.boundary,
        })


def prepare_execution_handoff(plan, validation, request_context=None, goal=None):
    """Build the inert handoff record for `plan`. `validation` must be the PlanValidationResult for THIS
    plan; `request_context` (optional RequestContext) contributes its blocking information gaps; `goal`
    (optional text) overrides the goal text carried on the record. Never raises for a Plan; never executes."""
    plan_id = getattr(plan, "plan_id", None)
    handoff = ExecutionHandoff(f"handoff-{plan_id}", plan_id, getattr(plan, "goal_id", None), goal)
    if request_context is not None and handoff.goal is None:
        handoff.goal = getattr(request_context, "goal", None)

    if not isinstance(plan, Plan):
        handoff.rejection_reasons.append("INVALID_PLAN_OBJECT")
        return handoff
    if validation is None or getattr(validation, "plan_id", None) != plan_id:
        handoff.rejection_reasons.append("VALIDATION_MISSING_OR_FOR_ANOTHER_PLAN")
    else:
        if not validation.valid:
            handoff.rejection_reasons.extend(validation.codes())
        elif not validation.execution_eligible:
            handoff.rejection_reasons.append("NOT_EXECUTION_ELIGIBLE")
    if request_context is not None:
        for gap in request_context.information_gaps:
            if gap.get("blocking"):
                handoff.blocking_gaps.append({"code": gap["code"], "message": gap["message"]})
        if handoff.blocking_gaps:
            handoff.rejection_reasons.append("BLOCKING_INFORMATION_GAPS")
    if handoff.rejection_reasons:
        return handoff

    by_id = {s.step_id: s for s in plan.steps}
    for sid in validation.ordered_step_ids:
        s = by_id[sid]
        handoff.steps.append({
            "step_id": s.step_id, "description": s.description,
            "dependencies": list(s.dependencies),
            "required_capabilities": list(s.required_capabilities),
            "expected_output": s.expected_output,
            "input_data": s.input_data,
        })
        for cap in s.required_capabilities:
            if cap not in handoff.required_capabilities:
                handoff.required_capabilities.append(cap)
    handoff.status = STATUS_READY_FOR_EXECUTOR
    return handoff
