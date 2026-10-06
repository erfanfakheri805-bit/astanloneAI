# Prompt 845 - Capability Discovery and Matching Foundation

Fifth step of Section 13 (Capability System).
Module: `capabilities/capability_matching.py` - ONE read-only function, `match_capability(requirement, registry)`, that looks for a capability in an explicitly supplied `CapabilityRegistry` (Prompt 841) and reports whether an exact, valid match exists. It adds no rules of its own: descriptor validity comes from Prompt 844 (`validate_capability`, which composes Prompt 841), version checks from Prompt 842 (`compare_capability_versions`, `parse_capability_version`, `build_capability_identity`). Nothing is registered, replaced, enabled, disabled, executed or mutated. No Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem; no global registry.

## Requirement
A plain dict, only these keys: `name` (required), `minimum_version`, `required_inputs`, `expected_outputs` (optional).
- `name`: exact string equality with the registered name only. No trimming, case folding, prefix, substring, alias, fuzzy or semantic matching; capabilities are never inferred from inputs/outputs.
- `minimum_version`: exact int 1..MAX_VERSION (Prompt 842 rule); candidate version must be equal or newer.
- `required_inputs`: unique identifiers (<= 16); each must be among the candidate's declared `inputs` (it may declare more).
- `expected_outputs`: unique identifiers (<= 16); each must be among the candidate's declared `outputs`.
- An omitted key and an empty list mean "no such requirement"; an explicit None is malformed. Unexpected keys are rejected.

## Discovery
Only the supplied registry is read (exact `CapabilityRegistry` type; its entries are read, never changed). Scan is bounded to `MAX_SCAN` (256) entries in name order. A candidate is an entry whose key or descriptor name equals the requirement name. The `enabled` flag is not a criterion and is only returned as part of the descriptor. A registry holds one descriptor per name, so a normal registry yields at most one candidate; several candidates can only appear if the private store was altered (those are validated and rejected individually).

## Result (fixed keys, JSON-safe, fresh every call)
`status, matched, candidate_count, matches, rejected, truncated, execution_allowed, executed`
- `status`: `matched` / `no_match` (no candidate with that exact name) / `no_valid_match` (candidates exist, all rejected) / `invalid_requirement` / `invalid_registry` / `matching_error`.
- `matches` (<= 16): `{identity: {name}, version, descriptor}` - a fresh copy of the explicitly registered descriptor; nothing else.
- `rejected` (<= 16): `{subject, name, version, reasons}`; reasons are `{code, where}` (<= 16): the Prompt 844 validation errors unchanged, `registry_key_mismatch`/`registry`, `descriptor_name_mismatch`/`name`, `version_below_minimum`/`minimum_version`, `required_input_missing`/`required_inputs[i]`, `expected_output_missing`/`expected_outputs[i]`, or the requirement/registry problems. A malformed value is never echoed.
- `truncated`: scan bound reached or any bounded list cut. `execution_allowed` and `executed`: always False.

Deterministic, bounded, never raises. All Registry (841), Identity/Version (842), Lifecycle (843) and Validation (844) APIs and behaviour are unchanged; none of them imports this module.

## Note on an existing behaviour (not changed)
The Prompt 841 identifier pattern ends in `$`, so a name with one trailing newline (e.g. `"text_summary\n"`) is accepted as a valid name. Matching stays exact string equality, so such a name can never select the plain name; it is only reported here, not altered.

Tests: `tests/test_capability_matching_prompt845.py` (79 tests: exact match, version constraints, input/output requirements, multiple candidates, no match, malformed requirements, invalid registry/entries, determinism/safety, boundaries, backward compatibility).
