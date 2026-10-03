"""
Audio Operation Request Foundation (Prompt 761, Section 8 - Multimedia)
=======================================================================
A small, immutable, in-memory REQUEST CONTRACT describing one future audio operation. It only describes and validates; it performs no audio
processing and it does not look the audio up anywhere. It follows the conventions of `ImageOperationRequest` (Prompt 748) but is a separate,
unrelated type.

    create_audio_operation_request(data) -> AudioOperationRequestResult(ok, request, failures)
    AudioOperationRequest.to_dict()      -> {"audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality"}

`data` is an exact plain `dict` holding exactly the six fields below. Nothing else is accepted.

    audio_id       str, not empty
    operation      str, not empty (validated FREE TEXT: no list of allowed operations yet)
    target_format  str, may be empty (any text; no fixed format list)
    duration_ms    int, exactly `int` (never bool), > 0
    sample_rate    int, exactly `int` (never bool), > 0
    quality        int, exactly `int` (never bool), 1 through 100 inclusive

RULES
- All six fields must be present (no defaults are invented). The three text fields must be exactly `str` (a `str` subclass or any other type
  is rejected, so no caller-supplied method is ever run); the three numbers must be exactly `int` (`bool`, an `int` subclass, `float`, `str`
  and every other type are rejected). "Not empty" means `value != ""`: values are NEVER trimmed, lower-cased, coerced, reordered or otherwise
  changed - what the caller supplied is what is stored (so a whitespace-only `audio_id` is accepted as-is), and the very same `str` objects are
  kept (identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_audio_operation_request()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields
  sorted by name, then the six fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `AudioOperationRequest(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization), exactly as for `ImageOperationRequest`.

WHAT THIS MODULE DOES NOT DO
It does not decode, encode, process or inspect any audio, does not check that `audio_id` names a registered audio asset, does not know which
operations or formats exist, and does not check that `duration_ms`/`sample_rate` fit any asset. No filesystem, network, subprocess, database, AI
model or external service, no clock or randomness, no module-level mutable state. Imports nothing at all and is not wired into
`process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality")
REQUIRED_NON_EMPTY = ("audio_id", "operation")
STRING_FIELDS = ("audio_id", "operation", "target_format")
POSITIVE_FIELDS = ("duration_ms", "sample_rate")
QUALITY_MIN = 1
QUALITY_MAX = 100

FAILURE_INVALID_INPUT = "AUDIO_OPERATION_REQUEST_INVALID_INPUT"
FAILURE_MISSING_FIELD = "AUDIO_OPERATION_REQUEST_MISSING_FIELD"
FAILURE_UNEXPECTED_FIELD = "AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD"
FAILURE_INVALID_AUDIO_ID = "AUDIO_OPERATION_REQUEST_INVALID_AUDIO_ID"
FAILURE_INVALID_OPERATION = "AUDIO_OPERATION_REQUEST_INVALID_OPERATION"
FAILURE_INVALID_TARGET_FORMAT = "AUDIO_OPERATION_REQUEST_INVALID_TARGET_FORMAT"
FAILURE_INVALID_DURATION_MS = "AUDIO_OPERATION_REQUEST_INVALID_DURATION_MS"
FAILURE_INVALID_SAMPLE_RATE = "AUDIO_OPERATION_REQUEST_INVALID_SAMPLE_RATE"
FAILURE_INVALID_QUALITY = "AUDIO_OPERATION_REQUEST_INVALID_QUALITY"

_INVALID_CODES = (FAILURE_INVALID_AUDIO_ID, FAILURE_INVALID_OPERATION, FAILURE_INVALID_TARGET_FORMAT, FAILURE_INVALID_DURATION_MS,
                  FAILURE_INVALID_SAMPLE_RATE, FAILURE_INVALID_QUALITY)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_MISSING_FIELD, FAILURE_UNEXPECTED_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class AudioOperationRequest:
    """Immutable data record of one audio operation request. Obtain it only from `create_audio_operation_request()`."""

    __slots__ = ("_audio_id", "_operation", "_target_format", "_duration_ms", "_sample_rate", "_quality")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationRequest cannot be subclassed.")

    def __init__(self, _token, audio_id, operation, target_format, duration_ms, sample_rate, quality):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_operation_request() to build an AudioOperationRequest.")
        object.__setattr__(self, "_audio_id", audio_id)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_target_format", target_format)
        object.__setattr__(self, "_duration_ms", duration_ms)
        object.__setattr__(self, "_sample_rate", sample_rate)
        object.__setattr__(self, "_quality", quality)

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationRequest is immutable.")

    @property
    def audio_id(self):
        return self._audio_id

    @property
    def operation(self):
        return self._operation

    @property
    def target_format(self):
        return self._target_format

    @property
    def duration_ms(self):
        return self._duration_ms

    @property
    def sample_rate(self):
        return self._sample_rate

    @property
    def quality(self):
        return self._quality

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this request."""
        return {"audio_id": self._audio_id, "operation": self._operation, "target_format": self._target_format,
                "duration_ms": self._duration_ms, "sample_rate": self._sample_rate, "quality": self._quality}

    def _key(self):
        return (self._audio_id, self._operation, self._target_format, self._duration_ms, self._sample_rate, self._quality)

    def __eq__(self, other):
        if type(other) is not AudioOperationRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return ("AudioOperationRequest(audio_id=%r, operation=%r, target_format=%r, duration_ms=%r, sample_rate=%r, quality=%r)"
                % self._key())


class AudioOperationRequestResult:
    """Outcome of `create_audio_operation_request()`: `request` is set only when `ok`."""

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


def create_audio_operation_request(data):
    """Validate `data` (a plain dict with exactly the six AudioOperationRequest fields) and build an immutable `AudioOperationRequest`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns an `AudioOperationRequestResult`."""
    if type(data) is not dict:
        return AudioOperationRequestResult(failures=[_failure(FAILURE_INVALID_INPUT, "Audio operation request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Audio operation request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected audio operation request field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing audio operation request field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field in STRING_FIELDS:
            if type(value) is not str:
                failures.append(_failure(code, "%s must be a str." % field, field))
            elif field in REQUIRED_NON_EMPTY and value == "":
                failures.append(_failure(code, "%s must not be empty." % field, field))
        elif type(value) is not int:
            failures.append(_failure(code, "%s must be an int." % field, field))
        elif field in POSITIVE_FIELDS:
            if value <= 0:
                failures.append(_failure(code, "%s must be greater than zero." % field, field))
        elif value < QUALITY_MIN or value > QUALITY_MAX:
            failures.append(_failure(code, "%s must be from %d through %d." % (field, QUALITY_MIN, QUALITY_MAX), field))
    if failures:
        return AudioOperationRequestResult(failures=failures)
    return AudioOperationRequestResult(request=AudioOperationRequest(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
