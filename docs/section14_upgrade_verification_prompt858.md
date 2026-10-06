# Prompt 858 - Upgrade Sandbox Verification

Ninth step of Section 14 (Self-Upgrade Engine), after request (849), project state (850), plan (851), change proposal (852), policy gate (854), change set (855), transaction boundary (856) and sandbox workspace (857).
Module: `upgrade/upgrade_verification.py` - a small, deterministic, read-only check that a sandbox result is internally consistent and still represents exactly the authorized change set. It repairs and modifies nothing, touches no real file, generates no code/patch, runs no subprocess or command, has no Core/Memory/AEL/LLM/network link and executes nothing.

## Result (exactly six keys, fixed order)
`valid` (True only for `valid`), `status`, `errors` (`[{code, where}]`, <= 16, empty only when valid), `proposal_id` (the change set's id when it is valid, else None), `execution_allowed` (False), `executed` (False).

## API
- `verify_sandbox_result(workspace, change_set, policy_result=None)`. First failing step decides the status:
  1. `validate_sandbox_workspace` (857, which reuses the 850 project-state validation) -> `invalid_workspace`; if every workspace error is a referential/authorization one (`duplicate_proposal_id`, `unknown_target`, `unsupported_change_action`) the workspace is structurally sound but its records are unauthorized -> `tampered`.
  2. `validate_change_set` (855) -> `invalid_change_set`.
  3. optional policy: `validate_upgrade_policy_result` (854), must be `allowed` / True for the same `proposal_id` -> `invalid_policy` (`invalid_policy_result`, `policy_not_allowed`, `policy_proposal_mismatch`).
  4. exactly one applied record with the change set's `proposal_id`; none -> `not_applied` (`change_set_not_applied`); several -> `tampered`.
  5. the record's changes must equal the change set's changes exactly and in order -> `tampered` (`changes_length_mismatch`, `change_id_changed`, `action_changed`, `target_changed`, `reason_changed`, where `changes[i].field`).
  6. otherwise `valid`. Any unexpected internal failure -> `verification_error`.
- `validate_sandbox_verification(result)` -> `{valid, errors, execution_allowed, executed}`. Exact keys/types, known status, `valid` agreeing with status, errors empty exactly when valid and made of exact bounded `{code, where}` dicts, bounded `proposal_id` (text when valid), flags exactly False. Never repairs.

Inputs are never modified or kept; results are fresh. Bounded, deterministic, never raises. No existing module was changed; nothing outside `upgrade/` imports the verification.

Tests: `tests/test_upgrade_verification_prompt858.py` (30 tests: valid, policy, determinism/immutability, each status, stale result, field-level tampering, reorder, identity mismatch, duplicate records, result validation, bounds, imports/no-I/O).
