# Prompt 700 - Section 5: controlled tool execution contract

Additive change to `tools/in_process_tool_registry.py` (plus a note in `tools/__init__.py`). `invoke()`, `ToolSpec`, `ToolDefinition`,
the permission vocabulary and the Prompt 699 gate are unchanged.

`InProcessToolRegistry.execute(name, tool_input, granted_permissions=None, confirmed=False)` runs `invoke()` exactly once and returns a
`ToolExecutionResult` built from the audit record that call appended (so result and record agree by construction).

`execution_status` (from the record's stable `outcome_code`):
- `succeeded` - TOOL_COMPLETED
- `handler_failed` - TOOL_HANDLER_EXCEPTION, TOOL_OUTPUT_INVALID (handler was called)
- `authorization_rejected` - TOOL_PERMISSION_DENIED, TOOL_CONFIRMATION_REQUIRED, INVALID_TOOL_AUTHORIZATION
- `input_rejected` - INVALID_TOOL_INPUT (authorization was already accepted)
- `tool_rejected` - UNKNOWN_TOOL, TOOL_DISABLED (before the gate; added so every outcome has a status)

Fields: `tool_name`, `execution_status`, `outcome_code`, `authorization_accepted` (decision accepted/not_required), `authorization_decision`,
`handler_called`, `output_available`, `output` (deep copy, only when succeeded), `failures`, `sequence` (audit record number), `ok`;
`to_dict()` returns fresh deep copies with a fixed key set. The handler is never stored on or exposed by the result or the record.
The handler runs at most once, only after unknown/disabled/authorization/input checks pass. No retries, threads, subprocesses, network.

Limitations: not wired into `process_input()`, Planner or Agent Loop; a handler `BaseException` still propagates and leaves no record or
result; history unbounded and in-memory; the caller's grant is trusted as given. Tests: `tests/test_tools_controlled_execution_prompt700.py`.
