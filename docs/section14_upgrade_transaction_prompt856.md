# Prompt 856 - Upgrade Transaction Boundary

Seventh step of Section 14 (Self-Upgrade Engine), after request (849), project state (850), plan (851), change proposal (852), policy gate (854) and change set (855).
Module: `upgrade/upgrade_transaction.py` - a small, deterministic, purely DECLARATIVE record of the lifecycle of a pending upgrade transaction for a future application process. It applies and executes nothing: no project file is modified, no backup or directory created, no code/patch generated, no command/test run, no filesystem scan, no Core/Memory/AEL/LLM/network link. Nothing is invented or repaired.

## Transaction (exactly seven keys, fixed order)
`version` (`"1"`), `transaction_id` (`tx_` + first 16 hex of the SHA-256 of the change set's canonical JSON - the truncated-SHA-256 convention of `change_proposal.derive_plan_id`), `change_set_id` (the change set's `proposal_id`), `status` (`pending` / `committed` / `rolled_back`), `changes` (fresh copy of the change set's changes), `execution_allowed` (False), `executed` (False).

## API
- `begin_upgrade_transaction(change_set)` -> `{valid, errors, transaction, execution_allowed, executed}`. The change set must pass `validate_change_set` (855, reused); the new transaction is always `pending`. Error: `invalid_change_set`.
- `validate_upgrade_transaction(transaction)` -> `{valid, errors, execution_allowed, executed}`. Exact keys/types, version, status, bounded ids, the 855 change rules (reused checkers), flags exactly False, and `transaction_id` equal to the id derived from the change set rebuilt from `change_set_id` + `changes` (`transaction_id_mismatch` otherwise).
- `finalize_upgrade_transaction(transaction, success=False)` -> same shape as begin. Needs a valid transaction and an exact-bool `success`; only `pending` moves: True -> `committed`, False -> `rolled_back`. `committed` / `rolled_back` are never changed again (`transaction_already_finalized`). The input is never modified; the result holds a fresh copy. Errors: `invalid_transaction`, `invalid_success`, `transaction_already_finalized`.

Finalizing records a state only: `executed` stays False even when committed. `errors` is `[{code, where}]`, at most 16, fixed order. Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the transaction layer.

Tests: `tests/test_upgrade_transaction_prompt856.py` (27 tests: pending creation, deterministic identity, commit, rollback, already-finalized, invalid change set/transaction/success, mismatched identity, malformed changes, execution attempts, bounds, imports/no-I/O).
