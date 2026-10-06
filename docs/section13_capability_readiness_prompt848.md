# Prompt 848 - Capability Readiness Boundary

Eighth step of Section 13 (Capability System) - the final composition layer.
Module: `capabilities/capability_readiness.py` - ONE small read-only function, `evaluate_capability_readiness(capability, match_result=None, selection_result=None)`, that reports whether a capability is fully READY to cross the execution boundary. It only composes results the existing layers already produce: it does no matching or selection, adds no validation/selection rules, and never executes, loads, registers, enables, disables, replaces or modifies anything. No Registry, Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem.

## Reused layers
- Descriptor validity and lifecycle state: the Prompt 847 execution boundary (which composes Prompt 844 validation and Prompt 843 lifecycle) evaluated with no selection.
- Match-result shape: the Prompt 846 input check (`capability_selection._well_formed`) on the supplied Prompt 845 result.
- Selection validity and "selected capability == supplied capability": the Prompt 847 execution boundary evaluated with the supplied Prompt 846 selection.
Nothing is repaired, normalised or inferred; the caller supplies the match and selection results.

## Ready only when (first failure reported, in this order)
1. capability structurally valid; 2. lifecycle state exactly `"enabled"`; 3. a valid, well-formed match result with status `matched`; 4. a valid selection with status `selected`; 5. the selected capability exactly equals the supplied capability; 6. selection reason `unique_match`; 7. the selection belongs to this match result (its single match equals the selected entry); 8. the execution boundary allows execution.

| status | reasons |
|---|---|
| invalid_input | invalid_capability_input, invalid_match_result, invalid_selection_result, readiness_error (never-raise fallback) |
| not_ready | invalid_capability, invalid_lifecycle_state, lifecycle_defined / lifecycle_validated / lifecycle_disabled / lifecycle_deprecated, missing_match_result, match_not_matched, missing_selection_result, not_selected, selection_mismatch, selection_not_unique, match_selection_inconsistent, execution_not_allowed |
| ready | ready |

## Result (fixed keys, JSON-safe, fresh every call)
`status, ready, reason, capability_name, capability_version, execution_allowed, executed`
`ready` is True only for status `ready`; `execution_allowed` equals `ready`; `executed` is always False. Name/version are the Prompt 847 values (None when not valid; malformed values are never echoed).

Deterministic, bounded, never raises. Registry (841), Identity (842), Lifecycle (843), Validation (844), Matching (845), Selection (846), Execution Boundary (847), `capability_system.py`, `capabilities/__init__.py`, Core, Memory, AEL and frozen-tree tests are unchanged; none of them imports this module.

Tests: `tests/test_capability_readiness_prompt848.py` (26 tests: ready, invalid capability, lifecycle, match result, selection result, mismatch, execution-boundary denial, safety, boundaries).
