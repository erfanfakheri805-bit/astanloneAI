# Prompt 706 - Section 6 integration boundary contract (Section 4 plan steps <-> Section 5 tools)

Status: contract + audit only. Nothing is wired. Tests: `tests/test_section6_integration_boundary_prompt706.py`
(one class per item below; `ToolStepBridge` in that module is a test-local reference of the proposal, not production code).

## Proposed boundary

```
trusted caller  ->  bridge = <executor closure>(registry, granted_permissions, granted_capabilities, confirmed)
execute_plan_step(plan, step_id, bridge)          Prompt 691: validate_plan -> start_plan_step (ready + execution_authorized) -> executor ONCE
  bridge(step_input)                              step-scoped dict only; tool named by step_input["input_data"]["tool_request"] = {"name", "input"}
    create_tool_request(name, input, caller grants, caller confirmation)      -> INVALID_TOOL_REQUEST_* stops here (not audited)
    registry.execute_request(request)             == execute(**request.to_registry_arguments()) -> _evaluate -> handler -> output checks -> ONE audit record
    result.ok        -> return {"tool_result": result.to_dict()}              -> complete_plan_step (output stored)
    not result.ok    -> raise ToolStepFailure("<outcome_code>|<execution_status>|seq=<n>")  -> fail_plan_step (reason stored)
```

`PlanStep` and `Plan` gain no field. The tool name is plain step data (`input_data`); the registry alone decides whether it exists.

## The 12 requested points

| # | Point | Contract |
|---|---|---|
| 1 | Plan step -> tool boundary | The executor callback of `execute_plan_step` is the only seam. Plan/step gates run first; a rejected plan/step never reaches a registry. `planning/` and `tools/` import each other nowhere. |
| 2 | Naming a tool | Exact name in `input_data["tool_request"]["name"]`. Description, `expected_output`, `required_capabilities` never select a tool; no fuzzy match, no listing/describing; unknown -> `UNKNOWN_TOOL`. |
| 3 | Grants | Held by the caller-owned executor. Anything in step data (`granted_*`, `confirmed`, `authorized`) is ignored. Plan `execution_authorized` is not a tool grant and tool grants are not plan authorization. `required_capabilities` on a step is a requirement, never a grant. |
| 4 | Confirmation | A real `bool` `confirmed=True` supplied by the caller for that executor. `user_confirmation` in `granted_permissions` is not confirmation. Never remembered between calls. |
| 5 | ToolRequest | Built only by `create_tool_request()` from (step name, step input) + (caller grants, caller confirmation). Malformed data fails at creation with `INVALID_TOOL_REQUEST_*`. |
| 6 | `execute_request()` | The only registry entry the bridge uses: one `_evaluate` before at most one handler call; forged/non-request objects -> `INVALID_TOOL_REQUEST`, handler never called. Check order unchanged. |
| 7 | Result -> step | Success: `{"tool_result": ToolExecutionResult.to_dict()}` becomes the step output (plain JSON, isolated from the audit history). Non-success MUST be raised, never returned (see hazard H1). |
| 8 | Audit | One `ToolInvocationRecord` per call that reaches `execute_request()`; `sequence` is echoed in the step result/reason. Records carry grants, confirmation and input; never the handler. |
| 9 | Failure mapping | See table below. Every failure leaves the step `failed` (never stuck `in_progress`); no retry/restart. |
| 10 | Nothing implicit | No auto-authorization, grants, selection, retry, persistence, scheduling, background work, network or external API (verified by patching sockets/threads/processes/sqlite/open during a full flow, and by import scans). |
| 11 | Preserved contracts | Section 4 and Section 5 public signatures, dict shapes, status/code vocabularies unchanged; full Section 4 and Section 5 regressions pass. |
| 12 | Duplicated authority | Findings F1-F7 below. |

### Failure mapping (step ends `failed`, reason `EXECUTOR_EXCEPTION`, message `code|status|seq`)

