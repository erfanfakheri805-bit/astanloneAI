# Prompt 846 - Capability Selection

Sixth step of Section 13 (Capability System).
Module: `capabilities/capability_selection.py` - ONE small read-only function, `select_capability(match_result)`, that picks at most one capability from the result of the Prompt 845 `match_capability()`. It does no matching: candidates come only from `match_result["matches"]`; descriptor validity is Prompt 844 `validate_capability`, version parsing/ordering is Prompt 842 (`parse_capability_version`, `compare_capability_versions`), identity is Prompt 842 `build_capability_identity`. Nothing is executed, registered, enabled, disabled, replaced or modified; nothing is invented. No registry is used. No Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem.

## Input check
The match result must be exactly the eight Prompt 845 keys: status known and in agreement with `matched`, exact-int `candidate_count`, `matches`/`rejected` lists (<= 16 matches), bool `truncated`, `execution_allowed` and `executed` False, a non-"matched" result without matches, a "matched" result with at least one. Every match must be exactly `{identity: {name}, version, descriptor}` with a valid descriptor (844), a valid version equal to the descriptor version (842) and an identity equal to the 842 identity of the descriptor. One bad match makes the whole input `invalid_input`; nothing is skipped or repaired.

## Selection order
1. highest valid version (842 comparison; numeric);
2. exact identity: every match already has an identity exactly equal to the 842 identity of its descriptor (checked above), so no similarity or guessing is ever used;
3. stable name order (code point order of the name); if still tied, the first tied match in the supplied order.
A single match is selected as `unique_match`.

## Result (fixed keys, JSON-safe, fresh every call)
`status, selected, candidate_count, reason, execution_allowed, executed`
- `status`: `selected` / `not_selected` (the result holds no valid match) / `invalid_input`.
- `selected`: a fresh copy of the explicitly matched entry `{identity, version, descriptor}`, else None.
- `candidate_count`: matches considered (0 unless selected).
- `reason`: `unique_match` / `highest_version` / `name_order`; for not_selected the Prompt 845 status (`no_match`, `no_valid_match`, `invalid_requirement`, `invalid_registry`, `matching_error`); for invalid_input `invalid_match_result`.
- `execution_allowed`, `executed`: always False.

Deterministic, bounded, never raises. Registry (841), Identity/Version (842), Lifecycle (843), Validation (844) and Matching (845) APIs and behaviour are unchanged; none of them imports this module.

Note: a registry holds one descriptor per name and `match_capability()` rejects key/name mismatches, so a real Prompt 845 result normally has at most one match; the multi-match ordering applies to any well-formed match result (tests build them explicitly).

Tests: `tests/test_capability_selection_prompt846.py` (43 tests: unique match, multiple versions, tie-breaking, no match, malformed input, freshness/safety, boundaries, backward compatibility).
