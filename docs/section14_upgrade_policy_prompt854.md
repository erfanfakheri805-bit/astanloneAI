# Prompt 854 - Upgrade Policy Gate

Fifth step of Section 14 (Self-Upgrade Engine), after request (849), project state (850), plan (851) and change proposal (852).
Module: `upgrade/upgrade_policy.py` - a small, deterministic, purely DECLARATIVE gate that decides whether a validated change proposal may proceed to a future, separate application stage. It applies, generates, modifies and executes nothing; no file I/O, subprocess, eval/exec, filesystem scan, test run, capability change, Core/Memory/AEL link, LLM or network. Permission is never inferred from action names, file names, capability names, purposes or the caller; nothing is repaired.

## Result (exactly seven keys, fixed order)
`version` (`"1"`), `status`, `allowed` (True only for `allowed`), `reason` (one fixed reason per status), `proposal_id` (the proposal's `plan_id` when known, else None; text when allowed), `execution_allowed` (always False), `executed` (always False).

## API
- `evaluate_upgrade_policy(change_proposal, project_state=None)`. Order, first failure decides: not a dict -> `invalid_input` (`change_proposal_missing` / `change_proposal_not_dict`); `validate_change_proposal` (Prompt 852, reused) fails -> `empty_proposal` if its only error is `empty_changes`, else `invalid_proposal`; supplied `project_state` fails `validate_project_state` (Prompt 850, reused) -> `invalid_project_state`; change targets differ from `affected_files + affected_capabilities` -> `policy_denied`; otherwise `allowed`. `project_state` is only validated, never used to grant permission. Any internal error -> `invalid_input` / `policy_evaluation_error`.
- `validate_upgrade_policy_result(result)` -> `{valid, errors, execution_allowed, executed}`. Exact keys and types, version, known status, `allowed` agreeing with status, the fixed reason of the status, bounded `proposal_id` (None for invalid_input / invalid_proposal, text for allowed / policy_denied / invalid_project_state), flags exactly False. Never repairs.

Statuses: `invalid_input`, `invalid_proposal`, `invalid_project_state`, `empty_proposal`, `policy_denied`, `allowed`. `allowed` is permission to proceed to a future stage, not an execution.

Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the policy.

Tests: `tests/test_upgrade_policy_prompt854.py` (30 tests: allowed, invalid proposal, empty proposal, invalid project state, malformed input, missing fields, execution attempts, deterministic reasons, malformed result validation, oversized/malformed values, import/no-I/O boundaries).
