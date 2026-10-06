# Prompt 851 - Upgrade Plan Contract

Third step of Section 14 (Self-Upgrade Engine), after the Prompt 849 request contract and the Prompt 850 project state.
Module: `upgrade/upgrade_plan.py` - a small, deterministic, DECLARATIVE plan describing WHAT would have to change, built only from an already validated upgrade request and an already validated project state. It generates no code or patch, reads/writes no file, runs no test or command, modifies no capability, performs no upgrade and is not connected to Core, Memory, AEL, the Capability System, LLMs or external services. Nothing is invented, inferred, trimmed, coerced or repaired.

## Normalized plan (exactly eight keys)
`version` (exactly `"1"`), `request_id` (text <= 64), `goal` (text <= 500), `steps` (non-empty list, <= 16 exact dicts with exactly `step_id` <= 64, `action` <= 64, `target` <= 200, `reason` <= 200; step ids unique), `affected_files` (list, <= 16, unique text <= 200), `affected_capabilities` (list, <= 16, unique text <= 64), `constraints` (list, <= 16, text <= 200), `execution_allowed` (exactly `False`). No `executed` key in the plan. "Text" is the Prompt 849 convention (imported, not duplicated).

## API
- `build_upgrade_plan(upgrade_request, project_state)` -> `{valid, errors, plan, execution_allowed, executed}`. Both inputs must already pass `validate_upgrade_request` / `validate_project_state`; nothing is repaired. The only planning rule: every item of the request `scope` must be represented in the project state as exactly one file path or exactly one capability name; one step per scope item, in order (`step_<n>`; action `modify_file` for a file, `update_capability` for a capability; target = the scope item; reason = `Listed in scope of request <request_id>`). `affected_files` / `affected_capabilities` list those targets. `request_id`, `goal`, `constraints` are copied from the request. No file or capability outside scope + state is ever named.
- `validate_upgrade_plan(plan)` -> `{valid, errors, execution_allowed, executed}`. Structural check: all eight keys, types, bounds, unique step ids and unique affected entries.

Build errors: `invalid_upgrade_request`, `invalid_project_state`, `empty_scope`, `empty_project_state`, `duplicate_scope_target`, `unknown_scope_target`, `ambiguous_scope_target` (where `scope[i]`), `validation_error`. Validation errors: see the module docstring. `errors` is `[{code, where}]`, at most 16, fixed order. `execution_allowed` and `executed` are always False in every result.

Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the plan.

Tests: `tests/test_upgrade_plan_prompt851.py` (30 tests: valid single/multi-step, invalid request/state, malformed input, unavailable planning information, malformed steps, affected files/capabilities, execution attempts, boundaries).
