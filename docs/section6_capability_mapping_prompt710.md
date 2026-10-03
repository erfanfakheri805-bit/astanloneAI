# Prompt 710 - Explicit capability mapping contract (Section 6, decision F2)

Status: one new pure module (`planning/tool_capability_mapping.py`) and one new caller-driven function
(`execute_plan_tool_step_mapped()` in `planning/tool_step_executor.py`). **Not wired anywhere else.**
Tests: `tests/test_section6_capability_mapping_prompt710.py` (48). F1 (the Prompt 689-694 step layer owns tool steps) and H3/H4 (Prompt 709) are unchanged.

## F2 decision

Section 4 `required_capabilities` (free-form strings) and Section 5 grant names (`^[a-z][a-z0-9_]{0,63}\Z`) stay **two separate vocabularies**.
They are connected only by a mapping the **caller supplies explicitly**. Nothing is inferred, guessed, auto-discovered, learned, normalized,
case-folded or trimmed, and the DB-backed `CapabilitySystem` is neither imported nor replaced. Neither the Section 4 contract nor the Section 5
validation rules changed.

## API

```python
map_required_capabilities(required_capabilities, mapping) -> CapabilityMappingResult
find_ungranted_capabilities(mapping_result, granted_capabilities) -> tuple    # mapped Section 5 names the caller did not grant
execute_plan_tool_step_mapped(plan, step_id, request, registry, required_capabilities, capability_mapping,
                              rejection_log=None) -> PreflightedToolStepResult   # 709 result type, unchanged shape
```

Mapping = list/tuple of `{"capability": "<Section 4 name>", "grants": ["<Section 5 name>", ...]}` (exactly those keys). `grants` is a non-empty
ordered list/tuple (one-to-many allowed). A dict shortcut is not accepted because it cannot represent duplicate/conflicting entries.

`CapabilityMappingResult` (immutable; `to_dict()` keys `ok, status, required, resolved, grant_names, missing, invalid_entries, failures`):

| status | meaning |
|---|---|
| `satisfied` | every required name mapped; `grant_names` = resulting Section 5 names (required order, first occurrence wins) |
| `unmapped` | valid mapping, but `missing` names have no entry (`UNMAPPED_REQUIRED_CAPABILITY`); the mapped part is still reported, nothing is dropped |
| `invalid_mapping` | bad structure/entry: `INVALID_MAPPING_STRUCTURE`, `INVALID_MAPPING_ENTRY`, `EMPTY_MAPPING_CAPABILITY_NAME`, `INVALID_MAPPING_GRANTS`, `EMPTY_MAPPING_GRANTS`, `INVALID_SECTION5_CAPABILITY_NAME`, `DUPLICATE_MAPPING_GRANT`, `DUPLICATE_MAPPING_ENTRY`, `CONFLICTING_MAPPING_ENTRY`; all problems listed, no partial translation |
| `invalid_input` | `required_capabilities` is not a list/tuple of non-empty strings (`INVALID_REQUIRED_CAPABILITIES`) |

## Mapping vs authorization

Mapping is **translation only**. It cannot create a grant: `grant_names` are names the caller *would need to have granted*. A test asserts the
mapper's signature has no access to grants at all, and that an unmapped/absent requirement never yields a name.

## Integration (only at the preflighted boundary)

`execute_plan_tool_step_mapped()` runs, in order, each stage stopping at its first rejection: `rejection_log` check; the bridge's own arguments and
`request.to_registry_arguments()` (same owners as 709); the mapping must be `satisfied`; every mapped Section 5 name must already be in the
request's grants. Any failure is a **pre-start rejection** (`pre_registry_rejection`, H3 record, step stays `pending`, no registry call, no handler
call, no audit record, plan untouched); failure entries `CAPABILITY_MAPPING_REJECTED` (with the mapping report and the mapper's own codes) or
`MAPPED_GRANT_NOT_SUPPLIED` (with `missing_grants`). Only then the **unchanged** `execute_plan_tool_step_preflighted()` runs, so plan context
(Section 4) and preflight/permissions/confirmation/capabilities/input (Section 5) are judged exactly as in Prompt 709. Extra caller grants stay
in the request; the request, grants, mapping and required list are never modified. The function was added beside, not into, the preflighted
function so its signature and 709 behaviour are untouched.

## Caller responsibilities

Supply the Section 4 names (e.g. `step.required_capabilities`), the mapping, and a `ToolRequest` that already grants the mapped names.
The module never reads a step for you, never grants, never repairs a request, never retries.

## Section 5 authority

Passing the mapping gate is necessary, never sufficient. A tool that needs a capability the mapping did not translate to is still rejected by
`registry.preflight()` (`TOOL_CAPABILITY_MISSING`), and permission/confirmation/unknown/disabled tool checks are unaffected (all tested).

## Production changes

- new `planning/tool_capability_mapping.py` (imports only `re`; the Section 5 name rule is restated and a test asserts identical pattern/flags).
- `planning/tool_step_executor.py`: import, two failure-code constants, `execute_plan_tool_step_mapped()`, docstring section.
- Guard tests adjusted (sanctioned import set only): 708 import-set/bare-name check for the caller-supplied parameter, 709 import set. No production defect found.

## Still open

Retry on the selected stack, the Agent Loop hand-over and `process_input()` wiring, the `ready`-status incompatibility between the two stacks,
F3 (NaN/inf asymmetry), and any automatic Plan-to-mapping sourcing (deliberately excluded).
