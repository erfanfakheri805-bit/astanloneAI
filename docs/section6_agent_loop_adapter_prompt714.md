# Prompt 714 - Section 6 Agent-Loop tool-step adapter

Status: one new module, `planning/tool_step_agent_adapter.py`, **not wired anywhere** (no `process_input()`, no `AgentLoop.run()`, no legacy
`execution/`, no `PlanManager.refresh_*`). Tests: `tests/test_section6_agent_loop_adapter_prompt714.py`. Implements the Prompt 713 hand-over
decisions (DECISION-1 to DECISION-4). No Section 4/5 file and no earlier Section 6 module changed.

## Why this adapter exists

Prompt 713 decided that the Section 4 PlanStep/tool-step stack owns Agent-Loop tool-step execution and that integration must go into a **new**
caller-side module. The adapter is that module: the single, narrow boundary a future Agent Loop calls. It closes the gaps the decision record listed
(C1/C2 ready/blocked conflict, unbounded `max_attempts`, request building) *before* any step starts, and returns one immutable, data-only result.

## Why AgentLoop is not modified yet

`AgentLoop.run()` drives only the legacy `PlanExecutionController` for capability-handler steps, and that behaviour is out of scope and byte-identical.
Wiring a second execution path into it needs its own decision (which plans go to which stack, how the Agent Loop obtains a caller-built
`ToolRequest`), so this prompt only provides and tests the boundary. `process_input()` and `retry_step` are untouched too.

## Why legacy `ready` / `blocked` states are rejected

`ready`/`blocked` are labels written by `PlanManager.refresh_*`, not Section 4 states. `validate_plan()` accepts a plan carrying them (conflict C2)
while `validate_plan_step_states()` and `start_plan_step()` reject it, so the adapter runs **both** validations and fails closed with
`ADAPTER_LEGACY_STEP_STATE`. Nothing is converted, repaired or refreshed, `PlanManager.refresh_*` is never called, and a legacy label on *any* step makes
the whole plan ineligible (one plan is driven by one stack at a time).

## API

```python
execute_agent_tool_step(plan, step_id, request, registry, max_attempts,
                        required_capabilities=None, capability_mapping=None, attempt_log=None) -> AgentToolStepResult
```

`request` is caller-built (`create_tool_request()`); the adapter never constructs or changes it. The mapping is the caller's explicit pair
(`required_capabilities` + `capability_mapping`, both or neither); nothing is inferred and a mapping never grants. `max_attempts` is 1..`MAX_ADAPTER_ATTEMPTS`
(10; the adapter's own finite bound, no default). `attempt_log` is an optional caller-owned list; the retry layer appends one record per attempt to it
(the only write on caller data). Result fields: `ok, status (completed|failed|rejected), failure_source (None|adapter|pre_start|tool_execution),
failure_code, step_id, execution_started, final_step_state, retry_stop_reason, attempt_count, attempts, outcome_kind, tool_result, failures,
invocation_sequence, mapping, preflight`; every structured value is a fresh copy, nothing references a handler, registry or plan.

## Validation order (all before any step starts; first failure rejects, zero attempts)

| stage | check | code |
|---|---|---|
| a | `Plan` object, then `validate_plan` valid | `ADAPTER_INVALID_PLAN_OBJECT`, `ADAPTER_INVALID_PLAN` |
| b | `validate_plan_step_states` valid; legacy `ready`/`blocked` named explicitly | `ADAPTER_LEGACY_STEP_STATE`, `ADAPTER_INCONSISTENT_STEP_STATE` |
| c | non-empty `str` step id that exists | `ADAPTER_INVALID_STEP_ID`, `ADAPTER_UNKNOWN_STEP` |
| d | `metadata["execution_authorized"] is True` (plan-level gate, never inferred) | `ADAPTER_EXECUTION_NOT_AUTHORIZED` |
| e | `max_attempts` int (not bool) in range; `attempt_log` None or list | `ADAPTER_INVALID_MAX_ATTEMPTS`, `ADAPTER_INVALID_ATTEMPT_LOG` |
| f | mapping pair together; a supplied pair well-formed | `ADAPTER_INVALID_MAPPING_ARGUMENTS`, `ADAPTER_MALFORMED_CAPABILITY_MAPPING` |

A rejection changes nothing: step unchanged, no registry call, no handler call, no invocation record, no registry sequence number. Request/registry
validity, an unmapped-but-well-formed mapping, an ungranted mapped grant and registry preflight rejections are judged by the retry layer, still before
the step starts, and may be retried only as Prompt 711 allows (never beyond `max_attempts`; a started, completed or failed step is terminal; malformed input
is never retried).

## Future Agent Loop -> adapter boundary

The Agent Loop (future, in its own prompt) is a **caller** that supplies: an already-owned `Plan` (authorization set by the plan's owner), a step id, a
`ToolRequest` built by `create_tool_request()` (permissions, grants, confirmation are its decision), the `InProcessToolRegistry`, `max_attempts`, and
optionally the explicit mapping pair. It calls `execute_agent_tool_step(...)` once per step and reads the `AgentToolStepResult`. It never selects a tool
for the step, never grants, never maps automatically, never touches handlers, and never re-runs a failed step (DECISION-4: another attempt is a new plan).

## Lower-level APIs that must NOT be called directly by the integration

`execute_plan_tool_step_with_retry` is called only by the adapter (its single execution entry point). The Agent Loop must NOT be calling
`execute_plan_tool_step`, `execute_tool_step`, `execute_plan_tool_step_preflighted` / `_mapped`, `registry.execute` / `execute_request` / `invoke`,
`start_plan_step` / `complete_plan_step` / `fail_plan_step` for tool steps, any tool handler, `PlanManager.refresh_*`, or the legacy `retry_step`.

## Still open (not done here)

`process_input()` / `AgentLoop.run()` integration; how a caller builds a `ToolRequest` from user intent; F3 (Section 4 still accepts non-finite plan data).
