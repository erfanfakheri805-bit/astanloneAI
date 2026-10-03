"""
Plan Step Execution Report (Prompt 692)
=========================================
A small, read-only reporting layer that pairs ONE `execute_plan_step()` result (Prompt 691) with the CURRENT
plan-level progress (`evaluate_plan_progress`, Prompt 687) and status (`rollup_plan_status`, Prompt 690):

    report_plan_step_execution(plan, execution_result) -> PlanStepExecutionReport

It never executes, retries, recovers, authorizes, reorders or mutates anything, never calls `execute_plan_step()`,
and is not wired into `process_input()`. Readiness, progress, status and execution state are NOT redefined here:
the execution fields are copied from the supplied result, the plan fields come straight from Prompts 687/690.

TWO DISTINCT SECTIONS
    execution : what THIS attempt did (step_id, ok, status, previous/final state, executor_called, output,
                reason, failures)
    plan      : the whole plan AFTER the attempt (status, reason, progress counts, ready/blocked step ids)
A failed step therefore reports `execution.ok == False` next to a `plan.status` of `failed`; a completed step
reports `execution.ok == True` next to whatever the plan status is (`pending`, `complete`, ...).

REJECTION (`ok=False`, `status="rejected"`, stable codes, nothing guessed or reconstructed)
    INVALID_PLAN_OBJECT, INVALID_EXECUTION_RESULT (not a PlanStepExecutionResult), EXECUTION_NOT_REPORTABLE
    (the result was itself a rejection: no step ran), UNKNOWN_STEP, EXECUTION_INCONSISTENT (result disagrees with
    the plan: states, executor_called, output, reason/failures), PLAN_STATE_UNDETERMINED (rollup/progress refused).
Same plan state + same result -> identical report, every time.
"""

import copy

from planning.plan import Plan, STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING
from planning.plan_builder import _failure, evaluate_plan_progress
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_orchestration import (PlanStepExecutionResult, STATUS_EXECUTION_COMPLETED,
                                              STATUS_EXECUTION_FAILED)

REPORT_OK = "reported"
REPORT_REJECTED = "rejected"

REPORT_INVALID_PLAN_OBJECT = "INVALID_PLAN_OBJECT"
REPORT_INVALID_EXECUTION_RESULT = "INVALID_EXECUTION_RESULT"
REPORT_EXECUTION_NOT_REPORTABLE = "EXECUTION_NOT_REPORTABLE"
REPORT_UNKNOWN_STEP = "UNKNOWN_STEP"
REPORT_EXECUTION_INCONSISTENT = "EXECUTION_INCONSISTENT"
REPORT_PLAN_STATE_UNDETERMINED = "PLAN_STATE_UNDETERMINED"


class PlanStepExecutionReport:
    __slots__ = ("status", "step_id", "execution_ok", "execution_status", "previous_state", "final_state",
                 "executor_called", "output", "reason", "execution_failures", "plan_status", "plan_status_reason",
                 "progress", "ready_step_ids", "blocked_step_ids", "failures")

    def __init__(self):
        self.status = REPORT_REJECTED
        # --- this execution attempt (copied from the supplied result) ---
        self.step_id = None
        self.execution_ok = None
        self.execution_status = None
        self.previous_state = None
        self.final_state = None
        self.executor_called = None
        self.output = None
        self.reason = None
        self.execution_failures = []
        # --- the whole plan after the attempt (from Prompts 687 / 690) ---
        self.plan_status = None
        self.plan_status_reason = None
        self.progress = {}
        self.ready_step_ids = []
        self.blocked_step_ids = []
        # --- rejection of the report itself ---
        self.failures = []

    @property
    def ok(self):
        return self.status == REPORT_OK

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "ok": self.ok,
            "status": self.status,
            "execution": {
                "step_id": self.step_id,
                "ok": self.execution_ok,
                "status": self.execution_status,
                "previous_state": self.previous_state,
                "final_state": self.final_state,
                "executor_called": self.executor_called,
                "output": copy.deepcopy(self.output),
                "reason": self.reason,
                "failures": copy.deepcopy(self.execution_failures),
            },
            "plan": {
                "status": self.plan_status,
                "reason": self.plan_status_reason,
                "progress": dict(self.progress),
                "ready_step_ids": list(self.ready_step_ids),
                "blocked_step_ids": list(self.blocked_step_ids),
            },
            "failures": [dict(f) for f in self.failures],
        }


