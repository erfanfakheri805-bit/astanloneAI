# Prompt 702 - Section 5: tool result validation & normalization

Additive change to `tools/in_process_tool_registry.py` (plus a note in `tools/__init__.py`). `ToolDefinition`/`ToolRegistry`, the permission
gate, capability preflight and the `ToolExecutionResult` field set are unchanged.

**Normalization** (`normalize_tool_output(value) -> (ok, copy)`, pure). Every handler return value is rebuilt as plain JSON data (exact
`dict`/`list`/`str`/`int`/`float`/`bool`/`None`) using only the base types' unbound methods, so no handler-supplied code (overridden
`__iter__`, `__str__`, `__deepcopy__` ...) runs and the caller never receives the handler's own object. Nothing is coerced: tuples, sets,
bytes, NaN/inf, non-str keys and other types are rejected; subclass instances of JSON types become their plain base type with the same
value; key order is preserved; nesting deeper than `MAX_OUTPUT_DEPTH` (100) is rejected, which also stops cyclic output (previously a
cycle raised `RecursionError` out of `invoke()`; now it is a normal `TOOL_OUTPUT_INVALID`).

**Validation metadata.** The existing `output_description` is free text: it stays descriptive-only and is never parsed or enforced (there is
no output schema to validate against, and none was invented). The one optional, enforceable addition is `ToolSpec.output_type` (default
`None` = no validation, identical behavior): a JSON type name from `OUTPUT_TYPES` (object, array, string, number, integer, boolean, null;
`number` = int or float, `integer` = int only, bool matches neither, no coercion). Invalid declarations are rejected at registration
(`INVALID_TOOL_OUTPUT_TYPE`). `get_output_type(name)` reads it; `describe()` is unchanged.

**Outcomes (distinct):**
- valid output -> `TOOL_COMPLETED`, status `succeeded`, output = fresh normalized copy
- handler returned, output rejected -> new `TOOL_OUTPUT_VALIDATION_FAILED` (declared type mismatch), execution status `output_invalid`,
  invocation status `failed`, failure has `expected_type` / `actual_type` (JSON names), output not exposed
- handler exception -> `TOOL_HANDLER_EXCEPTION`, or non-JSON-safe output -> `TOOL_OUTPUT_INVALID` (unchanged): `handler_failed`
- rejected before the handler -> `tool_rejected` / `authorization_rejected` / `input_rejected` (handler_called False)

Audit records agree with the final outcome (outcome code, handler_called, no output unless completed). Handlers are never retried; preflight
never runs handlers or validates output. Contract-driven test edit: Prompt 700 outcome-code set (one new code).

Limitations: output validation is a single top-level type check (no nested/schema validation); `output_description` is not machine-checked;
depth cap 100; input handling (`copy.deepcopy` of validated input) is unchanged; a handler `BaseException` still propagates unrecorded; not
wired into `process_input()`, Planner or Agent Loop. Tests: `tests/test_tools_output_validation_prompt702.py`.
