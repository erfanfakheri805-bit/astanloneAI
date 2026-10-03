"""
Voice Enrollment Result Contract (Prompt 790, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=====================================================================================================================
A small, immutable, in-memory description of the OUTCOME of ONE voice-enrollment request. It only DESCRIBES an outcome; nothing here ever performs an
enrollment:

    create_voice_enrollment_result(data) -> VoiceEnrollmentResultResult(ok, result, failures)
    VoiceEnrollmentResult.to_dict()      -> {"request_id", "profile_id", "status", "code", "metadata"}

`data` is an exact plain `dict` holding exactly the five fields below. Nothing else is accepted.

    request_id  str, not empty (NOT looked up or checked against a VoiceEnrollmentRequest)
    profile_id  str, not empty (NOT looked up or checked against a registry)
    status      str, not empty (any text; no fixed status list, no case folding)
    code        str, not empty (any text; no fixed code list)
    metadata    None, or an exact plain dict

RULES
- All five fields must be present (no defaults are invented; `metadata` must be given, even if None). The four strings must each be exactly `str`: a
  `bool`, an `int`, `None`, a `str` subclass or any other type is rejected, so no caller-supplied method is ever run. "Not empty" means `value != ""` -
  exactly that, nothing more. Values are NEVER trimmed, lower-cased, normalized, coerced or otherwise changed (string identity preserved).
- `metadata` must be `None` or exactly `dict` (a dict subclass, a mapping, a list, ... is rejected). Its contents are not inspected or validated.
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_voice_enrollment_result()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the five fields in the order above), using stable `VOICE_ENROLLMENT_RESULT_*` codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `VoiceEnrollmentResult(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND ISOLATED
- `__slots__`, attribute assignment/deletion raises, not subclassable. The caller's `data` dict and `metadata` dict are NOT retained: the metadata
  entries are copied into a private tuple (same key order, same value objects), so editing, clearing or reusing the input afterwards has no effect.
  `metadata` and `to_dict()` return a FRESH plain dict on every call (None when there was no metadata). Metadata VALUES are preserved as given (not
  deep-copied), the convention of the earlier status/code/metadata carriers.
- Equal data means equal objects; the hash covers the four strings only, so a result with unhashable metadata values is still hashable. copy/deepcopy
  return the same object; pickling is refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
It stores NO audio, embeddings, biometric samples, recordings, external-service data or credentials of its own - only the five fields above - and
performs no enrollment, voice recognition, matching or audio processing. It does not look up `request_id` or `profile_id` and does not check `status`
or `code`. No networking, filesystem, database, subprocess, AI model, external service or external dependency, no clock or randomness, no module-level
mutable state. Imports nothing at all and is not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or any other section.
`VoiceIdentityProfile` and `VoiceEnrollmentRequest` are unchanged.
"""

FIELDS = ("request_id", "profile_id", "status", "code", "metadata")

FAILURE_INVALID_INPUT = "VOICE_ENROLLMENT_RESULT_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "VOICE_ENROLLMENT_RESULT_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "VOICE_ENROLLMENT_RESULT_MISSING_FIELD"
FAILURE_INVALID_REQUEST_ID = "VOICE_ENROLLMENT_RESULT_INVALID_REQUEST_ID"
FAILURE_INVALID_PROFILE_ID = "VOICE_ENROLLMENT_RESULT_INVALID_PROFILE_ID"
FAILURE_INVALID_STATUS = "VOICE_ENROLLMENT_RESULT_INVALID_STATUS"
FAILURE_INVALID_CODE = "VOICE_ENROLLMENT_RESULT_INVALID_CODE"
FAILURE_INVALID_METADATA = "VOICE_ENROLLMENT_RESULT_INVALID_METADATA"

_INVALID_CODES = (FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_STATUS, FAILURE_INVALID_CODE, FAILURE_INVALID_METADATA)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class VoiceEnrollmentResult:
    """Immutable description of the outcome of one voice-enrollment request. Obtain it only from `create_voice_enrollment_result()`."""

    __slots__ = ("_request_id", "_profile_id", "_status", "_code", "_items")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentResult cannot be subclassed.")

    def __init__(self, _token, request_id, profile_id, status, code, items):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_enrollment_result() to build a VoiceEnrollmentResult.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_items", items)

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentResult is immutable.")

    @property
    def request_id(self):
        return self._request_id

    @property
    def profile_id(self):
        return self._profile_id

    @property
    def status(self):
        return self._status

    @property
    def code(self):
        return self._code

    @property
    def metadata(self):
        """A FRESH dict of the preserved metadata entries, or None when there was no metadata."""
        if self._items is None:
            return None
        return dict(self._items)

    def to_dict(self):
        """A fresh plain dict (fixed field order, exactly the five fields). Mutating it never affects this result."""
        return {"request_id": self._request_id, "profile_id": self._profile_id, "status": self._status, "code": self._code,
                "metadata": self.metadata}

    def _key(self):
        return (self._request_id, self._profile_id, self._status, self._code, self._items)

    def __eq__(self, other):
        if type(other) is not VoiceEnrollmentResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash((self._request_id, self._profile_id, self._status, self._code))

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentResult(request_id=%r, profile_id=%r, status=%r, code=%r)" % (
            self._request_id, self._profile_id, self._status, self._code)


class VoiceEnrollmentResultResult:
    """Outcome of `create_voice_enrollment_result()`: `result` is set only when `ok`."""

    __slots__ = ("result", "failures")

    def __init__(self, result=None, failures=None):
        self.result = result
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.result is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "result": self.result.to_dict() if self.result is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_voice_enrollment_result(data):
    """Validate `data` (a plain dict with exactly the five VoiceEnrollmentResult fields) and build an immutable `VoiceEnrollmentResult`.
    Deterministic, never raises for bad data, reads `data` without changing it or retaining it. Returns a `VoiceEnrollmentResultResult`."""
    if type(data) is not dict:
        return VoiceEnrollmentResultResult(failures=[_failure(FAILURE_INVALID_INPUT, "Voice enrollment result data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Voice enrollment result data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected voice enrollment result field: %r." % key, key))
    for index, field in enumerate(FIELDS):
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing voice enrollment result field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[index]
        if field == "metadata":
            if value is not None and type(value) is not dict:
                failures.append(_failure(code, "metadata must be None or a plain dict.", field))
        elif type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif value == "":
            failures.append(_failure(code, "%s must not be empty." % field, field))
    if failures:
        return VoiceEnrollmentResultResult(failures=failures)
    metadata = data["metadata"]
    items = None if metadata is None else tuple(metadata.items())
    return VoiceEnrollmentResultResult(result=VoiceEnrollmentResult(
        _CREATE_TOKEN, data["request_id"], data["profile_id"], data["status"], data["code"], items))
