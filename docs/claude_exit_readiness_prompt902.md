# Prompt 902 — Claude Exit Readiness Contract (Section 18 start)

Section 18 (Claude Exit / Autonomy Validation) starts with this contract. It is a
deterministic, read-only **description** of whether a capability-evolution request is
structurally ready to continue to the next controlled internal stage without asking Claude to
design the missing architecture.

This is **not** autonomous execution. Nothing implements, generates code, modifies files or
capabilities, self-modifies, persists, executes, uses the network, a subprocess or an external
AI / Claude API.

## Files

- `app/src/main/python/autonomy/claude_exit_readiness.py`
- `app/src/main/python/tests/test_claude_exit_readiness_prompt902.py`
- `docs/claude_exit_readiness_prompt902.md`

No existing production module is modified.

## Public API

- `build_claude_exit_readiness(authority_descriptor, scope_descriptor, <16 Section 16 chain
  objects>, request_validation_result, policy, approval_request,
  approval_request_validation_result, decision, decision_validation_result)` — same 24
  arguments as Prompt 900.
- `validate_claude_exit_readiness(result)` -> `{"valid", "errors", "execution_allowed", "executed"}`.

## Statuses

`ready_without_claude`, `not_ready`, `invalid_context`, `context_mismatch`,
`unsupported_operation`, `forbidden_execution_state`, `validation_error`.
There is no "approved" or "authorized" status.

## Result (14 keys)

`version` (int 1), `status`, `valid`, `claude_independent`, `request_id`,
`implementation_request_id`, `capability_name`, `operation`, `reason`,
`missing_requirements`, `implementation_allowed`, `execution_allowed`,
`implementation_started`, `executed`.

`valid` and `claude_independent` are True only for `ready_without_claude`.
`implementation_allowed`, `execution_allowed`, `implementation_started` and `executed` are
**always False**. `claude_independent=True` is **descriptive** readiness only: it never grants
implementation or execution. Identity fields are filled only for the ready status.

## Readiness dimensions (missing_requirements entries)

request_identity_consistent, capability_identity_consistent, operation_supported,
analysis_valid, specification_valid, definition_readiness_valid, implementation_design_valid,
implementation_blueprint_valid, implementation_contract_valid, implementation_boundary_valid,
implementation_request_valid, implementation_request_validation_valid,
controlled_autonomy_policy_valid, approval_request_valid, approval_decision_valid,
authority_scope_context_valid, no_forbidden_execution_state (plus `context_consistent` and
`evaluation_completed` for generic failures). Exactly one requirement — the first failing
prerequisite — is reported for any non-ready status; `[]` when ready.

## Evaluation order

1. Any permission/execution flag set in any supplied object -> `forbidden_execution_state`.
2. request_id / capability_name / operation differing between stages -> `context_mismatch`.
3. Section 16 chain re-derived by the Prompt 892 validator; unsupported -> `unsupported_operation`,
   forged -> `context_mismatch`, missing/invalid -> `not_ready`.
4. Supplied Prompt 892 result must equal the derived one (never trusted for `valid=True`).
5. Policy, approval request and decision re-derived with the real Prompt 894-896 builders.
6. Prompt 897 decision context, then the Prompt 898 authority and Prompt 899 scope validators.
7. Otherwise `ready_without_claude`. Unexpected failures -> `validation_error`.

## Scope statement

Section 18 has only started with this contract. No autonomous implementation has been enabled.
Section 16 and Section 17 behavior is unchanged.
