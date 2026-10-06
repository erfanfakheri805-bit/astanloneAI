# Prompt 907 — Controlled Internal Evolution Result Validation (Section 18)

One small deterministic validation layer for the Prompt 906 internal evolution result contract.

Descriptive validation only. It does **NOT** implement, execute, modify, generate or authorize
anything, grants no approval or permission, calls no Claude / external AI / API, and uses no
network or filesystem. `implementation_allowed`, `execution_allowed`, `implementation_started` and
`executed` are always `False` in its output.

## Files

- `app/src/main/python/autonomy/internal_evolution_result_validation.py`
- `app/src/main/python/tests/test_internal_evolution_result_validation_prompt907.py`
- `docs/internal_evolution_result_validation_prompt907.md`

No existing production module is modified.

## Public API

`validate_internal_evolution_result_context(result, expected_identity=None)`

The input's `valid` field is never trusted: validity is re-derived from the actual fields — the real
Prompt 906 validator, exact `evaluated` status, stage, result_type, summary and requirement labels
(missing / unexpected requirements reported separately), identity text rules, a forbidden-state
scan, and a code-like / external-service scan of identity text and requirement labels.

## Statuses (evaluation order)

| status | when |
|---|---|
| `forbidden_execution_state` | any permission / approval / execution flag truthy at any depth |
| `invalid_result` | malformed, forged, not `evaluated`, wrong stage/result_type, wrong requirements, code-like or external-service content |
| `context_mismatch` | `expected_identity` differs from the result identity (or is malformed) |
| `valid` | all checks pass |
| `validation_error` | unexpected internal failure |

## Output (15 keys)

`version`, `status`, `valid`, `request_id`, `implementation_request_id`, `capability_name`,
`operation`, `stage`, `result_type`, `errors` (list of `{code, where}`, bounded), `warnings`
(always `[]`), and the four always-`False` flags. Identity, stage and result_type are copied only
for `valid`.
