# Prompt 711 - Controlled retry policy for tool steps (Section 6)

Status: one new module `planning/tool_step_retry.py`, **not wired anywhere** (no `process_input()`, Agent Loop, Planner). No Section 4/5 or earlier
Section 6 API changed. Tests: `tests/test_section6_tool_step_retry_prompt711.py` (35).

## API

```python
execute_plan_tool_step_with_retry(plan, step_id, request, registry, max_attempts,
                                  required_capabilities=None, capability_mapping=None, attempt_log=None) -> ToolStepRetryResult
is_retryable_prestart_result(preflighted_result) -> bool      # the pure allow-list classifier
```

- `max_attempts`: caller-supplied `int > 0` (not `bool`); no default, never stored or inferred.
- Mapping arguments: both `None` -> each attempt is `execute_plan_tool_step_preflighted()` (709); both given -> each attempt is
  `execute_plan_tool_step_mapped()` (710). Exactly one given -> rejected, zero attempts.
- `attempt_log`: optional caller-owned `list`; one fresh dict per attempt is appended to it. The module keeps no state.
- Each attempt = exactly one call of that existing path. The module never touches handlers, the registry execution entry point, the bridge, step transitions or the registry.

## Result and attempt records

`ToolStepRetryResult.to_dict()`: `ok, status, stop_reason, step_id, max_attempts, attempts_made, attempts, final, reason, failures`.
`status`: `completed` | `failed` (step started, then failed) | `rejected` (never started). `stop_reason`: `completed`, `execution_failed`,
`non_retryable_rejection`, `attempt_limit_reached`, `invalid_arguments`.

Attempt record (`record_type == "tool_step_attempt"`): `attempt` (1-based), `outcome_kind`, `status`, `execution_started`, `retryable`, `step_id`,
`tool_name`, `previous_state`, `final_state`, `reason`, `codes`, `failures`, `invocation_recorded`, `sequence`. A pre-start rejection is **not** an
invocation: `sequence` is `None`, `invocation_recorded` is `False`, and the registry history is not written. Only a started execution carries the
registry's own `sequence`, copied unchanged.

## Exactly what can be retried (pre-start only, allow-list)

| condition | code / kind |
|---|---|
| Section 4 step state that can change outside this call, **only while the step is `pending`** | `STEP_NOT_READY`, `EXECUTION_NOT_AUTHORIZED` |
| well-formed mapping that does not satisfy the requirements | `CAPABILITY_MAPPING_REJECTED` with mapping status `unmapped` |
| mapped Section 5 grant the request did not supply | `MAPPED_GRANT_NOT_SUPPLIED` |
| Section 5 registry preflight rejection | `registry_preflight_rejection` (unknown/disabled tool, permission, confirmation, capability, input) |

## Exactly what is never retried

- Any step that **started**: a completed step is terminal and never runs again; a real tool/execution failure (incl. a TOCTOU failure after a passed
  preflight) is terminal and the step stays `failed`.
- A step that is already `completed`/`failed`/`in_progress` when the call begins (non-retryable rejection after one attempt).
- Malformed arguments and objects (`INVALID_BRIDGE_*`, `UNKNOWN_BRIDGE_STEP`, `INVALID_PRESTART_REQUEST`, `INVALID_REJECTION_LOG`), invalid plans
  (`INVALID_PLAN`, `INVALID_PLAN_OBJECT`, `PLAN_READINESS_UNDETERMINED`), unknown steps, a malformed mapping or required list (mapping status
  `invalid_mapping`/`invalid_input`), a defective registry `preflight()` (`PRESTART_PREFLIGHT_EXCEPTION`), and any code not on the retryable list.
- Invalid retry arguments (`max_attempts`, `attempt_log`, mapping pair): rejected with **zero** attempts.
- Programming errors / `BaseException`: propagate, no retry.

## Invariants

Nothing is changed between attempts (request, grants, permissions, confirmation, mapping and required list are passed unchanged); an unchanged
retryable condition is re-asked only because the caller allowed several attempts; if plan/registry state changed outside the call, the next attempt
sees it. No delay, backoff, thread, timer, clock, randomness or persistence. Section 4 and Section 5 remain the only authorities.

## Production changes

New `planning/tool_step_retry.py` (imports only `planning.tool_step_executor`). Two "not wired" guard tests (709, 710) now sanction this module as a
caller. No production defect found.

## Still open

Agent Loop / `process_input()` hand-over; the `ready`-status incompatibility between the two execution stacks; F3 (NaN/inf asymmetry);
any policy for retrying a *failed* step (deliberately excluded: it would need an explicit Section 4 reset transition).
