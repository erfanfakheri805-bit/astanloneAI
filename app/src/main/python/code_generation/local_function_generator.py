"""
Code Generation - Local Function Generator
=============================================
Foundation for local, deterministic Python code generation (Prompt
335) that can later be used by the Agent for capability creation and
self-upgrade:

    structured spec (dict) -> generate_function()
        -> CodeGenerationResult(request, target_file, generated_code,
                                 status, error)
           (code_generation/code_generation_result.py)

Explicitly NOT natural-language-to-arbitrary-code generation - this
stage deliberately does not attempt to parse free-form text, infer
intent, or generate anything beyond one, single `def` statement
assembled from a small set of already-structured fields (a function
name, parameter names, an optional docstring, and one return
expression) via plain string templating. There is no heuristic
inference and nothing "AI-driven" here - same "no fake intelligence"
convention already documented by reasoning/reasoning_result.py,
planning/goal_completion.py, and planning/adaptive_plan_analyzer.py.
A later stage may build a richer generator on top of this one; this
module is deliberately narrow.

Reuses, never duplicates, the project's own existing systems:
  - code-analysis / validation: `code_intelligence.python_inspector.
    inspect_source` - the exact same AST-based structural analysis
    `code_analysis_capability.py` already exposes - is used, unchanged,
    to confirm the assembled source text is actually syntactically
    valid Python (and that a function bearing the requested name was
    really produced) before this module ever labels a result
    `STATUS_GENERATED`. This module never re-implements Python syntax
    checking of its own; source that does not parse is reported as
    `STATUS_INVALID_REQUEST`, never silently returned as generated
    anyway.
  - Agent/model conventions: `CodeGenerationResult` follows the exact
    same plain, structured-record shape already used by
    `execution.execution_result.ExecutionResult` and by
    `agent.code_change_evaluation.build_code_change_evaluation`'s own
    return shape - so a future `AgentLoop` integration (not built in
    this stage - see that class's own module docstring for its
    "never a second, disagreeing" conventions) can consume this
    result the same way it already consumes every other structured
    evaluation/decision in this project.

Never touches the filesystem and never executes anything (requirements
6, 7, 8):
  - `target_file` is carried straight through into the returned
    `CodeGenerationResult` purely as a plain string label for *where a
    caller might later choose to apply this code* (e.g. via the
    existing, entirely unmodified `text_file_write`/
    `code_change_apply` capabilities - execution/
    text_file_write_capability.py, execution/
    code_change_apply_capability.py) - it is never opened, read, or
    written here, and this module has no import dependency on either
    capability at all. Generating code never writes a project file,
    automatically or otherwise.
  - The generated source is only ever handed to `ast.parse` (via
    `inspect_source`, itself parse-only, never `eval`/`exec`) - never
    executed, never `compile(..., mode="exec")`-run, and never
    spawned as a subprocess. Running the generated function is an
    entirely separate, not-yet-built step for a later stage; this
    module's own result is always inspectable (readable, comparable,
    loggable) before any such application ever happens.

Standard-library only (requirement 9): `keyword` (identifier safety)
and `code_intelligence.python_inspector` (itself `ast`-only) - no new
dependency of any kind.

Not a duplicate code-generation system (requirement 10): no other
module in this project assembles Python source from a structured
spec - `code_change_plan_capability.py`/`code_change_apply_capability.py`
only ever plan/apply an already-supplied exact-text-fragment
replacement inside an *existing* file, they never author new source
text of their own, and `self_upgrade/sandbox.py` explicitly still
performs no real code generation (see that module's own docstring).
This is the first, and only, place in the project that renders new
Python source from a structured specification.
"""

import keyword

from code_intelligence.python_inspector import inspect_source
from .code_generation_result import CodeGenerationResult, STATUS_GENERATED, STATUS_INVALID_REQUEST

# The only fields this minimal generator understands - a small, fixed
# vocabulary, same "controlled shape, nothing free-form" convention
# the rest of this module's docstring already describes. Kept as a
# tuple (not scattered string literals) purely for a single, shared
# point of truth when validating/rendering below.
_REQUIRED_SPEC_FIELDS = ("function_name", "return_expression")
_OPTIONAL_SPEC_FIELDS = ("parameters", "docstring")


def _is_valid_identifier(value):
    """A safe Python identifier: a real `str`, a syntactically valid
    identifier (`str.isidentifier`), and not a reserved keyword or
    soft keyword (`keyword.iskeyword`/`keyword.issoftkeyword`) - the
    same two standard-library checks `ast`-based tooling elsewhere in
    this project already relies on implicitly via `ast.parse` itself,
    made explicit here so a bad name is reported as a structured
    validation error rather than surfacing only as a confusing
    downstream `SyntaxError`."""
    if not isinstance(value, str) or not value.isidentifier():
        return False
    if keyword.iskeyword(value):
        return False
    if hasattr(keyword, "issoftkeyword") and keyword.issoftkeyword(value):
        return False
    return True


