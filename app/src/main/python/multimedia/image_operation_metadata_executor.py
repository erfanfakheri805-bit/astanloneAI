"""
Image Operation Metadata Executor (Prompt 754, Section 8 - Multimedia)
======================================================================
The first operation that really produces an `ImageOperationOutput`: the safe, metadata-only operation "metadata". It only copies five plan
values into an output; it reads, writes, decodes and modifies no image and touches no file. The Prompt 751 executor is untouched and still
reports "not implemented" for every plan.

    execute_image_operation_metadata(plan) -> ImageOperationMetadataExecutionResult(ok, plan, output, failures)

ORDER
1. `plan` must be exactly an `ImageOperationPlan`  -> else ok=False, plan=None, output=None, `..._INVALID_PLAN`. The object is never read.
2. `plan.operation` must equal exactly "metadata"  -> else ok=False, the SAME plan object, output=None, `..._UNSUPPORTED_OPERATION`.
   Matching is exact (no trimming, case-folding or aliases); no other operation is silently supported.
3. The output is built ONLY through the public `create_image_operation_output()` factory (never by direct construction) from:
       image_id      = plan.image_id
       operation     = plan.operation
       output_format = plan.target_format
       width         = plan.width
       height        = plan.height
   Values are passed through unchanged (the very same str / int objects), never normalized. The factory enforces non-empty
   `target_format` and positive `width` / `height`. If it unexpectedly fails (or raises), the result is ok=False, the same plan object,
   output=None and `..._OUTPUT_CREATION_FAILED`.
4. Success: ok=True, the exact plan object (identity preserved), the created exact `ImageOperationOutput`, no failures.
`quality` is not part of the output model and is ignored.

FAILURE CODES (only these three; prefix IMAGE_OPERATION_METADATA_EXECUTOR_)
INVALID_PLAN, UNSUPPORTED_OPERATION, OUTPUT_CREATION_FAILED. Each failure is {"code", "field", "message"} with field "plan", "operation" or "output".

RESULT
Immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value (exact type only), returns
itself from copy/deepcopy and refuses pickling. `failures`, `codes()` and `to_dict()` ({"ok", "plan", "output", "failures"}) are fresh on every call.
The function never raises for bad inputs, never mutates the plan and is deterministic.

WHAT THIS MODULE DOES NOT DO
No resize / convert / crop / decoding or any other image processing, no image bytes, paths, filesystem, network, database, AI model or external
service, no clock or randomness, no module-level mutable state, no image library. Its only imports are the Prompt 750 plan type and the Prompt 752
output type and factory. Not wired into `process_input()`, Core, the Planner, the Agent Loop, the Prompt 751 executor or Section 7.
"""

from .image_operation_output import ImageOperationOutput, create_image_operation_output
from .image_operation_plan import ImageOperationPlan

SUPPORTED_OPERATION = "metadata"

_PREFIX = "IMAGE_OPERATION_METADATA_EXECUTOR_"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_UNSUPPORTED_OPERATION = _PREFIX + "UNSUPPORTED_OPERATION"
FAILURE_OUTPUT_CREATION_FAILED = _PREFIX + "OUTPUT_CREATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_UNSUPPORTED_OPERATION, FAILURE_OUTPUT_CREATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class ImageOperationMetadataExecutionResult:
    """Immutable outcome of `execute_image_operation_metadata()`. Obtain it only from that function."""

    __slots__ = ("_plan", "_output", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationMetadataExecutionResult cannot be subclassed.")

    def __init__(self, _token, plan, output, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_image_operation_metadata() to obtain an ImageOperationMetadataExecutionResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_output", output)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationMetadataExecutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationMetadataExecutionResult is immutable.")

    @property
    def ok(self):
        return self._output is not None and not self._failures

    @property
    def plan(self):
        return self._plan

    @property
    def output(self):
        return self._output

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "output", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "plan": self._plan.to_dict() if self._plan is not None else None,
                "output": self._output.to_dict() if self._output is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._output, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationMetadataExecutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationMetadataExecutionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationMetadataExecutionResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def execute_image_operation_metadata(plan):
    """Run the metadata-only operation for an exact `ImageOperationPlan` and return an `ImageOperationMetadataExecutionResult`.
    Deterministic, never raises for bad inputs, never mutates the plan, performs no image processing and no I/O."""
    if type(plan) is not ImageOperationPlan:
        return ImageOperationMetadataExecutionResult(_CREATE_TOKEN, None, None, [_failure(
            FAILURE_INVALID_PLAN, "plan", "plan must be exactly an ImageOperationPlan.")])
    if plan.operation != SUPPORTED_OPERATION:
        return ImageOperationMetadataExecutionResult(_CREATE_TOKEN, plan, None, [_failure(
            FAILURE_UNSUPPORTED_OPERATION, "operation", "Only the %r operation is supported; got %r." % (SUPPORTED_OPERATION, plan.operation))])
    try:
        created = create_image_operation_output({"image_id": plan.image_id, "operation": plan.operation,
                                                 "output_format": plan.target_format, "width": plan.width, "height": plan.height})
        output = created.output if created.ok else None
    except Exception:
        output = None
    if type(output) is not ImageOperationOutput:
        return ImageOperationMetadataExecutionResult(_CREATE_TOKEN, plan, None, [_failure(
            FAILURE_OUTPUT_CREATION_FAILED, "output", "The image operation output could not be created from the plan.")])
    return ImageOperationMetadataExecutionResult(_CREATE_TOKEN, plan, output, ())
