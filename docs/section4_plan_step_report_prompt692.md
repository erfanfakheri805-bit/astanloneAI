# Prompt 692 - Plan step execution report

New module `planning/plan_step_report.py` (additive, read-only; `PlanStep`, `PlanManager`, `process_input()` and
Prompts 684-691 untouched). One function:

`report_plan_step_execution(plan, execution_result) -> PlanStepExecutionReport`

Pairs one `execute_plan_step()` result (691) with the current `evaluate_plan_progress()` (687) and
`rollup_plan_status()` (690). Nothing is redefined, executed, retried, recovered or authorized; the plan is never mutated.

`to_dict()` keeps two sections apart: `execution` (step_id, ok, status, previous_state, final_state, executor_called,
output, reason, failures = this attempt) and `plan` (status, reason, progress counts, ready_step_ids,
blocked_step_ids = whole plan after the attempt). Flat attributes mirror the same fields.

Rejections (`ok=False`, `status="rejected"`): INVALID_PLAN_OBJECT, INVALID_EXECUTION_RESULT, EXECUTION_NOT_REPORTABLE
(the result was itself a 691 rejection), UNKNOWN_STEP, EXECUTION_INCONSISTENT (states, executor_called, output,
reason/failures disagree with the plan), PLAN_STATE_UNDETERMINED.

Tests: `test_section4_plan_step_report_prompt692.py`.
