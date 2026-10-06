# Prompt 852 - Upgrade Change Proposal

Fourth step of Section 14 (Self-Upgrade Engine), after the request (849), project state (850) and plan (851).
Module: `upgrade/change_proposal.py` - a small, deterministic, DECLARATIVE change proposal derived one-to-one from an already validated upgrade plan and project state. It generates no code, diff or patch, reads/writes no file, inspects no filesystem, runs no test or command, modifies no capability, performs no upgrade and is not connected to Core, Memory, AEL, the Capability System, LLMs or external services. Nothing is invented, inferred, trimmed, coerced or repaired.

## Normalized proposal (exactly seven keys)
`version` (exactly `"1"`), `plan_id` (text <= 64), `changes` (non-empty list, <= 16 exact dicts with exactly `change_id` <= 64, `action` <= 64, `target` <= 200, `reason` <= 200; change ids unique), `affected_files`, `affected_capabilities`, `constraints` (same rules as the Prompt 851 plan - the 851 list checker is reused), `execution_allowed` (exactly `False`). No `executed` key in the proposal.

## API
- `build_change_proposal(upgrade_plan, project_state)` -> `{valid, errors, proposal, execution_allowed, executed}`. Both inputs must pass `validate_upgrade_plan` / `validate_project_state` and be consistent: every step is `modify_file` (target is a project-state file) or `update_capability` (target is a project-state capability), and the plan's affected lists equal the targets of its file / capability steps in order. `plan_id` = `plan_` + first 16 hex digits of SHA-256 of the plan's canonical JSON (sorted keys, compact separators, ASCII) - the truncated-SHA-256 convention of `planning/plan_builder.py`; it depends only on the plan. `changes[n]` = step n: `change_id` `change_<n>`, `action` / `target` / `reason` copied; affected lists and constraints copied unchanged. Nothing outside the plan is added.
- `validate_change_proposal(proposal)` -> `{valid, errors, execution_allowed, executed}`. Structural check of all seven keys, exact types, bounds, exact change keys and unique change ids. It does not re-derive `plan_id` (it never sees the plan).

Build errors: `invalid_upgrade_plan`, `invalid_project_state`, `unsupported_step_action`, `step_target_not_in_project_state` (where `steps[i]`), `affected_files_mismatch`, `affected_capabilities_mismatch`, `validation_error`. Validation errors: see the module docstring. `errors` is `[{code, where}]`, at most 16, fixed order. `execution_allowed` and `executed` are always False in every result.

Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the proposal.

Tests: `tests/test_change_proposal_prompt852.py` (30 tests: valid, multiple changes, deterministic ids, invalid plan/state, malformed input, inconsistent plan, malformed change, duplicate id, affected lists, constraints, execution attempts, oversized input, boundaries).
