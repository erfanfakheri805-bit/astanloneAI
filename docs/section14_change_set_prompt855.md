# Prompt 855 - Sandboxed Change Set

Sixth step of Section 14 (Self-Upgrade Engine), after request (849), project state (850), plan (851), change proposal (852) and policy gate (854).
Module: `upgrade/change_set.py` - a small, deterministic, purely DECLARATIVE layer that converts an ALLOWED change proposal into an isolated change set for a future sandboxed application stage. It is not a sandbox or executor: it creates no directory/file, copies nothing, applies or generates no patch/diff/source code, runs no command/test, reads/scans no filesystem, touches no capability, Core, Memory, AEL, LLM or network, and never modifies the real project. Nothing is added, removed, inferred or repaired.

## Change set (exactly four keys)
`version` (`"1"`), `proposal_id` (the proposal's `plan_id`, text <= 64), `changes` (non-empty, <= 16 exact dicts `change_id` / `action` / `target` / `reason`, non-empty bounded text, unique ids, action one of `modify_file` / `update_capability`), `execution_allowed` (exactly False). No `executed` key in the set.

## API
- `build_change_set(change_proposal, policy_result)` -> `{valid, errors, change_set, execution_allowed, executed}`. The proposal must pass `validate_change_proposal` (852) and the policy result `validate_upgrade_policy_result` (854); the policy result must be `allowed` / True and must correspond to the proposal: its `proposal_id` equals the proposal's `plan_id` and it equals `evaluate_upgrade_policy(proposal)`, so a forged or stale "allowed" is refused. `changes` are fresh, unchanged copies of the proposal's changes in the same order.
- `validate_change_set(change_set)` -> `{valid, errors, execution_allowed, executed}`. Exact keys/types, bounds, unique ids, supported actions, `execution_allowed` False; reuses the 852 change checker.

Build errors: `invalid_change_proposal`, `invalid_policy_result`, `policy_not_allowed`, `policy_proposal_mismatch`, or the validation errors of the produced set (e.g. `unsupported_change_action`). `errors` is `[{code, where}]`, at most 16, fixed order. `execution_allowed` and `executed` are always False in every result.

Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the change set.

Tests: `tests/test_change_set_prompt855.py` (28 tests: valid set, order/copies, denied policy, invalid proposal/policy, mismatch/forged policy, unsupported action, oversized input, malformed set/change/target/reason, duplicate id, execution attempts, imports/no-I/O).
