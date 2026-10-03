"""
Image Operation Dispatcher (Prompt 755, Section 8 - Multimedia)
===============================================================
A small deterministic dispatcher that routes an `ImageOperationPlan` to the one operation implementation that exists: the metadata-only
executor of Prompt 754. It selects nothing automatically, processes no image and touches no file. The generic Prompt 751 executor is untouched.

    dispatch_image_operation(plan) -> ImageOperationDispatchResult(ok, plan, result, failures)

ORDER
1. `plan` must be exactly an `ImageOperationPlan`  -> else ok=False, plan=None, result=None, `IMAGE_OPERATION_DISPATCHER_INVALID_PLAN`.
   The object is never read.
2. Only the exact string "metadata" is supported (no trimming, case-folding or aliases). Any other `plan.operation` gives ok=False, the SAME plan
   object, result=None, `IMAGE_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION`. The metadata executor is NOT called.
3. "metadata": the plan is passed to the public Prompt 754 `execute_image_operation_metadata(plan)` and the
   `ImageOperationMetadataExecutionResult` it returns is held UNCHANGED in `result` (same object). The plan identity is preserved.

`ok` mirrors the routed result: ok=True only when the executor result is ok. Dispatcher failures are only the two codes below; whatever the executor
reports (e.g. its own `..._OUTPUT_CREATION_FAILED`) stays inside `result` (`result.codes()`), is never copied, renamed or re-coded, and the dispatcher's
own `failures` is then empty.

FAILURE CODES (only these two; prefix IMAGE_OPERATION_DISPATCHER_)
INVALID_PLAN (field "plan") and UNSUPPORTED_OPERATION (field "operation"); each failure is {"code", "field", "message"}.

RESULT
Immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value (exact type only), returns
itself from copy/deepcopy and refuses pickling. `failures`, `codes()` and `to_dict()` ({"ok", "plan", "result", "failures"}, `result` as the
executor result's own `to_dict()`) are fresh on every call. The function never raises for bad inputs, never mutates the plan and is deterministic.

WHAT THIS MODULE DOES NOT DO
No image processing, decoding or any other operation than "metadata", no automatic operation selection, no image bytes, paths, filesystem, network,
database, AI model or external service, no clock or randomness, no module-level mutable state. Its only imports are the Prompt 750 plan type and the
Prompt 754 executor function. Not wired into `process_input()`, Core, the Planner, the Agent Loop, the Prompt 751 executor or Section 7.
"""

from .image_operation_metadata_executor import execute_image_operation_metadata
from .image_operation_plan import ImageOperationPlan

SUPPORTED_OPERATION = "metadata"

_PREFIX = "IMAGE_OPERATION_DISPATCHER_"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_UNSUPPORTED_OPERATION = _PREFIX + "UNSUPPORTED_OPERATION"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_UNSUPPORTED_OPERATION)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class ImageOperationDispatchResult:
    """Immutable outcome of `dispatch_image_operation()`. Obtain it only from that function."""

    __slots__ = ("_plan", "_result", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationDispatchResult cannot be subclassed.")

    def __init__(self, _token, plan, result, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use dispatch_image_operation() to obtain an ImageOperationDispatchResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_result", result)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationDispatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationDispatchResult is immutable.")

    @property
    def ok(self):
        return self._result is not None and not self._failures and self._result.ok

    @property
    def plan(self):
        return self._plan

    @property
    def result(self):
        return self._result

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "result", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "plan": self._plan.to_dict() if self._plan is not None else None,
                "result": self._result.to_dict() if self._result is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._result, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationDispatchResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationDispatchResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationDispatchResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def dispatch_image_operation(plan):
    """Route an exact `ImageOperationPlan` to its operation implementation (only "metadata" exists) and return an `ImageOperationDispatchResult`.
    Deterministic, never raises for bad inputs, never mutates the plan, performs no image processing and no I/O."""
    if type(plan) is not ImageOperationPlan:
        return ImageOperationDispatchResult(_CREATE_TOKEN, None, None, [_failure(
            FAILURE_INVALID_PLAN, "plan", "plan must be exactly an ImageOperationPlan.")])
    if plan.operation != SUPPORTED_OPERATION:
        return ImageOperationDispatchResult(_CREATE_TOKEN, plan, None, [_failure(
            FAILURE_UNSUPPORTED_OPERATION, "operation", "Only the %r operation is supported; got %r." % (SUPPORTED_OPERATION, plan.operation))])
    return ImageOperationDispatchResult(_CREATE_TOKEN, plan, execute_image_operation_metadata(plan), ())
