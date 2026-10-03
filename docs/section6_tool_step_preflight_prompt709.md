# Prompt 709 - Pre-start tool preflight and rejection recording (Section 6)

Status: one new caller-driven function in `planning/tool_step_executor.py`, **not wired anywhere**.
Tests: `tests/test_section6_tool_step_preflight_prompt709.py`. Resolves Prompt 706 hazards **H3** and **H4**.
F1 (decision: the Prompt 689-694 step layer owns tool steps) is unchanged. **F2 stays explicitly unresolved.** Retry design, the Agent Loop
hand-over, `process_input()` and the legacy `ExecutionEngine`/`PlanExecutionController` stack are untouched.

## API

```python
execute_plan_tool_step_preflighted(plan, step_id, request, registry, rejection_log=None) -> PreflightedToolStepResult
```

`execute_plan_tool_step()` (Prompt 708) is unchanged and still does not preflight (H4 behaviour preserved for callers that keep using it).

### Order (each stage stops at its first rejection)

1. `rejection_log` must be `None` or a `list`.
2. The bridge's own arguments: `validate_bridge_arguments()` (extracted from `execute_tool_step()` in `planning/tool_step_bridge.py`;
   behaviour-identical, the bridge remains their only owner), then `request.to_registry_arguments()` must be usable (a request forged without
   the factory is caught here).
3. Plan context: `validate_plan()` and `start_plan_step()` on a **deep copy** of the plan. Section 4 stays the only judge of unknown step,
   plan state, readiness and `execution_authorized`; the real plan is not touched.
4. `registry.preflight(**request.to_registry_arguments())`. Section 5 stays the sole authority for tool existence, enabled state,
   permissions, confirmation, capabilities and input; nothing of that is re-implemented. The complete `ToolPreflightResult.to_dict()` is kept.
5. Only after a passed preflight: exactly one call of the unchanged `execute_plan_tool_step()`, i.e. `start_plan_step`, then the bridge and
   `execute_request()` with all normal execution checks, then `complete_plan_step` / `fail_plan_step`. No retry.

A rejection in stages 1-4 never starts the step, never calls the handler, never reaches `execute_request()`, never mutates the plan and never
appends a `ToolInvocationRecord` (Section 5's `preflight()` itself is read-only and audit-free).

### Result: `PreflightedToolStepResult`

Fields / `to_dict()` keys: `ok, status, outcome_kind, step_id, tool_name, previous_state, final_state, preflight_called, preflight,
execution_called, execution, reason, failures, rejection_record, sequence`; also `codes()`.

| `outcome_kind` | `status` | meaning | `preflight_called` | `execution_called` | `rejection_record` |
|---|---|---|---|---|---|
| `pre_registry_rejection` | `rejected` | rejected before the Registry could be asked (bad log/bridge arguments/request object/registry object/plan or step context) | False | False | dict |
| `registry_preflight_rejection` | `rejected` | Section 5 preflight said no (complete report in `preflight`); also a defective `preflight()` (`PRESTART_PREFLIGHT_EXCEPTION`, no verdict, step not started) | True | False | dict |
| `tool_execution_failure` | `failed` | preflight passed, the step started and the normal execution path failed it (also a TOCTOU rejection); `execution` holds the actual `ToolStepExecutionResult.to_dict()` | True | True | None |
| `completed` | `completed` | preflight passed and the tool step completed | True | True | None |

`sequence` is the registry audit sequence of the ACTUAL execution only; it is `None` for every rejection. `preflight` is the Section 5
report (`None` before the registry is asked). Failure codes: pre-registry rejections use the bridge codes (`INVALID_BRIDGE_PLAN`,
`INVALID_BRIDGE_STEP_ID`, `UNKNOWN_BRIDGE_STEP`, `INVALID_BRIDGE_REQUEST`, `INVALID_BRIDGE_REGISTRY`), the Section 4 codes
(`INVALID_PLAN`, `STEP_NOT_READY`, `EXECUTION_NOT_AUTHORIZED`, ...) and three new ones: `INVALID_PRESTART_REQUEST`, `INVALID_REJECTION_LOG`,
`PRESTART_PREFLIGHT_EXCEPTION`. Registry rejections carry Section 5's own failure entries unchanged.

## H3 - recording rejections that never reach the registry

Every pre-start rejection is described by a plain-dict **rejection record**:
`{"record_type": "prestart_rejection", "rejection_kind", "step_id", "tool_name", "codes", "failures", "preflight", "invocation_recorded": False,
"sequence": None}`. It is returned as `result.rejection_record` and, when the caller passes a list as `rejection_log`, a fresh copy is appended to
THAT list. The record is caller-owned: the module keeps no log, no module state and no clock. It is deliberately not a `ToolInvocationRecord`:
no sequence is fabricated and the registry history is never written, so `get_invocation_history()` only ever describes real `execute_request()` calls.

## H4 - unusable request no longer starts a step

With the preflighted function an unusable request/registry, or a request Section 5 already knows it will reject, leaves the step `pending`
(`rejected`), so a caller can fix the request and run the same step again. Stale verdicts are never reused: every call preflights afresh.

## TOCTOU

Preflight is advisory, execution is authoritative. If the registry changes between the passed preflight and execution (for example a tool is
disabled), execution goes through the normal `execute_request()` path unchanged and is rejected there; the started step is failed normally
(`TOOL_STEP_TOOL_FAILED`), the actual result (with its audit `sequence`) is recorded on the step and returned, and nothing is retried.

## Boundaries and guards

- The executor imports no `tools` module and never names `execute_request`/`ToolRequest`; its only registry call is `preflight`. The Prompt 708
  source-guard test was updated accordingly (adds the `copy` import, allows `preflight` as the single sanctioned registry attribute, still forbids
  `execute_request`, `handler`, grants, confirmation and step `required_capabilities`).
- Terminal-state guarantee is unchanged: no pre-start rejection leaves a step `in_progress`; a started step always ends terminal.
- Not referenced by any other production module (test-enforced).

## Explicitly still open

F2 (Section 4 `required_capabilities` vs Section 5 grant names), retry on the selected stack, the Agent Loop hand-over, the `ready`-status
incompatibility between the two stacks, F3 (NaN/inf asymmetry).

## Production changes

- `planning/tool_step_executor.py`: added `execute_plan_tool_step_preflighted`, `PreflightedToolStepResult`, constants; `execute_plan_tool_step` untouched.
- `planning/tool_step_bridge.py`: extracted the bridge's own argument checks into `validate_bridge_arguments()` (used by `execute_tool_step()`, same
  failures, same order); no behaviour change (all 707 tests pass unchanged).
- No production defect was found.
