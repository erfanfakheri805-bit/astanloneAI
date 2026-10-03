"""
Voice Verification Request Validation (Prompt 799, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
==========================================================================================================================
A small deterministic validator for the `VoiceVerificationRequest` contract (Prompt 798). It follows the output-validator architecture of the earlier
Section 10 validator (Prompt 791) as a separate, unrelated type, and performs no verification.

    validate_voice_verification_request(request) -> VoiceVerificationRequestValidationResult(ok, request, failures)

RULES
1. `request` must be exactly a `VoiceVerificationRequest` (a subclass-free type check; None, a dict, a look-alike, a spoofed `__class__`, ... is
   `INVALID_REQUEST`). Nothing is read from an invalid input and it is never stored.
2. For an exact `VoiceVerificationRequest` the three public values are checked, in this order, and every problem is reported together:
   - `request_id`        must be an exact non-empty `str`   (otherwise `INVALID_REQUEST_ID`)
   - `profile_id`        must be an exact non-empty `str`   (otherwise `INVALID_PROFILE_ID`)
   - `verification_mode` must be an exact non-empty `str`   (otherwise `INVALID_VERIFICATION_MODE`)
   A read that raises counts as invalid for that field. "Non-empty" means `value != ""`, nothing more.
3. Nothing else is examined: string contents are NOT interpreted, normalized, trimmed or compared with anything. In particular `verification_mode`
   is checked for type and emptiness only; there is no mode list and `profile_id` is not looked up.

FAILURE CODES (stable, prefix `VOICE_VERIFICATION_REQUEST_VALIDATOR_`): `INVALID_REQUEST`, `INVALID_REQUEST_ID`, `INVALID_PROFILE_ID`,
`INVALID_VERIFICATION_MODE`.

RESULT
`VoiceVerificationRequestValidationResult` is immutable and has `ok`, `request`, `failures`, `codes()` and `to_dict()`. On success `request` is the very
object that was passed in (identity preserved). On ANY failure `request` is None: an invalid or malformed object is never retained. `failures` is a tuple
of fresh `{"code", "field", "message"}` dicts. `to_dict()` returns FRESH plain data {"ok", "request", "failures"} (`request` is the request's own fresh
`to_dict()` or None). It compares and hashes by value (exact type only), cannot be constructed directly or subclassed, returns itself from
copy/deepcopy and refuses pickling (`TypeError`). Validation is deterministic, never raises for bad inputs and never changes what it is given.

WHAT THIS MODULE DOES NOT DO
No verification, voice recognition, matching or audio processing. It stores and processes NO audio, recordings, embeddings or biometric data. No
networking, filesystem access, subprocess, persistence, database, AI model or external service call. It reads no project state other than the one
request it is given. No clock or randomness, no module-level mutable state. Its only import is the Prompt 798 request type. Not wired into
`process_input()`, Core, the Planner, the Agent Loop, Android or any runtime voice processing.
"""

from .voice_verification_request import VoiceVerificationRequest

FAILURE_INVALID_REQUEST = "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_REQUEST"
FAILURE_INVALID_REQUEST_ID = "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_REQUEST_ID"
FAILURE_INVALID_PROFILE_ID = "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_PROFILE_ID"
FAILURE_INVALID_VERIFICATION_MODE = "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_VERIFICATION_MODE"
FAILURE_CODES = (FAILURE_INVALID_REQUEST, FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_VERIFICATION_MODE)

_STRING_CHECKS = (("request_id", FAILURE_INVALID_REQUEST_ID), ("profile_id", FAILURE_INVALID_PROFILE_ID),
                  ("verification_mode", FAILURE_INVALID_VERIFICATION_MODE))
_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class VoiceVerificationRequestValidationResult:
    """Immutable outcome of `validate_voice_verification_request()`. Obtain it only from that function."""

    __slots__ = ("_request", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationRequestValidationResult cannot be subclassed.")

    def __init__(self, _token, request, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_voice_verification_request() to obtain a VoiceVerificationRequestValidationResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationRequestValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationRequestValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def request(self):
        """The `VoiceVerificationRequest` that was passed in (same object) when it is valid, otherwise None."""
        return self._request

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "request", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "request": self._request.to_dict() if self._request is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._request, self._failures)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationRequestValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationRequestValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationRequestValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def _is_non_empty_str(request, field):
    try:
        value = getattr(request, field)
        return type(value) is str and value != ""
    except Exception:
        return False


def validate_voice_verification_request(request):
    """Check that `request` is an exact `VoiceVerificationRequest` whose request_id, profile_id and verification_mode are exact non-empty strings.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, changes nothing it is given.
    Returns a `VoiceVerificationRequestValidationResult`."""
    if type(request) is not VoiceVerificationRequest:
        return VoiceVerificationRequestValidationResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_REQUEST, "request must be exactly a VoiceVerificationRequest.", "request")])
    failures = []
    for field, code in _STRING_CHECKS:
        if not _is_non_empty_str(request, field):
            failures.append(_failure(code, "%s must be an exact non-empty str." % field, field))
    if failures:
        return VoiceVerificationRequestValidationResult(_CREATE_TOKEN, None, failures)
    return VoiceVerificationRequestValidationResult(_CREATE_TOKEN, request, ())
