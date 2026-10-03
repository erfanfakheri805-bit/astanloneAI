"""
Caller-Driven Multi-Step Plan Runner (Prompt 693)
====================================================
The smallest orchestration layer above Prompts 691/692:

    run_plan_steps(plan, executor, max_steps) -> PlanRunResult

Per iteration it asks `evaluate_plan_progress` (687) for the current ready ids, takes the FIRST one only (existing
plan-order readiness ordering), calls `execute_plan_step` (691) and then `report_plan_step_execution` (692), and
records both. Readiness, progress, status, transitions and reporting are never re-implemented here. The executor is
the caller's injected callback and only ever receives the Prompt 691 step-scoped dict, never the plan.

STOP REASONS (checked in this order at the top of each iteration, after a step has been reported)
    STEP_FAILED          the executed step ended failed; recorded, never retried, never continued
    EXECUTION_REJECTED   execute_plan_step rejected before running (e.g. unauthorized plan); recorded, executor not run
    REPORT_REJECTED      the 692 report refused a completed/failed result (inconsistency); nothing guessed
    PLAN_COMPLETE        every step completed
    NO_READY_STEPS       nothing ready remains (may be a failed/stuck plan; `ok` is False if plan status is failed)
    MAX_STEPS_REACHED    `max_steps` executions attempted
    PLAN_PROGRESS_UNDETERMINED  progress could not be evaluated (invalid dependencies etc.)
Precondition rejections (nothing executed, plan untouched, executor never called): INVALID_PLAN_OBJECT, INVALID_PLAN,
INVALID_PLAN_STATE (step states/flags inconsistent, Prompt 684; added in 695), INVALID_EXECUTOR,
INVALID_MAX_STEPS (must be a plain int > 0; bool rejected).

The runner never authorizes, retries, reorders, runs concurrently, or uses threads/subprocesses/tools/network.
Same plan state + same deterministic executor -> identical result.
"""

from planning.plan import Plan
from planning.plan_builder import _failure, evaluate_plan_progress, validate_plan_step_states
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_orchestration import STATUS_EXECUTION_FAILED, STATUS_EXECUTION_REJECTED, execute_plan_step
from planning.plan_step_report import report_plan_step_execution
from planning.plan_validation import validate_plan

STOP_STEP_FAILED = "STEP_FAILED"
STOP_EXECUTION_REJECTED = "EXECUTION_REJECTED"
STOP_REPORT_REJECTED = "REPORT_REJECTED"
STOP_PLAN_COMPLETE = "PLAN_COMPLETE"
STOP_NO_READY_STEPS = "NO_READY_STEPS"
STOP_MAX_STEPS = "MAX_STEPS_REACHED"
STOP_PROGRESS_UNDETERMINED = "PLAN_PROGRESS_UNDETERMINED"
STOP_INVALID_PLAN_OBJECT = "INVALID_PLAN_OBJECT"
STOP_INVALID_PLAN = "INVALID_PLAN"
STOP_INVALID_PLAN_STATE = "INVALID_PLAN_STATE"
STOP_INVALID_EXECUTOR = "INVALID_EXECUTOR"
STOP_INVALID_MAX_STEPS = "INVALID_MAX_STEPS"

_OK_STOPS = (STOP_PLAN_COMPLETE, STOP_NO_READY_STEPS, STOP_MAX_STEPS)


class PlanRunResult:
    __slots__ = ("ok", "stop_reason", "steps_attempted", "completed_step_ids", "failed_step_ids", "reports",
                 "execution_results", "final_plan_status", "final_progress", "failures")

    def __init__(self):
        self.ok = False
        self.stop_reason = None
        self.steps_attempted = 0
        self.completed_step_ids = []
        self.failed_step_ids = []
        self.reports = []            # one 692 report dict per reportable attempt, in execution order
        self.execution_results = []  # one 691 result dict per attempt (includes a pre-execution rejection)
        self.final_plan_status = None
        self.final_progress = {}
        self.failures = []

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "ok": self.ok,
            "stop_reason": self.stop_reason,
            "steps_attempted": self.steps_attempted,
            "completed_step_ids": list(self.completed_step_ids),
            "failed_step_ids": list(self.failed_step_ids),
            "reports": [dict(r) for r in self.reports],
            "execution_results": [dict(r) for r in self.execution_results],
            "final_plan_status": self.final_plan_status,
            "final_progress": dict(self.final_progress),
            "failures": [dict(f) for f in self.failures],
        }


