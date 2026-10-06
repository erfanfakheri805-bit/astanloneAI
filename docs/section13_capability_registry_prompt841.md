# Prompt 841 - Capability Registry Foundation

First step of Section 13 (Capability System).
Module: `capabilities/capability_registry.py` - a small deterministic in-memory registry of explicitly defined capability descriptors. A descriptor only describes a capability; nothing is executed, inferred, invented, loaded or connected.

API (all non-raising, JSON-safe, fresh results, `executed` always False):
- `validate_capability_descriptor(descriptor)` -> `{version, valid, error_count, errors:[{code, where}], truncated}`
- `CapabilityRegistry().register(descriptor)` -> `{version, status, reason, name, errors, executed}`
- `CapabilityRegistry().lookup(name)` -> `{version, found, reason, descriptor, executed}`
- `CapabilityRegistry().list_capabilities()` -> `{version, count, capabilities, executed}`

Descriptor (exactly these keys): `name, version, purpose, inputs, outputs, constraints, enabled`.
- `name`: lowercase snake_case, 1..64 chars, never normalised or derived. It is the capability identity.
- `version`: int 1..1000000 (bool and int subclasses rejected).
- `purpose`: non-empty text <= 200 chars, no outer whitespace or control characters.
- `inputs`: unique snake_case identifiers (may be empty); `outputs`: unique snake_case identifiers (at least one); `constraints`: unique texts <= 120 chars (may be empty); each list at most 16 items.
- `enabled`: bool. A descriptor flag only; it never runs anything.
- Any other field (handler, tool, module, code, url, ...) is `unexpected_field` and rejected. Only exact built-in types are accepted (no subclasses).

Registration: `registered`, or `rejected` with reason `malformed` (invalid descriptor, validation errors listed), `duplicate` (same name, identical descriptor), `conflict` (same name, different version or content), `registry_full` (256 capabilities). The registry is unchanged unless `registered`. Entries are never replaced, updated or removed (no such API).

Lookup: exact name only (no trimming, case folding, prefix or fuzzy match). Reasons: `found`, `not_found`, `invalid_name`.
Listing: sorted by name (code point order), independent of registration order.
Isolation: descriptors are stored as private fixed-order copies and returned as deep copies; mutating a result or the originally registered dict never changes the registry. Each registry instance is independent; there is no global registry.

Not done here: no execution, no handlers/tools/code/external services, no connection to Core, Memory, AEL, NLU or reasoning. Pure stdlib (`copy`, `itertools`, `re`); no LLM, network or filesystem. `capabilities/capability_system.py`, `capabilities/__init__.py`, all NLU/reasoning/contract/boundary APIs and the frozen-tree tests are unchanged.

Tests: `tests/test_capability_registry_prompt841.py` (56 tests: validation, registration, duplicate/conflict rejection, malformed descriptors, lookup, listing, isolation, boundaries, backward compatibility).
Known baseline note: 8 frozen-tree tests (Section 6 / Section 9 byte-freeze checks) already fail on the unmodified Prompt 840 tree because of Section 11 additions; they are unchanged and fail identically.
