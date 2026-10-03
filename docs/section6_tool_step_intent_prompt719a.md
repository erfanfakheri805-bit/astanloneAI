# Prompt 719-A - Section 6 Tool Step Intent Adapter

`agent/tool_step_intent.py` · tests: `tests/test_section6_tool_step_intent_prompt719a.py`

## Purpose

A caller-side, data-only adapter. It validates ONE explicit tool-step intent and builds its `ToolRequest` through the existing
`create_tool_request(...)`. It executes nothing and is not wired into any caller yet.

```python
build_tool_step_intent(intent) -> ToolStepIntentResult
```

## Input contract

Exactly these keys; nothing is inferred, defaulted, renamed or repaired.

```python
{
    "plan_id": str,                      # exact str, not blank
    "step_id": str,                      # exact str, not blank
    "tool_request": {                    # exactly these five keys, all required
        "name": str,
        "tool_input": <JSON-safe value>,
        "granted_permissions": list | tuple of str,
        "granted_capabilities": list | tuple of str,
        "confirmed": bool,
    },
    "max_attempts": int,                 # exact int (not bool), > 0
    "required_capabilities": list | tuple of str,   # optional key
    "capability_mapping": list | tuple,             # optional key (existing Prompt 710 mapping value)
}
```

- Rejected: non-dict intent, missing required keys, extra/alternate keys (top level and inside `tool_request`), wrong types, subclasses of
  builtin types (`type(x) is T`), sets for grants, `None` for any present field.
- "Optional" means the key may be absent (result value `None`). If present it must be valid; `None` is not "absent".
- JSON-safe = `None`, `bool`, `int`, finite `float`, `str`, `list`, `dict` with exact-`str` keys. Tuples, sets, bytes, NaN/inf, objects, cycles, depth
  over 32 and more than 100000 nodes are rejected. Rejected values are never `repr()`'d, hashed, compared or copied with their own methods.
- `capability_mapping` is only checked to be plain data (list/tuple). Entry rules belong to Prompt 710; `required_capabilities` items are only checked
  to be `str`. The "both or neither" pairing of the two optional fields is enforced by Prompt 711 at use time.

## ToolRequest boundary

When the whole structure is valid, `create_tool_request(name, tool_input, granted_permissions, granted_capabilities, confirmed)` is called
exactly once with only those five explicit values (fresh copies). Its rejection is propagated verbatim: same `code` and `message`,
`field="tool_request"`. If the structure is invalid it is not called. `ToolRequest` and `create_tool_request` are unchanged.

## Result: `ToolStepIntentResult`

Immutable, data-only, not subclassable, obtainable only from `build_tool_step_intent()`.

| field | meaning |
|---|---|
| `ok` | True only for a fully valid intent with an accepted `ToolRequest` |
| `plan_id`, `step_id`, `max_attempts` | the caller's values (None when not ok) |
| `request` | the immutable `ToolRequest` (None when not ok) |
| `required_capabilities`, `capability_mapping` | fresh copy per read (container kind preserved); None when omitted or not ok |
| `failures` | fresh list of `{"code", "field", "message"}` per read; empty when ok |

Also `codes()` and `to_dict()`. Equality compares data; unhashable; copy/deepcopy return the same object; pickling is refused.

## Failure codes

Stable, all problems at once, fixed field order (`plan_id`, `step_id`, `tool_request`, `max_attempts`, `required_capabilities`,
`capability_mapping`): `INTENT_NOT_A_DICT`, `INTENT_MISSING_FIELD`, `INTENT_UNEXPECTED_FIELD`, `INTENT_INVALID_FIELD_NAME`,
`INTENT_INVALID_PLAN_ID`, `INTENT_INVALID_STEP_ID`, `INTENT_INVALID_TOOL_REQUEST`, `INTENT_TOOL_REQUEST_MISSING_FIELD`,
`INTENT_TOOL_REQUEST_UNEXPECTED_FIELD`, `INTENT_TOOL_REQUEST_INVALID_FIELD_NAME`, `INTENT_INVALID_TOOL_NAME`, `INTENT_INVALID_TOOL_INPUT`,
`INTENT_INVALID_GRANTED_PERMISSIONS`, `INTENT_INVALID_GRANTED_CAPABILITIES`, `INTENT_INVALID_CONFIRMED`, `INTENT_INVALID_MAX_ATTEMPTS`,
`INTENT_INVALID_REQUIRED_CAPABILITIES`, `INTENT_INVALID_CAPABILITY_MAPPING`; plus the `INVALID_TOOL_REQUEST_*` codes of `create_tool_request`.

## Responsibilities

Structural validation of the explicit intent; building the `ToolRequest` from explicit values only; returning fresh, immutable data.

## Non-responsibilities

Executing, resolving routes, inspecting plans or steps, AgentLoop / `process_input` / Core access, registry lookup or calls, capability
mapping (Prompt 710), retries (Prompt 711), authorization (Section 5), granting or inferring anything, mutating project state, module-level
state. Imports only `tools.tool_request` and stdlib `math`. No existing production module is modified.
