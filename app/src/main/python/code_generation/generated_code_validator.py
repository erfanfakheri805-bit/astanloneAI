"""
Code Generation - Generated Code Validator
=============================================
Connects the local code-generation result from Prompt 335
(`code_generation.code_generation_result.CodeGenerationResult`) to
this project's *existing* code-analysis/validation logic -
`code_intelligence.python_inspector.inspect_source`, the exact same
AST-based, read-only, parse-only analysis the `code_analysis`
capability (execution/code_analysis_capability.py) and
`code_generation.local_function_generator` already both rely on - so
generated code can be checked BEFORE it is ever executed or applied
to a real file:

    CodeGenerationResult -> validate_generated_code()
        -> {status: VALID|INVALID, error, target_file,
            generated_code, analysis}

Reuses, never duplicates (requirements 1, 2, 10):
  - `code_generation.code_generation_result.CodeGenerationResult` is
    the only input shape this module accepts - it is never rebuilt or
    re-derived, only read from.
  - `code_intelligence.python_inspector.inspect_source` is called
    directly, unchanged, for the Python-syntax check (requirement 5:
    "Python syntax using the standard library AST") - the exact same
    function `code_analysis_capability.py` and
    `local_function_generator.generate_function` already call. This
    module never re-implements `ast` parsing or walking of its own,
    and never opens a file for reading the way
    `code_analysis_capability.py` does (that capability validates an
    *already-saved* `.py` file on disk; this module validates
    already-in-memory generated source that has deliberately never
    been written anywhere - see requirement 8 below) - so it calls
    `inspect_source` directly on the in-memory text, the same
    standard-library-only entry point `code_analysis_capability.py`
    itself calls after its own file read, rather than duplicating
    that capability's file-handling machinery for text that was never
    on disk to begin with.

Three checks, and only three (requirement 5), each capable of failing
the result on its own, each reported with a plain, specific `error`
message (requirement 4: "clearly indicate VALID, INVALID, error"):
  1. `generated_code` is present and not empty/blank;
  2. `target_file` ("target information") is present;
  3. `generated_code` parses as valid Python, via `inspect_source`.

Never executes, applies, installs, or modifies anything (requirements
7, 8, 9):
  - the generated code is only ever handed to `inspect_source`
    (`ast.parse`, parse-only) - never `eval`'d, `exec`'d, or run as a
    subprocess, and this module has no import of `subprocess` or any
    process-spawning facility;
  - no file is opened for writing, created, moved, or installed
    anywhere - `target_file` is read as a plain string label only,
    exactly as `CodeGenerationResult`/`local_function_generator`
    themselves already treat it, never as a path this module touches;
  - `result.generated_code`/`.request`/`.target_file` are read only,
    never mutated - the `generated_code`/`target_file` values in the
    dict this module returns are the identical object the caller
    already had (requirement 6: "preserve the original generated code
    unchanged").

Standard-library only (requirement 13): no new import beyond what
`code_intelligence.python_inspector` (itself `ast`-only) already
brings in.
"""

from code_intelligence.python_inspector import inspect_source
from .code_generation_result import CodeGenerationResult

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"

ALL_VALIDATION_STATUSES = (VALIDATION_VALID, VALIDATION_INVALID)


def _invalid(error, target_file=None, generated_code=None, analysis=None):
    return {
        "status": VALIDATION_INVALID,
        "error": error,
        "target_file": target_file,
        "generated_code": generated_code,
        "analysis": analysis,
    }


def validate_generated_code(result):
    """Validate an already-produced `CodeGenerationResult` (Prompt
    335) before it is ever executed or applied anywhere (requirement
    3).

    Always returns:
        {
            "status": VALIDATION_VALID | VALIDATION_INVALID,
            "error": <str, or None only when status is VALID>,
            "target_file": <result.target_file, unchanged>,
            "generated_code": <result.generated_code, unchanged -
                               requirement 6>,
            "analysis": <the exact dict inspect_source(...) itself
                         returned, or None when a check before syntax
                         analysis already failed (nothing to hand
                         inspect_source in that case)>,
        }

    Checks, in order, the first failure short-circuiting the rest -
    same "one clear verdict, not a pile of accumulated errors"
    convention `classify_test_result`/`build_correction_decision`
    already follow:
      1. `result` must actually be a `CodeGenerationResult`; anything
         else is INVALID with no target_file/generated_code/analysis
         to report (there is nothing real to read them from).
      2. `result.generated_code` must be a non-empty, non-whitespace-
         only string - requirement 5: "generated code is not empty".
      3. `result.target_file` must be a non-empty string -
         requirement 5: "target information is present". Checked
         after emptiness but before syntax, since a caller most needs
         to know *where* it would go before spending a full parse on
         source with nowhere to be applied.
      4. `result.generated_code` must parse as valid Python -
         requirement 5: "Python syntax using the standard library
         AST" - via the existing, unchanged `inspect_source`.

    Never raises - always a structured VALID/INVALID verdict, same
    "no fake intelligence, never crash on bad input" convention this
    project already applies everywhere else (`classify_test_result`,
    `build_code_change_evaluation`, `AdaptivePlanProposal.
    validate_proposal`, ...).

    A `CodeGenerationResult` whose own `status` is already
    `STATUS_INVALID_REQUEST` (see `code_generation_result.py`) is
    still run through every one of these checks unchanged - this
    module never special-cases or trusts that prior status, since its
    only job is to independently verify the *code itself* is safe to
    consider executing/applying, exactly as if it had arrived from
    anywhere else."""
    if not isinstance(result, CodeGenerationResult):
        return _invalid(f"Expected a CodeGenerationResult, got {type(result).__name__}.")

    generated_code = result.generated_code
    target_file = result.target_file

    if not isinstance(generated_code, str) or not generated_code.strip():
        return _invalid(
            "generated_code is empty.", target_file=target_file, generated_code=generated_code,
        )

    if not isinstance(target_file, str) or not target_file.strip():
        return _invalid(
            "target_file is missing.", target_file=target_file, generated_code=generated_code,
        )

    analysis = inspect_source(generated_code, filename=target_file)
    if not analysis["valid"]:
        return _invalid(
            f"Generated code failed to parse: {analysis['syntax_error']}",
            target_file=target_file, generated_code=generated_code, analysis=analysis,
        )

    return {
        "status": VALIDATION_VALID,
        "error": None,
        "target_file": target_file,
        "generated_code": generated_code,
        "analysis": analysis,
    }
