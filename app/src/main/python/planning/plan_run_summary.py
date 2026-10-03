"""
Plan Run Summary (Prompt 694)
================================
A small, read-only summary of an existing Prompt 693 `PlanRunResult`:

    summarize_plan_run(run_result) -> PlanRunSummary

The run result is the authoritative record. Nothing is executed, retried, recovered, continued or authorized; the
executor and the plan are never touched (neither is even an input); the run result, its reports and its execution
results are only read (output is deep-copied). Execution, readiness, progress and status are not redefined: the
values are those the runner already recorded (`final_plan_status` from 690, `final_progress` from 687).

OUTCOME (derived only from `stop_reason`; the distinctions are kept apart)
    complete   PLAN_COMPLETE
    stopped    MAX_STEPS_REACHED, NO_READY_STEPS         (normal stopping conditions; not failures)
    failed     STEP_FAILED                               (a step ran and failed)
    rejected   EXECUTION_REJECTED (refused before the executor ran), REPORT_REJECTED, PLAN_PROGRESS_UNDETERMINED,
               and the precondition rejections INVALID_PLAN_OBJECT / INVALID_PLAN / INVALID_PLAN_STATE / INVALID_EXECUTOR / INVALID_MAX_STEPS
`run_ok` is the runner's own `ok`. `ended_by_execution_failure`, `ended_by_rejection` and `ended_abnormally`
(either) are exposed separately, as is `is_complete`.

REJECTION: a non-PlanRunResult (`INVALID_RUN_RESULT`) or a run record whose parts contradict each other
(`INCONSISTENT_RUN_RESULT`, with the list of issues) returns `ok=False` with no summary fields; nothing is guessed or
reconstructed. Same run result -> identical summary, every time.
"""

import copy

from planning.plan_builder import _failure
from planning.plan_runner import (PlanRunResult, STOP_EXECUTION_REJECTED, STOP_INVALID_EXECUTOR, STOP_INVALID_MAX_STEPS,
                                  STOP_INVALID_PLAN, STOP_INVALID_PLAN_OBJECT, STOP_INVALID_PLAN_STATE, STOP_MAX_STEPS, STOP_NO_READY_STEPS,
                                  STOP_PLAN_COMPLETE, STOP_PROGRESS_UNDETERMINED, STOP_REPORT_REJECTED,
                                  STOP_STEP_FAILED, _OK_STOPS)

OUTCOME_COMPLETE = "complete"
OUTCOME_STOPPED = "stopped"
OUTCOME_FAILED = "failed"
OUTCOME_REJECTED = "rejected"

SUMMARY_INVALID_RUN_RESULT = "INVALID_RUN_RESULT"
SUMMARY_INCONSISTENT_RUN_RESULT = "INCONSISTENT_RUN_RESULT"

_PRECONDITION_STOPS = (STOP_INVALID_PLAN_OBJECT, STOP_INVALID_PLAN, STOP_INVALID_PLAN_STATE, STOP_INVALID_EXECUTOR,
                       STOP_INVALID_MAX_STEPS)
_REJECTED_STOPS = _PRECONDITION_STOPS + (STOP_EXECUTION_REJECTED, STOP_REPORT_REJECTED, STOP_PROGRESS_UNDETERMINED)
_OUTCOMES = {STOP_PLAN_COMPLETE: OUTCOME_COMPLETE, STOP_MAX_STEPS: OUTCOME_STOPPED,
             STOP_NO_READY_STEPS: OUTCOME_STOPPED, STOP_STEP_FAILED: OUTCOME_FAILED}
_OUTCOMES.update({s: OUTCOME_REJECTED for s in _REJECTED_STOPS})
_PROGRESS_KEYS = ("total_steps", "pending_count", "in_progress_count", "completed_count", "failed_count",
                  "is_complete", "is_blocked", "ready_step_ids", "blocked_step_ids")
_COUNT_KEYS = _PROGRESS_KEYS[:5]


class PlanRunSummary:
    __slots__ = ("status", "outcome", "run_ok", "stop_reason", "is_complete", "ended_by_execution_failure",
                 "ended_by_rejection", "ended_abnormally", "steps_attempted", "completed_step_ids",
                 "failed_step_ids", "report_count", "final_plan_status", "progress_counts", "ready_step_ids",
                 "blocked_step_ids", "failures")

    def __init__(self):
        self.status = "rejected"      # "summarized" or "rejected"
        self.outcome = None
        self.run_ok = None
        self.stop_reason = None
        self.is_complete = None
        self.ended_by_execution_failure = None
        self.ended_by_rejection = None
        self.ended_abnormally = None
        self.steps_attempted = None
        self.completed_step_ids = []
        self.failed_step_ids = []
        self.report_count = None
        self.final_plan_status = None
        self.progress_counts = {}
        self.ready_step_ids = []
        self.blocked_step_ids = []
        self.failures = []            # rejection of the summary itself (not the run's own failures)

    @property
    def ok(self):
        return self.status == "summarized"

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "ok": self.ok, "status": self.status, "outcome": self.outcome, "run_ok": self.run_ok,
            "stop_reason": self.stop_reason, "is_complete": self.is_complete,
            "ended_by_execution_failure": self.ended_by_execution_failure,
            "ended_by_rejection": self.ended_by_rejection, "ended_abnormally": self.ended_abnormally,
            "steps_attempted": self.steps_attempted, "completed_step_ids": list(self.completed_step_ids),
            "failed_step_ids": list(self.failed_step_ids), "report_count": self.report_count,
            "final_plan_status": self.final_plan_status, "progress_counts": dict(self.progress_counts),
            "ready_step_ids": list(self.ready_step_ids), "blocked_step_ids": list(self.blocked_step_ids),
            "failures": [dict(f) for f in self.failures],
        }


