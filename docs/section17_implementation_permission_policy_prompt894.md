# Prompt 894 - Section 17: Implementation Permission Policy

First layer of Section 17 (Controlled Autonomy). New module: `autonomy/implementation_permission_policy.py` (`build_implementation_permission_policy`, `validate_implementation_permission_policy`). It is deterministic, read-only and side-effect free. No Section 16 module, test or historical manifest was changed.

## Why Section 17 exists

Section 16 ended with a validated planning/contract/request chain (Prompts 876-892) and explicitly no authority to act. Section 17 adds the controlled steps that may one day sit between "validated request" and "implementation", one small, auditable gate at a time. Prompt 894 is the first gate: a policy that only *describes* whether the request may be considered for a later approval step.

## Eligibility vs permission vs execution

- **Eligible** - every upstream condition holds and is consistent, so the request *may be considered* by a future controlled approval step. It is a statement about the data, nothing more.
- **Permission** - an explicit approval to implement. Nothing in Prompt 894 grants it: `implementation_allowed` is always `False`.
- **Execution** - actually running something. `execution_allowed`, `implementation_started` and `executed` are always `False`.

`eligible=True` therefore never means "implementation allowed" and never means "execution allowed". The validator rejects any policy, eligible or not, in which one of the four flags is not exactly `False`.

## Inputs and checks

The builder takes the Section 16 chain (request through Prompt 891 implementation request, including the 879 evolution validation, 883 definition readiness, 889 contract readiness and 890 boundary objects), the Prompt 892 validation result, a caller-supplied `policy_id` and an optional `permission_state`. The chain is judged by the existing Prompt 892 context validation, which reuses the Prompt 876-891 validators; no validation rule is duplicated. The supplied 892 result must be valid and must equal the result derived from the chain (a forged one gives `context_mismatch`).

## Statuses

`eligible`, `ineligible`, `blocked`, `unsupported`, `invalid_request`, `invalid_request_validation`, `invalid_boundary`, `invalid_contract`, `invalid_contract_readiness`, `invalid_definition_readiness`, `context_mismatch`, `validation_error`.

Mapping of the first failing Prompt 892 stage: invalid evolution or implementation request -> `invalid_request`; analysis, specification, 879 validation, plan, proposal, candidate, 883 readiness -> `invalid_definition_readiness`; design through contract validation -> `invalid_contract`; 889 -> `invalid_contract_readiness`; 890 -> `invalid_boundary`. An invalid or malformed `policy_id`, or a malformed `permission_state`, gives `validation_error`.

## Supported operations, conflict and blocked behaviour

- Supported: `create` (analysis `create_required`) and `improve` (analysis `improve_required`).
- `improve_or_conflict` is never supported: it yields `unsupported` and no downstream chain is evaluated.
- `blocked`: the chain is valid, but the optional `permission_state` (exactly the four flags, all bool) records that an implementation or execution permission, a start or an execution already exists.
- `ineligible`: the chain is valid but the request is not inside the controlled-autonomy boundary (boundary not `ready`, unsupported operation/analysis pair). Upstream validators already reject these cases, so this is a fail-closed guard that real inputs do not currently reach.

## Policy shape

Exactly 13 keys: `version` (int `1`), `policy_id`, `request_id`, `implementation_request_id`, `capability_name`, `operation`, `status`, `reason` (equals status), `eligible`, `implementation_allowed`, `execution_allowed`, `implementation_started`, `executed`. Identity comes only from trusted objects; `implementation_request_id` is set only for `eligible`, `blocked` and `ineligible`. No UUIDs or timestamps are generated.

## Safety invariants

No filesystem I/O, network, API/model client, subprocess, `exec`/`eval`/`compile`, Memory/AEL/registry mutation, project modification, code or patch generation, automatic execution or self-modification. Imports are limited to `capabilities.*` modules; the module defines no classes. Inputs are never modified; every call returns a fresh object; results do not depend on time, randomness or environment.

## Why Prompt 894 still cannot implement anything

The policy emits data only. It has no code path that writes, generates, loads or runs anything, and it cannot set any permission flag to `True`. Granting permission, if it ever exists, belongs to a later, separately specified step.
