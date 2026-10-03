# Prompt 718 - Section 6 Agent Loop / `process_input` wiring decision & seam audit

Status: **audit + decision only. Nothing is implemented, nothing is wired.** No production file changed. Pinned by
`tests/test_section6_agent_loop_wiring_decision_prompt718.py` (read-only). Baseline: Prompt 717 (`planning/tool_step_dispatch.py`, unwired).
The actual wiring is Prompt 719.

## 1. Audit of the current runtime path (facts, each re-checked by a test)

- **`Core.process_input(raw_text)`** (`core/core.py`) takes exactly one `str` and returns a `str`. It normalizes, logs, parses, and either
  runs AEL or calls `_handle_goal_or_conversation`, which, for goal-shaped text, calls `create_goal()` once (a Goal plus one **empty** Plan) and
  returns a "[GOAL CREATED]" string; everything else goes to `_handle_conversation`. It has no `plan_id`, no step, no registry, no structured
  input, and **no execution path at all**. `core/core.py` imports nothing from `agent/`; production code never instantiates `AgentLoop`.
  Core's only step runner is `StepExecutionController` via `execute_first_step`, which is not reachable from `process_input`.
- **`AgentLoop`** (`agent/agent_loop.py`) is constructed by callers/tests with `GoalManager`, `PlanManager`, `PlanExecutionController` (+ optional
  collaborators). Its two execution entry points are `run(goal_id, plan_id, max_iterations)` (bounded whole-plan loop over
  `PlanExecutionController.execute_plan`) and `execute_next_step(plan_id, capability_system=None)` (an explicitly invoked, single-step entry that
  calls `refresh_plan_step_statuses`, selects the next `ready` step through the legacy coordinator, and runs it through `StepExecutionController`).
  Both are legacy: they rewrite steps to `ready`/`blocked`, select steps themselves, and use handler-backed `required_capabilities`.
- **Prompt 716** `resolve_execution_route(declaration)` decides the route from one exact `str` only. **Prompt 717**
  `resolve_tool_step_dispatch(declaration, legacy_input, tool_input)` calls it once and selects the payload that belongs to the route. Payloads must
  be JSON-safe, exact-type structured data (deep-copied); objects (`Plan`, registry, `capability_system`, callables, tuples, sets, subclasses) are
  rejected as `REJECTED_PAYLOAD_INVALID`. Neither module is imported by any production module other than each other.
- **Prompt 714** `execute_agent_tool_step(plan, step_id, request, registry, max_attempts, required_capabilities=None, capability_mapping=None,
  attempt_log=None)` is the only tool-step entry. It validates plan, step-state consistency (rejecting `ready`/`blocked`), step existence,
  `execution_authorized is True`, retry arguments and the mapping pair before anything starts, then makes at most one call into the Prompt 711 retry
  layer. It never builds a `ToolRequest`, never touches a registry itself, never refreshes a plan.
- **`create_tool_request(name, tool_input, granted_permissions=None, granted_capabilities=None, confirmed=False)`** applies defaults (no grants, not
  confirmed) when arguments are omitted. Any caller-side builder therefore has to refuse omitted fields, or a default would be *inferred authority*.
- **`PlanManager.get_plan(plan_id)`** returns the live `Plan` or `None` (never raises); `None` passed to the adapter is rejected as
  `ADAPTER_INVALID_PLAN_OBJECT` before anything starts, so an unknown plan needs no new code.

## 2. Decisions

### DECISION-1: CHOSEN ARCHITECTURE - one additive `AgentLoop` method, caller-owned declaration, `process_input` untouched
The Section 6 tool path is entered **only** through one new, explicitly invoked, additive public method on the existing `AgentLoop`, placed beside
`execute_next_step` (same "explicit, single step, never called from `run()`" convention):

```
AgentLoop.execute_routed_step(declaration=None, legacy_input=None, tool_input=None, capability_system=None, tool_registry=None) -> dict
```

