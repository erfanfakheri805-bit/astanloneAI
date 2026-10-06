# Prompt 843 - Capability Lifecycle Foundation

Third step of Section 13 (Capability System).
Module: `capabilities/capability_lifecycle.py` - a stateless, read-only description of capability lifecycle states and of which transitions between them are allowed. It only EVALUATES a requested transition. It stores no state, changes no registered capability, has no imports, and is not linked to the registry, descriptors, identity layer, Core, Memory or AEL. A lifecycle state never implies that a capability can execute: every result carries `execution_allowed=False` and `executed=False`.

API (all non-raising, JSON-safe, fresh results):
- `validate_lifecycle_state(value)` -> `{version, valid, state, errors, execution_allowed, executed}`
- `evaluate_lifecycle_transition(current, requested)` -> `{version, allowed, current, requested, reason, errors, execution_allowed, executed}`
- `get_allowed_next_states(current)` -> `{version, valid, current, next_states, errors, execution_allowed, executed}`
- `list_lifecycle_states()` -> `{version, count, states, ...}`; `list_lifecycle_transitions()` -> `{version, count, transitions:[{from, to}], ...}`

States (exact lowercase strings, canonical order): `defined`, `validated`, `enabled`, `disabled`, `deprecated`. Exact string equality only: no trimming, case folding or guessing; str subclasses, bytes, None, numbers and anything longer than 16 chars are malformed. A state is never inferred from a name, version, purpose or other descriptor field. The lifecycle state `enabled` is unrelated to the descriptor's `enabled` flag. The descriptor structure (Prompt 841) is unchanged and still rejects `state` / `lifecycle` fields.

Allowed transitions (exactly 9):
- defined -> validated, deprecated
- validated -> enabled, disabled, deprecated
- enabled -> disabled, deprecated
- disabled -> enabled, deprecated
- deprecated -> (none; terminal)

Evaluation of the 25 state pairs: 9 `allowed` (reason `allowed`), 5 `same_state`, 4 `terminal_state` (deprecated to another state), 7 `transition_not_allowed` (e.g. defined -> enabled/disabled, any move back to defined, enabled/disabled -> validated). Every rejection carries one error `{code: <reason>, where: "transition"}`.
Malformed input: reason `invalid_current_state` (checked first) or `invalid_requested_state`; one error per bad argument with code `invalid_state_type` (not an exact str) or `unknown_state`, located at `current` / `requested` / `state`. A valid argument is echoed, an invalid one is None. Malformed values are never "the same state".

Deterministic, bounded (constant work), never raises; nothing is executed, loaded, registered, replaced, upgraded, removed or mutated; there is no function that applies a transition. No Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem. `capability_registry.py` (841), `capability_identity.py` (842), `capability_system.py`, reasoning (838-840), NLU, core/core.py, Memory, AEL and the frozen-tree tests are unchanged.
Tests: `tests/test_capability_lifecycle_prompt843.py` (52 tests; all 5 states, all 9 allowed and all 16 rejected transitions, malformed input, boundaries, backward compatibility).
Known baseline note: the same 8 frozen-tree tests (Section 6 / Section 9 byte-freeze checks) that already fail on the unmodified Prompt 840 tree still fail identically; they are unchanged.
