"""
Voice Verification Authorization Boundary (Prompt 811, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=============================================================================================================================
One small deterministic boundary that COMPOSES the existing Section 10 contracts and decides whether a verification may go ahead. It authorizes nothing
by itself and executes nothing: no real verification of any kind takes place here.

    authorize_voice_verification(request, registry, plan) -> VoiceVerificationAuthorization(authorized, profile_id, failure_codes)

COMPOSITION (fixed order, each stage is the EXISTING function, none is recreated)
1. `resolve_voice_verification_profile(request, registry)`   - Prompt 808 resolver
2. `decide_voice_verification(resolution)`                   - Prompt 809 decision gate
3. `create_voice_verification_handoff(decision, plan)`       - Prompt 810 handoff
Only public properties of the stage results are read (`approved`, `profile_id`, `failure_codes`); private internals are never inspected.

RULES
1. `request`, `registry` and `plan` must be exactly a `VoiceVerificationRequest`, a `VoiceVerificationRegistry` and a `VoiceVerificationPlan` (subclass-free
   `type(...) is` checks; None, dicts, look-alikes and objects that spoof `__class__` are invalid). If any is not, the result is NOT authorized with the single
   failure code `VOICE_VERIFICATION_AUTHORIZATION_INVALID_INPUT`, and none of the three stages runs.
2. Otherwise the three stages run in the order above, exactly once each.
3. The result is authorized only when the final handoff is approved (with an exact non-empty `str` `profile_id`). `profile_id` is then exactly the handoff's string and
   `failure_codes` is empty.
4. Any other outcome (rejected resolution, missing profile, rejected decision, profile mismatch, a malformed request or plan that a stage rejects, ...) is NOT
   authorized with `profile_id` None and `failure_codes` = (`VOICE_VERIFICATION_AUTHORIZATION_REJECTED`,) followed by the underlying codes IN ORDER: first the
   decision's failure codes (which carry the resolver's codes), then the handoff's failure codes. Nothing is rewritten, deduplicated or reordered.
Only the two codes `INVALID_INPUT` and `REJECTED` (prefix `VOICE_VERIFICATION_AUTHORIZATION_`) are new; every underlying code keeps its own stage prefix.

AUTHORIZATION
`VoiceVerificationAuthorization` holds ONLY `authorized`, `profile_id` and `failure_codes` (tuple of str). It keeps none of the request, registry, plan,
resolution, decision or handoff objects. It is immutable, not subclassable, cannot be constructed directly, compares and hashes by value (exact type only),
`to_dict()` returns FRESH plain data, copy/deepcopy return the same object and pickling is refused (`TypeError`). It is deterministic, never raises for bad
inputs and mutates nothing it is given. `enabled` and `enrollment_status` of the profile are not interpreted.

WHAT THIS MODULE DOES NOT DO
It never calls the verification executor, the dispatch step, the pipeline or the batch runner, and performs no voice recognition, verification, matching,
biometrics, embeddings, ML models or audio processing. No microphone, networking, filesystem, persistence, database, external AI, cloud service, Android API,
clock or randomness, no module-level mutable state and no automatic execution. It changes no earlier module and is not wired into `process_input()`, Core,
the Planner, the Agent Loop, Android or any other section.
"""

from .voice_verification_decision import decide_voice_verification
from .voice_verification_handoff import create_voice_verification_handoff
from .voice_verification_plan import VoiceVerificationPlan
from .voice_verification_profile_resolver import resolve_voice_verification_profile
from .voice_verification_registry import VoiceVerificationRegistry
from .voice_verification_request import VoiceVerificationRequest

FAILURE_INVALID_INPUT = "VOICE_VERIFICATION_AUTHORIZATION_INVALID_INPUT"
FAILURE_REJECTED = "VOICE_VERIFICATION_AUTHORIZATION_REJECTED"
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_REJECTED)

_CREATE_TOKEN = object()


class VoiceVerificationAuthorization:
    """Immutable authorization outcome. Obtain it only from `authorize_voice_verification()`."""

    __slots__ = ("_authorized", "_profile_id", "_failure_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationAuthorization cannot be subclassed.")

    def __init__(self, _token, authorized, profile_id, failure_codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use authorize_voice_verification() to obtain a VoiceVerificationAuthorization.")
        object.__setattr__(self, "_authorized", authorized)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_failure_codes", tuple(failure_codes))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationAuthorization is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationAuthorization is immutable.")

    @property
    def authorized(self):
        return self._authorized

    @property
    def profile_id(self):
        """The authorized profile id, otherwise None."""
        return self._profile_id

    @property
    def failure_codes(self):
        """Tuple of failure code strings (empty when authorized)."""
        return self._failure_codes

    def to_dict(self):
        """Fresh plain data: {"authorized", "profile_id", "failure_codes"}. Mutating it never affects this authorization."""
        return {"authorized": self._authorized, "profile_id": self._profile_id, "failure_codes": list(self._failure_codes)}

    def _key(self):
        return (self._authorized, self._profile_id, self._failure_codes)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationAuthorization:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationAuthorization is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationAuthorization(authorized=%r, profile_id=%r, failure_codes=%r)" % self._key()


def authorize_voice_verification(request, registry, plan):
    """Compose resolver -> decision -> handoff and report whether the verification is authorized. Executes nothing and performs no I/O.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceVerificationAuthorization`."""
    if type(request) is not VoiceVerificationRequest or type(registry) is not VoiceVerificationRegistry or type(plan) is not VoiceVerificationPlan:
        return VoiceVerificationAuthorization(_CREATE_TOKEN, False, None, (FAILURE_INVALID_INPUT,))
    resolution = resolve_voice_verification_profile(request, registry)
    decision = decide_voice_verification(resolution)
    handoff = create_voice_verification_handoff(decision, plan)
    profile_id = handoff.profile_id
    if handoff.approved is True and type(profile_id) is str and profile_id != "":
        return VoiceVerificationAuthorization(_CREATE_TOKEN, True, profile_id, ())
    return VoiceVerificationAuthorization(_CREATE_TOKEN, False, None, (FAILURE_REJECTED,) + tuple(decision.failure_codes) + tuple(handoff.failure_codes))
