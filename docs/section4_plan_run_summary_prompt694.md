# Prompt 694 - Plan run summary

New module `planning/plan_run_summary.py` (additive, read-only; the runner, `PlanStep`, `PlanManager`, `process_input()`
and Prompts 684-693 untouched). One function: `summarize_plan_run(run_result) -> PlanRunSummary`.

Reads only a Prompt 693 `PlanRunResult` (the authoritative record); no plan or executor input, nothing executed,
retried or continued; output is copied. Status/progress values are the ones the runner already recorded (690/687).

Outcome from `stop_reason`: `complete` (PLAN_COMPLETE); `stopped` (MAX_STEPS_REACHED, NO_READY_STEPS); `failed`
(STEP_FAILED); `rejected` (EXECUTION_REJECTED, REPORT_REJECTED, PLAN_PROGRESS_UNDETERMINED, precondition rejections).
Fields: `outcome`, `run_ok`, `stop_reason`, `is_complete`, `ended_by_execution_failure`, `ended_by_rejection`,
`ended_abnormally`, `steps_attempted`, `completed_step_ids`, `failed_step_ids`, `report_count`, `final_plan_status`,
`progress_counts`, `ready_step_ids`, `blocked_step_ids`, `to_dict()`.

Rejection (`ok=False`): INVALID_RUN_RESULT (not a PlanRunResult) or INCONSISTENT_RUN_RESULT (contradictory record, with
`issues`); nothing is guessed or reconstructed.

Tests: `test_section4_plan_run_summary_prompt694.py`.
