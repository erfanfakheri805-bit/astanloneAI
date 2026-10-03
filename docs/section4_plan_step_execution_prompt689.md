# Prompt 689 - Controlled plan step execution state

New module `planning/plan_step_execution.py` (additive; `PlanStep`, `PlanManager`, `plan_builder.py`, `process_input()`
untouched). Three explicit, caller-invoked transitions on a `Plan`, each returning a `PlanStepTransitionResult`
(`status` applied/rejected, `previous_state`, `new_state`, fresh `step` copy, ordered `failures`, `codes()`):

- `start_plan_step(plan, step_id)`: pending -> in_progress. Requires consistent plan state (Prompt 684), the step in
  `get_ready_plan_steps` (Prompt 686) and `execution_authorized is True`. Produces no output. Sets
  `metadata["executed"] = True` (an in_progress step implies execution); never touches `execution_authorized`.
- `complete_plan_step(plan, step_id, output)`: in_progress -> completed; stores explicit output.
- `fail_plan_step(plan, step_id, reason)`: in_progress -> failed; stores explicit reason/output.

Output/reason must be non-None, not a blank string and JSON-safe (`ensure_structured_data`). All checks run before any
mutation: a rejected transition leaves plan, metadata and steps unchanged. Authorization is permission only; it never
changes a step. Failure codes: INVALID_PLAN_OBJECT, INVALID_STEP_ID, UNKNOWN_STEP, INVALID_PLAN_STATE,
PLAN_READINESS_UNDETERMINED, STEP_NOT_READY, EXECUTION_NOT_AUTHORIZED, STEP_NOT_IN_PROGRESS,
MISSING_EXECUTION_OUTPUT, INVALID_EXECUTION_OUTPUT.

Tests: `test_section4_plan_step_execution_prompt689.py`.