- `run()`, `execute_next_step()`, `__init__` and every other existing method stay **byte-identical**. No optional route parameter is added to them.
- The declaration, `legacy_input` and `tool_input` are **caller-owned**: nothing in `AgentLoop` computes, defaults or infers any of them.
- `capability_system` (legacy collaborator) and `tool_registry` (Section 5 collaborator) are **objects**, so they can never travel inside a dispatch
  payload; they are separate, caller-supplied arguments, each used only by its own route and never defaulted, discovered or substituted for the other.
- Rejected alternatives: (a) an optional `declaration=` parameter on `run()`/`execute_next_step()` - changes frozen legacy signatures and invites
  cross-route drift; (b) a module-level router function outside `AgentLoop` - would need `AgentLoop`'s private `_plan_manager`, and the requirement
  is that `AgentLoop` owns the branch; (c) changing `process_input` - see DECISION-2.

### DECISION-2: `process_input` is NOT a seam (option D: narrowly defined - it neither carries nor makes routing decisions)
Justification from the existing architecture: (1) its contract is `str -> str` (721 `process_input(` occurrences across 116 test modules, whose callers expect the string reply); (2) it
never reaches `AgentLoop` or a plan's steps, so there is nothing to route; (3) the only way to feed it a declaration would be to parse the text
(forbidden: natural-language wording never picks a route) or to widen its signature (changes a public contract for no functional gain); (4) options A
(carry metadata into planning), B (decide) and C (adapter) would all add a route concept to a function that executes nothing. Consequence: `process_input`
stays legacy-only, unchanged and unaware; a future prompt that gives Core a plan-execution path must decide its own seam (out of scope, gap G6 stays open
by design). `core/core.py` is **not** in the Prompt 719 file list.

### DECISION-3: routing contract (unchanged from 715/716/717)
`"section6_tool"` -> Section 6 path. `"legacy_capability"` -> legacy path. Absent/None/unknown/malformed -> Prompt 716 fallback -> **legacy**, never
Section 6. The declaration is a bare exact `str` (no new declaration type is needed - see section 6). It is never inferred from tool names, capability
names, permissions, plan contents, natural-language wording, object type, presence of a registry, or `ToolRequest`-like data. Its only source is the
`declaration` argument of the routed method, handed unchanged to `resolve_tool_step_dispatch`, which is called exactly once per routed call.

### DECISION-4: payload ownership
- `legacy_input` is caller-built structured data `{"plan_id": <str>}` (exactly that key). Existing runtime objects (`Plan`, `PlanManager`,
  `capability_system`, `PlanExecutionController`) cannot supply it because dispatch rejects objects; the legacy step operation needs only the plan id.
- `tool_input` is a **new structured intent** (a plain dict, schema in section 6), built by the caller from already-decided intent.
- Both arguments are optional at the method level (`None` default), but the **selected** route's payload is mandatory: `None` there is
  `REJECTED_PAYLOAD_ABSENT` on the same route. The payload of the other route is never inspected, copied or used.
- Legacy behavior is unaffected by a missing/invalid `tool_input` (never looked at). A malformed `tool_input` on an explicit `section6_tool` route is
  rejected on that route (dispatch `REJECTED_PAYLOAD_INVALID` for non-JSON-safe data; intent-schema rejection for JSON-safe but wrong-shaped data) and
  **never** produces a legacy call.

### DECISION-5: `ToolRequest` construction - caller-side adapter, after dispatch, Section 6 route only
`ToolRequest` is built inside a dedicated caller-side module (`agent/tool_step_intent.py`), **after** dispatch has returned a ready Section 6 payload and
**after** the payload schema check, **only** on the Section 6 route. Not before dispatch (no route is known yet, and the legacy path must never
construct a `ToolRequest`), and not inside `AgentLoop` itself (keeps request logic out of the loop and keeps `agent_loop.py` small).
The builder is a **pure structural mapper**: `tool_input["tool_request"]` must contain exactly the five keys `name`, `tool_input`,
`granted_permissions`, `granted_capabilities`, `confirmed`, all present. An omitted key is a rejection, because `create_tool_request` would otherwise
default it. It calls `create_tool_request` once and passes its failures through. It never adds a grant, never confirms, never maps a capability, never
reads a plan, registry or `execution_authorized`.

