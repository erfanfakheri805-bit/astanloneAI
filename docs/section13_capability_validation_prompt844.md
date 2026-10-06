# Prompt 844 - Capability Validation Foundation

Fourth step of Section 13 (Capability System).
Module: `capabilities/capability_validation.py` - ONE read-only function, `validate_capability(descriptor, lifecycle_state=<omitted>)`, that composes the existing layers. It adds no rules of its own: descriptor structure comes from Prompt 841 (`validate_capability_descriptor`), the version check from Prompt 842 (`parse_capability_version`, and `build_capability_identity` for a fully valid descriptor), the optional lifecycle state check from Prompt 843 (`validate_lifecycle_state`). Nothing is registered, replaced, enabled, disabled, deprecated, executed or mutated; nothing is invented, normalised or inferred. No registry is used. No Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem.

Result (fixed keys, in order, JSON-safe, fresh on every call):
`valid, errors, name, version, identity_valid, version_valid, lifecycle_valid, truncated, execution_allowed, executed`
- `valid`: descriptor structurally valid (841) AND, if a lifecycle state was supplied, it is a lifecycle state (843).
- `errors`: `[{code, where}]`, at most 16, in this order: the Prompt 841 descriptor errors unchanged (same codes and locations, e.g. `missing_field`/`name`, `invalid_version`/`version`, `unexpected_field`/`handler`), then the Prompt 843 lifecycle error (`invalid_state_type` or `unknown_state`, located at `lifecycle_state`). Defined here: `validation_error`/`descriptor` if this function fails internally (841 itself reports `validator_error`). `truncated` is True when more were found.
- `name` / `version`: the descriptor's name / capability version only when each is valid, else None (an invalid value is never echoed or normalised).
- `identity_valid`: the name is a valid identity (841 name rule). `version_valid`: 842 accepts the version (False when absent or not a dict). The flags are independent of each other: a malformed purpose leaves both True while `valid` is False.
- `lifecycle_valid`: None when the argument is omitted (no check), else True/False. An explicit `None` is validated and is an `invalid_state_type`. The state is never inferred from or cross-checked with the descriptor (its `enabled` flag, name, version, ...).
- `execution_allowed` and `executed`: always False; a valid result never implies execution.

Bounded (841 limits; huge inputs cost the same as small ones), deterministic, never raises. The descriptor structure and all Registry (841), Identity/Version (842) and Lifecycle (843) APIs and behaviour are unchanged; none of them imports this module.
Tests: `tests/test_capability_validation_prompt844.py` (56 tests: valid descriptors, malformed descriptors, invalid versions, invalid lifecycle states, combined failures, truncation, isolation, boundaries, backward compatibility).
Known baseline note: the same 8 frozen-tree tests (Section 6 / Section 9 byte-freeze checks) that already fail on the unmodified Prompt 840 tree still fail identically; they are unchanged.
