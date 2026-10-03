# Prompt 715 - Agent Loop tool-step routing decision & contract audit

Status: **audit + decision only. Nothing is implemented, nothing is wired.** No production file changed; no defect was found that the decision
contract requires fixing. Pinned by `tests/test_section6_agent_loop_routing_decision_prompt715.py` (read-only). Baseline: Prompt 714 (adapter
`planning/tool_step_agent_adapter.py`, unwired).

## 1. Audit of the current execution paths (facts, each re-checked by a test)

- **Executable work today** is found only through the legacy stack: `AgentLoop.run(goal_id, plan_id, max_iterations)` evaluates the Goal, then calls
  `PlanExecutionController.execute_plan(plan_id)` once per iteration. `execute_plan` first calls `PlanManager.refresh_plan_step_statuses` (one-time
  rewrite of every step to `ready`/`blocked`), then loops `PlanExecutionCoordinator.get_next_ready_step` (only steps whose status is `ready` and that
  pass `PreflightValidator` + capability readiness), runs each through `StepExecutionController`/`ExecutionEngine`, and calls
  `PlanManager.refresh_after_step_change` on success. `AgentLoop` imports no `planning.tool_*` module and no `tools.*` module.
- **Capability-handler steps** run via `ExecutionEngine.execute_capability_step`: for each name in `step.required_capabilities`, in order, a *registered
  handler* is called (`handler(step)`); `retry_step` is the legacy bounded re-run of one such step. `required_capabilities` on the legacy path therefore
  means "names of executable capabilities that have handlers".
- **A tool step differs**: its unit of work is a caller-built `ToolRequest` run against an `InProcessToolRegistry` through
  `execute_agent_tool_step`; Section 4 states are `pending/in_progress/completed/failed` only; `required_capabilities` is read **only** as an explicit
  caller argument paired with a `capability_mapping` (the adapter never reads `step.required_capabilities`); it never calls a handler of the legacy stack.
- **`PlanStep` has no step-type, kind, route or metadata field** (`__slots__` are `step_id, description, dependencies, required_capabilities,
  expected_output, status, input_data, output_data`). `Plan.metadata` exists (plan-level: `executed`, `execution_authorized`, `phase`).
- **Can one plan safely hold both kinds? No.** The two stacks disagree on the state vocabulary (`ready`/`blocked` vs none) and the legacy controller
  rewrites the whole plan (live evidence in tests): a fresh plan is `pending/pending` and tool-eligible; after `refresh_plan_step_statuses` it is
  `ready/blocked` and the adapter rejects it (`ADAPTER_LEGACY_STEP_STATE`, no start); after a *legacy* completion + `refresh_after_step_change` a dependent
  becomes `ready` and is no longer tool-eligible.

## 2. Decisions

### DECISION-1: B-EXPLICIT-PLAN-SCOPED-ROUTE
Option **B**. Option A is **not expressible**: `PlanStep` cannot carry a type without modifying Section 4 (implementation gap G1). The route is an
explicit, caller-owned declaration **per plan, per call**, with exactly two values: `legacy_capability` and `section6_tool`.
- It is **never** derived from tool names, capability names, required-capability contents, registry inspection, handler availability, plan shape or
  any inference. Absent, unknown or malformed declaration => **legacy** (the status quo; existing callers are unchanged) and **never** the tool path.
- Only an explicit `section6_tool` declaration may reach `execute_agent_tool_step`. There is no default into the tool path.
- The declaration is not stored in `Plan`/`PlanStep`, and is not a new field on the adapter (the adapter keeps its 8-parameter signature; it does not
  know about routes). Gap G2: the declaration type and the routing function do not exist yet (future implementation prompt, see section 9).

### DECISION-2: MIXED-PLANS-REJECTED
A plan is driven by exactly one stack. Reasons (all pinned): no per-step type exists (G1); the stacks' state vocabularies conflict; the legacy
controller rewrites every step; a legacy completion flips tool dependents to `ready`; a failed tool step is terminal and leaves dependents `pending`
(Section 4 has no blocked marker) while legacy would compute `blocked`. Consequences: dependencies never cross stacks; no cross-stack failure
propagation is defined; completion is represented only in Section 4 terms (`completed`/`failed`, `AgentToolStepResult`) for tool plans and only in
legacy terms for legacy plans. Enforcement: a `section6_tool` plan must never be handed to `AgentLoop.run`/`PlanExecutionController`/`ExecutionEngine`;
a `legacy_capability` plan must never be handed to the adapter; a legacy label on **any** step makes the whole plan tool-ineligible (already enforced by
the adapter). Mixed-plan support would need a new decision (future, only after G1).

### DECISION-3: SECTION4-STATES-ONLY-FOR-TOOL-ROUTE
Tool steps use Section 4 readiness (`get_ready_plan_steps`, `validate_plan_step_states`). Legacy `ready`/`blocked` are *labels written by
`PlanManager.refresh_*`*, not Section 6 execution states. No automatic conversion, no repair, **no `PlanManager.refresh_*` during tool execution**. If
a legacy coordinator already rewrote the plan, the caller must not convert it: the call is rejected with `ADAPTER_LEGACY_STEP_STATE` (nothing started,
plan/registry unchanged) and the caller either keeps the plan on the legacy route or builds a *new* Section 4 plan (DECISION-4 of Prompt 713: another
attempt is a new plan).

