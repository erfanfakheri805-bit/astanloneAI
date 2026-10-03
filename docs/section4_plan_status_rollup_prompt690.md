# Prompt 690 - Plan-level status rollup

New module `planning/plan_status_rollup.py` (additive; `PlanStep`, `PlanManager`, `plan_builder.py`,
`plan_step_execution.py`, `process_input()` untouched). One explicit, caller-invoked, read-only function:
`rollup_plan_status(plan) -> PlanStatusRollupResult`.

Built on the existing contracts: input is checked with `validate_plan_step_states` (Prompt 684); counts, ready ids,
blocked ids and the complete/blocked flags come from `evaluate_plan_progress` (Prompt 687, stays authoritative).
Only step states are used: `execution_authorized`, `executed` and `Plan.status` never change the result.

Precedence (first match wins): no steps -> `pending` (EMPTY_PLAN); all completed -> `complete` (ALL_STEPS_COMPLETED);
any failed -> `failed` (STEP_FAILED); any in_progress -> `in_progress` (STEP_IN_PROGRESS); progress `is_blocked` ->
`blocked` (NO_EXECUTABLE_PATH); otherwise `pending` (PENDING). `ROLLUP_STATUSES` = pending, in_progress, completed,
failed, blocked, complete (`completed` is the step-level state and is never emitted as a plan status).

Note: a stuck pending step only arises behind a failed step (Prompt 687), and `failed` wins, so `blocked` is a
defensive branch; stuck steps of a failed plan are reported in `blocked_step_ids`.

Result: `status` (None if rejected), `ok`, `reason`, `total_steps`, per-state counts, per-state step id lists
(plan order), `ready_step_ids`, `blocked_step_ids`, `failures`, `codes()`, `to_dict()`. Rejections (status None):
INVALID_PLAN_OBJECT, INVALID_PLAN_STATE (with `issues`), PLAN_PROGRESS_UNDETERMINED (with `issues`).

Tests: `tests/test_section4_plan_status_rollup_prompt690.py`.
