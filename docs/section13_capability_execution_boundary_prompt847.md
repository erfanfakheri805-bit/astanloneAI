# Prompt 847 - Capability Execution Boundary

Seventh step of Section 13 (Capability System).
Module: `capabilities/capability_execution_boundary.py` - ONE small read-only function, `evaluate_capability_execution(capability, request=None)`, that evaluates whether execution of a capability MAY proceed. It never executes anything, loads no handler/tool/module/code, and registers, enables, disables, replaces or modifies nothing. It reuses Prompt 844 `validate_capability` (which composes 841 descriptor structure and the 843 lifecycle state check), Prompt 842 `build_capability_identity` and the Prompt 846 selection layer (`_valid_match`, status/reason constants). No registry is used. No Core, Memory, AEL, NLU, reasoning, LLM, network or filesystem; not connected to execution yet.

## Inputs (exact keys only; nothing inferred, repaired or normalised)
- `capability`: `{"descriptor", "lifecycle_state"}` - a Prompt 841 descriptor plus the EXPLICIT Prompt 843 lifecycle state. The state is never inferred from the descriptor (its `enabled` flag, name, purpose, ...); permissions are never derived from name, purpose or implementation.
- `request`: `None`, or `{"selection": <Prompt 846 select_capability() result>}`. Without a selection nothing is selected, so nothing is allowed.

## Execution may be allowed only when
1. the capability input is well formed;
2. the descriptor is structurally valid (844);
3. the lifecycle state is exactly `"enabled"` (843);
4. the request holds a valid 846 selection with status `selected` whose selected entry is exactly this capability (identity, version, descriptor).

Otherwise the FIRST failing reason (in this order) is returned:

| status | reason | meaning |
|---|---|---|
| invalid_input | invalid_capability_input | capability is not exactly `{descriptor, lifecycle_state}` |
| invalid_input | invalid_request | request is neither None nor exactly `{selection}` |
| denied | invalid_capability | descriptor not valid (844) |
| denied | invalid_lifecycle_state | state is not a lifecycle state (843) |
| denied | lifecycle_defined / lifecycle_validated / lifecycle_disabled / lifecycle_deprecated | state is not `enabled` |
| denied | no_selection | no request / no selection supplied |
| denied | not_selected | selection result says nothing was selected |
| denied | invalid_selection | selection malformed, or an `invalid_input` selection result |
| denied | selection_mismatch | the selected capability is not this capability |
| allowed | allowed | all conditions hold |

`boundary_error` (status invalid_input) is the never-raise fallback for an unexpected internal failure.

## Result (fixed keys, JSON-safe, fresh every call)
`status, allowed, reason, capability_name, capability_version, execution_allowed, executed`
- `status`: `allowed` / `denied` / `invalid_input`; `allowed` is True only for `allowed`.
- `capability_name` / `capability_version`: from 844 validation when valid identity name / valid version, else None (malformed values are never echoed).
- `execution_allowed` equals `allowed` (the check says execution MAY proceed; nothing is started). `executed` is always False.

Deterministic, bounded (841 bounds apply), never raises. Registry (841), Identity (842), Lifecycle (843), Validation (844), Matching (845), Selection (846), `capability_system.py`, `capabilities/__init__.py`, Core, Memory, AEL and frozen-tree tests are unchanged; none of them imports this module.

Tests: `tests/test_capability_execution_boundary_prompt847.py` (34 tests: allowed, lifecycle denials, invalid capability, selection denials, malformed input, safety/freshness, boundaries, backward compatibility).