### DECISION-4: F3-REJECT-BEFORE-START (contract only)
Section 4 plan data may currently contain NaN/inf (`validate_plan` and `validate_plan_step_states` accept them - asymmetry F3). `ToolRequest` rejects
them (`create_tool_request` -> `ok=False`, `INVALID_TOOL_REQUEST_INPUT`). The routing path must not sanitise, clamp, coerce or drop such values. So a
non-finite number in the tool input means **no `ToolRequest` exists**, nothing can be handed to `execute_agent_tool_step`, and the tool step fails
before start (`execution_started` False, handler count 0, registry untouched, step unchanged; the retry layer only records the one rejected pre-start attempt). A non-`ToolRequest` object passed to the adapter is itself rejected before start.
Implementation is unchanged (gap G3: Section 4 still accepts non-finite data).

### DECISION-5: CALLER-OWNED-TOOLREQUEST
The caller constructs the `ToolRequest` (via `create_tool_request`) from **already validated structured input** with explicit `name`, `tool_input`,
`granted_permissions`, `granted_capabilities`, `confirmed`. Neither `AgentLoop`/`process_input` nor the adapter infers permissions, capabilities,
confirmation or mappings from user intent, and the adapter never builds or alters a request. A dedicated request-builder module is **deferred**: if a
later prompt adds one it must be a pure structural mapper of explicit fields (no intent interpretation, no defaults that grant anything). Gap G4: no
"validated structured intent" type exists yet.

### DECISION-6: ADAPTER-IS-THE-ONLY-TOOL-STEP-ENTRY
`execute_agent_tool_step` is the only future entry point for tool steps. It stays the final pre-execution boundary: it re-validates everything below.
Forbidden for the integration: `execute_plan_tool_step*`, `execute_tool_step`, `execute_plan_tool_step_with_retry` (adapter-internal),
`registry.execute/execute_request/invoke`, `start/complete/fail_plan_step` on tool steps, handlers, `PlanManager.refresh_*`, legacy `retry_step`.

## 3. Tool-step eligibility contract (all must hold before the future Agent Loop may call `execute_agent_tool_step`)

Caller-side (routing layer, future): (R1) the caller declared route `section6_tool` explicitly for this plan; (R2) the plan has never been handed to the
legacy stack; (R3) the caller built the `ToolRequest` itself; (R4) the caller chose `max_attempts`; (R5) the caller supplies the registry.
Adapter-side (enforced today, fixed order, first failure rejects, zero attempts): valid `Plan` object and `validate_plan` (`ADAPTER_INVALID_PLAN_OBJECT`,
`ADAPTER_INVALID_PLAN`); `validate_plan_step_states` valid, no `ready`/`blocked` on any step (`ADAPTER_INCONSISTENT_STEP_STATE`,
`ADAPTER_LEGACY_STEP_STATE`); non-empty existing step id (`ADAPTER_INVALID_STEP_ID`, `ADAPTER_UNKNOWN_STEP`); `metadata["execution_authorized"] is True`
(`ADAPTER_EXECUTION_NOT_AUTHORIZED`); `max_attempts` int (not bool) in `1..MAX_ADAPTER_ATTEMPTS` (10), `attempt_log` None or list
(`ADAPTER_INVALID_MAX_ATTEMPTS`, `ADAPTER_INVALID_ATTEMPT_LOG`); optional `required_capabilities` + `capability_mapping` both or neither, well-formed
(`ADAPTER_INVALID_MAPPING_ARGUMENTS`, `ADAPTER_MALFORMED_CAPABILITY_MAPPING`). Judged by the retry layer, still before the step starts: request is a
valid `ToolRequest`, registry is a valid `InProcessToolRegistry`, registry preflight (exists/enabled/permissions/confirmation/capabilities/input). A
started, completed or failed step is terminal.

## 4. Legacy capability-step contract

A step/plan stays on the legacy path unless the caller explicitly declared `section6_tool` for the whole plan. Legacy plans are created/held by
`PlanManager`, carry `required_capabilities` = handler-backed capability names, use `ready`/`blocked`, and run only through
`AgentLoop.run` -> `PlanExecutionController.execute_plan` -> `StepExecutionController`/`ExecutionEngine`. The legacy path is not changed in any way.
**Legacy `retry_step` does not apply to Section 6 tool steps** (tool retries exist only inside `execute_plan_tool_step_with_retry`, bounded by the
adapter's `max_attempts`, and never after a started step).

## 5. Exact future boundary

```
AgentLoop / process_input
  -> routing decision            (explicit caller-owned route declaration per plan; absent => legacy)
       legacy_capability -> AgentLoop.run -> PlanExecutionController -> StepExecutionController -> ExecutionEngine   (unchanged)
       section6_tool     -> caller-owned ToolRequest construction (create_tool_request, explicit fields, no inference)
                         -> execute_agent_tool_step(plan, step_id, request, registry, max_attempts,
                                                    required_capabilities=None, capability_mapping=None, attempt_log=None)
                         -> Section 6 retry (execute_plan_tool_step_with_retry) / preflight / bridge
                         -> Section 5 tool authority (InProcessToolRegistry.preflight()/execute())
```

## 6. Implementation gaps (documented, not fixed here)

G1 `PlanStep` has no type/route/metadata (Section 4 model change needed for per-step routing or mixed plans). G2 no route-declaration type or routing
function. G3 Section 4 accepts non-finite plan data. G4 no validated-structured-intent type / request builder. G5 `AgentLoop.run` only knows
`PlanExecutionController`; wiring a second path needs its own prompt. G6 `process_input()` produces no structured tool intent.

## 7. Recommended Prompt 716

Add a new, isolated module (e.g. `planning/tool_step_route.py`) holding only the two route constants and a pure `resolve_execution_route(declaration)`
(absent/unknown/malformed => legacy; never reads a plan, registry, name or handler), with tests; still **no** AgentLoop/`process_input` wiring. Wiring,
request building and non-finite hardening (G3) follow as separate later prompts.
