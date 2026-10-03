# Prompt 708 - F1 decision record and the tool-step execution adapter (Section 6)

Status: decision + one production module, **not wired anywhere**. Module: `planning/tool_step_executor.py`.
Tests: `tests/test_section6_tool_step_executor_prompt708.py`. Neither existing stack was rewritten or removed.

## Decision (F1)

**The Prompt 689-694 `PlanStep` layer (`start_plan_step` / `complete_plan_step` / `fail_plan_step`, `execute_plan_step`) owns the future
tool-step lifecycle.** The legacy `ExecutionEngine` / `PlanExecutionController` stack stays where it is (capability-handler execution for the
current Agent Loop) and is not extended to tools. The Prompt 707 bridge and the Prompt 708 adapter compose with the first stack only.

## Comparison

| Criterion | Legacy `ExecutionEngine` / `PlanExecutionController` | Prompt 689-694 layer | Verdict |
|---|---|---|---|
| Step start / transitions | Writes step status through `PlanManager.update_step_status`; needs a step already in status `ready` (set by `PlanManager` refresh); records `ExecutionResult` objects | Three explicit, record-only transitions; every check runs before any mutation; plan re-validated by `validate_plan_step_states`; a rejected transition changes nothing | 689 layer: smaller, stricter, fully pre-checked |
| Tool authorization | Never reads `metadata["execution_authorized"]` (the flag is used only inside `planning/`); authority is `CapabilitySystem`/handler registration | `start_plan_step` requires `execution_authorized is True`; tool grants/confirmation stay Section 5's, carried only by a `ToolRequest` | 689 layer: keeps plan authorization and tool authorization as two separate single owners (706 F5) |
| Retry policy | `retry_step` with a configurable `max_retries`, `retry_of`/`retry_number` metadata | None: a failed step is final (`STEP_NOT_READY` on re-run) | Legacy is richer. **Cost of this decision: no retry exists on the selected stack** (see "Follow-ups") |
| Failure recording | Failed `ExecutionResult` in `ExecutionHistory` + `ExecutionEventLog`; step output synced | Structured reason stored as the step's `output_data`; step ends `failed` | Equivalent for a step; the adapter stores the complete Section 5 outcome |
| Completion / output | Output synced to the step | `complete_plan_step` stores explicit JSON-safe output | Equivalent |
| Audit preservation | Execution-level history/events (with timestamps and generated ids) | Tool-level audit already exists in Section 5 (`ToolInvocationRecord.sequence`); the adapter copies `sequence` onto the step so both can be joined | 689 layer + Section 5 audit loses nothing for tool calls; legacy history keeps covering capability execution |
| Determinism | Timestamps (`_now_iso`) and execution ids are part of its records | Pure functions of plan state; no clock, ids, randomness | 689 layer |
| Fit with the bridge | Bridge would have to be adapted to `PlanManager`/`ExecutionResult` | `ToolStepBridgeResult.to_dict()` was designed as the argument of `fail_plan_step` / `complete_plan_step` | 689 layer |

**Incompatibility found (documented, not fixed).** The stacks disagree on what "runnable" means: the legacy engine runs steps whose status is `ready`
(assigned by `PlanManager` refresh), while the 689 layer treats readiness as computed (`pending` + completed dependencies) and rejects a plan that
contains a `ready`/`blocked` status step with `INVALID_PLAN_STATE`. One plan therefore cannot be driven by both stacks. This does not affect the
adapter (it composes only the 689 layer) but it is a real constraint on any future Agent Loop hand-over.

## Responsibilities of the selected stack for tool steps

1. `validate_plan` and `start_plan_step` are the only gate before a tool is touched (unknown step, inconsistent state, readiness, plan authorization).
2. `execute_tool_step` (707) is the only route to Section 5; Section 5 `_evaluate()` remains the only tool authorization/input/output authority.
3. `complete_plan_step` / `fail_plan_step` are the only writers of the terminal step state and output; a started step is never left `in_progress`.
4. The step's `output_data` carries the entire `ToolStepBridgeResult.to_dict()` so reports can reconstruct what happened.
5. Retry, tool selection, grants, confirmation and audit storage are NOT step-layer responsibilities.

## Adapter API

```python
execute_plan_tool_step(plan, step_id, request, registry) -> ToolStepExecutionResult
```

Flow: `validate_plan` -> `start_plan_step` -> `execute_tool_step` (exactly once) -> `complete_plan_step` (bridge `succeeded`) or `fail_plan_step`
(bridge `failed` / `rejected`, or a defective registry). No other parameters exist (a `confirmed`, grants, tool name or retry keyword is a `TypeError`).

- Pre-start rejection (`status="rejected"`, `bridge_called=False`): not a Plan (`INVALID_PLAN_OBJECT`), invalid plan (`INVALID_PLAN`, with `issues`), or any
  `start_plan_step` code passed through unchanged (`INVALID_STEP_ID`, `UNKNOWN_STEP`, `INVALID_PLAN_STATE`, `STEP_NOT_READY`, `EXECUTION_NOT_AUTHORIZED`, ...).
  Plan and registry are untouched; the request/registry objects are not even inspected.
- `completed`: step output is `{"tool_result": <bridge to_dict()>}` (the tool output is `tool_result["output"]`).
- `failed`: step output is `{"code", "message", "tool_result", ...details}`; `code` is one of `TOOL_STEP_TOOL_FAILED` (Section 5 failure; details `outcome_code`,
  `execution_status`, `sequence`), `TOOL_STEP_BRIDGE_REJECTED` (details `outcome_code`), `TOOL_STEP_BRIDGE_EXCEPTION` (defective registry; `tool_result` is `None`;
  a `BaseException` is recorded and then re-raised), `TOOL_STEP_OUTPUT_NOT_RECORDED` (defensive).
- `ToolStepExecutionResult` fields / `to_dict()` keys: `ok, status, step_id, previous_state, final_state, bridge_called, tool_result, recorded_output, reason, failures`; also `codes()`.
- The tool's execution status, outcome code, authorization decision, `handler_called`, failures and audit `sequence` are preserved unchanged inside `tool_result`.

## Explicitly not decided (still open)

- **F2** - Section 4 `required_capabilities` (free-form, checked against `CapabilitySystem`) vs Section 5 grant names (`^[a-z][a-z0-9_]{0,63}$`). The adapter never reads
  `required_capabilities`, maps nothing and compares nothing; a step can still require a name no request can be granted.
- **H3** - rejections that never reach the registry (bridge rejection, `create_tool_request` failure, pre-start rejection) leave no audit record.
- **H4** - the request is judged by the bridge after `start_plan_step`, so an unusable request/registry ends a started step `failed`. Calling
  `registry.preflight(**request.to_registry_arguments())` first is the caller's option; the adapter does not, to avoid duplicating Section 5.
- Retry on the selected stack, the Agent Loop hand-over, the `ready`-status incompatibility above, F3 (NaN/inf asymmetry).

## Production changes

Added `planning/tool_step_executor.py`. No existing production module was modified. Test-only change: `test_bridge_is_not_wired_into_any_production_module`
(Prompt 707) now names the adapter as the single sanctioned importer of the bridge. No production defect was found while composing the contracts.
