# Prompt 705 - Section 5 end-to-end acceptance (Tools & Controlled Task Execution, Prompts 697-705)

Verified path (in-process only, caller-driven, no production code changed):
`ToolSpec -> InProcessToolRegistry -> ToolRequest -> execute_request() -> execute() -> invoke() -> _invoke() -> _evaluate() -> handler -> ToolExecutionResult -> ToolInvocationRecord`.
Tests: `tests/test_section5_final_acceptance_prompt705.py` (one class per row below).

## Acceptance checklist

| # | Requirement | Verified by |
|---|---|---|
| 1 | Registration and exact-name validation (`^[a-z][a-z0-9_]{0,63}\Z`, no fuzzy lookup, duplicates rejected, spec edits after register ignored) | T01 |
| 2 | Enabled/disabled behavior (disabled/unknown rejected before authorization, enable grants nothing, flag owned by registry) | T02 |
| 3 | `ToolRequest` creation and immutability (factory only, no subclass, fresh copies, no callables, all failure codes in order) | T03 |
| 4 | `execute_request()` passes exactly `to_registry_arguments()` to one `execute()`; result equals direct `execute()` | T04 |
| 5 | Permissions, confirmation, capabilities, input validation cannot be bypassed (fixed check order, forged/non-request objects, nothing remembered) | T05 |
| 6 | Handler called at most once, only after `_evaluate()` passes; one call site; never retried | T06 |
| 7 | Valid output goes through `normalize_tool_output` and the declared output-type check; result is a fresh plain-JSON copy | T07 |
| 8 | Invalid handler output -> `TOOL_OUTPUT_INVALID` / `handler_failed` (handler called, no output exposed) | T08 |
| 9 | Handler exceptions -> `TOOL_HANDLER_EXCEPTION` / `handler_failed` (message truncated, hostile `__str__` survived) | T09 |
| 10 | Every returned execution has exactly one, correctly numbered audit record (including invalid requests) | T10 |
| 11 | Result and record agree on status, outcome, `handler_called`, output availability, output, failures, sequence; real handler call counts match | T10/T11 |
| 12 | Caller inputs, handler inputs/outputs, requests, results and history are isolated from later mutation | T12 |
| 13 | Rejected requests never call the handler (all entry points: `execute_request`, `execute`, `invoke`, `preflight`) | T13 |
| 14 | No hidden authorization state, tool selection, retry, persistence, background work, I/O or wiring outside `tools/` | T14 |
| 15 | Backwards compatibility of `InProcessToolRegistry`, `ToolSpec`, legacy `ToolDefinition`/`ToolRegistry`, constants and dict shapes | T15 |
| 16 | Regressions stay fixed: trailing-newline names/capabilities, cyclic/deep input/schema/output, input isolation | T16 |

Project integrity (T17): pristine DB SHA-256 `0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb` unchanged by the flow.

## Intentional limitations (unchanged, by design)

- Not wired into `process_input()`, Planner, Agent Loop or Section 4; nothing outside `tools/` and `tests/` imports these modules.
- No network, filesystem, subprocess, persistence, scheduling, retries, background execution, request storage or ids.
- No automatic tool selection or fuzzy matching; authorization is caller-supplied per call and never stored.
- A handler `BaseException` (KeyboardInterrupt, SystemExit) propagates unrecorded (Prompt 698 decision).
- Input/output nesting deeper than `MAX_OUTPUT_DEPTH` (100) is rejected, so a handler that echoes input at the limit can fail output validation.
- Caller-supplied hostile `list`/`set` subclasses for `granted_*` are iterated in `_evaluate` (grants are caller-authoritative; the request path passes plain lists).
- A `str` subclass used directly as a tool name runs its own `__hash__`/`__eq__` in `has()`; requests store an exact `str`.
- `execute_request` has no preflight-only twin: use `preflight(**request.to_registry_arguments())`.
- Legacy definition-only `ToolDefinition`/`ToolRegistry` are unchanged and separate from the executable registry.
