# Prompt 701 - Section 5: tool capability requirements & preflight validation

Additive change to `tools/in_process_tool_registry.py` (plus a note in `tools/__init__.py`). `ToolDefinition`/`ToolRegistry`, the permission
vocabulary, the Prompt 699 gate and the Prompt 700 result contract are unchanged in meaning.

**Capability declaration.** `ToolSpec.capabilities` (optional, default empty). Reuses the existing `ToolDefinition.capabilities` convention
(list of free-form capability-name strings, no fixed vocabulary, never interpreted) and the registry's name format `^[a-z][a-z0-9_]{0,63}$`.
Rejected at registration: non-list/tuple or malformed names (`INVALID_TOOL_CAPABILITIES`), duplicates (`DUPLICATE_TOOL_CAPABILITY`).
Stored as a sorted private copy (`get_required_capabilities(name)`); `describe()` is unchanged.

**Per-call grant.** `granted_capabilities=` (list/tuple/set/frozenset of valid names, default none) on `preflight()`, `invoke()`, `execute()`.
Never inferred (not from names, descriptions, permissions, request or earlier calls), never stored or cached.

**One authoritative check** (`_evaluate`, read-only, stops at first failure): exists `UNKNOWN_TOOL` -> enabled `TOOL_DISABLED` -> authorization
arguments well-formed `INVALID_TOOL_AUTHORIZATION` -> permissions `TOOL_PERMISSION_DENIED` -> confirmation `TOOL_CONFIRMATION_REQUIRED` ->
capabilities `TOOL_CAPABILITY_MISSING` (decision `capability_missing`, `missing_capabilities` listed) -> input `INVALID_TOOL_INPUT`.
`invoke()` (hence `execute()`) runs it before the handler, so neither can bypass it. Capability rejection maps to execution status
`authorization_rejected`.

**`preflight(name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None)`** returns `ToolPreflightResult`:
`tool_name`, `tool_exists`, `tool_enabled`, `authorization_decision`, `authorization_accepted`, `required/granted_permissions`, `confirmed`,
`required/granted/missing_capabilities`, `input_valid` (True/False; None when input was not reached), `preflight_status` (`passed`/`rejected`),
`outcome_code` (`TOOL_PREFLIGHT_PASSED` or first failure), `failure_codes`, `failures`, `ok`. It never calls the handler, appends no audit
record, changes no state and never exposes the handler. A passing preflight authorizes nothing for a later call.

**Audit.** Records gain `required_capabilities` and `granted_capabilities`. `ToolExecutionResult` fields are unchanged.

Contract-driven test edits: Prompt 698 record keys/expected record (two new fields) and the Prompt 700 outcome-code set (new code).

Limitations: the first failure only is reported (no multi-failure listing); capability names are free-form and not checked against the
application `CapabilitySystem` (kept separate: it is database-backed); granted names not declared by any tool are accepted silently; not wired
into `process_input()`, Planner or Agent Loop. Tests: `tests/test_tools_capability_preflight_prompt701.py`.
