# Prompt 840 - Reasoning-to-Capability Boundary Checkpoint

Final small checkpoint of the Reasoning & Planning foundation.
Module: `reasoning/capability_boundary.py` - `evaluate_reasoning_capability_boundary(decision, spec=None, integrator=integrate_capability_contract)`.
It reuses the Prompt 839 `integrate_capability_contract` and `classify_capability_result`; it contains no decision, spec or contract logic of its own. No NLU, reasoning, capability-contract (838) or integration (839) API is changed. `integrator` is only a seam for testing against a faulty integration.

Chain: NLU analysis -> reasoning input/request (834) -> plan (835) -> plan validation (836) -> decision (837) -> capability contract (838) -> integration + classifier (839) -> boundary (840).

Result keys (fixed order): `version, decision_state, capability_classification, contract_valid, execution_allowed, next_stage, reason, executed`.
- `decision_state`: `ready`, `needs_clarification`, `needs_information`, `invalid` (unusable decision / invalid plan), `unknown` (unusable integration result).
- `capability_classification`: `decision_not_ready`, `spec_missing`, `spec_invalid`, `contract_valid`, `integration_error`.
- `contract_valid`: True only when a validated contract exists. `execution_allowed` and `executed`: always False.
- `next_stage` is only one of `clarify`, `request_information`, `capability_definition`, `capability_system`.
- `reason`: the Prompt 838 build reason (e.g. `built`, `decision_invalid`, `capability_unspecified`, `missing_field`); `boundary_error` in the safe result.

Mapping: needs_clarification -> `clarify`; needs_information / invalid decision -> `request_information`; spec_missing / spec_invalid / integration_error -> `capability_definition`; contract_valid -> `capability_system`.
`capability_system` only when `contract_valid` is True; anything that would break this (faulty integrator: raises, malformed result, "built" without a valid contract) yields the safe result `{decision_state: unknown, capability_classification: integration_error, contract_valid: False, next_stage: capability_definition, reason: boundary_error}`.

The boundary only describes the next stage: nothing is executed, registered, installed, repaired, modified or invented, and the contract itself, capability names, tools and handlers are not carried in the result. Bounded, JSON-safe, deterministic, fresh, non-raising. No Memory, AEL, Core, LLM or network.
Tests: `tests/test_capability_boundary_prompt840.py` (30 tests).