| Cause | Code | Execution status | Handler calls | Audited |
|---|---|---|---|---|
| Permission not granted | `TOOL_PERMISSION_DENIED` | `authorization_rejected` | 0 | yes |
| Confirmation missing | `TOOL_CONFIRMATION_REQUIRED` | `authorization_rejected` | 0 | yes |
| Capability not granted | `TOOL_CAPABILITY_MISSING` | `authorization_rejected` | 0 | yes |
| Handler raised | `TOOL_HANDLER_EXCEPTION` | `handler_failed` | 1 | yes |
| Output not JSON-safe | `TOOL_OUTPUT_INVALID` | `handler_failed` | 1 | yes |
| Output type mismatch | `TOOL_OUTPUT_VALIDATION_FAILED` | `output_invalid` | 1 | yes |
| Disabled tool | `TOOL_DISABLED` | `tool_rejected` | 0 | yes |
| Unknown tool | `UNKNOWN_TOOL` | `tool_rejected` | 0 | yes |
| Bad input / grants / confirmation / name | `INVALID_TOOL_REQUEST_{INPUT,PERMISSIONS,CAPABILITIES,CONFIRMATION,NAME}` | `request_rejected` (bridge label) | 0 | no |

`INVALID_TOOL_INPUT` and `INVALID_TOOL_AUTHORIZATION` are unreachable through a `ToolRequest` (creation rejects first); they remain as registry defense in depth. The code is first in the message so it survives Section 4's 500-character reason truncation.

## Invariants

1. Grants and confirmation come from trusted caller code only, never from plan data, the planner, or `CapabilitySystem` state.
2. One tool call per executor call, through `execute_request()`; `_evaluate()` stays the only authorization check.
3. A tool failure is a raised exception; a returned value is a success.
4. A step that failed is final (`STEP_NOT_READY` on re-run); nothing retries.
5. Audit lives only in the registry instance; the plan holds only what the executor returned.

## Findings (duplicated / contradictory authority)

- **F1** Two step-execution stacks: the legacy `ExecutionEngine`/`PlanExecutionController` (used by `AgentLoop`; has `retry_step`; never reads `execution_authorized`) and the Prompt 689-694 layer (authorization flag, no retry, not consumed outside `planning/`). Tool calls must go through the second; wiring `AgentLoop` to it is undecided.
- **F2** Capability vocabularies: Section 4 `required_capabilities` is free-form (checked against `CapabilitySystem` availability); Section 5 grants are strict `^[a-z][a-z0-9_]{0,63}$` names. A step can require a name (e.g. `cap.x`) that can never be granted. All seeded planned capabilities are compatible.
- **F3** JSON-safety: Section 4 structured data accepts NaN/inf, Section 5 does not. plan->tool fails closed at `create_tool_request`; tool->plan is always accepted.
- **F4** Names and permissions have one authority (`_NAME_RE`, `SUPPORTED_PERMISSIONS`, `normalize_tool_output` are shared objects). No duplicate.
- **F5** Plan authorization and tool confirmation/grants each have exactly one owner and do not derive from each other.
- **F6** Section 4's failure channel is binary (return/raise); no structured "tool failed" outcome. The bridge encodes `code|status|seq` in the message.
- **F7** Section 5 request/registry share one execution path; no second authority.

Hazards pinned by tests: **H1** returning a rejected `ToolExecutionResult` completes the step; **H2** one confirmed executor confirms every step it runs; **H3** request-creation failures and plan-level rejections leave no audit record; **H4** rejection happens after `start_plan_step`, so the step ends `failed` (use `registry.preflight(**request.to_registry_arguments())` before `execute_plan_step` to avoid starting a step that would be rejected).

## Defect found and fixed

`planning.plan.ensure_structured_data` documented `TypeError` for a container that contains itself but recursed to `RecursionError`. Through this boundary an executor returning such a value escaped `execute_plan_step` (documented never-raises) and left the step `in_progress`. Fix (only production change): track the containers currently being walked and raise `TypeError` on re-entry; shared non-cyclic references and all valid data behave as before. Regression tests: `TestDefectCyclicStructuredData` (fail on the old code, pass now).

## Remaining gaps (not addressed here)

Structured tool-failure channel (F6/H1); per-request confirmation binding (H2); auditing of pre-registry rejections (H3); F1 stack choice; F2 vocabulary alignment; very deep non-cyclic nesting still relies on Python's recursion limit in Section 4.
