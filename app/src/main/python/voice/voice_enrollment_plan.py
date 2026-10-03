"""
Voice Enrollment Plan (Prompt 792, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
==========================================================================================================
A small deterministic planner that turns a VALIDATED voice-enrollment request into an immutable PLAN DESCRIPTION. It only describes; it performs no
enrollment, no recognition, no audio or biometric processing and touches no file. It mirrors the architecture of the earlier Section 9 plan contract (Prompt 777) as a
separate, unrelated type.

    create_voice_enrollment_plan(validation_result) -> VoiceEnrollmentPlanResult(ok, plan, failures)
    VoiceEnrollmentPlan.to_dict() -> {"request_id", "profile_id", "enrollment_mode"}

WHICH OBJECT IS THE "VALIDATION RESULT"
The voice package has no separate request validator, so the validation result of a `VoiceEnrollmentRequest` is the `VoiceEnrollmentRequestResult` returned
by `create_voice_enrollment_request()` (Prompt 789): it carries `ok`, `request` and `failures`. No existing voice contract or validator is changed.

INPUT AND ORDER (every applicable problem of step 3 is reported together, in field order)
1. `validation_result` must be exactly a `VoiceEnrollmentRequestResult` (subclass-free type check). Anything else (None, a dict, a look-alike, a
   spoofed `__class__`) gives `VOICE_ENROLLMENT_PLAN_INVALID_VALIDATION_RESULT`; nothing is read from it.
2. It must be successful. A failed validation (`ok` false, or an `ok` read that raises) gives `VOICE_ENROLLMENT_PLAN_VALIDATION_FAILED`.
3. Its `request` must be exactly a `VoiceEnrollmentRequest` (`VOICE_ENROLLMENT_PLAN_INVALID_REQUEST`, otherwise), and its three values are re-checked
   with the exact-type rules, because the carrier is a mutable object: `request_id`, `profile_id` and `enrollment_mode` must each be an exact
   non-empty `str` (`INVALID_REQUEST_ID`, `INVALID_PROFILE_ID`, `INVALID_ENROLLMENT_MODE`). "Non-empty" means `value != ""`, nothing more.
4. On success the three values are copied exactly: the very same `str` objects (identity preserved), in the fixed order request_id, profile_id,
   enrollment_mode. Nothing is normalized, trimmed, case-folded, coerced, reordered or reinterpreted. `enrollment_mode` stays free text.

THE PLAN HOLDS ONLY THE THREE VALUES
It does not keep the `VoiceEnrollmentRequest`, any registry or the validation result, so it carries no link back to any of them, and a failed result
does not keep the rejected input either. It stores no audio, recordings, embeddings, biometric samples, service data or credentials.

IMMUTABLE AND DETERMINISTIC
`VoiceEnrollmentPlan` and `VoiceEnrollmentPlanResult` use `__slots__`, refuse assignment/deletion, direct construction and subclassing (`TypeError`),
compare and hash by value (exact type only), return themselves from copy/deepcopy and refuse pickling. `to_dict()` returns FRESH plain data on every
call. The factory never raises for bad inputs and only reads what it is given.

FAILURE CODES (stable, prefix `VOICE_ENROLLMENT_PLAN_`): `INVALID_VALIDATION_RESULT`, `VALIDATION_FAILED`, `INVALID_REQUEST`, `INVALID_REQUEST_ID`,
`INVALID_PROFILE_ID`, `INVALID_ENROLLMENT_MODE`.

WHAT THIS MODULE DOES NOT DO
No enrollment, voice recognition, matching, audio or biometric processing, no networking, filesystem access, persistence, subprocess, database, AI model
or external service. No clock or randomness, no module-level mutable state. Its only imports are the Prompt 789 request and result types. Not wired
into `process_input()`, Core, the Planner, the Agent Loop, Android or any runtime voice processing.
"""

from .voice_enrollment_request import VoiceEnrollmentRequest, VoiceEnrollmentRequestResult

FIELDS = ("request_id", "profile_id", "enrollment_mode")

