# Section 4 - Plan step state validation (Prompt 684)

Baseline: Prompt 683 (verified). One additive improvement in `planning/plan_builder.py`; no other production file changed
(`core/core.py`, `process_input()`, `plan.py`, `plan_validation.py` untouched).

`validate_plan_step_states(plan)` -> `StepStateValidationResult(valid, issues, states)`. Pure and read-only: never raises, never
mutates, never normalizes or repairs. Issue order is deterministic: execution flags, then steps in plan order, then plan-level
combinations.

Supported step states at this layer (`STEP_STATES`): `pending` (the only state generated plans use), `in_progress`, `completed`,
`failed`. The last three (`EXECUTION_STATES`) imply execution happened. `ready`/`blocked` (computed by PlanManager) are not
planning-phase states and are reported as unsupported here; `PlanStep` itself is unchanged.

Stable codes: `INVALID_PLAN_OBJECT`, `INVALID_STEP_ID` (empty / non-string), `DUPLICATE_STEP_ID`, `UNSUPPORTED_STEP_STATE`
(step or plan), `INVALID_EXECUTION_FLAG` (`metadata["executed"]` / `["execution_authorized"]` missing or not a real bool - 0/1
and strings rejected), `EXECUTED_STEP_PENDING` (step has recorded output but is still pending), `EXECUTION_IMPLIED_WITHOUT_EXECUTION`
(execution state or output while `executed=False`), `EXECUTION_WITHOUT_AUTHORIZATION` (execution implied or `executed=True` while
`execution_authorized=False`), `PLAN_EXECUTED_WITHOUT_STEP_PROGRESS` (`executed=True` but every step still pending).
Authorized-but-unexecuted is allowed.

Generated Prompt 681-683 plans are unchanged (all steps `pending`, `executed=False`, `execution_authorized=False`) and validate
clean. Nothing is executed, written or hooked into Core.
