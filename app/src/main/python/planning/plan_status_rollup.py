"""
Plan-Level Status Rollup (Prompt 690)
=======================================
One explicit, caller-invoked, read-only function that derives the current plan-level status from the CURRENT step
states of a `Plan`:

    rollup_plan_status(plan) -> PlanStatusRollupResult

It executes, retries, reorders, authorizes and modifies nothing, is not wired into `process_input()`, and imports no
tool/capability/engine/os/network module. `PlanStep`, `PlanManager` and the Prompt 684-689 code are reused, not
changed. The Prompt 687 progress contract stays authoritative: counts, ready ids, blocked ids and the
complete/blocked flags come from `evaluate_plan_progress`; input is validated with `validate_plan_step_states`
(Prompt 684). This module adds only the precedence below.

STATUS VOCABULARY (`ROLLUP_STATUSES`, the plan/step state names already used by `planning.plan`, plus `complete`)
    pending, in_progress, completed, failed, blocked, complete
`complete` is the plan-level terminal success. `completed` is the STEP-level state and is never produced as a plan
status here; it is listed only so the vocabulary matches the existing architecture.

PRECEDENCE (first match wins; derived only from step states, never from authorization / `execution_authorized` /
`executed` / `Plan.status`)
    1. no steps                                   -> pending    (reason EMPTY_PLAN; documented empty-plan result)
    2. every step completed                       -> complete   (reason ALL_STEPS_COMPLETED)
    3. any step failed                            -> failed     (reason STEP_FAILED; `failed_step_ids`, and any
                                                                 pending steps stuck behind it in `blocked_step_ids`)
    4. any step in_progress                       -> in_progress (reason STEP_IN_PROGRESS)
    5. progress says blocked (pending steps and no executable path) -> blocked (reason NO_EXECUTABLE_PATH)
    6. otherwise                                  -> pending    (reason PENDING)
NOTE: under the Prompt 687 contract a pending step can only be stuck behind a FAILED dependency, and rule 3 wins
over rule 5, so `blocked` is a defensive branch that follows the progress contract rather than a state a
consistent plan normally reaches; the stuck steps of a failed plan are still reported in `blocked_step_ids`.

REJECTION: a non-Plan, an inconsistent plan state (Prompt 684), or undeterminable progress (invalid dependencies,
Prompt 686/687) returns `status=None`, `ok=False` and stable failure codes; nothing is guessed or repaired.
Same input state -> identical result, every time. Step ids are always reported in plan order.
"""

from planning.plan import (Plan, STATUS_BLOCKED, STATUS_COMPLETED, STATUS_FAILED, STATUS_IN_PROGRESS,
                           STATUS_PENDING)
from planning.plan_builder import _failure, evaluate_plan_progress, validate_plan_step_states

STATUS_COMPLETE = "complete"

ROLLUP_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED, STATUS_BLOCKED,
                   STATUS_COMPLETE)

REASON_EMPTY_PLAN = "EMPTY_PLAN"
REASON_ALL_COMPLETED = "ALL_STEPS_COMPLETED"
REASON_STEP_FAILED = "STEP_FAILED"
REASON_STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
REASON_NO_EXECUTABLE_PATH = "NO_EXECUTABLE_PATH"
REASON_PENDING = "PENDING"

ROLLUP_INVALID_PLAN = "INVALID_PLAN_OBJECT"
ROLLUP_INVALID_PLAN_STATE = "INVALID_PLAN_STATE"
ROLLUP_PROGRESS_UNDETERMINED = "PLAN_PROGRESS_UNDETERMINED"


class PlanStatusRollupResult:
    __slots__ = ("status", "reason", "total_steps", "pending_count", "in_progress_count", "completed_count",
                 "failed_count", "pending_step_ids", "in_progress_step_ids", "completed_step_ids",
                 "failed_step_ids", "ready_step_ids", "blocked_step_ids", "failures")

    def __init__(self):
        self.status = None           # one of ROLLUP_STATUSES, or None when the input was rejected
        self.reason = None
        self.total_steps = 0
        self.pending_count = 0
        self.in_progress_count = 0
        self.completed_count = 0
        self.failed_count = 0
        self.pending_step_ids = []
        self.in_progress_step_ids = []
        self.completed_step_ids = []
        self.failed_step_ids = []
        self.ready_step_ids = []
        self.blocked_step_ids = []   # pending steps behind a failed dependency (Prompt 687)
        self.failures = []

    @property
    def ok(self):
        return self.status is not None

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "status": self.status,
            "reason": self.reason,
            "total_steps": self.total_steps,
            "pending_count": self.pending_count,
            "in_progress_count": self.in_progress_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "pending_step_ids": list(self.pending_step_ids),
            "in_progress_step_ids": list(self.in_progress_step_ids),
            "completed_step_ids": list(self.completed_step_ids),
            "failed_step_ids": list(self.failed_step_ids),
            "ready_step_ids": list(self.ready_step_ids),
            "blocked_step_ids": list(self.blocked_step_ids),
            "failures": [dict(f) for f in self.failures],
        }


def _reject(result, code, message, **details):
    result.failures = [_failure(code, message, **details)]
    return result


def rollup_plan_status(plan):
    """Derive the plan-level status from current step states (see module docstring). Read-only; never raises."""
    result = PlanStatusRollupResult()
    if not isinstance(plan, Plan):
        return _reject(result, ROLLUP_INVALID_PLAN, "Not a Plan; nothing to roll up.")
    check = validate_plan_step_states(plan)
    if not check.valid:
        return _reject(result, ROLLUP_INVALID_PLAN_STATE,
                       "The plan's step states/flags are inconsistent; no status derived.",
                       issues=[dict(i) for i in check.issues])
    progress = evaluate_plan_progress(plan)
    if not progress.ok:
        return _reject(result, ROLLUP_PROGRESS_UNDETERMINED, "Plan progress could not be determined.",
                       issues=[dict(f) for f in progress.failures])

    by_state = {STATUS_PENDING: result.pending_step_ids, STATUS_IN_PROGRESS: result.in_progress_step_ids,
                STATUS_COMPLETED: result.completed_step_ids, STATUS_FAILED: result.failed_step_ids}
    for step in plan.steps:                      # plan order; states already validated
        by_state[step.status].append(step.step_id)
    result.total_steps = progress.total_steps
    result.pending_count = progress.pending_count
    result.in_progress_count = progress.in_progress_count
    result.completed_count = progress.completed_count
    result.failed_count = progress.failed_count
    result.ready_step_ids = list(progress.ready_step_ids)
    result.blocked_step_ids = list(progress.blocked_step_ids)

    if progress.total_steps == 0:
        result.status, result.reason = STATUS_PENDING, REASON_EMPTY_PLAN
    elif progress.is_complete:
        result.status, result.reason = STATUS_COMPLETE, REASON_ALL_COMPLETED
    elif progress.failed_count:
        result.status, result.reason = STATUS_FAILED, REASON_STEP_FAILED
    elif progress.in_progress_count:
        result.status, result.reason = STATUS_IN_PROGRESS, REASON_STEP_IN_PROGRESS
    elif progress.is_blocked:
        result.status, result.reason = STATUS_BLOCKED, REASON_NO_EXECUTABLE_PATH
    else:
        result.status, result.reason = STATUS_PENDING, REASON_PENDING
    return result