FAILURE_INVALID_VALIDATION_RESULT = "VOICE_ENROLLMENT_PLAN_INVALID_VALIDATION_RESULT"
FAILURE_VALIDATION_FAILED = "VOICE_ENROLLMENT_PLAN_VALIDATION_FAILED"
FAILURE_INVALID_REQUEST = "VOICE_ENROLLMENT_PLAN_INVALID_REQUEST"
FAILURE_INVALID_REQUEST_ID = "VOICE_ENROLLMENT_PLAN_INVALID_REQUEST_ID"
FAILURE_INVALID_PROFILE_ID = "VOICE_ENROLLMENT_PLAN_INVALID_PROFILE_ID"
FAILURE_INVALID_ENROLLMENT_MODE = "VOICE_ENROLLMENT_PLAN_INVALID_ENROLLMENT_MODE"
FAILURE_CODES = (FAILURE_INVALID_VALIDATION_RESULT, FAILURE_VALIDATION_FAILED, FAILURE_INVALID_REQUEST, FAILURE_INVALID_REQUEST_ID,
                 FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_ENROLLMENT_MODE)

_FIELD_CODES = (FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_ENROLLMENT_MODE)   # aligned with FIELDS
_CREATE_TOKEN = object()


def _failure(code, message, field="validation_result"):
    return (code, field, message)


class VoiceEnrollmentPlan:
    """Immutable plan description of one voice-enrollment request. Obtain it only from `create_voice_enrollment_plan()`."""

    __slots__ = ("_request_id", "_profile_id", "_enrollment_mode")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentPlan cannot be subclassed.")

    def __init__(self, _token, request_id, profile_id, enrollment_mode):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_enrollment_plan() to build a VoiceEnrollmentPlan.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_enrollment_mode", enrollment_mode)

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentPlan is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentPlan is immutable.")

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
        """A fresh plain dict (fixed field order, exactly the three fields). Mutating it never affects this plan."""
        return {"request_id": self._request_id, "profile_id": self._profile_id, "enrollment_mode": self._enrollment_mode}

    def _key(self):
        return (self._request_id, self._profile_id, self._enrollment_mode)

    def __eq__(self, other):
        if type(other) is not VoiceEnrollmentPlan:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentPlan is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentPlan(request_id=%r, profile_id=%r, enrollment_mode=%r)" % self._key()


class VoiceEnrollmentPlanResult:
    """Immutable outcome of `create_voice_enrollment_plan()`: `plan` is set only when `ok`."""

    __slots__ = ("_plan", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentPlanResult cannot be subclassed.")

    def __init__(self, _token, plan, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_enrollment_plan() to obtain a VoiceEnrollmentPlanResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentPlanResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentPlanResult is immutable.")

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
        if type(other) is not VoiceEnrollmentPlanResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentPlanResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentPlanResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def _rejected(failures):
    return VoiceEnrollmentPlanResult(_CREATE_TOKEN, None, failures)


def create_voice_enrollment_plan(validation_result):
    """Build an immutable `VoiceEnrollmentPlan` from an exact, successful `VoiceEnrollmentRequestResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceEnrollmentPlanResult`."""
    if type(validation_result) is not VoiceEnrollmentRequestResult:
        return _rejected([_failure(FAILURE_INVALID_VALIDATION_RESULT, "validation_result must be exactly a VoiceEnrollmentRequestResult.")])
    try:
        passed = bool(validation_result.ok)
    except Exception:
        passed = False
    if not passed:
        return _rejected([_failure(FAILURE_VALIDATION_FAILED, "The voice enrollment request did not pass validation.")])
    try:
        request = validation_result.request
        if type(request) is not VoiceEnrollmentRequest:
            raise TypeError("not a VoiceEnrollmentRequest")
    except Exception:
        return _rejected([_failure(FAILURE_INVALID_REQUEST, "The validated request must be exactly a VoiceEnrollmentRequest.", "request")])
    values = []
    failures = []
    for field, code in zip(FIELDS, _FIELD_CODES):
        try:
            value = getattr(request, field)
            good = type(value) is str and value != ""
        except Exception:
            value, good = None, False
        values.append(value)
        if not good:
            failures.append(_failure(code, "%s must be an exact non-empty str." % field, field))
    if failures:
        return _rejected(failures)
    return VoiceEnrollmentPlanResult(_CREATE_TOKEN, VoiceEnrollmentPlan(_CREATE_TOKEN, *values), ())
