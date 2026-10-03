"""
Image Operation Output Result Contract (Prompt 752, Section 8 - Multimedia)
===========================================================================
A small, immutable, in-memory RESULT MODEL describing the METADATA of one future, successful image operation output. It only describes and
validates; it performs no image processing, holds no image data and touches no file.

    create_image_operation_output(data) -> ImageOperationOutputResult(ok, output, failures)
    ImageOperationOutput.to_dict()      -> {"image_id", "operation", "output_format", "width", "height"}

`data` is an exact plain `dict` holding exactly the five fields below. Nothing else is accepted.

    image_id       exact str, not empty
    operation      exact str, not empty (FREE TEXT: no list of allowed operations)
    output_format  exact str, not empty (FREE TEXT: no list of allowed formats)
    width          exact int (never bool), > 0
    height         exact int (never bool), > 0

RULES
- All five fields are required (no defaults are invented). Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict
  subclass) is rejected. A `str` subclass, `bool`, `int` subclass, `float` or any other wrong type is rejected, so no caller-supplied method is run.
- "Not empty" means `value != ""`. Values are NEVER trimmed, case-folded, coerced or reordered: a whitespace-only string is non-empty and is
  accepted exactly as supplied. What the caller supplied is what is stored, and the very same `str` objects are kept (identity preserved).
- `create_image_operation_output()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields
  sorted by name, then the five fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `ImageOperationOutput(...)` / `ImageOperationOutputResult(...)` construction is refused (TypeError).

WHAT THE MODEL HOLDS
Exactly the five values. It never contains a file path, image bytes, a filesystem object, an `ImageAsset`, an `ImageOperationPlan`, a registry or
any other external resource, and it keeps no link back to the data it was built from.

IMMUTABLE AND DETERMINISTIC
`__slots__`, read-only properties, assignment/deletion raises `AttributeError`, not subclassable (`TypeError`). Equal data means equal objects and
equal hashes (exact type only). `to_dict()` and `failures` return FRESH plain data on every call. copy/deepcopy return the same object; pickling is
refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
No image processing, decoding, resizing or conversion; no check that the values match any plan, asset or real image; no filesystem, network,
subprocess, database, AI model or external service; no clock or randomness; no module-level mutable state. It imports nothing at all and is not
wired into `process_input()`, Core, the Planner, the Agent Loop, the Prompt 751 executor or Section 7.
"""

FIELDS = ("image_id", "operation", "output_format", "width", "height")
STRING_FIELDS = ("image_id", "operation", "output_format")
DIMENSION_FIELDS = ("width", "height")

FAILURE_INVALID_INPUT = "IMAGE_OPERATION_OUTPUT_INVALID_INPUT"
FAILURE_MISSING_FIELD = "IMAGE_OPERATION_OUTPUT_MISSING_FIELD"
FAILURE_UNEXPECTED_FIELD = "IMAGE_OPERATION_OUTPUT_UNEXPECTED_FIELD"
FAILURE_INVALID_IMAGE_ID = "IMAGE_OPERATION_OUTPUT_INVALID_IMAGE_ID"
FAILURE_INVALID_OPERATION = "IMAGE_OPERATION_OUTPUT_INVALID_OPERATION"
FAILURE_INVALID_OUTPUT_FORMAT = "IMAGE_OPERATION_OUTPUT_INVALID_OUTPUT_FORMAT"
FAILURE_INVALID_WIDTH = "IMAGE_OPERATION_OUTPUT_INVALID_WIDTH"
FAILURE_INVALID_HEIGHT = "IMAGE_OPERATION_OUTPUT_INVALID_HEIGHT"

_INVALID_CODES = (FAILURE_INVALID_IMAGE_ID, FAILURE_INVALID_OPERATION, FAILURE_INVALID_OUTPUT_FORMAT, FAILURE_INVALID_WIDTH,
                  FAILURE_INVALID_HEIGHT)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_MISSING_FIELD, FAILURE_UNEXPECTED_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return (code, field, message)


class ImageOperationOutput:
    """Immutable metadata of one future image operation output. Obtain it only from `create_image_operation_output()`."""

    __slots__ = ("_image_id", "_operation", "_output_format", "_width", "_height")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationOutput cannot be subclassed.")

    def __init__(self, _token, image_id, operation, output_format, width, height):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_operation_output() to build an ImageOperationOutput.")
        object.__setattr__(self, "_image_id", image_id)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_output_format", output_format)
        object.__setattr__(self, "_width", width)
        object.__setattr__(self, "_height", height)

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationOutput is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationOutput is immutable.")

    @property
    def image_id(self):
        return self._image_id

    @property
    def operation(self):
        return self._operation

    @property
    def output_format(self):
        return self._output_format

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this output."""
        return {"image_id": self._image_id, "operation": self._operation, "output_format": self._output_format,
                "width": self._width, "height": self._height}

    def _key(self):
        return (self._image_id, self._operation, self._output_format, self._width, self._height)

    def __eq__(self, other):
        if type(other) is not ImageOperationOutput:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationOutput is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationOutput(image_id=%r, operation=%r, output_format=%r, width=%r, height=%r)" % self._key()


class ImageOperationOutputResult:
    """Immutable outcome of `create_image_operation_output()`: `output` is set only when `ok`."""

    __slots__ = ("_output", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationOutputResult cannot be subclassed.")

    def __init__(self, _token, output, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_operation_output() to obtain an ImageOperationOutputResult.")
        object.__setattr__(self, "_output", output)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationOutputResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationOutputResult is immutable.")

    @property
    def ok(self):
        return self._output is not None and not self._failures

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
        """Fresh plain data: {"ok", "output", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "output": self._output.to_dict() if self._output is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._output, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationOutputResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationOutputResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationOutputResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def create_image_operation_output(data):
    """Validate `data` (a plain dict with exactly the five ImageOperationOutput fields) and build an immutable `ImageOperationOutput`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns an `ImageOperationOutputResult`."""
    if type(data) is not dict:
        return ImageOperationOutputResult(_CREATE_TOKEN, None, [_failure(FAILURE_INVALID_INPUT, "Image operation output data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Image operation output data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected image operation output field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing image operation output field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field in STRING_FIELDS:
            if type(value) is not str:
                failures.append(_failure(code, "%s must be a str." % field, field))
            elif value == "":
                failures.append(_failure(code, "%s must not be empty." % field, field))
        elif type(value) is not int:
            failures.append(_failure(code, "%s must be an int." % field, field))
        elif value <= 0:
            failures.append(_failure(code, "%s must be greater than zero." % field, field))
    if failures:
        return ImageOperationOutputResult(_CREATE_TOKEN, None, failures)
    return ImageOperationOutputResult(_CREATE_TOKEN, ImageOperationOutput(_CREATE_TOKEN, *(data[f] for f in FIELDS)), ())