def _reject(report, code, message, **details):
    report.failures = [_failure(code, message, **details)]
    return report


def _inconsistent(report, what, **details):
    return _reject(report, REPORT_EXECUTION_INCONSISTENT,
                   "The execution result is inconsistent with the plan: " + what, **details)


def report_plan_step_execution(plan, execution_result):
    """Summarize one finished `execute_plan_step()` result together with the current plan progress/status.
    Read-only; never raises, never executes anything, never repairs an inconsistent input."""
    report = PlanStepExecutionReport()
    if not isinstance(plan, Plan):
        return _reject(report, REPORT_INVALID_PLAN_OBJECT, "Not a Plan; nothing to report.")
    if not isinstance(execution_result, PlanStepExecutionResult):
        return _reject(report, REPORT_INVALID_EXECUTION_RESULT, "Not a PlanStepExecutionResult.")
    res = execution_result
    if res.status not in (STATUS_EXECUTION_COMPLETED, STATUS_EXECUTION_FAILED):
        return _reject(report, REPORT_EXECUTION_NOT_REPORTABLE,
                       "The execution was rejected before any step ran; there is no executed step to report.",
                       execution_status=res.status)

    step = next((s for s in plan.steps if getattr(s, "step_id", None) == res.step_id), None) \
        if isinstance(plan.steps, list) and isinstance(res.step_id, str) else None
    if step is None:
        return _reject(report, REPORT_UNKNOWN_STEP, "The result's step is not in the plan.", step_id=res.step_id)

    # The result must match the plan's current facts exactly; nothing is reconstructed.
    if res.executor_called is not True:
        return _inconsistent(report, "a completed/failed execution must have called the executor.")
    if res.previous_state != STATUS_PENDING:
        return _inconsistent(report, "the step must have been pending before execution.",
                             previous_state=res.previous_state)
    expected_final = STATUS_COMPLETED if res.status == STATUS_EXECUTION_COMPLETED else STATUS_FAILED
    if res.final_state != expected_final or step.status != expected_final:
        return _inconsistent(report, "final state does not match the result status and the plan's step state.",
                             final_state=res.final_state, plan_step_state=step.status)
    if res.status == STATUS_EXECUTION_COMPLETED:
        if res.failures or res.reason is not None:
            return _inconsistent(report, "a completed execution must carry no reason or failures.")
        if res.output != step.output_data:
            return _inconsistent(report, "the reported output differs from the step's stored output.")
    else:
        if not res.failures or res.reason != res.failures[0].get("code"):
            return _inconsistent(report, "a failed execution must carry failures whose first code is the reason.")

    progress = evaluate_plan_progress(plan)
    rollup = rollup_plan_status(plan)
    if not progress.ok or not rollup.ok:
        return _reject(report, REPORT_PLAN_STATE_UNDETERMINED, "The current plan state could not be determined.",
                       issues=[dict(f) for f in (progress.failures + rollup.failures)])

    report.status = REPORT_OK
    report.step_id = res.step_id
    report.execution_ok = res.ok
    report.execution_status = res.status
    report.previous_state = res.previous_state
    report.final_state = res.final_state
    report.executor_called = res.executor_called
    report.output = copy.deepcopy(res.output)
    report.reason = res.reason
    report.execution_failures = copy.deepcopy(res.failures)
    report.plan_status = rollup.status
    report.plan_status_reason = rollup.reason
    report.progress = {"total_steps": progress.total_steps, "pending_count": progress.pending_count,
                       "in_progress_count": progress.in_progress_count,
                       "completed_count": progress.completed_count, "failed_count": progress.failed_count,
                       "is_complete": progress.is_complete, "is_blocked": progress.is_blocked}
    report.ready_step_ids = list(progress.ready_step_ids)
    report.blocked_step_ids = list(progress.blocked_step_ids)
    return report
