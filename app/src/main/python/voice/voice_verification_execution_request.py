"""
Voice Verification Execution Request (Prompt 812, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=========================================================================================================================
A small immutable boundary AFTER authorization. It combines an authorized `VoiceVerificationAuthorization` (Prompt 811) with the matching
`VoiceVerificationPlan` (Prompt 800) into a plain, read-only description of what could be run. It does NOT execute, dispatch or verify anything.

    create_voice_verification_execution_request(authorization, plan)
        -> VoiceVerificationExecutionRequest(request_id, profile_id, verification_mode, failure_codes)

RULES (checked in this order; only public properties are read, private internals are never inspected)
1. `authorization` must be exactly a `VoiceVerificationAuthorization` and `plan` exactly a `VoiceVerificationPlan` (subclass-free `type(...) is` checks; None, dicts,
   look-alikes and objects that spoof `__class__` are invalid). Otherwise `VOICE_VERIFICATION_EXECUTION_REQUEST_INVALID_INPUT`; nothing is read from either object.
2. An authorization whose `authorized` is exactly False gives `VOICE_VERIFICATION_EXECUTION_REQUEST_NOT_AUTHORIZED`. The plan is not read and no executable
   request exists.
3. An `authorized` that is neither exactly True nor exactly False, an authorization or plan `profile_id` that is not an exact non-empty `str`, a plan `request_id` or
   `verification_mode` that is not an exact non-empty `str`, or any public read that raises gives `VOICE_VERIFICATION_EXECUTION_REQUEST_INVALID_INPUT`.
4. An authorized authorization whose `profile_id` differs from `plan.profile_id` (exact string comparison, nothing normalized) gives
   `VOICE_VERIFICATION_EXECUTION_REQUEST_PROFILE_MISMATCH`.
5. Otherwise the request is EXECUTABLE-DESCRIBING (`ok` True): `request_id` and `verification_mode` are the plan's very same `str` objects, `profile_id` is the
   authorization's very same `str` object, in that fixed order, and `failure_codes` is empty. Nothing is normalized, trimmed, case-folded or coerced.
`ok` means only that the authorization and the plan agree; no verification has happened or is started.

FAILURE CODES (stable, prefix `VOICE_VERIFICATION_EXECUTION_REQUEST_`): `INVALID_INPUT`, `NOT_AUTHORIZED`, `PROFILE_MISMATCH`. A rejected request has exactly one code and
`request_id`, `profile_id` and `verification_mode` all None.

EXECUTION REQUEST
`VoiceVerificationExecutionRequest` holds ONLY `request_id`, `profile_id`, `verification_mode` and `failure_codes` (tuple of str); `ok` is derived from an empty
`failure_codes`. It keeps neither the authorization nor the plan. It is immutable, not subclassable, cannot be constructed directly, compares and hashes by value
(exact type only), `to_dict()` returns FRESH plain data, copy/deepcopy return the same object and pickling is refused (`TypeError`). It is deterministic and
never raises for bad inputs.

WHAT THIS MODULE DOES NOT DO
It never calls the verification executor, the dispatch step, the pipeline or the batch runner, and performs no voice recognition, verification, matching,
biometrics, embeddings, ML models or audio processing. No microphone, networking, filesystem, persistence, database, external AI, cloud service, Android API,
clock or randomness, no module-level mutable state and no automatic execution. It changes no earlier module and is not wired into `process_input()`, Core,
the Planner, the Agent Loop, Android or any other section.
"""

from .voice_verification_authorization import VoiceVerificationAuthorization
from .voice_verification_plan import VoiceVerificationPlan

FAILURE_INVALID_INPUT = "VOICE_VERIFICATION_EXECUTION_REQUEST_INVALID_INPUT"
FAILURE_NOT_AUTHORIZED = "VOICE_VERIFICATION_EXECUTION_REQUEST_NOT_AUTHORIZED"
FAILURE_PROFILE_MISMATCH = "VOICE_VERIFICATION_EXECUTION_REQUEST_PROFILE_MISMATCH"
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_NOT_AUTHORIZED, FAILURE_PROFILE_MISMATCH)

_CREATE_TOKEN = object()


def _text(value):
    return type(value) is str and value != ""


class VoiceVerificationExecutionRequest:
    """Immutable execution-request description. Obtain it only from `create_voice_verification_execution_request()`."""

    __slots__ = ("_request_id", "_profile_id", "_verification_mode", "_failure_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationExecutionRequest cannot be subclassed.")

    def __init__(self, _token, request_id, profile_id, verification_mode, failure_codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_verification_execution_request() to obtain a VoiceVerificationExecutionRequest.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_verification_mode", verification_mode)
        object.__setattr__(self, "_failure_codes", tuple(failure_codes))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationExecutionRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationExecutionRequest is immutable.")

    @property
    def ok(self):
        return not self._failure_codes

    @property
    def request_id(self):
        return self._request_id

    @property
    def profile_id(self):
        return self._profile_id

    @property
    def verification_mode(self):
        return self._verification_mode

    @property
    def failure_codes(self):
        """Tuple of failure code strings (empty when ok)."""
        return self._failure_codes

    def to_dict(self):
        """Fresh plain data: {"ok", "request_id", "profile_id", "verification_mode", "failure_codes"}. Mutating it never affects this request."""
        return {"ok": self.ok, "request_id": self._request_id, "profile_id": self._profile_id, "verification_mode": self._verification_mode,
                "failure_codes": list(self._failure_codes)}

    def _key(self):
        return (self._request_id, self._profile_id, self._verification_mode, self._failure_codes)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationExecutionRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationExecutionRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationExecutionRequest(ok=%r, request_id=%r, profile_id=%r, verification_mode=%r, failure_codes=%r)" % ((self.ok,) + self._key())


def _rejected(code):
    return VoiceVerificationExecutionRequest(_CREATE_TOKEN, None, None, None, (code,))


def create_voice_verification_execution_request(authorization, plan):
    """Describe the run that an authorized `authorization` and its matching `plan` allow. Executes nothing and performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceVerificationExecutionRequest`."""
    if type(authorization) is not VoiceVerificationAuthorization or type(plan) is not VoiceVerificationPlan:
        return _rejected(FAILURE_INVALID_INPUT)
    try:
        authorized = authorization.authorized
        if authorized is False:
            return _rejected(FAILURE_NOT_AUTHORIZED)
        if authorized is not True:
            return _rejected(FAILURE_INVALID_INPUT)
        authorization_profile_id = authorization.profile_id
        plan_profile_id = plan.profile_id
        request_id = plan.request_id
        verification_mode = plan.verification_mode
    except Exception:
        return _rejected(FAILURE_INVALID_INPUT)
    if not (_text(authorization_profile_id) and _text(plan_profile_id) and _text(request_id) and _text(verification_mode)):
        return _rejected(FAILURE_INVALID_INPUT)
    if authorization_profile_id != plan_profile_id:
        return _rejected(FAILURE_PROFILE_MISMATCH)
    return VoiceVerificationExecutionRequest(_CREATE_TOKEN, request_id, authorization_profile_id, verification_mode, ())
