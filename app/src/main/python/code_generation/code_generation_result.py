"""
Code Generation - Code Generation Result
===========================================
`CodeGenerationResult` is the small, structured record
`code_generation/local_function_generator.py` (and any later local code
generator built alongside it - see that module's own "never a second,
duplicate generator" convention) produces for one attempt at local,
deterministic Python code generation:

    structured spec (dict) -> local_function_generator.generate_function()
        -> CodeGenerationResult

Same "plain, JSON-shaped record with `to_dict()`" convention already
used throughout this project - see execution/execution_result.py,
planning/goal.py, planning/plan.py, reasoning/reasoning_result.py,
understanding/result.py, context/context_entry.py - rather than
formatted text, so a caller (a test, a future Agent integration, a UI)
gets everything it needs without re-deriving anything from a message
string.

Purely a data record: nothing here generates code, validates a spec,
writes a file, or executes anything - it only carries the already-
computed outcome of one generation attempt, exactly the way
`SandboxResult` (self_upgrade/sandbox.py) and `ExecutionResult`
(execution/execution_result.py) already carry the already-computed
outcome of their own, unrelated operations, never re-deriving it.

Inspectable before any application (requirement: "the generated result
must be inspectable before any application"): a caller always gets
`generated_code` (or `None` for a failed/invalid request) plus a
`status`/`error` verdict back, entirely separately from
`target_file` - the code is never written to `target_file`, and
`target_file` is never opened, read, or written by anything in this
module. Applying the generated code to a real file (e.g. via the
existing, unmodified `text_file_write`/`code_change_apply`
capabilities - execution/text_file_write_capability.py,
execution/code_change_apply_capability.py) and executing it both
remain entirely separate, not-yet-built steps for a later stage; this
record only ever describes what *could* be applied, never performs
the application itself.
"""

# Small, fixed vocabulary for code-generation status - same STATUS_*/
# ALL_* controlled-vocabulary convention already used throughout this
# project (see execution/execution_result.py's STATUS_*,
# agent/code_change_evaluation.py's STATE_*,
# agent/test_result_evaluation.py's RESULT_*).
STATUS_GENERATED = "GENERATED"
STATUS_INVALID_REQUEST = "INVALID_REQUEST"

ALL_CODE_GENERATION_STATUSES = (STATUS_GENERATED, STATUS_INVALID_REQUEST)


class CodeGenerationResult:
    """One, plain, JSON-shaped record of a single local code-generation
    attempt - requirement: "represent request, target_file,
    generated_code, status, error".

    Purely a data record, exactly like `ExecutionResult`/`SandboxResult`
    above: nothing here decides *to* generate anything, validates a
    spec, touches the filesystem, or executes anything. Never mutated
    by anything outside this constructor after creation - a caller
    who wants a different result calls `generate_function` (or a
    future sibling generator) again, never edits an existing result
    in place.

    `request` is always the exact, unmodified structured specification
    (or malformed input) the generator was called with - never
    copied-with-changes - so a caller can see exactly what a result
    was based on without a second lookup, same convention
    `build_code_change_evaluation` (agent/code_change_evaluation.py)
    already follows for its own `change_result`/`test_result` fields.

    `generated_code` is `None` for any `STATUS_INVALID_REQUEST` result
    reached before source text could even be assembled (e.g. a
    malformed spec), but may still be a non-`None` string for a
    `STATUS_INVALID_REQUEST` result reached *after* assembly (e.g. the
    assembled text failed the generator's own post-generation
    validation) - see `local_function_generator.generate_function`'s
    own docstring for exactly when each case applies. A caller must
    always check `status`, never infer success from
    `generated_code`'s mere presence.
    """

    __slots__ = ("request", "target_file", "generated_code", "status", "error")

    def __init__(self, request, target_file, generated_code, status, error=None):
        if status not in ALL_CODE_GENERATION_STATUSES:
            raise ValueError(f"Unknown code generation status: {status!r}")

        self.request = request
        self.target_file = target_file
        self.generated_code = generated_code
        self.status = status
        self.error = error

    @property
    def success(self):
        """`True` only for `STATUS_GENERATED` - a small, derived
        convenience, never stored twice; same "derive, don't
        duplicate" convention `ExecutionResult`'s own status checks
        already follow."""
        return self.status == STATUS_GENERATED

    def to_dict(self):
        """Plain, JSON-shaped view of this result - requirement 2:
        "small CodeGenerationResult model or equivalent
        existing-compatible structure"."""
        return {
            "request": self.request,
            "target_file": self.target_file,
            "generated_code": self.generated_code,
            "status": self.status,
            "error": self.error,
        }

    def __repr__(self):
        return (
            f"CodeGenerationResult(status={self.status!r}, "
            f"target_file={self.target_file!r}, error={self.error!r})"
        )
