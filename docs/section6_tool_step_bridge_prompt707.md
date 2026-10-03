# Prompt 707 - Section 6 structured tool-step bridge (Section 4 plan step <-> Section 5 tool)

Status: production module, **not wired anywhere**. Module: `planning/tool_step_bridge.py`. Tests: `tests/test_section6_tool_step_bridge_prompt707.py`.
It formalizes the boundary proposed in Prompt 706 (`docs/section6_integration_boundary_prompt706.md`) as a pure function plus an immutable result.

## API

```python
execute_tool_step(plan, step_id, request, registry) -> ToolStepBridgeResult
```

| Argument | Must be | Role |
|---|---|---|
| `plan` | `planning.plan.Plan` | read-only context; never started/completed/failed/mutated, step state is not checked (Section 4's gate) |
| `step_id` | non-blank `str` naming a step of `plan` | labels the result; the step's description/`input_data`/`expected_output`/`required_capabilities` are never read |
| `request` | `tools.tool_request.ToolRequest` | the ONLY carrier of tool name, input, grants and confirmation |
| `registry` | `tools.in_process_tool_registry.InProcessToolRegistry` | executed via `registry.execute_request(request)` only |

No other parameters exist (no `confirmed`, grants or tool name): a call with such a keyword is a `TypeError`.

### `ToolStepBridgeResult` (immutable; obtainable only from `execute_tool_step`)

Fields / `to_dict()` keys (fixed, in this order): `ok, status, failure_source, step_id, tool_name, execution_status, outcome_code,
authorization_decision, authorization_accepted, handler_called, output_available, output, failures, sequence`. Also `codes()`.
`output`/`failures` return fresh deep copies; `to_dict()` is plain JSON and valid Section 4 structured data.

| `status` | `failure_source` | Meaning |
|---|---|---|
| `succeeded` | `None` | tool completed; `output` is the tool's normalized output |
| `failed` | `"tool"` | Section 5 rejected/failed the call. `tool_name`, `execution_status`, `outcome_code`, `authorization_decision`, `handler_called`, `output_available`, `failures`, `sequence` are copied unchanged from the registry's `ToolExecutionResult` (which is derived from the audit record) |
| `rejected` | `"bridge"` | the bridge's own arguments were unusable; registry never called, handler never run, `sequence is None`, `execution_status`/`authorization_decision` are `None`, `outcome_code` is the first of the codes below |

Bridge rejection codes (all problems reported at once, in argument order): `INVALID_BRIDGE_PLAN`, `INVALID_BRIDGE_STEP_ID`,
`UNKNOWN_BRIDGE_STEP`, `INVALID_BRIDGE_REQUEST`, `INVALID_BRIDGE_REGISTRY`. Request-content validation is not repeated: it stays in
`create_tool_request()` (`INVALID_TOOL_REQUEST_*`), so an invalid tool input never becomes a request. A `ToolRequest` forged without the
factory is passed on and the registry reports `INVALID_TOOL_REQUEST` (a `failed` result with an audit sequence).

## Semantics

- One call = at most one `execute_request()` = at most one audit record and one handler call. No retry, fallback, preflight, listing or selection.
- Tool failures are returned data, not exceptions. `BaseException` (and any unexpected exception from a defective registry) propagates.
- Confirmation is per request: it lives only inside the `ToolRequest` the caller built, so it cannot authorize another request or tool, and there
  is no executor-level "confirmed" state anywhere (closes Prompt 706 hazard H2 / gap "per-request confirmation binding"). `user_confirmation`
  in granted permissions is still not a confirmation; that rule remains the registry's.
- No hidden state: no module-level registry/request, no persistence, threads, network or scheduling. The request and plan are not modified.
- A future executor maps a tool failure to a failed step without loss: `fail_plan_step(plan, step_id, result.to_dict())` keeps the complete
  Section 5 outcome (proven with the public Section 4 transitions in the tests; nothing is wired). This replaces the Prompt 706
  `code|status|seq` string encoding (F6) for callers that use the bridge directly.
- `planning/tool_step_bridge.py` is the only `planning/` module that imports `tools/` (the two Prompt 706 import-scan tests now name it explicitly).

## Preserved, unresolved decisions (integration constraints)

- **F1 - two step-execution stacks.** The legacy `ExecutionEngine`/`PlanExecutionController` (used by `AgentLoop`; has `retry_step`; never
  reads `execution_authorized`) and the Prompt 689-694 layer (authorization flag, no retry, not consumed outside `planning/`) both still exist.
  The bridge is stack-neutral: it does not start/finish steps, is not called by `execute_plan_step()` or the Agent Loop, and nothing was
  rewritten. Which stack the Agent Loop uses for tool steps remains undecided (later dedicated prompt).
- **F2 - capability vocabularies.** Section 4 `required_capabilities` is free-form (checked against `CapabilitySystem`); Section 5 grants are
  strict `^[a-z][a-z0-9_]{0,63}$` names. The bridge neither maps nor compares them and never reads a step's `required_capabilities`; a step can
  still require a name that no request can be granted. Any alignment must be an explicit, separate decision.
- Still open from Prompt 706: auditing of rejections that never reach the registry (H3 - bridge rejections and `create_tool_request` failures
  leave no audit record), F3 (NaN/inf asymmetry), and rejection-after-`start_plan_step` (H4: use `registry.preflight(**request.to_registry_arguments())` first).

## Production changes

Added `planning/tool_step_bridge.py`. No existing production module was modified. Two Prompt 706 test assertions were updated to allow exactly this one importer.
