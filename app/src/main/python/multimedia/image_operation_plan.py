"""
Image Operation Plan (Prompt 750, Section 8 - Multimedia)
=========================================================
A small deterministic planner that turns a VALIDATED image operation request into an immutable EXECUTION DESCRIPTION. It only describes; it
executes nothing, decodes nothing and touches no file.

    create_image_operation_plan(validation_result) -> ImageOperationPlanResult(ok, plan, failures)
    ImageOperationPlan.to_dict() -> {"image_id", "operation", "target_format", "width", "height", "quality"}

INPUT AND ORDER
1. `validation_result` must be exactly an `ImageOperationValidationResult` (Prompt 749). Anything else (None, a dict, a look-alike) gives
   `IMAGE_OPERATION_PLAN_INVALID_VALIDATION_RESULT`; nothing is read from it.
2. It must have `ok=True`. A failed validation gives `IMAGE_OPERATION_PLAN_VALIDATION_FAILED`; no plan is created.
3. On success the six request values are copied exactly from `validation_result.request`: the very same `str` and `int` objects (identity
   preserved), in the fixed order image_id, operation, target_format, width, height, quality. Nothing is normalized, trimmed, case-folded,
   coerced, reordered or reinterpreted.

THE PLAN HOLDS ONLY THE SIX VALUES
It does not keep the `ImageAsset`, the registry, the request or the validation result, so it carries no link back to any of them. `operation`
and `target_format` stay free text; no operation is interpreted or checked here.

IMMUTABLE AND DETERMINISTIC
`ImageOperationPlan` and `ImageOperationPlanResult` use `__slots__`, refuse assignment/deletion, direct construction and subclassing
(`TypeError`), compare and hash by value (exact type only), return themselves from copy/deepcopy and refuse pickling. `to_dict()` returns FRESH
plain data on every call. The factory never raises for bad inputs and only reads what it is given.

WHAT THIS MODULE DOES NOT DO
No image processing, decoding, file paths, filesystem, network, database, AI model or external service, no clock or randomness, no module-level
mutable state. Its only import is the Prompt 749 result type. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .image_operation_validator import ImageOperationValidationResult

FIELDS = ("image_id", "operation", "target_format", "width", "height", "quality")

FAILURE_INVALID_VALIDATION_RESULT = "IMAGE_OPERATION_PLAN_INVALID_VALIDATION_RESULT"
FAILURE_VALIDATION_FAILED = "IMAGE_OPERATION_PLAN_VALIDATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_VALIDATION_RESULT, FAILURE_VALIDATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, message):
    return (code, "validation_result", message)


class ImageOperationPlan:
    """Immutable execution description of one image operation. Obtain it only from `create_image_operation_plan()`."""

    __slots__ = ("_image_id", "_operation", "_target_format", "_width", "_height", "_quality")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationPlan cannot be subclassed.")

    def __init__(self, _token, image_id, operation, target_format, width, height, quality):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_operation_plan() to build an ImageOperationPlan.")
        object.__setattr__(self, "_image_id", image_id)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_target_format", target_format)
        object.__setattr__(self, "_width", width)
        object.__setattr__(self, "_height", height)
        object.__setattr__(self, "_quality", quality)

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationPlan is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationPlan is immutable.")

    @property
    def image_id(self):
        return self._image_id

    @property
    def operation(self):
        return self._operation

    @property
    def target_format(self):
        return self._target_format

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def quality(self):
        return self._quality

    def to_dict(self):
        """A fresh plain dict (fixed field order). Mutating it never affects this plan."""
        return {"image_id": self._image_id, "operation": self._operation, "target_format": self._target_format,
                "width": self._width, "height": self._height, "quality": self._quality}

    def _key(self):
        return (self._image_id, self._operation, self._target_format, self._width, self._height, self._quality)

    def __eq__(self, other):
        if type(other) is not ImageOperationPlan:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationPlan is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationPlan(image_id=%r, operation=%r, target_format=%r, width=%r, height=%r, quality=%r)" % self._key()


class ImageOperationPlanResult:
    """Immutable outcome of `create_image_operation_plan()`: `plan` is set only when `ok`."""

    __slots__ = ("_plan", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationPlanResult cannot be subclassed.")

    def __init__(self, _token, plan, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_operation_plan() to obtain an ImageOperationPlanResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationPlanResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationPlanResult is immutable.")

    @property
    def ok(self):
        return self._plan is not None and not self._failures

    @property
    def plan(self):
        return self._plan

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "plan": self._plan.to_dict() if self._plan is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationPlanResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationPlanResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationPlanResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def create_image_operation_plan(validation_result):
    """Build an immutable `ImageOperationPlan` from an exact, successful `ImageOperationValidationResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns an `ImageOperationPlanResult`."""
    if type(validation_result) is not ImageOperationValidationResult:
        return ImageOperationPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_VALIDATION_RESULT, "validation_result must be exactly an ImageOperationValidationResult.")])
    if not validation_result.ok:
        return ImageOperationPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_VALIDATION_FAILED, "The image operation request did not pass validation (codes: %s)." % ", ".join(validation_result.codes()))])
    request = validation_result.request
    plan = ImageOperationPlan(_CREATE_TOKEN, request.image_id, request.operation, request.target_format,
                              request.width, request.height, request.quality)
    return ImageOperationPlanResult(_CREATE_TOKEN, plan, ())