def _validate_spec(spec):
    """Structural validation only (requirement 5: no free-form
    natural-language parsing) - every check here inspects the already-
    structured `spec` dict's own fields, never any free text. Returns
    a list of human-readable error strings; empty means `spec` is
    well-formed enough to attempt generation. Never raises for any
    input shape, including a non-`dict` `spec` - same "always return a
    structured, honest verdict" convention `classify_test_result`/
    `inspect_source` already follow."""
    if not isinstance(spec, dict):
        return [f"spec must be a dict, got {type(spec).__name__}."]

    errors = []

    function_name = spec.get("function_name")
    if not _is_valid_identifier(function_name):
        errors.append(
            f"function_name must be a valid, non-keyword Python identifier: "
            f"{function_name!r}"
        )

    parameters = spec.get("parameters", [])
    if not isinstance(parameters, list) or not all(_is_valid_identifier(p) for p in parameters):
        errors.append(
            f"parameters must be a list of valid Python identifiers: {parameters!r}"
        )
    elif len(set(parameters)) != len(parameters):
        errors.append(f"parameters must not contain duplicate names: {parameters!r}")

    return_expression = spec.get("return_expression")
    if not isinstance(return_expression, str) or not return_expression.strip():
        errors.append(
            f"return_expression must be a non-empty string: {return_expression!r}"
        )

    docstring = spec.get("docstring")
    if docstring is not None and not isinstance(docstring, str):
        errors.append(f"docstring must be a string when provided: {docstring!r}")

    unknown_fields = set(spec.keys()) - set(_REQUIRED_SPEC_FIELDS) - set(_OPTIONAL_SPEC_FIELDS)
    if unknown_fields:
        errors.append(f"spec contains unrecognized fields: {sorted(unknown_fields)!r}")

    return errors


def _render_function_source(spec):
    """Assemble the source text for one Python function via plain
    string templating - no `eval`, no `exec`, no code-object
    construction, nothing beyond joining already-validated strings.
    Only ever called with a `spec` `_validate_spec` has already
    approved."""
    function_name = spec["function_name"]
    parameters = spec.get("parameters") or []
    return_expression = spec["return_expression"]
    docstring = spec.get("docstring")

    lines = [f"def {function_name}({', '.join(parameters)}):"]
    if docstring:
        # Triple-double-quoted docstring; the docstring text itself is
        # already required to be a plain string (see _validate_spec)
        # - any embedded quotes are escaped so the assembled source
        # always stays syntactically well-formed.
        escaped = docstring.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        lines.append(f'    """{escaped}"""')
    lines.append(f"    return {return_expression}")
    return "\n".join(lines) + "\n"


def generate_function(spec, target_file=None):
    """Deterministically render one small Python function from `spec`
    and wrap the outcome in a `CodeGenerationResult` - the single
    entry point this module exposes (requirement 4).

    `spec` must be a plain dict of the form:
        {
            "function_name": <str, a valid, non-keyword identifier>,
            "parameters": <list of str identifiers, optional,
                           defaults to []>,
            "return_expression": <str, a non-empty Python expression -
                                  never executed, only ever assembled
                                  into a `return` statement's source
                                  text>,
            "docstring": <str, optional>,
        }
    Any other shape - not a dict, a missing/invalid `function_name`,
    non-identifier/duplicate `parameters`, a missing/empty
    `return_expression`, a non-string `docstring`, or an unrecognized
    field - is reported as `STATUS_INVALID_REQUEST` with a structured
    `error` message; `generate_function` never raises for a malformed
    `spec` (requirement 11: "invalid input" is always a normal,
    structured result, not an exception).

    `target_file`, if given, is carried straight through into the
    returned result unmodified (requirement 3) - it is never opened,
    read, written, or even checked for existence (requirements 6, 8);
    a caller is free to pass any string label, or omit it entirely
    (`None`, the default).

    Two distinct ways a result can be `STATUS_INVALID_REQUEST`:
      1. `spec` itself fails structural validation - `generated_code`
         is `None`, since no source text was ever assembled.
      2. `spec` is well-formed, source text *was* assembled, but that
         text fails this module's own post-generation check via
         `code_intelligence.python_inspector.inspect_source` (it does
         not parse as valid Python, or - despite parsing - does not
         actually contain a function named `spec["function_name"]`) -
         `generated_code` is still the (invalid/unexpected) assembled
         text, preserved for inspection, never silently discarded.
         Every valid `spec` this templating logic can actually produce
         is expected to pass this check; it exists as a defense-in-
         depth safety net (same "verify your own output, never assume
         it" convention `AdaptivePlanAnalyzer._analyze_plan_state`
         already applies to its own COMPLETE/blockers cross-check),
         not a normally-reachable path.

    Only `STATUS_GENERATED` for a fully successful attempt:
    `generated_code` is the assembled source text, `error` is `None`.

    Never executes the generated source, never writes it anywhere,
    and never mutates `spec` (requirements 7, 8) - the returned
    `CodeGenerationResult.request` is the exact `spec` object handed
    in, unchanged, so a caller can always see exactly what a result
    was based on."""
    errors = _validate_spec(spec)
    if errors:
        return CodeGenerationResult(
            request=spec, target_file=target_file, generated_code=None,
            status=STATUS_INVALID_REQUEST, error="; ".join(errors),
        )

    source = _render_function_source(spec)

    analysis = inspect_source(source, filename=target_file or "<generated>")
    if not analysis["valid"]:
        return CodeGenerationResult(
            request=spec, target_file=target_file, generated_code=source,
            status=STATUS_INVALID_REQUEST,
            error=f"Generated source failed to parse: {analysis['syntax_error']}",
        )
    if not any(f["name"] == spec["function_name"] for f in analysis["functions"]):
        return CodeGenerationResult(
            request=spec, target_file=target_file, generated_code=source,
            status=STATUS_INVALID_REQUEST,
            error="Generated source does not contain the requested function.",
        )

    return CodeGenerationResult(
        request=spec, target_file=target_file, generated_code=source,
        status=STATUS_GENERATED, error=None,
    )
