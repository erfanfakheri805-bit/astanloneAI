# Prompt 838 - Capability Contract Foundation

Module: `reasoning/capability_contract.py` - `build_capability_contract(decision, spec=None)` and `validate_capability_contract(contract)`.
It receives a validated reasoning decision (Prompt 837 `decide_reasoning`) and turns explicitly supplied capability information into a contract. Nothing is executed, registered or modified; no capability, tool or implementation detail is ever invented. No existing module, NLU API or reasoning API is changed.

Contract keys (fixed order): `version, name, purpose, required_inputs, expected_outputs, constraints, execution_allowed` (always `False`).
- `name`: lowercase snake_case, 1..64 chars, supplied as-is (never normalised or derived).
- `purpose`: non-empty text <= 200 chars, no outer whitespace, no control characters.
- `required_inputs` (may be empty) / `expected_outputs` (at least one): unique snake_case identifiers, <= 16 items.
- `constraints` (may be empty): unique texts <= 120 chars, <= 16 items.

Spec: dict with `name, purpose, required_inputs, expected_outputs, constraints` (`version` and `execution_allowed=False` tolerated). Any other key (tool, implementation, handler, ...) is rejected as `unexpected_field` and never kept; `execution_allowed` other than `False` is rejected.

Build result keys: `version, status, reason, contract, validation, executed` (always `False`).
- `built` / `built`: validated contract in `contract`.
- `unknown`: decision missing, malformed, executed, not validated or `invalid_plan` (`decision_invalid`); or no spec (`capability_unspecified`). Nothing is created.
- `insufficient`: decision is `needs_clarification` / `needs_information` (reason = that decision). Nothing is created.
- `incomplete`: spec lacks required fields (all errors `missing_field`).
- `invalid`: spec is not a dict (`spec_not_dict`) or fails validation (reason = first error code).
Only a `ready` decision lets a contract be built; the decision supplies no capability information.

Validation result keys: `version, valid, status, error_count, errors, truncated`; errors `{code, where}` in discovery order, no duplicates, <= 16.
Error codes: `contract_not_dict, missing_field, unexpected_field, invalid_version, invalid_name, invalid_purpose, invalid_required_inputs, invalid_expected_outputs, invalid_constraints, no_expected_outputs, too_many_items, invalid_item, duplicate_item, execution_allowed_not_false, validator_error`.

Bounded (<= 8+1 fields and <= 16 items per list examined), read-only, deterministic, fresh (deep-copied) results, never raises. Pure stdlib; no Memory, AEL, Core, LLM or network.
Tests: `tests/test_capability_contract_prompt838.py` (47 tests).
