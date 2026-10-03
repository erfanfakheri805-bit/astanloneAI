# Prompt 693 - Caller-driven multi-step plan runner

New module `planning/plan_runner.py` (additive; `PlanStep`, `PlanManager`, `process_input()` and Prompts 684-692
untouched). One function: `run_plan_steps(plan, executor, max_steps) -> PlanRunResult`.

Loop: `evaluate_plan_progress` (687) -> first ready id only -> `execute_plan_step` (691) ->
`report_plan_step_execution` (692) -> record. No readiness/progress/status/transition logic is duplicated; the executor
gets only the 691 step-scoped dict. No authorization, retries, concurrency, threads, subprocesses, tools or network.

Stop reasons: STEP_FAILED (recorded, never retried/continued), EXECUTION_REJECTED (e.g. unauthorized; executor not run),
REPORT_REJECTED, PLAN_COMPLETE, NO_READY_STEPS, MAX_STEPS_REACHED, PLAN_PROGRESS_UNDETERMINED. Precondition rejections
(nothing executed, plan untouched): INVALID_PLAN_OBJECT, INVALID_PLAN, INVALID_PLAN_STATE (added in Prompt 695), INVALID_EXECUTOR, INVALID_MAX_STEPS (plain int > 0).

Result: `ok`, `stop_reason`, `steps_attempted`, `completed_step_ids`, `failed_step_ids`, `reports` (692 dicts),
`execution_results` (691 dicts), `final_plan_status` (690), `final_progress` (687), `failures`, `codes()`, `to_dict()`.
`ok` is False for failures/rejections and when the final plan status is `failed`.

Tests: `test_section4_plan_runner_prompt693.py`.
