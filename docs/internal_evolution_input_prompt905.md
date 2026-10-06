# Prompt 905 — Internal Evolution Input Contract (Section 18)

Defines the minimal deterministic **input contract** for the existing
`controlled_internal_evolution` stage: WHAT information that stage would receive, built from a
valid Prompt 904 `stage_ready` result.

This is a descriptive contract only. It does **NOT** implement or execute the evolution stage,
modify source code, generate code, grant implementation/execution permission or approval, call
Claude or any external AI, or use the network or filesystem. It contains no source code, patches,
commands, executable instructions, API keys, URLs or service calls — only fixed descriptive
labels. `implementation_allowed`, `execution_allowed`, `implementation_started` and `executed` are
always `False`.

## Files

- `app/src/main/python/autonomy/internal_evolution_input.py`
- `app/src/main/python/tests/test_internal_evolution_input_prompt905.py`
- `docs/internal_evolution_input_prompt905.md`

No existing production module is modified.

## Public API

- `build_internal_evolution_input(stage_decision, expected_identity=None)`
- `validate_internal_evolution_input(result)` -> `{"valid", "errors", "execution_allowed", "executed"}`;
  independently re-verifies every field and never trusts `valid`.

## Statuses (evaluation order)

| status | when |
|---|---|
| `forbidden_execution_state` | any permission / execution / approval flag truthy at any depth |
| `invalid_stage_decision` | not a dict, malformed, forged (fails the real Prompt 904 validator), or wrong stage |
| `context_mismatch` | `expected_identity` differs from the decision identity |
| `not_ready` | structurally valid Prompt 904 result that is not `stage_ready` |
| `ready` | `stage_ready`, valid, correct decision and `next_stage` |
| `validation_error` | unexpected internal failure |

## Result (16 keys)

`version`, `status`, `valid`, `request_id`, `implementation_request_id`, `capability_name`,
`operation`, `stage`, `goal`, `inputs`, `outputs`, `constraints`, `implementation_allowed`,
`execution_allowed`, `implementation_started`, `executed`.

For `ready`:

- `stage = "controlled_internal_evolution"`, `goal = "controlled_capability_evolution"`
- `inputs`: `validated_capability_context`, `validated_evolution_request`, `validated_stage_decision`
- `outputs`: `future_evolution_result_description` (a future result, not executable code)
- `constraints`: `no_automatic_execution`, `no_automatic_self_modification`,
  `no_external_ai_dependency`, `controlled_validation_required`

Rejected results carry `None` identity/stage/goal and empty lists.
