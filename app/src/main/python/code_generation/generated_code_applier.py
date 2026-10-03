"""
Code Generation - Generated Code Applier
============================================
Connects a validated (Prompt 336:
`code_generation.generated_code_validator.validate_generated_code`)
`CodeGenerationResult` (Prompt 335:
`code_generation.code_generation_result.CodeGenerationResult`) to the
existing, unmodified `text_file_write` capability
(execution/text_file_write_capability.py) so a caller can safely write
generated Python source to a brand-new file - never a second,
duplicate file-writing system (requirement 14):

    CodeGenerationResult -> apply_generated_code()
        -> {status, target_file, bytes_written, error}

Reuses, never duplicates (requirements 1, 2, 14):
  - `execution.text_file_write_capability.make_text_file_write_handler`
    is called directly, unchanged, to actually write the file - the
    exact same allowed-directory containment check, existing-file
    protection, and standard-library-only (`os`, built-in `open`)
    write logic that module already implements. This step never
    re-implements path-safety checking, directory creation, or file
    writing of its own; every one of that handler's existing safety
    behaviors (see that module's own docstring) applies here
    automatically, with nothing to keep in sync.
  - `code_generation.generated_code_validator.validate_generated_code`
    is called again, immediately before writing (requirement 9),
    using the exact same validation Prompt 336 already added - never
    a second, differently-behaving validator.

Applies only a VALID result (requirement 4): a `CodeGenerationResult`
whose freshly-recomputed validation status is not `VALIDATION_VALID`
right now is rejected before the write handler is ever even called -
`apply_generated_code` never trusts a validation verdict computed
earlier and handed in separately; it always re-validates the exact
`CodeGenerationResult` it was given, right before writing.

Create-only, never overwrite (requirements 6, 7, 8): `overwrite` is
always passed as `False` to the write handler - a fixed, no-caller-
override contract for this specific application step (the underlying
`text_file_write` capability itself still supports `overwrite=True`
for a caller who explicitly wants that; this module never asks for
it). A `ValueError` the handler raises because the target already
exists is caught here and reported as a clear, structured failure -
never a crash - and the existing file is left completely untouched
(the handler itself never even opens the file for writing in that
case - see that module's own docstring for exactly when it raises
before writing).

Write only to an explicitly provided allowed directory (requirement
5): `allowed_dirs` is passed straight through, unmodified, to
`make_text_file_write_handler` - this module never widens, guesses,
or defaults that list beyond what the underlying capability itself
already defaults to.

Never executes the generated code, never modifies any file this step
didn't itself just create, and never installs anything (requirements
11, 12, 13): the generated source is only ever handed to
`validate_generated_code` (parse-only, via `ast.parse`) and then, if
and only if that revalidation passes, to the write handler's own
`text` argument (bytes on disk, never a code object, never `eval`'d
or `exec`'d). No package-manager/pip call, no `subprocess`, no
network call, and no new import beyond what
`text_file_write_capability`/`generated_code_validator` already bring
in (requirement 15).
"""

from execution.text_file_write_capability import make_text_file_write_handler
from .code_generation_result import CodeGenerationResult
from .generated_code_validator import validate_generated_code, VALIDATION_VALID

STATUS_APPLIED = "APPLIED"
STATUS_REJECTED = "REJECTED"

ALL_APPLY_STATUSES = (STATUS_APPLIED, STATUS_REJECTED)


def _rejected(error, target_file=None):
    return {
        "status": STATUS_REJECTED,
        "target_file": target_file,
        "bytes_written": 0,
        "error": error,
    }


def apply_generated_code(result, allowed_dirs=None):
    """Write an already-generated `CodeGenerationResult` (Prompt 335)
    to a brand-new file, using the existing `text_file_write`
    capability - the single, small "controlled application step" this
    module adds (requirement 3).

    `allowed_dirs`, if given, is passed straight through to
    `make_text_file_write_handler` unchanged (requirement 5: "write
    only to an explicitly provided allowed project directory") - a
    caller integrating this into a real workflow supplies this
    explicitly, the same way every other capability/test in this
    project that touches the filesystem already does; if omitted, the
    underlying handler falls back to the application's own real
    data/skills/temp directories, exactly as `text_file_write_capability.py`
    itself already documents.

    Always returns:
        {
            "status": STATUS_APPLIED | STATUS_REJECTED,
            "target_file": <str or None - see below>,
            "bytes_written": <int - the write handler's own byte_size
                              for STATUS_APPLIED, 0 for
                              STATUS_REJECTED (requirement 10)>,
            "error": <str, or None only for STATUS_APPLIED>,
        }

    `target_file` is `result.target_file` unchanged for every
    `STATUS_REJECTED` outcome (nothing was resolved or written), and
    the write handler's own resolved `path` (the real, on-disk
    location actually written to) for `STATUS_APPLIED`.

    Rejects (`STATUS_REJECTED`, before any write is ever attempted)
    for:
      - `result` not actually a `CodeGenerationResult`;
      - revalidating `result` right now (via
        `validate_generated_code`, requirement 9) does not report
        `VALIDATION_VALID` - covers empty/missing generated_code,
        missing target_file, and invalid Python syntax alike, exactly
        as Prompt 336's validator already reports them (requirement
        4: "may be applied only when its validation status is
        VALID");
      - the underlying `text_file_write` handler itself raises
        `ValueError` - most notably because the target path already
        exists (requirements 7, 8: never overwrite, clear failure,
        file left untouched) or because the resolved path falls
        outside every allowed directory (requirement 5) - the
        handler's own message is preserved unchanged as `error`.

    Never executes `result.generated_code` (requirement 11): the only
    two things ever done with it are handing it to
    `validate_generated_code` (parse-only) and, on success, to the
    write handler's own `text` argument.

    Never modifies an existing file (requirement 12) and never
    installs anything (requirement 13) - the write handler is only
    ever asked to create the one target path, with `overwrite=False`
    always, and this module makes no package-manager/subprocess call
    of any kind."""
    if not isinstance(result, CodeGenerationResult):
        return _rejected(f"Expected a CodeGenerationResult, got {type(result).__name__}.")

    target_file = result.target_file

    # Requirement 9: revalidate immediately before writing - never
    # trust a validation verdict computed at some earlier point in
    # time, even though CodeGenerationResult is never mutated
    # anywhere in this project once created.
    validation = validate_generated_code(result)
    if validation["status"] != VALIDATION_VALID:
        return _rejected(
            f"Generated code is not valid; refusing to apply it. "
            f"({validation['error']})",
            target_file=target_file,
        )

    handler = make_text_file_write_handler(allowed_dirs=allowed_dirs)
    try:
        write_result = handler({
            "path": target_file,
            "text": result.generated_code,
            "overwrite": False,
        })
    except ValueError as exc:
        return _rejected(str(exc), target_file=target_file)

    return {
        "status": STATUS_APPLIED,
        "target_file": write_result["path"],
        "bytes_written": write_result["byte_size"],
        "error": None,
    }
