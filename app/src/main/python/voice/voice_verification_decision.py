"""
Voice Verification Decision Gate (Prompt 809, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=====================================================================================================================
A small deterministic decision gate that runs AFTER profile resolution. It turns the EXISTING `VoiceVerificationProfileResolutionResult` (Prompt 808)
into an immutable approved / rejected decision. It follows the immutable result conventions of Prompts 799 and 808 and performs no verification.

    decide_voice_verification(resolution_result) -> VoiceVerificationDecision(approved, profile_id, failure_codes, code)

RULES
1. `resolution_result` must be exactly a `VoiceVerificationProfileResolutionResult` (subclass-free `type(...) is` check; None, dicts, look-alikes and
   objects that spoof `__class__` are invalid). Only its public `ok`, `profile` and `codes()` are read; private internals are never touched.
2. Successful resolution (`ok` is True, `profile` is an exact `VoiceIdentityProfile` with an exact non-empty `str` `profile_id`, no failure codes):
   APPROVED, `profile_id` is exactly that string, `failure_codes` is empty, `code` is `VOICE_VERIFICATION_DECISION_APPROVED`.
3. Failed resolution (`ok` is False, no profile, one or more exact `str` failure codes): REJECTED, `profile_id` is None, `failure_codes` is the
   resolution's own codes in order, `code` is `VOICE_VERIFICATION_DECISION_REJECTED`.
4. Anything else - invalid input, or an exact result whose public data contradicts itself or cannot be read - is REJECTED with `profile_id` None,
   `failure_codes` of exactly (`VOICE_VERIFICATION_DECISION_INVALID_RESULT`,) and that same `code`.
`enabled` and `enrollment_status` of the profile are not interpreted: approval here means only that a profile was resolved.

DECISION
`VoiceVerificationDecision` holds ONLY `approved`, `profile_id`, `failure_codes` (tuple of str) and `code`. The resolution object and the profile are
never retained. It is immutable, not subclassable, cannot be constructed directly, compares and hashes by value (exact type only), `to_dict()` returns
FRESH plain data, copy/deepcopy return the same object and pickling is refused (`TypeError`). Decisions are deterministic and never raise for bad inputs.

WHAT THIS MODULE DOES NOT DO
No voice recognition, verification, matching, biometrics, embeddings, ML models or audio processing, and no microphone, networking, filesystem,
persistence, database, external AI, cloud service, Android API, clock or randomness, no module-level mutable state and no automatic execution. It
changes no earlier module and is not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or any other section.
"""

from .voice_identity_profile import VoiceIdentityProfile
from .voice_verification_profile_resolver import VoiceVerificationProfileResolutionResult

DECISION_APPROVED = "VOICE_VERIFICATION_DECISION_APPROVED"
DECISION_REJECTED = "VOICE_VERIFICATION_DECISION_REJECTED"
FAILURE_INVALID_RESULT = "VOICE_VERIFICATION_DECISION_INVALID_RESULT"
DECISION_CODES = (DECISION_APPROVED, DECISION_REJECTED, FAILURE_INVALID_RESULT)

_CREATE_TOKEN = object()


class VoiceVerificationDecision:
    """Immutable approved/rejected decision. Obtain it only from `decide_voice_verification()`."""

    __slots__ = ("_approved", "_profile_id", "_failure_codes", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationDecision cannot be subclassed.")

    def __init__(self, _token, approved, profile_id, failure_codes, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use decide_voice_verification() to obtain a VoiceVerificationDecision.")
        object.__setattr__(self, "_approved", approved)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_failure_codes", tuple(failure_codes))
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationDecision is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationDecision is immutable.")

    @property
    def approved(self):
        return self._approved

    @property
    def profile_id(self):
        """The resolved profile's id when approved, otherwise None."""
        return self._profile_id

    @property
    def failure_codes(self):
        """Tuple of failure code strings (empty when approved)."""
        return self._failure_codes

    @property
    def code(self):
        return self._code

    def to_dict(self):
        """Fresh plain data: {"approved", "profile_id", "failure_codes", "code"}. Mutating it never affects this decision."""
        return {"approved": self._approved, "profile_id": self._profile_id, "failure_codes": list(self._failure_codes), "code": self._code}

    def _key(self):
        return (self._approved, self._profile_id, self._failure_codes, self._code)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationDecision:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationDecision is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationDecision(approved=%r, profile_id=%r, code=%r)" % (self._approved, self._profile_id, self._code)


def _invalid():
    return VoiceVerificationDecision(_CREATE_TOKEN, False, None, (FAILURE_INVALID_RESULT,), FAILURE_INVALID_RESULT)


def decide_voice_verification(resolution_result):
    """Decide from an exact `VoiceVerificationProfileResolutionResult`: approved only for a successful resolution with a profile.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceVerificationDecision`."""
    if type(resolution_result) is not VoiceVerificationProfileResolutionResult:
        return _invalid()
    try:
        ok = resolution_result.ok
        profile = resolution_result.profile
        codes = tuple(resolution_result.codes())
    except Exception:
        return _invalid()
    if ok is True:
        if codes or type(profile) is not VoiceIdentityProfile:
            return _invalid()
        try:
            profile_id = profile.profile_id
        except Exception:
            return _invalid()
        if type(profile_id) is not str or profile_id == "":
            return _invalid()
        return VoiceVerificationDecision(_CREATE_TOKEN, True, profile_id, (), DECISION_APPROVED)
    if ok is False and profile is None and codes and all(type(c) is str for c in codes):
        return VoiceVerificationDecision(_CREATE_TOKEN, False, None, codes, DECISION_REJECTED)
    return _invalid()