### DECISION-6: capability mapping stays adapter-side
`required_capabilities` and `capability_mapping` travel in the payload verbatim (both `None` or both lists) into `execute_agent_tool_step`, whose stage f
and the retry layer apply `map_required_capabilities`. The routed method and the builder **never** call the mapping module and never derive either value.
A mapping is translation, never authorization; Section 5 preflight stays the final authority.

### DECISION-7: mixed-plan policy (Prompt 715 DECISION-2 reconfirmed) and where rejection belongs
One plan, one execution stack. A Section 6 plan never silently becomes legacy; a legacy plan never silently becomes Section 6; mixed stacks are
rejected, never converted.
- **Legacy plan -> tool route:** rejected by the **adapter** (stage b, `ADAPTER_LEGACY_STEP_STATE`, stateless, before any start). No new code.
- **Tool plan -> legacy route:** no Plan/PlanStep marker exists (`PlanStep` has no type/route/metadata; changing it is forbidden), and plan contents may
  not be used to infer a route. Decision: the routed method keeps a **private, in-memory, per-`AgentLoop` map `plan_id -> route`**, written only when a
  step actually **starts** through the routed method (Section 6: `execution_started` is true; legacy: the legacy result reports `executed` true). A later
  routed call that resolves to the *other* route for the same `plan_id` is rejected `MIXED_PLAN_ROUTE_CONFLICT` before any execution, with nothing
  started, on the route it resolved to. No persistence, no Plan change, no route stored anywhere else.
- **Residual gap (documented, not fixable in 719): G1.** Direct calls to `run()` / `execute_next_step()` bypass the map (they are frozen and must not be
  guarded), and a new `AgentLoop` instance starts empty. A durable guarantee needs a Plan-level route marker, i.e. a Section 4 change and a new decision.

### DECISION-8: ready/blocked and authorization
The Section 6 route needs the Section 4 states `pending/in_progress/completed/failed` only. Legacy `ready`/`blocked` are labels written by
`PlanManager.refresh_*`; they are never converted, repaired or reinterpreted. The boundary that rejects incompatible plans **before any Section 6 step
starts** is the adapter (stages a-b). On the Section 6 route `AgentLoop` must not call `refresh_plan_step_statuses`, `refresh_step_status`,
`refresh_after_step_change`, `_identify_next_step`, `get_next_ready_step` or any legacy coordinator method, and the step is chosen only by the explicit
`step_id` in the payload (never "next ready step"). `execution_authorized` is read **only** by the adapter (stage d); it remains a plan-owner-set
`metadata` flag and is never read, set or inferred by dispatch, the builder or `AgentLoop`.

