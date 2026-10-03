# Prompt 719-C - Section 6: AgentLoop wiring to the tool-step runner

Status: **implemented, additive, one new public method.** Pinned by `tests/test_section6_agent_loop_routed_step_prompt719c.py`.
Builds on 716 (route), 717 (dispatch), 718 (wiring decision), 719-A (intent adapter), 719-B (runner).

## The seam

```
AgentLoop.execute_routed_step(declaration=None, legacy_input=None, tool_input=None,
                              capability_system=None, tool_registry=None) -> dict
```

All routing inputs are caller-owned; nothing in `AgentLoop` computes, defaults or infers them. It sits beside `execute_next_step` in `agent/agent_loop.py`. It is explicitly invoked only; `run()`, `execute_next_step()`, `__init__` and every
other existing method are byte-identical (the test reconstructs the pre-719-C file by removing exactly three import lines and this one method and
checks the original SHA-256). The method resolves the route once with `resolve_tool_step_dispatch`, then branches once.

## Caller-owned inputs

| input | owner | used by |
|---|---|---|
| `declaration` | caller | route resolution only; exact `"section6_tool"` or `"legacy_capability"` |
| `legacy_input` | caller | legacy route only: `{"plan_id": <non-blank str>}` |
| `tool_input` | caller | Section 6 route only: the 719-A intent dict (plain JSON-safe data) |
| `capability_system` | caller | legacy route only, passed to `execute_next_step` |
| `tool_registry` | caller | Section 6 route only, passed to the runner |

The **Plan** comes from this loop's own `PlanManager.get_plan(intent.plan_id)`; a miss (`None`) is passed on and the runner rejects it
(`RUNNER_PLAN_ID_MISMATCH`). Nothing is defaulted, discovered or held in global state.

## Legacy vs Section 6 boundary

- **Legacy route** (absent, unknown, malformed, or explicit `"legacy_capability"`): `execute_next_step(plan_id, capability_system)` is called once,
  unchanged, and its dict is returned as `legacy_result`. `tool_input` is never inspected.
- **Section 6 route** (explicit `"section6_tool"` only): `build_tool_step_intent(tool_input)` (719-A) -> `run_tool_step_intent(intent, plan, registry)`
  (719-B), called exactly once. Authorization, retry, capability mapping and `ToolRequest` construction stay in those existing layers. The runner
  result is returned as `tool_result` (`to_dict()`).
- An explicit Section 6 route **never falls back to legacy**: dispatch rejection, intent rejection, runner rejection and a non-ok run are all
  returned as they are, nothing is caught, and `execute_next_step` / `refresh_plan_step_statuses` are unreachable from that branch.

Envelope keys: `route, explicit, fallback, route_code, dispatch_status, dispatch_code, stage, status, error_code, failures, legacy_result, tool_result`.
`stage` is `dispatch | payload | execution`; `status` is `rejected` (nothing handed to an executor), `executed`/`not_executed` (legacy), or
`completed`/`failed` (runner `ok`). Error codes added here: `LEGACY_INPUT_INVALID`, `SECTION6_INTENT_REJECTED`, `SECTION6_RUN_NOT_OK`; dispatch
codes are passed through unchanged. At most one of `legacy_result` / `tool_result` is populated.

## `process_input` stays intentionally untouched

`Core.process_input` is `str -> str`, has no plan, step, registry or execution path, and never reaches `AgentLoop`. Giving it a route would mean
parsing text (forbidden) or widening a public contract. `core/core.py`, `Plan`, `PlanStep`, `PlanManager`, `ToolRequest`, Section 5 and the retry
implementation are unchanged; their frozen hashes are re-checked.

## Test-only guard updates

Older guards (712-718, 719-A) pinned the pre-719-C bytes of `agent/agent_loop.py` or forbade references to Section 6 / route vocabulary there.
Each now reads that **one exact path** through `tests/section6_agent_loop_baseline_prompt719c.py`, which removes only the sanctioned additions; 712 and
719-A list `agent/agent_loop.py` as one more exact-path consumer, and 718's "no `execute_routed_step` yet" assertion now expects that one method.
All other paths and all other assertions are unchanged.

## Remaining architectural limitations (residual, not addressed here)

- **Mixed-plan guard (718 DECISION-7 / gap G1):** no in-memory `plan_id -> route` pin was added, so a plan started through Section 6 can still be fed
  to the legacy route (and the reverse is rejected only by the adapter's legacy-state check). Direct `run()` / `execute_next_step()` calls were never guarded.
- `tool_input` must be JSON-safe exact-type data (dispatch rejects tuples), so tuple-valued grant lists are rejected on this route.
- No `ExecutionEventLog` event is written on the Section 6 route (the Section 5 registry audit trail remains the audit authority).
- `process_input` / Core still has no plan-execution path (gap G6); a Core-level seam is a separate decision.
