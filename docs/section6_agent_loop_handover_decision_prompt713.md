# Prompt 713 - Section 6 Agent-Loop hand-over decision record

**Status: DECISIONS RECORDED AND TEST-PINNED. Nothing is implemented.** No production file was added or changed (Section 4, Section 5,
Section 6, legacy execution stack and `agent/` are byte-identical to Prompt 712). Only this document and
`tests/test_section6_agent_loop_handover_decision_prompt713.py` were added. Every statement below was checked against the current
code; the test file re-checks it on every run.

Machine-checked markers: `DECISION-1: A`, `DECISION-2: SECTION4-PENDING-READY`, `DECISION-3: REJECT-BEFORE-START-AT-REQUEST`,
`DECISION-4: FAILED-IS-TERMINAL`.

---

## DECISION-1: A - the Section 4 PlanStep/tool-step stack owns Agent Loop tool-step execution

**Selected owner:** the Prompt 689-712 stack (`start_plan_step` / `complete_plan_step` / `fail_plan_step`, the Prompt 707-711 bridge, preflight,
mapping and retry modules) on `planning.plan.Plan` objects.

**Why not the legacy `ExecutionEngine` / `PlanExecutionController` (B):**
- It has no contract for tools at all: it imports no `tools` module and never mentions Section 5. It executes *capability handlers*
  (`CapabilityHandlerRegistry`, `ExecutableCapabilityRegistry`), a different concept from Section 5 tools.
- It has no notion of `execution_authorized` (zero occurrences in `execution/`). Section 4 makes that flag a hard gate on every start; adopting B
  for tools would drop the authorization gate that Section 5's guarantees are layered on.
- Its step lifecycle is written through `PlanManager.update_step_status` (any recognised status, no transition rules), while the Section 4 layer
  has three explicit, pre-checked transitions. Its audit (`ExecutionHistory`, timestamps, generated ids) is not the Section 5 audit; the Section 4
  path joins the step to the registry record by `sequence`.
- Its `retry_step` re-runs a FAILED step; that contradicts DECISION-4 and would duplicate the Prompt 711 retry policy.

**What remains of the legacy stack:** unchanged and still the Agent Loop's path for **capability-handler steps** (`AgentLoop.run()` ->
`PlanExecutionController.execute_plan`). It is not extended to tools, not deprecated, not modified. It never calls Section 6.

**Exact boundary between planning and execution:**
- *Planning side (Section 4, owns plan truth):* builds/validates the `Plan`, owns step state, dependencies, `executed`/`execution_authorized`
  flags, readiness (`get_ready_plan_steps`) and every step transition.
- *Execution side (Section 5, owns tool truth):* the `InProcessToolRegistry` alone decides whether a tool exists, is enabled and is authorized
  (`preflight()` / `_evaluate()`), and is the only writer of the invocation audit.
- *Section 6 (the only place they meet):* caller-driven composition; the bridge is the only `planning/` module that imports `tools`.
- *Agent Loop (future):* a caller. It supplies the plan, step id, a caller-built `ToolRequest`, the registry, `max_attempts`, and (optionally) an
  explicit mapping pair. It never selects a tool, never grants, never maps capabilities automatically, never touches handlers.

**APIs future integration MAY call (and nothing else in Section 6):**
`execute_plan_tool_step_with_retry` (preferred single entry), `execute_plan_tool_step_mapped`, `execute_plan_tool_step_preflighted`,
`get_ready_plan_steps` / `validate_plan` / `validate_plan_step_states` (read-only), `create_tool_request` (Section 5 factory),
`map_required_capabilities` (only with a caller-supplied mapping).
`execute_plan_tool_step` and `execute_tool_step` stay callable but are lower-level and post-start-validating; the integration should not use them
directly because they judge an unusable request *after* the step started.

