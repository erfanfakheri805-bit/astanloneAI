# Prompt 697 - Section 5 foundation: in-process Tool Registry and metadata contract

New module `tools/in_process_tool_registry.py` (additive). The existing definition-only `ToolDefinition` / `ToolRegistry`,
Section 4 and `process_input()` are unchanged; nothing imports the new module (a test enforces this). `tools/__init__.py`
only gained a docstring paragraph.

- `ToolSpec(name, description, handler, input_schema, output_description, enabled=True)`: plain record; construction never
  raises. `validate_tool_spec()` returns ordered failures: INVALID_TOOL_SPEC, INVALID_TOOL_NAME (exact, case-sensitive
  `^[a-z][a-z0-9_]{0,63}$`), INVALID_TOOL_DESCRIPTION, INVALID_TOOL_HANDLER (must be callable), INVALID_TOOL_INPUT_SCHEMA
  (JSON-safe dict; descriptive only, never enforced), INVALID_TOOL_OUTPUT_DESCRIPTION, INVALID_TOOL_ENABLED (real bool).
- `InProcessToolRegistry` (instance state only, no global registry): `register` (invalid or duplicate -> rejected,
  `DUPLICATE_TOOL_NAME`, first entry kept; the registry stores its own copy and owns the `enabled` flag), exact `has` /
  `describe` (never exposes the handler) / `is_invokable`, sorted `list_names` / `list_descriptions`, explicit `enable` /
  `disable`, and explicit `invoke(name, tool_input)`.
- `invoke` rejects unknown names (UNKNOWN_TOOL), disabled tools (TOOL_DISABLED) and non-JSON-safe dict input
  (INVALID_TOOL_INPUT) WITHOUT calling the handler. Otherwise it calls the handler once, in-process, with a deep copy of the
  input; an `Exception` becomes status `failed` (TOOL_HANDLER_EXCEPTION), invalid output becomes TOOL_OUTPUT_INVALID. No
  retries, no selection, no scheduling, no threads/subprocesses/network/files. `BaseException` is not caught.

Limitations: no unregister, no schema enforcement, no permission/confirmation model, no wiring into the Agent Loop or plans
(later Section 5 prompts). Tests: `tests/test_tools_registry_foundation_prompt697.py`.
