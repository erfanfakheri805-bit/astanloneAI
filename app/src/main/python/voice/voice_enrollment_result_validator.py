"""
Voice Enrollment Result Validation (Prompt 791, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
======================================================================================================================
A small deterministic validator for the `VoiceEnrollmentResult` contract (Prompt 790). It follows the output-validator architecture of the earlier
Section 8/9 validators (e.g. Prompt 780) as a separate, unrelated type, and performs no enrollment.

    validate_voice_enrollment_result(result) -> VoiceEnrollmentResultValidationResult(ok, result, failures)

RULES
1. `result` must be exactly a `VoiceEnrollmentResult` (a subclass-free type check; None, a dict, a look-alike, a spoofed `__class__`, ... is
   `INVALID_RESULT`). Nothing is read from an invalid input and it is never stored.
2. For an exact `VoiceEnrollmentResult` the five public values are checked, in this order, and every problem is reported together:
   - `request_id` must be an exact non-empty `str`   (otherwise `INVALID_REQUEST_ID`)
   - `profile_id` must be an exact non-empty `str`   (otherwise `INVALID_PROFILE_ID`)
   - `status`     must be an exact non-empty `str`   (otherwise `INVALID_STATUS`)
   - `code`       must be an exact non-empty `str`   (otherwise `INVALID_CODE`)
   - `metadata`   must be `None` or an exact `dict`  (otherwise `INVALID_METADATA`)
   A read that raises counts as invalid for that field. "Non-empty" means `value != ""`, nothing more.
3. Nothing else is examined: string contents and the metadata keys and values are NOT interpreted, normalized, trimmed or compared with anything.

FAILURE CODES (stable, prefix `VOICE_ENROLLMENT_RESULT_VALIDATOR_`): `INVALID_RESULT`, `INVALID_REQUEST_ID`, `INVALID_PROFILE_ID`, `INVALID_STATUS`,
`INVALID_CODE`, `INVALID_METADATA`.

RESULT
`VoiceEnrollmentResultValidationResult` is immutable and has `ok`, `result`, `failures`, `codes()` and `to_dict()`. On success `result` is the very object
that was passed in (identity preserved). On ANY failure `result` is None: an invalid or malformed object is never retained. `failures` is a tuple of fresh
`{"code", "field", "message"}` dicts. `to_dict()` returns FRESH plain data {"ok", "result", "failures"} (`result` is the result's own fresh `to_dict()` or
None). It compares and hashes by value (exact type only), cannot be constructed directly or subclassed, returns itself from copy/deepcopy and refuses
pickling (`TypeError`). Validation is deterministic, never raises for bad inputs and never changes what it is given.

WHAT THIS MODULE DOES NOT DO
No enrollment, voice recognition, matching or audio processing, no networking, filesystem access, subprocess, persistence, database, AI model or external
service call. It reads no project state other than the one result it is given. No clock or randomness, no module-level mutable state. Its only import is
the Prompt 790 result type. Not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or any runtime voice processing.
"""

from .voice_enrollment_result import VoiceEnrollmentResult

FAILURE_INVALID_RESULT = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_RESULT"
FAILURE_INVALID_REQUEST_ID = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_REQUEST_ID"
FAILURE_INVALID_PROFILE_ID = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_PROFILE_ID"
FAILURE_INVALID_STATUS = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_STATUS"
FAILURE_INVALID_CODE = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_CODE"
FAILURE_INVALID_METADATA = "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_METADATA"
FAILURE_CODES = (FAILURE_INVALID_RESULT, FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_STATUS, FAILURE_INVALID_CODE,
                 FAILURE_INVALID_METADATA)

_STRING_CHECKS = (("request_id", FAILURE_INVALID_REQUEST_ID), ("profile_id", FAILURE_INVALID_PROFILE_ID), ("status", FAILURE_INVALID_STATUS),
                  ("code", FAILURE_INVALID_CODE))
_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class VoiceEnrollmentResultValidationResult:
    """Immutable outcome of `validate_voice_enrollment_result()`. Obtain it only from that function."""

    __slots__ = ("_result", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentResultValidationResult cannot be subclassed.")

    def __init__(self, _token, result, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_voice_enrollment_result() to obtain a VoiceEnrollmentResultValidationResult.")
        object.__setattr__(self, "_result", result)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentResultValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentResultValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def result(self):
        """The `VoiceEnrollmentResult` that was passed in (same object) when it is valid, otherwise None."""
        return self._result

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "result", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "result": self._result.to_dict() if self._result is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._result, self._failures)

    def __eq__(self, other):
        if type(other) is not VoiceEnrollmentResultValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentResultValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentResultValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def _is_non_empty_str(result, field):
    try:
        value = getattr(result, field)
        return type(value) is str and value != ""
    except Exception:
        return False


def _is_valid_metadata(result):
    try:
        metadata = result.metadata
        return metadata is None or type(metadata) is dict
    except Exception:
        return False


def validate_voice_enrollment_result(result):
    """Check that `result` is an exact `VoiceEnrollmentResult` whose request_id, profile_id, status and code are exact non-empty strings and whose
    metadata is None or an exact dict. Performs no I/O of any kind. Deterministic, never raises for bad inputs, changes nothing it is given.
    Returns a `VoiceEnrollmentResultValidationResult`."""
    if type(result) is not VoiceEnrollmentResult:
        return VoiceEnrollmentResultValidationResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_RESULT, "result must be exactly a VoiceEnrollmentResult.", "result")])
    failures = []
    for field, code in _STRING_CHECKS:
        if not _is_non_empty_str(result, field):
            failures.append(_failure(code, "%s must be an exact non-empty str." % field, field))
    if not _is_valid_metadata(result):
        failures.append(_failure(FAILURE_INVALID_METADATA, "metadata must be None or an exact dict.", "metadata"))
    if failures:
        return VoiceEnrollmentResultValidationResult(_CREATE_TOKEN, None, failures)
    return VoiceEnrollmentResultValidationResult(_CREATE_TOKEN, result, ())
