# Prompt 698 - Section 5: tool invocation record and audit trail

Additive change to `tools/in_process_tool_registry.py` only. `invoke()` keeps its behavior and return value (the body is now
`_invoke`); the public `invoke()` appends exactly one `ToolInvocationRecord` per returned call to an instance-local, in-memory
history. `ToolSpec` validation, input-schema semantics, registration and lookup are unchanged; nothing is wired into
`process_input()`, the Planner, the Agent Loop or Section 4.

Record (built only from the `ToolInvocationResult` already produced, nothing re-decided): `sequence` (1-based, invocation
order), `tool_name` (the name if a string, else None), `status`, `ok`, `outcome_code` (`TOOL_COMPLETED` or the first failure
code), `handler_called`, `input_json_safe` / `input_type` / `input` (deep copy when JSON-safe, else None - never a repr, so
records are deterministic), `output_available` / `output` (deep copy, completed calls only), `failures`. The handler is never
stored or exposed.

Inspection: `get_invocation_history()` returns a new list of fresh deep-copied dicts (read-only, never mutates history);
`invocation_count()`. Rejected calls (unknown, disabled, invalid input) show `handler_called=False`; completed calls and
handler failures show `True`. No retries.

Limitations: history is unbounded and in memory only (no persistence, no clear/export, no timestamps); a handler
`BaseException` propagates and leaves no record; registration and enable/disable are not audited. Tests:
`tests/test_tools_invocation_audit_prompt698.py`.
