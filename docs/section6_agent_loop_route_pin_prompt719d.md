# Prompt 719-D - Section 6: mixed-plan route boundary (per-AgentLoop route pin)

Status: **implemented, narrow, inside the existing `AgentLoop.execute_routed_step` only.** Pinned by
`tests/test_section6_agent_loop_route_pin_prompt719d.py`. Closes the mixed-plan gap named in Prompt 719-C: a plan already executed through the
explicit Section 6 route could later be sent through the legacy route because nothing remembered the route.

## The pin

`AgentLoop` keeps a private in-memory map `_plan_route_pins = {plan_id: route}` (created lazily inside `execute_routed_step`, so `__init__` and
every other method stay byte-identical). Values are exactly `"section6_tool"` or `"legacy_capability"`. The map belongs to one AgentLoop
instance: no module/class state, nothing written to `Plan`, `PlanStep`, `PlanManager`, the database or any file, and it is not exposed in the
result envelope (the envelope keys are unchanged).

## Transitions

| plan pinned as | next explicit `section6_tool` | next legacy (explicit or undeclared) |
|---|---|---|
| (none) | allowed, pins `section6_tool` | allowed; explicit `legacy_capability` pins, undeclared fallback does not |
| `section6_tool` | allowed | **rejected** |
| `legacy_capability` | **rejected** | allowed |

A rejection returns the usual envelope with `stage="route_pin"`, `status="rejected"`, `error_code="ROUTE_PIN_CONFLICT"`; neither
`execute_next_step` nor the runner is called and nothing changes. A plan never silently switches routes.

When the pin is created: Section 6 pins after the intent is valid and the loop's PlanManager knows the plan, immediately before the runner is
called (so a later runner failure or exception keeps the pin; dispatch/payload/intent rejections and unknown plans create none). Legacy pins only
for an explicit `"legacy_capability"` declaration with a valid, known `plan_id`, before `execute_next_step` is called. An explicit Section 6
failure never falls back to legacy, before or after the pin.

## Why the pin is intentionally non-persistent

The pin is an in-process guard against mixing routes within one loop's lifetime, not plan state. Persisting it would change Plan / PlanManager /
the database (out of scope and frozen), and would make a plan's route outlive the process that chose it. A new AgentLoop starts unpinned.

## Scope

`execute_next_step()` and `run()` called directly neither read nor write the pin, and undeclared legacy calls only check it, so existing legacy
callers behave exactly as before. `process_input`, Core, Plan, PlanStep, PlanManager, ToolRequest, Section 5 and the retry layer are untouched and
`process_input` remains outside this scope.

## residual limitations

- The guard covers only `execute_routed_step`; a caller who invokes `execute_next_step` directly on a Section 6 plan is not stopped.
- Pins reset with the AgentLoop instance, and two AgentLoop instances over the same PlanManager do not see each other's pins.
- Undeclared (fallback) legacy execution creates no pin, so such a plan can still later be executed explicitly through Section 6.
