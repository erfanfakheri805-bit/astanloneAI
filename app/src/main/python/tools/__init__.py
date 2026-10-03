"""
Tools (foundation)
=====================
Home for a small, generic registry of future Agent tools. So far this
holds:
  - `ToolDefinition` (tool_definition.py) - a plain data record
    describing the shape of one tool (name, description, version,
    input/output schema pair, an enabled flag, and a free-form
    metadata dict), with deterministic `is_valid()`/`to_dict()`
    methods. Construction never raises (same convention as
    `learning.learning_record.LearningRecord`) - `is_valid()` reports
    whether a given instance is fit to register.
  - `ToolRegistry` (tool_registry.py) - a small, in-memory registry
    that tracks `ToolDefinition` objects by name: register/unregister,
    get/has/list_all, enable/disable, and a read-only `is_available`
    check (registered and currently enabled).

This is deliberately just a registry foundation for tool *definitions*
- no handler, no execution, no automatic discovery/installation, no
network access, no access to any external application, and no
integration with plans, goals, capabilities, or the learning system
happens anywhere in this package yet. It exists so that later stages
have somewhere concrete to register tools such as web browsing, web
search, file operations, image generation/editing, video processing,
code generation/execution, 3D asset creation, project creation,
application interaction, social media automation, or app/game
publishing - none of which are implemented here.

Prompt 697 (Section 5 foundation) adds `in_process_tool_registry.py`: `ToolSpec` (name, description, caller-provided
handler, input schema metadata, output description, enabled) and `InProcessToolRegistry` (explicit register/lookup/
enable/disable/invoke; duplicates, unknown and disabled tools are rejected; in-process only). The two definition-only
modules above are unchanged, and nothing here is wired into `process_input()`, the Agent Loop or Section 4.

Prompt 699 adds an explicit, per-call permission/confirmation gate to `InProcessToolRegistry.invoke()`, reusing the existing
`SUPPORTED_PERMISSIONS` vocabulary: deny by default, caller-supplied grants only, rejections never call the handler and are audited.

Prompt 700 adds `InProcessToolRegistry.execute()` and `ToolExecutionResult`: a stable execution-result contract (succeeded /
handler_failed / authorization_rejected / input_rejected / tool_rejected) derived from the invocation audit record; the gate is unchanged.

Prompt 701 adds optional `ToolSpec.capabilities` (per-call `granted_capabilities`, `TOOL_CAPABILITY_MISSING`) and a read-only
`InProcessToolRegistry.preflight()`; `invoke()`/`execute()` run the same single `_evaluate()` check before any handler.

Prompt 702 normalizes every handler output to a fresh plain-JSON copy (`normalize_tool_output`, no coercion, no handler code run) and adds an
optional `ToolSpec.output_type` check (`TOOL_OUTPUT_VALIDATION_FAILED`, execution status `output_invalid`); `output_description` stays descriptive-only.

Prompt 703 adds `tool_request.py`: an immutable, data-only `ToolRequest` (name, input, granted permissions/capabilities, confirmation) built by
`create_tool_request()` with stable `INVALID_TOOL_REQUEST_*` codes, and `to_registry_arguments()`, which hands the caller's own values to the
unchanged `preflight()`/`execute()`/`invoke()`. It holds no handler, grants nothing, runs nothing and is not wired into `process_input()`.

Prompt 704 adds `InProcessToolRegistry.execute_request(request)` (= `execute(**request.to_registry_arguments())`; non-requests are rejected as
`INVALID_TOOL_REQUEST`) and hardens the registry boundary found by its contract audit: true end-of-string-anchored names, one JSON-safety authority
(no unbounded recursion, no caller hooks), and a plain private input copy for the handler. See docs/section5_tool_request_integration_prompt704.md.
"""
