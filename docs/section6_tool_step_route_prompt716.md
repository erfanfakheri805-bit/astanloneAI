# Prompt 716 - Explicit tool-step execution route resolver

Status: **isolated, additive, unwired.** One new production module, `planning/tool_step_route.py`, implements the routing contract decided in
Prompt 715 (DECISION-1, `B-EXPLICIT-PLAN-SCOPED-ROUTE`; gap G2). Nothing imports it: not `AgentLoop`, not `process_input()`, not `execution/`,
not `PlanManager`, not the Section 6 adapter. Pinned by `tests/test_section6_tool_step_route_prompt716.py`.

## API

```python
from planning.tool_step_route import (ROUTE_LEGACY_CAPABILITY, ROUTE_SECTION6_TOOL, resolve_execution_route, RouteResolutionResult)

ROUTE_LEGACY_CAPABILITY == "legacy_capability"
ROUTE_SECTION6_TOOL     == "section6_tool"

resolve_execution_route(declaration=None) -> RouteResolutionResult
```

`RouteResolutionResult` is immutable, data-only, not subclassable and obtainable only from the resolver. Fields: `route`, `explicit`, `fallback`,
`declaration_valid`, `code`, `reason`; helpers `is_section6_tool`, `is_legacy_capability`, and `as_dict()` (a fresh dict on every call).

| declaration | route | explicit | fallback | declaration_valid | code |
|---|---|---|---|---|---|
| exactly `"section6_tool"` | `section6_tool` | True | False | True | `EXPLICIT_SECTION6_TOOL` |
| exactly `"legacy_capability"` | `legacy_capability` | True | False | True | `EXPLICIT_LEGACY_CAPABILITY` |
| omitted or `None` | `legacy_capability` | False | True | False | `FALLBACK_ABSENT_DECLARATION` |
| any other `str` (`""`, `" section6_tool"`, `"SECTION6_TOOL"`, ...) | `legacy_capability` | False | True | False | `FALLBACK_UNKNOWN_DECLARATION` |
| any non-`str`, or a `str` subclass instance | `legacy_capability` | False | True | False | `FALLBACK_MALFORMED_DECLARATION` |

Invariant: `route == "section6_tool"` **if and only if** the declaration is exactly the `str` `"section6_tool"`.

## Why routing is explicit

`PlanStep` has no type/route field and the two stacks disagree on state vocabulary (Prompt 715 section 1), so the route cannot be read off the
data. It is an explicit, caller-owned declaration. The tool route is the only route that can start a Section 6 tool step, so it must never be
reachable by accident: it requires the caller to say exactly `"section6_tool"`.

## Why unknown/malformed values fall back to legacy

Legacy is the status quo: existing callers do not declare anything and must behave exactly as today. A missing, misspelled or wrongly typed value
therefore means "not opted in" and keeps the plan on the legacy stack. A failure to opt in can never start a tool step. The fallback is reported
(`fallback=True`, distinct codes) so a later caller can log or reject it, but the resolver itself never raises.

## Why no inference occurs

Matching is exact: no trimming, case folding, normalisation, fuzzy matching, prefix matching or intent guessing. Only an object whose type is
exactly `str` is compared, so a `str` subclass (which could override `__eq__`/`__hash__`) is malformed and none of its methods is called;
containers and objects are never iterated, indexed, stringified or hashed. The resolver reads no plan, step, registry, tool name, handler,
capability, permission, execution state or Agent Loop state, imports nothing, and keeps no state or routing registry. A route derived from any of
those would be a hidden default into the tool path, which DECISION-1 forbids.

## What this module does not do

It does not validate anything (no plan, step, request or mapping check - the adapter stays responsible), does not execute anything, does not
construct a `ToolRequest`, does not resolve capabilities, and does not modify `AgentLoop`, `process_input()`, `execution/`, `PlanManager`,
`Plan`/`PlanStep`, Section 4, Section 5 or the existing Section 6 adapter/retry/bridge. A `section6_tool` result is **not** authorization and
does not mean a plan is eligible; it only says the caller asked for that route.

## How Prompt 717+ may consume it

A later, separately reviewed prompt may call `resolve_execution_route(caller_declaration)` at the single decision point in front of the two stacks
and branch on `result.route`: `legacy_capability` -> the unchanged legacy path (`AgentLoop.run`), `section6_tool` -> caller-owned `ToolRequest`
construction and `execute_agent_tool_step(...)`. Consumers must pass only a caller-provided value (never a value derived from plan or tool data),
must treat the result as routing metadata only, and must not reinterpret `fallback`/`code` into a tool route. Wiring into `AgentLoop`/`process_input()`,
the request builder (G4) and non-finite hardening (G3) remain separate future prompts.