**APIs that MUST remain untouched by the integration prompt:** everything in `tools/`, every non-Section-6 `planning/` module (including
`plan_manager.py` and `plan_builder.py`), the four Section 6 modules' signatures and behaviour, and the whole legacy `execution/` package and
`agent/agent_loop.py` existing behaviour. Integration code goes into a **new** adapter module.

## DECISION-2: SECTION4-PENDING-READY - one readiness contract, owned by Section 4

| State | Meaning under this contract |
|---|---|
| `pending` | Not started, no output. The **only** state from which a step can become ready. |
| `ready` | **Not a Section 4 state.** A legacy derived label written by `PlanManager.refresh_*`. It is never authoritative and never authorizes execution. |
| `blocked` | Same: legacy derived label, not a Section 4 state. |
| `in_progress` | Started (`start_plan_step`); must end `completed` or `failed`. Never ready, never re-startable. |
| `completed` | Terminal. Satisfies dependencies of other steps. |
| `failed` | Terminal (DECISION-4). Never satisfies a dependency. |

- **Ready (Section 4):** a step is ready iff the plan's flags are explicit booleans, every step state is one of the four Section 4 states, the
  dependency graph is valid, the step is `pending`, has no `output_data`, and every dependency is `completed`. Computed **only** by
  `planning.plan_builder.get_ready_plan_steps` (pure, read-only, plan order).
- **Authorization is separate from readiness.** `execution_authorized is True` is required to *start* a step (`start_plan_step`), never to be
  *ready*. Only the caller that owns the plan sets it; the Agent Loop must not set it. Readiness never implies authorization and authorization
  never implies readiness.
- **Eligibility of a plan for Agent-Loop tool-step execution:** `validate_plan` valid AND `validate_plan_step_states` valid (so only the four
  Section 4 states, boolean flags) AND `execution_authorized is True`, AND the step in question is in `ready_step_ids`. Section 6's dry-run start
  already enforces exactly this on a copy; the integration adds no second rule.
- **Who computes readiness:** Section 4 (`get_ready_plan_steps`). Not `PlanManager.get_ready_step_ids` (a weaker third notion: ignores flags and
  output) and not the legacy coordinator (`get_next_ready_step`, which looks only for the label `ready`).
- **When the stacks disagree, Section 4 wins for tool steps.** Nothing is converted or repaired automatically: a plan holding `ready`/`blocked`
  labels is *ineligible* and the rejection (`INVALID_PLAN_STATE`, non-retryable) is reported as-is. The legacy stack keeps judging capability
  steps by its own rule on plans it owns. One plan is driven by one stack at a time.

**Conflicts documented for the implementation prompt (current behaviour, deliberately NOT changed):**
- C1. `PlanManager.refresh_plan_step_statuses` rewrites `pending` steps to `ready`/`blocked`; after that call Section 4 rejects the whole plan
  (`UNSUPPORTED_STEP_STATE`, start -> `INVALID_PLAN_STATE`) while the legacy coordinator accepts it. A pending-only plan is invisible to the legacy
  coordinator (`No READY steps found`). The two stacks therefore cannot share a plan.
- C2. `validate_plan()` reports a plan with a `ready` step as **valid**, but `start_plan_step()` rejects the same plan
  (`validate_plan_step_states`). The two Section 4 surfaces disagree; the integration must gate on `validate_plan_step_states` too.
- C3. Correction to the Prompt 712 wording: it said "Section 4 plan validation rejects ready/blocked"; precisely, `validate_plan_step_states` /
  `start_plan_step` / `get_ready_plan_steps` reject them, `validate_plan` does not (see C2).

## DECISION-3: REJECT-BEFORE-START-AT-REQUEST - non-finite numbers never cross into Section 5

