# Prompt 830 - Semantic Slot Relations

Module: `understanding/nlu_relations.py` (`extract_relations`, `extract_relations_from_analysis`).
Exposed as the last key `relations` of `NLUAnalysis.normalized()` (after `slots`; `schema_version` stays 1).

Relation kinds (explicit only): `name_ownership` (owner phrase + name), `key_value` (key -> value),
`request_target` (request action -> argument), `quoted_target` (request action -> quoted text that is the whole argument).

Each relation: `kind, subject, relation, value, slot, start, end`. Output: `{version, items, count, truncated, ambiguous}`.

Skipped, never guessed (counted in `ambiguous` when a candidate existed): name without owner phrase, request prohibition,
same key with different values, several quoted slots with none the whole argument, request without action/argument.

Bounds: 16 relations. Pure, deterministic, JSON-safe, no Memory, no storage, no changes to existing slots/fields.
Tests: `tests/test_nlu_relations_prompt830.py` (34 tests).
