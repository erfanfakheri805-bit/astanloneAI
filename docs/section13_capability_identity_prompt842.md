# Prompt 842 - Capability Identity and Versioning

Second step of Section 13 (Capability System).
Module: `capabilities/capability_identity.py` - a read-only, deterministic identity/version layer on top of the Prompt 841 descriptor and registry. It describes and compares only: it never registers, replaces, upgrades, downgrades or executes anything, and it does not use a registry instance at all. `capabilities/capability_registry.py` is unchanged (it does not import this module).

API (all non-raising, JSON-safe, fresh results, `executed` always False):
- `parse_capability_version(value)` -> `{version, valid, number, errors, truncated, executed}`
- `compare_capability_versions(left, right)` -> `{version, valid, relation, left, right, errors, truncated, executed}`
- `build_capability_identity(descriptor)` -> `{version, valid, identity, errors, truncated, executed}`
- `compare_capability_identities(left, right)` -> `{version, valid, relation, errors, truncated, executed}`
- `classify_capability_descriptors(existing, candidate)` -> `{version, classification, identity_match, version_relation, content_identical, existing_name, candidate_name, errors, truncated, executed}`

Version format (the existing descriptor `version` field, unchanged): an exact `int`, 1..1000000. bool, int subclasses, floats, strings ("1", "1.0", "v1"), None and out-of-range numbers are malformed (`invalid_version_type` / `version_out_of_range`); nothing is coerced or parsed from text. Ordering is numeric. `compare_capability_versions` gives `relation` of `left` to `right`: `equal`, `newer`, `older` (None when either side is invalid, with errors located at `left` / `right`).

Identity: `{"name": <exact name>}` of a structurally valid (Prompt 841) descriptor. Version, purpose, inputs, outputs, constraints and enabled are not part of the identity. Names are compared by exact equality only; no trimming, case folding, normalisation or fuzzy matching (a name needing that is an invalid descriptor, so variants such as `Text_Summary` or `text_summary ` are `invalid`, never "the same"). Identity comparison: `same`, `different` or None (invalid).

Classification of `candidate` relative to `existing`:
- `same_version` - same identity, same version
- `newer_version` - same identity, candidate version higher
- `older_version` - same identity, candidate version lower
- `different_identity` - different names
- `invalid` - either descriptor is not structurally valid (errors located as `existing.<field>` / `candidate.<field>`; nothing else is concluded)
`content_identical` is True/False for the three same-identity classes (whole descriptor equal?) and None otherwise. The classification is advice only; no action follows from it. The registry still treats a same-name, different-version registration as a `conflict` (Prompt 841 behaviour).

Bounded (Prompt 841 limits, at most 16 errors with `truncated`), read-only with respect to inputs, deterministic, never raises. Pure stdlib plus the Prompt 841 module. No Core, Memory, AEL, NLU, reasoning, execution, LLM, network or filesystem.
Tests: `tests/test_capability_identity_prompt842.py` (54 tests).
Known baseline note: the same 8 frozen-tree tests (Section 6 / Section 9 byte-freeze checks) that already fail on the unmodified Prompt 840 tree still fail identically; they are unchanged.
