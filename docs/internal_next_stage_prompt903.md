# Prompt 903 — Internal Next-Stage Readiness (Section 18)

Converts a validated Prompt 902 `ready_without_claude` result into a deterministic description of
the next controlled internal stage. Planning / readiness only.

It does **not** execute anything, modify source code, generate executable code, grant
implementation or execution permission, access Claude or any external AI, use the network or the
filesystem, or modify the project. `ready_for_internal_stage` does **NOT** mean implementation is
allowed; it only says the request passed the current structural readiness boundary.

## Files

- `app/src/main/python/autonomy/internal_next_stage.py`
- `app/src/main/python/tests/test_internal_next_stage_prompt903.py`
- `docs/internal_next_stage_prompt903.md`

No existing production module is modified.

## Public API

- `build_internal_next_stage(readiness, expected_identity=None)` — `expected_identity` is an
  optional dict of any of the four identity keys; a difference gives `context_mismatch`.
- `validate_internal_next_stage(result)` -> `{"valid", "errors", "execution_allowed", "executed"}`.

## Statuses (evaluation order)

| status | when |
|---|---|
| `forbidden_execution_state` | any permission/execution flag truthy at any depth |
| `invalid_readiness` | not a dict, malformed, or forged (fails the real Prompt 902 validator, incl. `claude_independent=False` or `valid=False` on a ready status) |
| `context_mismatch` | `expected_identity` differs from the readiness identity |
| `not_ready` | structurally valid Prompt 902 result that is not `ready_without_claude` |
| `ready_for_internal_stage` | `ready_without_claude`, `valid`, `claude_independent` |
| `validation_error` | unexpected internal failure |

## Result (13 keys)

`version` (int 1), `status`, `valid`, `request_id`, `implementation_request_id`,
`capability_name`, `operation`, `next_stage`, `reason`, `implementation_allowed`,
`execution_allowed`, `implementation_started`, `executed`.

For the ready status `next_stage = "controlled_internal_evolution"`; all four flags are always
`False`. Rejected results carry `None` identity and `None` next_stage.
