# Prompt 695 - Section 4 end-to-end consistency audit

Audited Prompts 684-694 as one pipeline (validation, dependencies/order, readiness, progress, rollup, transitions,
execution, report, runner, summary) with deterministic in-memory scenarios in
`tests/test_section4_end_to_end_audit_prompt695.py`.

Agreed (no change needed): "executed" means step-state evidence only (`start_plan_step` sets it; authorization never does
and never changes readiness); readiness ids == progress ids == rollup ids after every transition; rollup status agrees with
progress counts; transitions and `execute_plan_step` are gated by `validate_plan_step_states`; rejections never call the
executor or mutate; reports and summaries match plan state and the runner record; ordering is plan order everywhere.

Genuine defect (reproduced): `get_ready_plan_steps` / `evaluate_plan_progress` (686/687) deliberately do not check
flag/state combinations (684 keeps that check separate), but `run_plan_steps` (693) only pre-validated with
`validate_plan`. For a state-inconsistent plan the runner either reported `PLAN_COMPLETE`/`ok=True` with no final status
(all steps completed but `executed=False`), or `EXECUTION_REJECTED` after one attempt with no final status - records the
Prompt 694 summary then rejected as inconsistent.

Fix (smallest root cause): `run_plan_steps` now also calls the existing `validate_plan_step_states` as a precondition and
rejects with the new precondition stop reason `INVALID_PLAN_STATE` (nothing executed or mutated). The summary lists it
with the other precondition rejections. `PlanStep`, `PlanManager`, 684-692 code and validation strictness are unchanged.
