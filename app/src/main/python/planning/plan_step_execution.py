"""
Controlled Plan Step Execution State (Prompt 689)
===================================================
The smallest deterministic, caller-controlled transition layer for ONE plan step at a time:

    pending -> in_progress      start_plan_step(plan, step_id)
    in_progress -> completed    complete_plan_step(plan, step_id, output)
    in_progress -> failed       fail_plan_step(plan, step_id, reason)

These functions only RECORD state the caller explicitly asks for. They execute nothing, call no tool or
capability, import no engine/handler/os/network module, never run automatically and are not wired into
`process_input()`. `PlanStep`, `PlanManager` and the Prompt 684-688 functions are reused, not changed.

RULES
- start: the plan must pass `validate_plan_step_states`, the step must be in `get_ready_plan_steps` (Prompt 686:
  pending, no output, every dependency completed), and the plan must be authorized. Starting produces NO output.
  Because an `in_progress` step implies execution (Prompt 684), a successful start also sets
  `metadata["executed"] = True`; that is the only plan-level change and it never touches
  `execution_authorized`.
- complete: the step must be `in_progress`; explicit output (not None, not a blank string, JSON-safe) is stored.
- fail: the step must be `in_progress`; an explicit reason/output (same rules) is stored as its output.
- Authorization (`metadata["execution_authorized"]`) is permission only: it never changes a step and never implies
  execution. Only these transitions (step state + recorded output) are evidence of execution.
- Every check runs BEFORE any mutation. A rejected transition returns stable failure codes and leaves the plan,
  its metadata and all steps exactly as they were. Same input state -> same result, every time.
"""

from planning.plan import (Plan, STATUS_COMPLETED, STATUS_FAILED, STATUS_IN_PROGRESS, STATUS_PENDING,
                           ensure_structured_data)
from planning.plan_builder import (_copy_step, _failure, get_ready_plan_steps, validate_plan_step_states)

STATUS_TRANSITION_APPLIED = "applied"
STATUS_TRANSITION_REJECTED = "rejected"

TRANSITION_INVALID_PLAN = "INVALID_PLAN_OBJECT"
TRANSITION_INVALID_STEP_ID = "INVALID_STEP_ID"
TRANSITION_UNKNOWN_STEP = "UNKNOWN_STEP"
TRANSITION_INVALID_PLAN_STATE = "INVALID_PLAN_STATE"
TRANSITION_PLAN_NOT_READY = "PLAN_READINESS_UNDETERMINED"
TRANSITION_STEP_NOT_READY = "STEP_NOT_READY"
TRANSITION_NOT_AUTHORIZED = "EXECUTION_NOT_AUTHORIZED"
TRANSITION_NOT_IN_PROGRESS = "STEP_NOT_IN_PROGRESS"
TRANSITION_MISSING_OUTPUT = "MISSING_EXECUTION_OUTPUT"
TRANSITION_INVALID_OUTPUT = "INVALID_EXECUTION_OUTPUT"


class PlanStepTransitionResult:
    __slots__ = ("status", "step_id", "previous_state", "new_state", "step", "failures")

    def __init__(self, step_id=None):
        self.status = STATUS_TRANSITION_REJECTED
        self.step_id = step_id
        self.previous_state = None
        self.new_state = None        # equals previous_state when rejected (nothing changed)
        self.step = None             # fresh copy of the step as it stands after the call (never the original)
        self.failures = []

    @property
    def ok(self):
        return self.status == STATUS_TRANSITION_APPLIED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "step_id": self.step_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "step": None if self.step is None else self.step.to_dict(),
            "failures": [dict(f) for f in self.failures],
        }


def _reject(result, code, message, **details):
    result.failures = [_failure(code, message, **details)]
    return result


def _locate(plan, step_id):
    """(result, step). On any problem `step` is None and `result` is the rejection. Read-only."""
    result = PlanStepTransitionResult(step_id if isinstance(step_id, str) else None)
    if not isinstance(plan, Plan):
        return _reject(result, TRANSITION_INVALID_PLAN, "Not a Plan; nothing to transition."), None
    if not isinstance(step_id, str) or not step_id.strip():
        return _reject(result, TRANSITION_INVALID_STEP_ID, "The step id must be a non-empty string."), None
    check = validate_plan_step_states(plan)
    if not check.valid:
        return _reject(result, TRANSITION_INVALID_PLAN_STATE,
                       "The plan's step states/flags are inconsistent; no transition applied.",
                       issues=[dict(i) for i in check.issues]), None
    for step in plan.steps:
        if step.step_id == step_id:
            result.previous_state = result.new_state = step.status
            return result, step
    return _reject(result, TRANSITION_UNKNOWN_STEP, f"Unknown step id: {step_id}.", step_id=step_id), None


def _validate_output(value, what):
    """(sanitized_value, None) or (None, (code, message)). Explicit means: not None, not a blank string, and
    JSON-safe structured data (the same check PlanStep.set_output uses)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, (TRANSITION_MISSING_OUTPUT, f"An explicit {what} is required.")
    try:
        return ensure_structured_data(value), None
    except TypeError as exc:
        return None, (TRANSITION_INVALID_OUTPUT, f"The {what} is not safe structured data: {exc}")


def start_plan_step(plan, step_id):
    """pending -> in_progress for a READY step of an AUTHORIZED plan. Produces no output. Never raises."""
    result, step = _locate(plan, step_id)
    if step is None:
        return result
    readiness = get_ready_plan_steps(plan)
    if not readiness.ok:
        return _reject(result, TRANSITION_PLAN_NOT_READY, "Step readiness could not be determined.",
                       issues=[dict(f) for f in readiness.failures])
    if step_id not in readiness.ready_step_ids:
        return _reject(result, TRANSITION_STEP_NOT_READY,
                       f"Step {step_id} is not ready (state {step.status!r}).", step_id=step_id,
                       state=step.status)
    if plan.metadata.get("execution_authorized") is not True:
        return _reject(result, TRANSITION_NOT_AUTHORIZED, "Execution is not authorized for this plan.")
    step.status = STATUS_IN_PROGRESS
    plan.metadata["executed"] = True      # an in_progress step implies execution (Prompt 684 consistency)
    result.status = STATUS_TRANSITION_APPLIED
    result.new_state = STATUS_IN_PROGRESS
    result.step = _copy_step(step)
    return result


def _finish(plan, step_id, value, what, final_state):
    result, step = _locate(plan, step_id)
    if step is None:
        return result
    if step.status != STATUS_IN_PROGRESS:
        return _reject(result, TRANSITION_NOT_IN_PROGRESS,
                       f"Step {step_id} is {step.status!r}; only an in_progress step can move to "
                       f"{final_state!r}.", step_id=step_id, state=step.status)
    output, problem = _validate_output(value, what)
    if problem is not None:
        return _reject(result, problem[0], problem[1], step_id=step_id)
    step.output_data = output
    step.status = final_state
    result.status = STATUS_TRANSITION_APPLIED
    result.new_state = final_state
    result.step = _copy_step(step)
    return result


def complete_plan_step(plan, step_id, output):
    """in_progress -> completed, storing the explicit `output`. Never raises."""
    return _finish(plan, step_id, output, "execution output", STATUS_COMPLETED)


def fail_plan_step(plan, step_id, reason):
    """in_progress -> failed, storing the explicit failure `reason`/output. Never raises."""
    return _finish(plan, step_id, reason, "failure reason/output", STATUS_FAILED)