def _precondition_reject(result, code, message, **details):
    result.stop_reason = code
    result.failures = [_failure(code, message, **details)]
    return result


def _finalize(result, plan, stop_reason, ok_when_clean=True):
    """Fill the final plan status/progress from the existing rollup/progress functions (read-only)."""
    result.stop_reason = stop_reason
    rollup, progress = rollup_plan_status(plan), evaluate_plan_progress(plan)
    result.final_plan_status = rollup.status
    if progress.ok:
        result.final_progress = {"total_steps": progress.total_steps, "pending_count": progress.pending_count,
                                 "in_progress_count": progress.in_progress_count,
                                 "completed_count": progress.completed_count, "failed_count": progress.failed_count,
                                 "is_complete": progress.is_complete, "is_blocked": progress.is_blocked,
                                 "ready_step_ids": list(progress.ready_step_ids),
                                 "blocked_step_ids": list(progress.blocked_step_ids)}
    result.ok = ok_when_clean and stop_reason in _OK_STOPS and rollup.status != "failed"
    return result


def run_plan_steps(plan, executor, max_steps):
    """Execute up to `max_steps` ready steps, one at a time, first-ready-first, via the caller's `executor`.
    Stops at the first failure/rejection. Never raises for executor failures; never retries."""
    result = PlanRunResult()
    if not isinstance(plan, Plan):
        return _precondition_reject(result, STOP_INVALID_PLAN_OBJECT, "Not a Plan; nothing to run.")
    if not callable(executor):
        return _precondition_reject(result, STOP_INVALID_EXECUTOR, "An explicit callable executor is required.")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        return _precondition_reject(result, STOP_INVALID_MAX_STEPS, "max_steps must be an integer greater than 0.")
    validation = validate_plan(plan)
    if not validation.valid:
        return _precondition_reject(result, STOP_INVALID_PLAN, "The plan is not valid; nothing executed.",
                                    issues=[dict(i) for i in validation.issues])
    states = validate_plan_step_states(plan)      # same gate 689/690 use; readiness/progress alone do not check it
    if not states.valid:
        return _precondition_reject(result, STOP_INVALID_PLAN_STATE,
                                    "The plan's step states/flags are inconsistent; nothing executed.",
                                    issues=[dict(i) for i in states.issues])

    while True:
        progress = evaluate_plan_progress(plan)
        if not progress.ok:
            result.failures = [dict(f) for f in progress.failures]
            return _finalize(result, plan, STOP_PROGRESS_UNDETERMINED)
        if progress.is_complete:
            return _finalize(result, plan, STOP_PLAN_COMPLETE)
        if not progress.ready_step_ids:
            return _finalize(result, plan, STOP_NO_READY_STEPS)
        if result.steps_attempted >= max_steps:
            return _finalize(result, plan, STOP_MAX_STEPS)

        step_id = progress.ready_step_ids[0]              # first ready step only
        result.steps_attempted += 1
        execution = execute_plan_step(plan, step_id, executor)
        result.execution_results.append(execution.to_dict())
        if execution.status == STATUS_EXECUTION_REJECTED:
            result.failures = [dict(f) for f in execution.failures]
            return _finalize(result, plan, STOP_EXECUTION_REJECTED)

        report = report_plan_step_execution(plan, execution)
        if not report.ok:
            result.failures = [dict(f) for f in report.failures]
            return _finalize(result, plan, STOP_REPORT_REJECTED)
        result.reports.append(report.to_dict())
        if execution.status == STATUS_EXECUTION_FAILED:
            result.failed_step_ids.append(step_id)
            result.failures = [dict(f) for f in execution.failures]
            return _finalize(result, plan, STOP_STEP_FAILED)
        result.completed_step_ids.append(step_id)