### DECISION-9: result propagation
The routed method returns a fresh plain dict (the project's `AgentLoop._result` convention). Fields: `route`, `explicit`, `fallback`, `route_code`,
`dispatch_status`, `dispatch_code`, `stage` (`dispatch` | `payload` | `request` | `route_guard` | `execution`), `status` (`rejected` = nothing started on the
selected route; otherwise the selected route's native status), `error_code` (a stable code or `None`), `legacy_result` (the unchanged
`execute_next_step` dict, else `None`), `tool_result` (`AgentToolStepResult.to_dict()`, else `None`). Exactly one of `legacy_result`/`tool_result` is
ever populated. `route` always reports the route that was actually selected; it never changes after selection.

## 3. Exact future call sequences (not implemented)

Section 6 route (explicit `"section6_tool"` only):

```
caller
 -> AgentLoop.execute_routed_step(declaration="section6_tool", tool_input=<intent dict>, tool_registry=<registry>)
 -> resolve_tool_step_dispatch(declaration, legacy_input, tool_input)     # Prompt 716 route + Prompt 717 payload selection, once
      rejected (absent / not JSON-safe)  -> return rejected envelope, route stays section6_tool
 -> route guard: plan_id already started under legacy through this loop?   # MIXED_PLAN_ROUTE_CONFLICT -> rejected, nothing started
 -> agent/tool_step_intent.py: payload schema validation                   # exact keys/types; failure -> rejected (stage payload)
 -> agent/tool_step_intent.py: create_tool_request from the 5 explicit fields   # failure -> rejected (stage request); adapter never called
 -> plan = PlanManager.get_plan(plan_id)                                   # None is passed through; adapter rejects it
 -> execute_agent_tool_step(plan, step_id, request, registry, max_attempts, required_capabilities, capability_mapping)
      -> adapter validation (plan, states, step, execution_authorized, retry args, mapping pair)
      -> optional capability mapping (adapter/retry layer, never AgentLoop)
      -> Prompt 711 retry -> Prompt 709 preflight -> Prompt 707 bridge
      -> Section 5 InProcessToolRegistry preflight()/execute_request()      # authorization + audit sequence stay Section 5's
 -> record route pin only if the step started; return envelope with tool_result
```

Legacy route (absent / `None` / unknown / malformed / explicit `"legacy_capability"`):

```
caller
 -> AgentLoop.execute_routed_step(declaration=<absent|legacy|anything not exactly "section6_tool">, legacy_input={"plan_id": ...}, capability_system=...)
 -> resolve_tool_step_dispatch(...)                                        # route legacy_capability; only legacy_input is looked at
 -> route guard (same check, other direction)
 -> AgentLoop.execute_next_step(plan_id, capability_system)                # the existing method, unchanged, called once
 -> return envelope with legacy_result
```

**Isolation points (must never be crossed):** (1) `tool_input`, the builder, `create_tool_request`, the adapter, the registry and the mapping are unreachable
from the legacy branch; (2) `execute_next_step`, `refresh_*`, `_identify_next_step`, the legacy coordinator and legacy `retry_step` are unreachable from
the Section 6 branch; (3) the two branches share only the dispatch result and the route guard; (4) neither branch is reachable after the other has been
selected in the same call; (5) no `try/except` in the routed method may turn a Section 6 failure into a legacy call.

## 4. `AgentLoop` seam (exact)
One new public method, `execute_routed_step`, in `agent/agent_loop.py`, after `execute_next_step` and before `_finish`. It branches once, on
`dispatch.is_section6_tool`, and only on a *ready* dispatch. It invokes Section 6 only for an explicit `"section6_tool"`; it never selects a tool,
registry, step, permission, capability, confirmation or attempt count itself; it never bypasses `ToolRequest` validation or the adapter; it never reaches
Section 5 except through `execute_agent_tool_step`; it never calls legacy `retry_step` for a Section 6 step. It writes no `ExecutionEventLog` event on the
Section 6 route in 719 (a new event type would touch `execution/*`; the Section 5 registry audit sequence is the audit authority).

## 5. `process_input` seam (exact)
None. `process_input` and `core/core.py` stay byte-identical and are never given a route, a payload or an `AgentLoop`.

## 6. Missing types / contracts (specified, NOT implemented here)
| item | verdict |
|---|---|
| route declaration type | **not needed**: an exact `str` (Prompt 716). No class, enum or registry. |
| structured tool intent | **needed**, as a plain-dict schema plus a pure validator: exactly the keys `plan_id` (non-empty `str`), `step_id` (non-empty `str`), `tool_request` (dict with exactly `name`, `tool_input`, `granted_permissions`, `granted_capabilities`, `confirmed`), `max_attempts` (`int`, not `bool`; range judged by the adapter), `required_capabilities` and `capability_mapping` (both `None` or both lists; well-formedness judged by the adapter). No key has a default; extra or missing keys reject. |
| `ToolRequest` builder input | the `tool_request` sub-dict above; output: `ok` + `ToolRequest` or the `create_tool_request` failures unchanged. |
| legacy input | plain dict `{"plan_id": <non-empty str>}`, exactly one key. |
| `AgentLoop` handoff | the routed method signature in DECISION-1. |
| `process_input` handoff | none (DECISION-2). |
| result propagation | the envelope in DECISION-9. |

## 7. Failure propagation (no failure after an explicit `section6_tool` selection ever reaches the legacy path)
| failure | behavior |
|---|---|
| malformed / unknown / absent declaration | Prompt 716 fallback: **legacy** route, `explicit=False`, `fallback=True`; never Section 6; `tool_input` is not inspected; a missing `legacy_input` is then `REJECTED_PAYLOAD_ABSENT` on the legacy route |
| missing tool payload | `REJECTED_PAYLOAD_ABSENT`, route stays `section6_tool`, nothing runs, `legacy_input` never inspected |
| malformed tool payload | not JSON-safe: `REJECTED_PAYLOAD_INVALID`; JSON-safe but wrong schema: intent rejection (stage `payload`); no `ToolRequest`, no adapter call, route stays `section6_tool` |
| `ToolRequest` construction failure | `create_tool_request` failure codes passed through (stage `request`); adapter and registry never called; plan unchanged |
| capability mapping failure | malformed pair: adapter `ADAPTER_INVALID_MAPPING_ARGUMENTS` / `ADAPTER_MALFORMED_CAPABILITY_MAPPING`; unmapped or ungranted: retry-layer pre-start rejection; nothing repaired or defaulted |
| preflight rejection | pre-start (`failure_source="pre_start"`); retryable only per the Prompt 711 allow-list and only within the caller's `max_attempts`; step never started |
| tool execution failure | `failure_source="tool_execution"`; step `failed`, terminal; no retry |
| retry exhaustion | the adapter reports the retry stop reason; step unstarted; terminal for this call; another attempt is a new call/new plan; **never** legacy `retry_step` |
| invalid plan state / unknown plan / not authorized | adapter `ADAPTER_*` rejection (including `ADAPTER_LEGACY_STEP_STATE`, `ADAPTER_INVALID_PLAN_OBJECT`, `ADAPTER_EXECUTION_NOT_AUTHORIZED`); nothing starts |
| mixed-plan conflict | `MIXED_PLAN_ROUTE_CONFLICT` (stage `route_guard`); nothing starts |
| legacy execution failure | the unchanged legacy dict is returned in `legacy_result`; no switch to Section 6; legacy `retry_step` stays a legacy-only mechanism |
| unexpected exception | not caught for fallback; never converted into a call on the other route |

## 8. Minimal production files for Prompt 719
1. **`agent/agent_loop.py`** - add `execute_routed_step` (+ a lazily created private route map). *Receives:* dispatch call, one branch, route guard, plan lookup by id,
   delegation to `execute_next_step` or `execute_agent_tool_step`, envelope shaping. *Must NOT receive:* changes to any existing method or `__init__`, registry/handler
   imports, `ToolRequest` construction, mapping calls, `refresh_*`, retry loops, tool/permission/capability selection, event-type additions.
2. **`agent/tool_step_intent.py`** (new) - payload schema validation and `ToolRequest` construction. *Receives:* the only `tools.tool_request` import on the agent side.
   *Must NOT receive:* plan/registry access, defaults, grants, confirmation, mapping, adapter calls, execution, global state.

Not changed: `core/core.py`, `execution/*`, `planning/*`, `tools/*`, the Prompt 716 resolver, the Prompt 717 dispatch layer, the adapter.
**Required test-only guard updates in 719** (narrow exact-path exemptions, each proven limited to the two new/changed paths): the Prompt 712 "only the bridge
imports `tools`" and "consumers of `tool_step`" lists; the Prompt 713/715/716/717 "no production module references route/dispatch vocabulary" checks;
and the frozen `agent_loop.py` hash / legacy digest (replace with per-method source pins proving every pre-existing method is byte-identical).

## 9. Non-goals of Prompt 718
No wiring; no change to `AgentLoop`, `process_input`, `execution/*`, `Plan`, `PlanStep`, `PlanManager`, Section 5 or any Section 6 module; no `ToolRequest`
builder; no new type, class or module; no route declaration storage; no event types; no automatic tool selection; no mixed-plan support; no non-finite
hardening (G3); no durable route marker (G1).

## 10. Remaining Section 6 work
Prompt 719 wiring (section 8); a Core-level plan-execution path if one is ever wanted (G6, separate decision); durable per-plan route marker (G1, Section 4
change); non-finite plan data hardening (G3); final end-to-end Section 6 acceptance.
