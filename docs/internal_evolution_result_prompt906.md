# Prompt 906 — Internal Evolution Result Contract (Section 18)

Defines the minimal deterministic **result contract** for the future `controlled_internal_evolution`
stage: WHAT it would report after evaluating a capability-evolution request. Built from a valid
Prompt 905 `ready` input result.

This is descriptive only. It does **NOT** perform the evolution, generate source code or patches,
modify files, execute commands or capabilities, grant implementation/execution permission, call
Claude or any external AI, or use the network or filesystem. `evaluated` does **NOT** mean the
capability was implemented or improved — only that a structured evaluation result was produced.
`implementation_allowed`, `execution_allowed`, `implementation_started` and `executed` are always
`False`. No field contains code, patches, commands, keys, URLs or service references.

## Files

- `app/src/main/python/autonomy/internal_evolution_result.py`
- `app/src/main/python/tests/test_internal_evolution_result_prompt906.py`
- `docs/internal_evolution_result_prompt906.md`

No existing production module is modified.

## Public API

- `build_internal_evolution_result(evolution_input, expected_identity=None)`
- `validate_internal_evolution_result(result)` -> `{"valid", "errors", "execution_allowed", "executed"}`;
  independently re-verifies every field and never trusts `valid`.

## Statuses (evaluation order)

| status | when |
|---|---|
| `forbidden_execution_state` | any permission / execution / approval flag truthy at any depth |
| `invalid_evolution_input` | not a dict, malformed, forged (fails the real Prompt 905 validator), wrong stage, or code-like identity text |
| `context_mismatch` | `expected_identity` differs from the input identity |
| `not_ready` | structurally valid Prompt 905 result that is not `ready` |
| `evaluated` | `ready`, valid, correct stage |
| `validation_error` | unexpected internal failure |

## Result (16 keys)

`version`, `status`, `valid`, `request_id`, `implementation_request_id`, `capability_name`,
`operation`, `stage`, `result_type`, `summary`, `requirements_met`, `requirements_missing`,
`implementation_allowed`, `execution_allowed`, `implementation_started`, `executed`.

For `evaluated`:

- `stage = "controlled_internal_evolution"`, `result_type = "descriptive_evaluation"`
- `summary`: fixed sentence stating this is a descriptive evaluation only and nothing was
  implemented, improved or executed
- `requirements_met`: `stage_decision_validated`, `evolution_input_validated`,
  `identity_context_consistent`, `execution_constraints_preserved`
- `requirements_missing`: `implementation_permission`, `execution_permission`,
  `controlled_validation_of_future_result`

Rejected results carry `None` identity/stage/result_type/summary and empty lists.
