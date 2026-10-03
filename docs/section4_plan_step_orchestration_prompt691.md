# Prompt 691 - Controlled plan step execution orchestration

New module `planning/plan_step_orchestration.py` (additive; `PlanStep`, `PlanManager`, `plan_step_execution.py` and
Prompts 684-690 untouched, not wired into `process_input()`). One function:

`execute_plan_step(plan, step_id, executor) -> PlanStepExecutionResult`

This is not the Tools section: `executor` is a caller-owned callback. No tool discovery/invocation, network,
filesystem, threads, subprocesses, scheduling or retries.

Gates (all reject before any mutation and before the executor is called): Plan object, non-empty `step_id`, callable
executor, `validate_plan(plan)` valid, then `start_plan_step` (authoritative for unknown step, inconsistent plan state,
readiness and `execution_authorized is True`; its codes are passed through).

After start the executor is called exactly once with a plain dict of only that step's data (`step_id`, `description`,
`input_data`, `expected_output`, `required_capabilities`; deep copies). Its return value becomes the step output via
`complete_plan_step`. An `Exception` is caught at the boundary, never re-raised, and recorded via `fail_plan_step` as
`{"code": "EXECUTOR_EXCEPTION", "exception_type", "message"}`. An output `complete_plan_step` refuses (None, blank,
not JSON-safe) fails the started step with `EXECUTOR_OUTPUT_INVALID`. A failed step stays consistent with
`validate_plan_step_states` / `validate_plan`; it is not retried (a second call is rejected `STEP_NOT_READY`).

Result: `ok`, `status` (completed/failed/rejected), `step_id`, `previous_state`, `final_state`, `output` (success),
`reason` (first failure code), `failures`, `executor_called`, `codes()`, `to_dict()`.
Codes: INVALID_PLAN_OBJECT, INVALID_PLAN, INVALID_STEP_ID, INVALID_EXECUTOR, EXECUTOR_EXCEPTION,
EXECUTOR_OUTPUT_INVALID, plus the Prompt 689 transition codes.

Tests: `test_section4_plan_step_orchestration_prompt691.py`.
