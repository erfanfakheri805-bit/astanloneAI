# Prompt 918 - Reasoning handoff activation

Section 19: Runtime Integration / Productization. Subsection: Reasoning Runtime Integration.

## Where the handoff is created

`runtime_integration/bridge.py::_reasoning_section()` already ran, read-only, the existing chain
`analysis.reasoning_input()` -> `build_reasoning_request()` -> `build_reasoning_plan()` ->
`decide_reasoning()` -> `evaluate_reasoning_capability_boundary()`. It now also keeps that result together as
`reasoning["reasoning_handoff"]` inside the runtime result's `reasoning` section
(`RuntimeCore.last_runtime_result`, `GET /api/runtime-result`).
`RuntimeCore.get_last_reasoning_handoff()` returns it for the last turn, or
`bridge.unavailable_reasoning_handoff(reason)` when that turn has none.

## What it carries

`version`, `descriptive_only` (True), `request` (the existing reasoning request: status, goal, known,
unresolved, missing, next_action), `decision` (decision, reason, next_step), `plan` (status, step_count),
`capability_boundary` (decision_state, next_stage, reason), `executed` (always False) and
`consumed_by_runtime` (always False).

## Current status

Descriptive/read-only. Nothing consumes it: `Core` reply selection, memory, the database schema, AEL and
capabilities are untouched, and nothing is executed. Turns without a reasoning section (AEL, empty input,
bridge error, a failing section) keep their existing `{"available": False, "reason": ...}` shape; the
top-level runtime-result keys are unchanged (the handoff is one added key inside `reasoning`).

## Later

Later prompts may read this handoff to make controlled runtime decisions; that will need its own focused
change and tests. No external AI/API/service, no network, no self-modification or self-upgrade here.
