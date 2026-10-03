# Prompt 717 - Section 6 Tool-Step Dispatch Decision Layer

`planning/tool_step_dispatch.py` · tests: `tests/test_section6_tool_step_dispatch_prompt717.py`

## Boundary

- **Prompt 716 decides the route.** `planning.tool_step_route.resolve_execution_route(declaration)` is the only thing that ever picks `legacy_capability` or `section6_tool`.
- **Prompt 717 converts that route into a caller-facing dispatch decision.** It calls the resolver exactly once, then says which caller-owned payload (`legacy_input` or `tool_input`) belongs to the selected route, and returns that as immutable data.
- **Neither module performs actual execution.** Nothing is invoked, constructed, registered, granted or retried.
- **AgentLoop / `process_input` wiring is intentionally deferred.** This layer is not imported by `AgentLoop`, `process_input`, `Planner`, `PlanManager`, `ExecutionEngine`, `execution/*` or the Section 6 adapter.

## API

```python
resolve_tool_step_dispatch(declaration=None, legacy_input=None, tool_input=None) -> DispatchResolutionResult
```

| declaration | route | explicit | fallback | route_code |
|---|---|---|---|---|
| exactly `"section6_tool"` | `section6_tool` | yes | no | `EXPLICIT_SECTION6_TOOL` |
| exactly `"legacy_capability"` | `legacy_capability` | yes | no | `EXPLICIT_LEGACY_CAPABILITY` |
| omitted / `None` (same absent case) | `legacy_capability` | no | yes | `FALLBACK_ABSENT_DECLARATION` |
| any other `str` | `legacy_capability` | no | yes | `FALLBACK_UNKNOWN_DECLARATION` |
| non-`str` or `str` subclass | `legacy_capability` | no | yes | `FALLBACK_MALFORMED_DECLARATION` |

A fallback is never upgraded to `section6_tool`. The route is never inferred from payload contents, plan data, tool names, capabilities, permissions or object types.

## Result: `DispatchResolutionResult`

Immutable, data-only, not subclassable, obtainable only from `resolve_tool_step_dispatch()`.

| field | meaning |
|---|---|
| `route`, `explicit`, `fallback`, `declaration_valid` | propagated unchanged from the Prompt 716 result |
| `route_code`, `route_reason` | Prompt 716 code and fixed reason |
| `route_result` | the Prompt 716 `RouteResolutionResult` itself |
| `dispatch_kind` | `legacy_capability_dispatch` or `section6_tool_dispatch` (follows the route, even when rejected) |
| `dispatch_status` | `ready` or `rejected` |
| `dispatch_code` | `LEGACY_INPUT_SELECTED`, `TOOL_INPUT_SELECTED`, `REJECTED_PAYLOAD_ABSENT`, `REJECTED_PAYLOAD_INVALID` |
| `dispatch_reason` | fixed sentence for the code |
| `payload_source` | `legacy_input` or `tool_input` |
| `has_payload`, `payload` | `payload` is a fresh deep copy per access; `None` when rejected |
| `is_section6_tool`, `is_legacy_capability`, `is_ready`, `is_rejected` | convenience booleans |
| `as_dict()` | fresh plain dict every call |

No handlers, registry objects, plans or mutable internal state are exposed. `repr()` never includes the payload.

## Payload validation and isolation

Route resolution is independent of payload validity. A bad tool payload never turns the route into legacy; a bad legacy payload never turns it into tool. The result is a `rejected` dispatch on the same route.

- Only the selected route's payload is looked at. The other payload is never inspected, copied or returned.
- `None` means "not provided": the selected route is rejected with `REJECTED_PAYLOAD_ABSENT`. No default is invented. Falsy values such as `""`, `0`, `False`, `[]`, `{}` are valid payloads.
- Accepted payloads are JSON-safe structured data of exact types only: `None`, `bool`, `int`, finite `float`, `str`, `list`, `dict` with exact `str` keys. Anything else (tuples, sets, bytes, NaN/inf, subclasses, enums, `OrderedDict`, arbitrary objects, plans, callables, cycles, depth over 32, more than 100000 nodes) is `REJECTED_PAYLOAD_INVALID`. Nothing is coerced.
- Rejected objects are never `repr()`'d, stringified, hashed or compared, and none of their methods is called.
- Accepted payloads are deep-copied. Caller inputs are never mutated, and later mutation of caller data (or of a returned copy) cannot reach the result.

## What this layer does not do

It does not execute, invoke tools or handlers, construct `ToolRequest`, call the registry, grant permissions or capabilities, map capabilities, retry, read `execution_authorized`, read or modify `Plan` / `PlanStep`, or keep a global routing registry. It does not execute anything; it only returns data. Its only project import is the Prompt 716 resolver.

## Guard changes

Four older test-only guards listed the set of modules allowed to mention route vocabulary or import `tool_step_*`. Each got a narrow exception for the exact path `planning/tool_step_dispatch.py` (Prompt 712, 713, 715, 716 tests). The Prompt 717 tests prove the exception is limited to that file: no other production module references the resolver or dispatch layer.

## Remaining Section 6 work

Wiring the dispatch decision into the Agent Loop / `process_input` (caller supplies the declaration and both payloads), then end-to-end Section 6 acceptance.
