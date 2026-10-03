# Prompt 719-B - Section 6 Tool Step Runner

`agent/tool_step_runner.py` · tests: `tests/test_section6_tool_step_runner_prompt719b.py`

## Purpose

A caller-side, stateless adapter that connects a successful Prompt 719-A `ToolStepIntentResult` to the existing Prompt 711 retry
authority, `execute_plan_tool_step_with_retry(...)`. It adds no execution behavior and is not wired into AgentLoop or `process_input`.

```python
run_tool_step_intent(intent_result, plan, registry, attempt_log=None) -> ToolStepRunResult
```

`plan` is the caller's Plan: the retry API needs one and the intent result carries none. `capability_system` is not a parameter,
because no existing Section 6 execution API takes one.

## Input / output

Input: a successful `ToolStepIntentResult` (exact type, `ok` True). The runner reads `plan_id`, `step_id`, `request`, `max_attempts`,
`required_capabilities` and `capability_mapping` from it; the intent dictionary is never rebuilt or revalidated.

Output: an immutable, data-only `ToolStepRunResult` with `ok`, `plan_id`, `step_id`, `outcome_kind`, `stop_reason`, `attempts`,
`final_step_state`, `failures`, `execution_result` (the retry layer's last-attempt plain data). Every read of a mutable value returns a
fresh copy. No handler, registry or capability-system object is held.

Rejected before execution (registry, executor and plan untouched, no attempt record appended; `outcome_kind` =
`runner_rejection`, `stop_reason` = `runner_rejected`):

| Code | Cause |
|---|---|
| `RUNNER_INVALID_INTENT_RESULT` | not an exact `ToolStepIntentResult` |
| `RUNNER_INTENT_NOT_OK` | the intent result has `ok == False` |
| `RUNNER_INVALID_MAPPING_PAIR` | exactly one of the two mapping fields is present |
| `RUNNER_PLAN_ID_MISMATCH` | `plan.plan_id` differs from the intent's `plan_id` |

## Delegation boundary

After those four checks the runner makes exactly one call to `execute_plan_tool_step_with_retry`, passing the plan, step id, the
`ToolRequest` object, the registry, `max_attempts`, the mapping pair and the caller's `attempt_log` unchanged. Preflight, capability
mapping, authorization, retry, step transitions and the bridge stay in the existing Section 4/5/6 modules.

## Mapping behavior (Prompt 711 rules)

- neither field present: the retry layer is called without a mapping
- both present: both are passed unchanged
- only one present: rejected before execution; no mapping is invented

## Attempt-log ownership

`attempt_log` belongs to the caller. It is passed to the retry layer as-is (or `None`). The runner keeps no log, creates no hidden
global log and appends no record of its own; the retry layer writes one record per attempt.

## Explicit non-responsibilities

The runner does not retry, start or complete PlanSteps, authorize, map capabilities, create ToolRequests, resolve routes, select
tools, inspect natural language, revalidate the intent, touch AgentLoop, `process_input` or Core, inspect the registry, or keep
module-level state.