def _is_id_list(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _consistency_issues(run):
    """Contradictions inside the run record itself; nothing is inferred or repaired."""
    issues = []
    stop = run.stop_reason
    if stop not in _OUTCOMES:
        return ["unknown stop_reason"]
    if not isinstance(run.ok, bool):
        issues.append("ok is not a bool")
    if isinstance(run.steps_attempted, bool) or not isinstance(run.steps_attempted, int) or run.steps_attempted < 0:
        return issues + ["steps_attempted is not a non-negative int"]
    if not (_is_id_list(run.completed_step_ids) and _is_id_list(run.failed_step_ids)):
        return issues + ["completed/failed step ids must be lists of strings"]
    if not (isinstance(run.reports, list) and isinstance(run.execution_results, list)
            and all(isinstance(r, dict) for r in run.reports + run.execution_results)):
        return issues + ["reports/execution_results must be lists of dicts"]
    if not isinstance(run.failures, list):
        return issues + ["failures must be a list"]

    reports, results = run.reports, run.execution_results
    done, failed = run.completed_step_ids, run.failed_step_ids
    if set(done) & set(failed):
        issues.append("a step is both completed and failed")
    if len(failed) > 1:
        issues.append("more than one failed step")
    if len(done) + len(failed) != len(reports):
        issues.append("reports do not match completed + failed steps")
    if len(results) != run.steps_attempted:
        issues.append("execution_results do not match steps_attempted")
    if (stop == STOP_STEP_FAILED) != bool(failed):
        issues.append("failed_step_ids and stop_reason disagree")
    reported = [(r.get("execution") or {}).get("step_id") if isinstance(r.get("execution"), dict) else None
                for r in reports]
    if reported != done + failed:
        issues.append("report step ids do not match completed + failed step ids in order")
    if [r.get("step_id") for r in results][:len(reports)] != reported:
        issues.append("execution result step ids do not match reports")

    extra = len(results) - len(reports)
    if stop == STOP_EXECUTION_REJECTED:
        if extra != 1 or results[-1].get("status") != "rejected" or not run.failures:
            issues.append("EXECUTION_REJECTED needs one trailing rejected execution result and failures")
    elif stop == STOP_REPORT_REJECTED:
        if extra != 1 or results[-1].get("status") not in ("completed", "failed") or not run.failures:
            issues.append("REPORT_REJECTED needs one trailing executed result and failures")
    elif extra != 0:
        issues.append("unreported execution results")

    if stop in _PRECONDITION_STOPS:
        if run.steps_attempted or results or run.final_plan_status is not None or run.final_progress:
            issues.append("a precondition rejection must record nothing")
        if not run.failures:
            issues.append("a precondition rejection needs failures")
    else:
        progress = run.final_progress
        if not isinstance(run.final_plan_status, str):
            issues.append("final_plan_status missing")
        if not isinstance(progress, dict) or any(k not in progress for k in _PROGRESS_KEYS):
            issues.append("final_progress is incomplete")
        elif (not _is_id_list(progress["ready_step_ids"]) or not _is_id_list(progress["blocked_step_ids"])
              or any(isinstance(progress[k], bool) or not isinstance(progress[k], int) for k in _COUNT_KEYS)):
            issues.append("final_progress has malformed values")
        elif stop == STOP_PLAN_COMPLETE and not (progress["is_complete"] and run.final_plan_status == "complete"):
            issues.append("PLAN_COMPLETE does not match the final plan state")
        elif stop == STOP_NO_READY_STEPS and progress["ready_step_ids"]:
            issues.append("NO_READY_STEPS but steps are ready")
    if isinstance(run.ok, bool) and not issues:
        if run.ok != (stop in _OK_STOPS and run.final_plan_status != "failed"):
            issues.append("ok does not match stop_reason and final plan status")
    return issues


def summarize_plan_run(run_result):
    """Summarize a `PlanRunResult` (see module docstring). Read-only; never raises, never executes anything."""
    summary = PlanRunSummary()
    if not isinstance(run_result, PlanRunResult):
        summary.failures = [_failure(SUMMARY_INVALID_RUN_RESULT, "Not a PlanRunResult; nothing to summarize.")]
        return summary
    try:
        issues = _consistency_issues(run_result)
    except Exception:       # a tampered, half-built record: reject rather than guess
        issues = ["run result could not be read"]
    if issues:
        summary.failures = [_failure(SUMMARY_INCONSISTENT_RUN_RESULT,
                                     "The run result is internally inconsistent; no summary produced.",
                                     issues=issues)]
        return summary

    run, stop = run_result, run_result.stop_reason
    summary.status = "summarized"
    summary.outcome = _OUTCOMES[stop]
    summary.run_ok = run.ok
    summary.stop_reason = stop
    summary.is_complete = stop == STOP_PLAN_COMPLETE
    summary.ended_by_execution_failure = stop == STOP_STEP_FAILED
    summary.ended_by_rejection = stop in _REJECTED_STOPS
    summary.ended_abnormally = summary.ended_by_execution_failure or summary.ended_by_rejection
    summary.steps_attempted = run.steps_attempted
    summary.completed_step_ids = list(run.completed_step_ids)
    summary.failed_step_ids = list(run.failed_step_ids)
    summary.report_count = len(run.reports)
    summary.final_plan_status = run.final_plan_status
    if run.final_progress:
        progress = copy.deepcopy(run.final_progress)
        summary.progress_counts = {k: progress[k] for k in _PROGRESS_KEYS if k not in
                                   ("ready_step_ids", "blocked_step_ids")}
        summary.ready_step_ids = list(progress["ready_step_ids"])
        summary.blocked_step_ids = list(progress["blocked_step_ids"])
    return summary
