"""
Voice Enrollment Request Contract (Prompt 789, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=====================================================================================================================
A small, immutable, in-memory description of ONE voice-enrollment request. It only DESCRIBES a request; nothing here ever performs an enrollment:

    create_voice_enrollment_request(data) -> VoiceEnrollmentRequestResult(ok, request, failures)
    VoiceEnrollmentRequest.to_dict()      -> {"request_id", "profile_id", "enrollment_mode"}

`data` is an exact plain `dict` holding exactly the three fields below. Nothing else is accepted.

    request_id       str, not empty
    profile_id       str, not empty (any text; it is NOT looked up or checked against a registry)
    enrollment_mode  str, not empty (any text; no fixed mode list, no case folding)

RULES
- All three fields must be present (no defaults are invented) and each must be exactly `str`: a `bool`, an `int`, `None`, a `str` subclass or any
  other type is rejected, so no caller-supplied method is ever run. "Not empty" means `value != ""` - exactly that, nothing more. Values are NEVER
  trimmed, lower-cased, normalized, coerced or otherwise changed: what the caller supplied is what is stored (string identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_voice_enrollment_request()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields
  sorted by name, then the three fields in the order above), using stable `VOICE_ENROLLMENT_REQUEST_*` codes from `FAILURE_CODES`. The caller's
  dict is only read.
- Direct `VoiceEnrollmentRequest(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It stores NO audio, embeddings, biometric samples, recordings or external-service data - only the three fields above - and performs no enrollment,
voice recognition, matching or audio processing. It does not look up `profile_id` and does not check `enrollment_mode`. No networking, filesystem,
database, subprocess, AI model, external service or external dependency, no clock or randomness, no module-level mutable state. Imports nothing at
all and is not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or any other section.
"""

FIELDS = ("request_id", "profile_id", "enrollment_mode")

FAILURE_INVALID_INPUT = "VOICE_ENROLLMENT_REQUEST_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "VOICE_ENROLLMENT_REQUEST_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "VOICE_ENROLLMENT_REQUEST_MISSING_FIELD"
FAILURE_INVALID_REQUEST_ID = "VOICE_ENROLLMENT_REQUEST_INVALID_REQUEST_ID"
FAILURE_INVALID_PROFILE_ID = "VOICE_ENROLLMENT_REQUEST_INVALID_PROFILE_ID"
FAILURE_INVALID_ENROLLMENT_MODE = "VOICE_ENROLLMENT_REQUEST_INVALID_ENROLLMENT_MODE"

_INVALID_CODES = (FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_ENROLLMENT_MODE)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class VoiceEnrollmentRequest:
    """Immutable description of one voice-enrollment request. Obtain it only from `create_voice_enrollment_request()`."""

    __slots__ = ("_request_id", "_profile_id", "_enrollment_mode")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentRequest cannot be subclassed.")

    def __init__(self, _token, request_id, profile_id, enrollment_mode):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_enrollment_request() to build a VoiceEnrollmentRequest.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_enrollment_mode", enrollment_mode)

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentRequest is immutable.")

    @property
    def request_id(self):
        return self._request_id

    @property
    def profile_id(self):
        return self._profile_id

    @property
    def enrollment_mode(self):
        return self._enrollment_mode

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe, exactly the three fields). Mutating it never affects this request."""
        return {"request_id": self._request_id, "profile_id": self._profile_id, "enrollment_mode": self._enrollment_mode}

    def _key(self):
        return (self._request_id, self._profile_id, self._enrollment_mode)

    def __eq__(self, other):
        if type(other) is not VoiceEnrollmentRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentRequest(request_id=%r, profile_id=%r, enrollment_mode=%r)" % (
            self._request_id, self._profile_id, self._enrollment_mode)


class VoiceEnrollmentRequestResult:
    """Outcome of `create_voice_enrollment_request()`: `request` is set only when `ok`."""

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


def create_voice_enrollment_request(data):
    """Validate `data` (a plain dict with exactly the three VoiceEnrollmentRequest fields) and build an immutable `VoiceEnrollmentRequest`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `VoiceEnrollmentRequestResult`."""
    if type(data) is not dict:
        return VoiceEnrollmentRequestResult(failures=[_failure(FAILURE_INVALID_INPUT, "Voice enrollment request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Voice enrollment request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected voice enrollment request field: %r." % key, key))
    for index, field in enumerate(FIELDS):
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing voice enrollment request field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[index]
        if type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif value == "":
            failures.append(_failure(code, "%s must not be empty." % field, field))
    if failures:
        return VoiceEnrollmentRequestResult(failures=failures)
    return VoiceEnrollmentRequestResult(request=VoiceEnrollmentRequest(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
