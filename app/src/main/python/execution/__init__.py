"""
Execution (foundation)
=========================
Home for the future Execution Engine. So far this holds:
  - `ExecutionResult` (execution_result.py) - the structured record one
    execution attempt produces.
  - `ExecutionEngine` (execution_engine.py) - a minimal engine that can
    run a single READY PlanStep through a caller-supplied handler,
    record the outcome as an ExecutionResult, and sync that same
    outcome onto the PlanStep itself (COMPLETED/FAILED) via
    PlanManager's own status rules, refreshing dependents on success.
    Also provides a controlled `retry_step` for a previously FAILED
    step, and preflight-validates both `execute_step` and `retry_step`
    before ever creating a RUNNING execution or calling a handler.
    `execute_registered_capability` runs one named `Capability`
    (capability.py) from `self.executable_capabilities` directly
    against caller-supplied input, with no PlanStep involved at all -
    reusing `Capability.validate_input`/`Capability.execute` and
    `ExecutableCapabilityRegistry.is_available` unchanged rather than
    duplicating either.
  - `ExecutionHistory` (execution_history.py) - a small, in-memory,
    order-preserving store of every ExecutionResult an ExecutionEngine
    has produced, retrievable by execution_id, plan_id, or step_id.
  - `PreflightValidator`/`PreflightResult` (preflight.py) - a
    read-only checkpoint that checks whether a PlanStep is currently
    safe to run (plan/step exist, step is READY, dependencies
    resolved, required capabilities available) by reusing PlanManager's
    own dependency/capability logic, never a second copy of it.
  - `Capability`/`CapabilityValidationResult`/`CapabilityExecutionResult`
    (capability.py) - a small, standard interface for one executable
    capability (name, description, version, input/output schema, an
    explicit handler, metadata) with deterministic `validate_input`/
    `execute`/`describe`/`to_dict` methods. Independent of
    `capabilities.capability_system.CapabilitySystem` (the
    registered/enabled yes-no tracker) and of
    `CapabilityHandlerRegistry` below (the name-to-callable map); a
    `Capability` can optionally be stored in that registry, but
    neither module requires the other.
  - `CapabilityOutput` (capability_output.py) - a small, standardized,
    validated `{success, capability_name, execution_id, output,
    output_type, error, warnings, metadata, created_at}` record a
    capability handler can optionally return, with deterministic
    `validate()`/`to_dict()`/`is_successful()`/`get_output()` methods
    and safe, never-raising normalization of `output`/`metadata` into
    JSON-shaped structured data (`None`/`bool`/`int`/`float`/`str`/
    `list`/`dict`, nested arbitrarily) - never eval()/exec()/
    subprocess/shell/network/an external AI API. Entirely additive: a
    handler that keeps returning its own existing output format is
    completely unaffected. `ExecutionResult.attach_capability_output`
    (execution_result.py) can optionally record one per capability
    name without changing that class's existing shape, and
    `execute_capability_step` (execution_engine.py) does so
    automatically whenever a handler happens to return one.
    `unwrap_for_previous_output` lets `execute_capability_step`'s own
    `previous_outputs` data flow (execution_context.py) use a
    CapabilityOutput's normalized output exactly like any other safe,
    structured handler return value.
  - `ExecutableCapabilityRegistry` (executable_registry.py) - a
    dedicated, in-memory registry for `Capability` objects
    specifically, with its own per-entry enabled/disabled state and a
    read-only `is_available` check (exists, enabled, currently has a
    callable handler). Separate from `CapabilityHandlerRegistry` (which
    still maps names to plain callables, or to `Capability` objects via
    its own optional wrappers); `CapabilityHandlerRegistry.check_execution_readiness`
    can optionally consult an `ExecutableCapabilityRegistry` as an
    additional source of handlers when one is explicitly supplied,
    otherwise behaves exactly as it did before this registry existed.
  - `text_file_read_capability.py` - the project's first real,
    executable built-in `Capability`: safely reads a text file (using
    only standard-library file operations) from one of the
    application's own already-defined safe directories
    (`PlatformConfig`'s `data_dir`/`skills_dir`/`temp_dir` by default,
    or an explicit `allowed_dirs` override) and returns its text plus
    basic metadata. `create_text_file_read_capability` builds it;
    `register_text_file_read_capability` registers it into a
    caller-supplied `ExecutableCapabilityRegistry` or
    `CapabilityHandlerRegistry` - nothing registers it anywhere
    automatically.
  - `text_file_write_capability.py` - the write-side sibling of
    `text_file_read_capability.py`: safely writes text content to a
    file (standard-library file operations only) inside one of the
    application's own already-defined safe directories, refusing to
    overwrite an existing file unless the caller explicitly passes
    `overwrite: True` and only ever creating parent directories that
    already fall inside an allowed directory. Same
    `create_text_file_write_capability`/
    `register_text_file_write_capability` shape as the read
    capability; independent module, nothing shared between the two
    beyond the pattern.
  - `text_file_edit_capability.py` - a controlled, exact-fragment
    text edit built-in `Capability`: replaces exactly one occurrence
    of an exact existing text fragment in an already-existing file,
    failing safely (no write at all) if the fragment is missing or
    ambiguous (appears more than once). Reuses
    `text_file_read_capability.py`'s own allowed-directory validation
    (`_resolve_allowed_dirs`/`_is_within_allowed_dirs`) by importing
    it directly rather than re-implementing it a third time; that
    module (and `text_file_write_capability.py`) are unmodified by
    this addition. Same `create_text_file_edit_capability`/
    `register_text_file_edit_capability` shape as its two siblings.
  - `project_structure_inspect_capability.py` - a read-only built-in
    `Capability` that lists the files and directories inside an
    allowed project/data directory (relative paths + file-or-directory
    type), bounded to a fixed maximum entry count
    (`DEFAULT_MAX_ENTRIES`) so a single call can never walk an
    unbounded amount of the filesystem into memory. Reuses
    `text_file_read_capability.py`'s own `_resolve_allowed_dirs` for
    resolving the allowed-directory list (that module is unmodified);
    containment itself is checked with a local variant that - unlike
    the file capabilities above - also accepts the allowed directory
    itself as a valid inspection target. Never creates, modifies, or
    deletes anything. Same `create_project_structure_inspect_capability`/
    `register_project_structure_inspect_capability` shape as its
    siblings.
  - `python_test_runner_capability.py` - a built-in `Capability` that
    runs a project's Python tests with the standard library's own
    `unittest` runner (invoked as a fixed
    `[sys.executable, "-m", "unittest", ...]` argument list via
    `subprocess.run(shell=False, ...)` - never an arbitrary shell
    command) inside an allowed project directory only, with a
    configurable execution timeout
    (`DEFAULT_TIMEOUT_SECONDS`/`timeout_seconds=`) and a structured
    `{success, timed_out, return_code, stdout, stderr, tests_run,
    failures, errors, skipped, duration_seconds}` result. Reuses
    `text_file_read_capability._resolve_allowed_dirs` and
    `project_structure_inspect_capability._is_within_or_equal_allowed_dirs`
    unchanged for path resolution/containment (both modules are
    untouched by this addition) rather than a third copy of either.
    Never modifies project files (`PYTHONDONTWRITEBYTECODE=1` is
    always forced in the child process's deliberately minimal
    environment) and performs no network operation itself. Same
    `create_python_test_runner_capability`/
    `register_python_test_runner_capability` shape as its siblings.
  - `code_analysis_capability.py` - connects the project's existing,
    already-implemented `code_intelligence.python_inspector.inspect_source`
    (AST-based, parse-only, read-only) to this same Capability
    Registry / Agent execution path, rather than building a second
    code-analysis system. Reuses
    `text_file_read_capability.make_text_file_read_handler` directly
    (unchanged) to safely read a `.py` file inside an allowed
    directory - path resolution, containment, size limit, binary
    sniff, and UTF-8 decoding all come from that one existing handler
    - then hands the resulting text to `inspect_source` unchanged and
    returns its structured `{valid, syntax_error, functions, classes,
    imports}` result alongside the resolved path. Never writes to the
    file it analyzes. Same `create_code_analysis_capability`/
    `register_code_analysis_capability` shape as its siblings.
  - `code_change_plan_capability.py` - a read-only planning capability
    for one controlled, exact-fragment text change to an existing
    Python (`.py`) file: reuses `code_analysis_capability.
    make_code_analysis_handler` unchanged for the safe-path/`.py`-only
    validation and the AST-based analysis, and
    `text_file_read_capability.make_text_file_read_handler` unchanged
    to read the file's current text for an exact-occurrence check of
    the proposed fragment (the same rule `text_file_edit_capability.py`
    itself already enforces, applied here read-only rather than by
    calling that capability's own write path). Never writes to, or
    otherwise modifies, the file it plans a change for - it only
    returns a structured `{path, target_fragment, replacement,
    validation_status, analysis_summary, ready_to_apply,
    apply_capability}` change plan, naming the existing
    `text_file_edit` capability (by its own `CAPABILITY_NAME`, reused
    rather than duplicated) as the one that would actually apply it.
    Same `create_code_change_plan_capability`/
    `register_code_change_plan_capability` shape as its siblings.
  - `code_change_apply_capability.py` - connects the existing
    `code_change_plan` capability to the existing `text_file_edit`
    capability, rather than building a second file-edit system: it
    reuses `code_change_plan_capability.make_code_change_plan_handler`
    unchanged to (re-)produce the exact same structured plan, and,
    only when that plan reports `ready_to_apply`, reuses
    `text_file_edit_capability.make_text_file_edit_handler` unchanged
    to actually apply it - exactly one validated change per call,
    never a loop and never an automatic retry. When the plan is not
    ready, the file is left untouched and the handler returns a
    `{..., success: False, change_applied: False, ...}` result instead
    of raising. Returns a structured `{path, requested_path, success,
    change_applied, change_metadata}` result; never imports, runs, or
    otherwise executes the file it changes. Same
    `create_code_change_apply_capability`/
    `register_code_change_apply_capability` shape as its siblings.

No automatic handler discovery, no tool calling, no
filesystem/shell/network/Android-API access, no eval()/exec()/
subprocess, no automatic *next-step* execution, no automatic retry, no
capability creation/enabling, no automatic BLOCKED-to-READY promotion,
and no persistent (only in-memory) execution history live here - see
execution_result.py's, execution_engine.py's, execution_history.py's,
and preflight.py's module docstrings.
"""

