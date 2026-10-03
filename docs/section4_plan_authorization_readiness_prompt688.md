# Prompt 688 - Plan authorization vs step readiness

Contract: `metadata["execution_authorized"]` is permission to execute; step state / recorded output is the only
evidence of execution. Authorization never makes a pending step unready and never marks anything executed.

Defect fixed: `get_ready_plan_steps` returned no ready steps for any authorized plan (Prompt 686 early return), which
made `evaluate_plan_progress` report `ready_step_ids == []` while startable pending steps existed. The early return was
removed; readiness still requires pending state, no recorded output, a valid dependency graph, and all dependencies
completed. Flag/state validation (`validate_plan_step_states`) is unchanged and still rejects execution implied without
authorization/execution flag. `PlanStep`, `PlanManager`, `process_input()` and execution behavior are untouched.

Tests updated (old contradictory expectation only): Prompt 686 `test_authorized_plan_offers_nothing`, Prompt 687
`test_authorized_plan_startable_step_prevents_blocked`. New: `test_section4_plan_authorization_readiness_prompt688.py`.