Policy for `float('nan')`, `float('inf')`, `float('-inf')` on the path Plan data -> `ToolRequest` -> Section 5:
- **Rejected, never coerced.** No clamping, no `null`, no string, no dropping of a key. Deterministic and fail-closed.
- **Where:** at `create_tool_request()` (Section 5's existing rule, `INVALID_TOOL_REQUEST_INPUT`), i.e. **before any executor is called and
  therefore before any plan step can start**. No request object exists, so no step starts, no preflight runs, no invocation record or sequence is
  created. The registry independently rejects the same input (`INVALID_TOOL_INPUT` from `preflight`) as defence in depth.
- **Nested values:** any depth, inside dict values, lists or tuples, is rejected exactly like a top-level value.
- **Direct `ToolRequest` input vs plan-generated input:** identical. Plan data is never read by Section 6 (the bridge ignores a step's
  `input_data`); the only way plan data reaches a tool is the caller explicitly passing it to `create_tool_request()`, which applies the rule. A
  forged request (built without the factory) is rejected pre-start by the Section 6 preflight.
- **Section 5 is not weakened**; the rule lives where it already lives.
- **Tool output direction:** Section 5 rejects non-finite handler output (`TOOL_OUTPUT_INVALID`), so Section 6 can never store a non-finite value from
  a tool as step output (the step is `failed` with a JSON-strict output).
- **Not changed (recorded asymmetry):** Section 4 structured data (`PlanStep.input_data`, and `complete_plan_step`'s caller-supplied output) still
  *accepts* non-finite floats. That is allowed as plan-internal data; it simply cannot cross to Section 5. Tightening Section 4 is optional and out of
  scope; if ever done it must be its own prompt with migration tests.

## DECISION-4: FAILED-IS-TERMINAL - a failed step is never re-run in place

- **No reset/retry transition exists and none is authorized.** `failed` is terminal for this architecture: the only transitions are
  `pending -> in_progress -> completed|failed`. Nothing (not the Agent Loop, not a caller flag) may move a failed step back.
- **Another attempt = a new step in a new plan.** A caller that wants another attempt builds a **new** `Plan` (new plan id, new step id, fresh
  `pending` state, `execution_authorized` set by the plan's owner) and a new `ToolRequest`. Dependencies of the new step are declared explicitly in
  the new plan by the planner; a dependent of a failed step is never ready (a failed step does not satisfy dependencies), so the old dependents are
  not silently released.
- **History:** the old plan keeps the failed step and its recorded failure output unchanged; the registry keeps the old invocation record
  (`sequence` unchanged). The new attempt gets its own, new invocation record and the next registry `sequence`; pre-start rejections still never
  consume one.
- **Legacy `ExecutionEngine.retry_step`** re-runs a FAILED capability step in the legacy stack. It is not part of the tool-step path, is never called by
  Section 6, and must not be used for tool steps. The Prompt 711 retry stays the only retry (pre-start rejections only, caller-bounded).
- Nothing implements a reset in this prompt or the next one unless a later prompt reverses this decision explicitly, together with the tests below.

---

## Recorded conflicts for the next implementation prompt
1. C1/C2 above (ready/blocked labels, `validate_plan` vs `validate_plan_step_states`): the adapter must gate on `validate_plan_step_states`
   and report, never repair, a plan carrying legacy labels.
2. `AgentLoop.run()` currently drives only `PlanExecutionController`; a tool-step path needs a **new** caller-side adapter, not edits to `run()`.
3. Section 4 accepts non-finite plan data (DECISION-3 asymmetry); the adapter must build requests only through `create_tool_request()` and treat
   its rejection as terminal for that build (no coercion).
4. `max_attempts` has no upper bound (caller responsibility); the adapter should choose and document its own finite bound.
5. Legacy `retry_step` stays reachable through the legacy stack; the adapter must never route tool steps to it.

## Recommended Prompt 714
A new, isolated **Agent-Loop tool-step adapter module** (caller-side only, not wired into `process_input()`): given an already-eligible plan it gates on
`validate_plan` + `validate_plan_step_states` + `execution_authorized`, builds nothing itself, calls only `execute_plan_tool_step_with_retry`, and
reports a structured result. Tests must include the C1/C2 conflict cases and prove the legacy stack is untouched.
