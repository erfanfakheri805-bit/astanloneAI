"""
Image Operation Executor Boundary (Prompt 751, Section 8 - Multimedia)
======================================================================
A small deterministic EXECUTION BOUNDARY for an `ImageOperationPlan`. It defines the execution result contract and the one safe entry point
a future executor will sit behind. For this prompt execution is DELIBERATELY NOT IMPLEMENTED: nothing is executed, decoded or modified.

    execute_image_operation(plan) -> ImageOperationExecutionResult(ok, plan, status, failures)

BEHAVIOUR
1. `plan` must be exactly an `ImageOperationPlan` (Prompt 750). Anything else (None, a dict, a look-alike, a subclass-like object) gives
   ok=False, plan=None, status="rejected" and `IMAGE_OPERATION_EXECUTOR_INVALID_PLAN`. The object is never read.
2. A valid plan gives ok=False, the SAME plan object (identity preserved), status="not_implemented" and
   `IMAGE_OPERATION_EXECUTOR_NOT_IMPLEMENTED`. A valid plan is never reported as a success, because no operation is performed.

`ok` is therefore always False in this prompt. `status` is an exact `str` limited to "rejected" and "not_implemented". Only the two failure
codes above exist.

IMMUTABLE AND DETERMINISTIC
`ImageOperationExecutionResult` uses `__slots__`, refuses assignment/deletion, direct construction and subclassing (`TypeError`), compares and
hashes by value (exact type only), returns itself from copy/deepcopy and refuses pickling. `to_dict()` and `failures` return FRESH plain data on
every call. The function never raises for bad inputs and only reads what it is given.

WHAT THIS MODULE DOES NOT DO
No image processing, decoding or modification, no file paths, filesystem, network, database, AI model or external service, no clock or
randomness, no module-level mutable state. It never mutates the supplied plan. Its only import is the Prompt 750 plan type. Not wired into
`process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .image_operation_plan import ImageOperationPlan

STATUS_REJECTED = "rejected"
STATUS_NOT_IMPLEMENTED = "not_implemented"
STATUSES = (STATUS_REJECTED, STATUS_NOT_IMPLEMENTED)

FAILURE_INVALID_PLAN = "IMAGE_OPERATION_EXECUTOR_INVALID_PLAN"
FAILURE_NOT_IMPLEMENTED = "IMAGE_OPERATION_EXECUTOR_NOT_IMPLEMENTED"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_NOT_IMPLEMENTED)

_CREATE_TOKEN = object()


def _failure(code, message):
    return (code, "plan", message)


class ImageOperationExecutionResult:
    """Immutable outcome of `execute_image_operation()`. Obtain it only from that function. `ok` is always False in Prompt 751."""

    __slots__ = ("_plan", "_status", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationExecutionResult cannot be subclassed.")

    def __init__(self, _token, plan, status, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_image_operation() to obtain an ImageOperationExecutionResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationExecutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationExecutionResult is immutable.")

    @property
    def ok(self):
        return False

    @property
    def plan(self):
        """The exact plan object that was supplied (same identity) when it was valid, otherwise None."""
        return self._plan

    @property
    def status(self):
        return self._status

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "status", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "plan": self._plan.to_dict() if self._plan is not None else None, "status": self._status,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._status, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationExecutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationExecutionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationExecutionResult(ok=%r, status=%r, codes=%r)" % (self.ok, self._status, self.codes())


def execute_image_operation(plan):
    """Execution boundary: executes NOTHING. An exact `ImageOperationPlan` yields status "not_implemented"; anything else yields "rejected".
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns an `ImageOperationExecutionResult`."""
    if type(plan) is not ImageOperationPlan:
        return ImageOperationExecutionResult(_CREATE_TOKEN, None, STATUS_REJECTED, [_failure(
            FAILURE_INVALID_PLAN, "plan must be exactly an ImageOperationPlan.")])
    return ImageOperationExecutionResult(_CREATE_TOKEN, plan, STATUS_NOT_IMPLEMENTED, [_failure(
        FAILURE_NOT_IMPLEMENTED, "Image operation execution is not implemented; no operation was performed.")])
