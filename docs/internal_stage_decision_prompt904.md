# Prompt 904 — Controlled Internal Stage Decision (Section 18)

A small deterministic **descriptive** decision over a Prompt 903 `ready_for_internal_stage`
result: may the system proceed to the next controlled internal stage
(`controlled_internal_evolution`)?

`stage_ready` is a planning / readiness decision only. It does **NOT** mean implementation is
allowed, execution is allowed, approval was granted, or code may be changed. Nothing here
implements, executes, modifies, generates or authorizes anything, calls Claude or any external AI,
or uses the network or filesystem. `implementation_allowed`, `execution_allowed`,
`implementation_started` and `executed` are always `False`.

## Files

- `app/src/main/python/autonomy/internal_stage_decision.py`
- `app/src/main/python/tests/test_internal_stage_decision_prompt904.py`
- `docs/internal_stage_decision_prompt904.md`

No existing production module is modified.

## Public API

- `build_internal_stage_decision(next_stage, expected_identity=None)` — `expected_identity` is an
  optional dict of any of the four identity keys; a difference gives `context_mismatch`.
- `validate_internal_stage_decision(result)` -> `{"valid", "errors", "execution_allowed", "executed"}`;
  independently re-verifies every field and never trusts the `valid` field.

## Statuses (evaluation order)

| status | when |
|---|---|
| `forbidden_execution_state` | any permission / execution / approval flag truthy at any depth |
| `invalid_next_stage` | not a dict, malformed, forged (fails the real Prompt 903 validator), or wrong `next_stage` |
| `context_mismatch` | `expected_identity` differs from the result identity |
| `not_ready` | structurally valid Prompt 903 result that is not `ready_for_internal_stage` |
| `stage_ready` | `ready_for_internal_stage`, `valid`, `next_stage = controlled_internal_evolution` |
| `validation_error` | unexpected internal failure |

## Result (14 keys)

`version` (int 1), `status`, `valid`, `decision`, `request_id`, `implementation_request_id`,
`capability_name`, `operation`, `next_stage`, `reason`, `implementation_allowed`,
`execution_allowed`, `implementation_started`, `executed`.

For `stage_ready`: `decision = "proceed_to_controlled_internal_stage"`,
`next_stage = "controlled_internal_evolution"`. Rejected results carry `None` decision, identity
and next_stage.
