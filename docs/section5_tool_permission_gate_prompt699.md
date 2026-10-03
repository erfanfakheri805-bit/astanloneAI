# Prompt 699 - Section 5: explicit tool permission & confirmation gate

Additive change to `tools/in_process_tool_registry.py` (plus a note in `tools/__init__.py`). `ToolDefinition`/`ToolRegistry` are
untouched. The gate reuses the existing closed vocabulary `tools.tool_definition.SUPPORTED_PERMISSIONS`
(`network`, `filesystem`, `external_application`, `user_account`, `user_confirmation`); no new permission system.

Contract
- `ToolSpec.permissions` (optional, default empty): what the tool needs; validated (`INVALID_TOOL_PERMISSIONS`); the registry stores a
  sorted, deduplicated private copy (`get_required_permissions(name)`). `describe()` is unchanged.
- `invoke(name, tool_input, granted_permissions=None, confirmed=False)`: explicit per-call authorization.
  - unmet permission -> `TOOL_PERMISSION_DENIED` (decision `denied`, `missing_permissions` listed) - default for any tool that lists permissions;
  - tool lists `user_confirmation` and `confirmed is not True` -> `TOOL_CONFIRMATION_REQUIRED` (decision `confirmation_required`); naming
    `user_confirmation` in `granted_permissions` does NOT count; permission denial is reported first;
  - malformed arguments -> `INVALID_TOOL_AUTHORIZATION` (decision `invalid`);
  - else decision `accepted` (`not_required` for a tool listing no permissions, i.e. unchanged prior behavior).
- Gate order: unknown -> disabled -> authorization -> input validation -> handler. A rejection never calls the handler.
- Audit: each `ToolInvocationRecord` gains `authorization_decision` (`not_evaluated` for unknown/disabled), `authorization_code`,
  `required_permissions`, `granted_permissions` (sorted, deduplicated, as supplied), `confirmed`; rejected calls keep `handler_called=False`.
- Nothing is inferred, auto-granted, persisted or shared: no authorization state exists on the registry; each call stands alone.

Test updates required by the contract: Prompt 698 `RECORD_KEYS`/success-record expectation (new record fields) and the 697/698 import
guards (now also allow the existing `tools.tool_definition` vocabulary import). Tests: `tests/test_tools_permission_gate_prompt699.py`.

Limitations: a tool that declares no permissions needs no authorization (backward compatible); the caller-supplied grant is trusted as
given (no identity/policy check); no per-permission confirmation prompts, expiry, or UI; not wired into `process_input()`, Planner or
Agent Loop; history remains unbounded and in-memory.
