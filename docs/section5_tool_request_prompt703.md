# Prompt 703 - Section 5: explicit tool request contract

Additive: new `tools/tool_request.py` (plus a note in `tools/__init__.py`). `in_process_tool_registry.py`, `ToolSpec`, the permission gate,
capability preflight, audit and execution behavior are unchanged.

**What it is.** `ToolRequest` is an immutable, data-only record of one caller's explicit request: `name`, `input`, `granted_permissions`,
`granted_capabilities`, `confirmed`. It is created only by `create_tool_request(name, tool_input, granted_permissions=None,
granted_capabilities=None, confirmed=False)`, which returns a `ToolRequestResult(ok, request, failures)`, never raises for bad data and never
runs anything. Direct `ToolRequest(...)` construction and subclassing raise `TypeError`.

**Stable failure codes** (all problems reported, in field order): `INVALID_TOOL_REQUEST_NAME`, `INVALID_TOOL_REQUEST_INPUT`,
`INVALID_TOOL_REQUEST_PERMISSIONS`, `INVALID_TOOL_REQUEST_CAPABILITIES`, `INVALID_TOOL_REQUEST_CONFIRMATION`. Rules are the registry's own:
name `^[a-z][a-z0-9_]{0,63}$` (matched with `fullmatch`), permissions from `SUPPORTED_PERMISSIONS`, capabilities matching the name format,
JSON-safe dict input, real-bool confirmation; grants must be a list/tuple/set/frozenset.

**Caller intent preserved.** Nothing is inferred, defaulted from a tool, trimmed, case-folded, de-duplicated or granted. Omitted grants = none,
omitted confirmation = `False`; naming `user_confirmation` as a permission is not a confirmation. List/tuple grants keep order and repeats;
set/frozenset grants (no order) are stored sorted. The registry remains the only place that sorts/de-duplicates and authorizes.

**Immutable and isolated.** No `__dict__`, assignment/deletion raise, grants are tuples, input is rebuilt with the registry's
`normalize_tool_output()` (plain JSON, no caller code runs) so later caller edits change nothing. `input`, `to_dict()` and
`to_registry_arguments()` return fresh copies each call. copy/deepcopy return the same object; pickling is refused; `==` compares data;
unhashable. No handler or callable is ever held.

**Conversion.** `request.to_registry_arguments()` -> `{"name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"}`,
usable as `registry.preflight(**args)` / `execute(**args)` / `invoke(**args)`. It does not call the registry; those methods still run the
single `_evaluate()` check (unknown/disabled, authorization args, permissions, confirmation, capabilities, input) before any handler.
A request never authorizes anything by itself.

Limitations: not wired into `process_input()`, Planner or Agent Loop; no request storage/history/ids; no tool lookup at creation time (an
unknown tool name is a valid request and is rejected by the registry at preflight/execute); input must be a JSON-safe dict nested <= 100
levels; the helper is stricter than the registry on trailing newlines in names (the registry's `$`-anchored regex accepts `"tool\n"`;
left untouched here). Tests: `tests/test_tools_request_contract_prompt703.py`.
