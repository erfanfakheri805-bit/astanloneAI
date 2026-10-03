"""
Image Operation Request Foundation (Prompt 748, Section 8 - Multimedia)
=======================================================================
A small, immutable, in-memory REQUEST CONTRACT describing one future image operation. It only describes and validates; it performs no
image processing and it does not look the image up anywhere.

    create_image_operation_request(data) -> ImageOperationRequestResult(ok, request, failures)
    ImageOperationRequest.to_dict()      -> {"image_id", "operation", "target_format", "width", "height", "quality"}

`data` is an exact plain `dict` holding exactly the six fields below. Nothing else is accepted.

    image_id       str, not empty / not blank
    operation      str, not empty / not blank (validated FREE TEXT: no list of allowed operations yet)
    target_format  str, may be empty (any text; no fixed format list)
    width          int, exactly `int` (never bool), > 0
    height         int, exactly `int` (never bool), > 0
    quality        int, exactly `int` (never bool), 1 through 100 inclusive

RULES
- All six fields must be present (no defaults are invented). The three text fields must be exactly `str` (a `str` subclass or any other type
  is rejected, so no caller-supplied method is ever run); the three numbers must be exactly `int` (`bool`, an `int` subclass, `float`, `str`
  and every other type are rejected). "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased, coerced, reordered or
  otherwise changed - what the caller supplied is what is stored, and the very same `str` objects are kept (identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_image_operation_request()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields
  sorted by name, then the six fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `ImageOperationRequest(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It does not process, decode, resize, convert or inspect any image, does not check that `image_id` names a registered image, does not know
which operations or formats exist, and does not check that `width`/`height` fit any image. No filesystem, network, subprocess, database, AI
model or external service, no clock or randomness, no module-level mutable state. Imports nothing at all and is not wired into
`process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("image_id", "operation", "target_format", "width", "height", "quality")
REQUIRED_NON_BLANK = ("image_id", "operation")
STRING_FIELDS = ("image_id", "operation", "target_format")
DIMENSION_FIELDS = ("width", "height")
QUALITY_MIN = 1
QUALITY_MAX = 100

FAILURE_INVALID_INPUT = "IMAGE_OPERATION_REQUEST_INVALID_INPUT"
FAILURE_MISSING_FIELD = "IMAGE_OPERATION_REQUEST_MISSING_FIELD"
FAILURE_UNEXPECTED_FIELD = "IMAGE_OPERATION_REQUEST_UNEXPECTED_FIELD"
FAILURE_INVALID_IMAGE_ID = "IMAGE_OPERATION_REQUEST_INVALID_IMAGE_ID"
FAILURE_INVALID_OPERATION = "IMAGE_OPERATION_REQUEST_INVALID_OPERATION"
FAILURE_INVALID_TARGET_FORMAT = "IMAGE_OPERATION_REQUEST_INVALID_TARGET_FORMAT"
FAILURE_INVALID_WIDTH = "IMAGE_OPERATION_REQUEST_INVALID_WIDTH"
FAILURE_INVALID_HEIGHT = "IMAGE_OPERATION_REQUEST_INVALID_HEIGHT"
FAILURE_INVALID_QUALITY = "IMAGE_OPERATION_REQUEST_INVALID_QUALITY"

_INVALID_CODES = (FAILURE_INVALID_IMAGE_ID, FAILURE_INVALID_OPERATION, FAILURE_INVALID_TARGET_FORMAT, FAILURE_INVALID_WIDTH,
                  FAILURE_INVALID_HEIGHT, FAILURE_INVALID_QUALITY)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_MISSING_FIELD, FAILURE_UNEXPECTED_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class ImageOperationRequest:
    """Immutable data record of one image operation request. Obtain it only from `create_image_operation_request()`."""

    __slots__ = ("_image_id", "_operation", "_target_format", "_width", "_height", "_quality")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationRequest cannot be subclassed.")

    def __init__(self, _token, image_id, operation, target_format, width, height, quality):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_operation_request() to build an ImageOperationRequest.")
        object.__setattr__(self, "_image_id", image_id)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_target_format", target_format)
        object.__setattr__(self, "_width", width)
        object.__setattr__(self, "_height", height)
        object.__setattr__(self, "_quality", quality)

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationRequest is immutable.")

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
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this request."""
        return {"image_id": self._image_id, "operation": self._operation, "target_format": self._target_format,
                "width": self._width, "height": self._height, "quality": self._quality}

    def _key(self):
        return (self._image_id, self._operation, self._target_format, self._width, self._height, self._quality)

    def __eq__(self, other):
        if type(other) is not ImageOperationRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationRequest(image_id=%r, operation=%r, target_format=%r, width=%r, height=%r, quality=%r)" % self._key()


class ImageOperationRequestResult:
    """Outcome of `create_image_operation_request()`: `request` is set only when `ok`."""

    __slots__ = ("request", "failures")

    def __init__(self, request=None, failures=None):
        self.request = request
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.request is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "request": self.request.to_dict() if self.request is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_image_operation_request(data):
    """Validate `data` (a plain dict with exactly the six ImageOperationRequest fields) and build an immutable `ImageOperationRequest`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns an `ImageOperationRequestResult`."""
    if type(data) is not dict:
        return ImageOperationRequestResult(failures=[_failure(FAILURE_INVALID_INPUT, "Image operation request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Image operation request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected image operation request field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing image operation request field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field in STRING_FIELDS:
            if type(value) is not str:
                failures.append(_failure(code, "%s must be a str." % field, field))
            elif field in REQUIRED_NON_BLANK and value.strip() == "":
                failures.append(_failure(code, "%s must not be empty or blank." % field, field))
        elif type(value) is not int:
            failures.append(_failure(code, "%s must be an int." % field, field))
        elif field in DIMENSION_FIELDS:
            if value <= 0:
                failures.append(_failure(code, "%s must be greater than zero." % field, field))
        elif value < QUALITY_MIN or value > QUALITY_MAX:
            failures.append(_failure(code, "%s must be from %d through %d." % (field, QUALITY_MIN, QUALITY_MAX), field))
    if failures:
        return ImageOperationRequestResult(failures=failures)
    return ImageOperationRequestResult(request=ImageOperationRequest(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
