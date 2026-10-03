"""
Voice Verification Profile Resolver (Prompt 808, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
=======================================================================================================================
A small deterministic resolver that connects the EXISTING `VoiceVerificationRequest` (Prompt 798) to the EXISTING `VoiceVerificationRegistry`
(Prompt 807) through the registry's public `lookup()` API. It follows the result conventions of the Prompt 799 request validator (an immutable,
token-guarded result with `ok`, the payload, `failures`, `codes()` and `to_dict()`), and performs no verification of any kind.

    resolve_voice_verification_profile(request, registry) -> VoiceVerificationProfileResolutionResult(ok, profile, failures)

RULES
1. `request` must be exactly a `VoiceVerificationRequest` (subclass-free `type(...) is` check) that also passes the existing Prompt 799
   `validate_voice_verification_request()`; otherwise `INVALID_REQUEST`.
2. `registry` must be exactly a `VoiceVerificationRegistry`; otherwise `INVALID_REGISTRY`. No registry internals are ever read - only `lookup()`.
3. Both inputs are checked first and every problem is reported together (request, then registry). If either is invalid NO lookup is attempted.
4. For valid inputs the resolver calls `registry.lookup(request.profile_id)` exactly once. A found profile is returned as the very same
   `VoiceIdentityProfile` object (identity preserved, never copied or rebuilt); anything else is `PROFILE_NOT_FOUND`.
5. The profile is returned as registered: `enabled`, `enrollment_status` and `display_name` are not interpreted, so resolving says nothing about
   whether a profile may be used.

FAILURE CODES (stable, prefix `VOICE_VERIFICATION_PROFILE_RESOLVER_`): `INVALID_REQUEST`, `INVALID_REGISTRY`, `PROFILE_NOT_FOUND`.

RESULT
`VoiceVerificationProfileResolutionResult` is immutable and has `ok`, `profile`, `failures`, `codes()` and `to_dict()`. On success `profile` is the registry's
own profile object and `failures` is empty; on any failure `profile` is None. The result keeps NO reference to the request or the registry - only the
profile (success) and plain failure data. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts; `to_dict()` returns FRESH plain data
{"ok", "profile", "failures"}. It compares and hashes by value (exact type only), cannot be constructed directly or subclassed, returns itself from
copy/deepcopy and refuses pickling (`TypeError`). Resolution is deterministic, never raises for bad inputs and never changes what it is given.

WHAT THIS MODULE DOES NOT DO
No voice recognition, verification, matching, biometrics, embeddings or audio processing, and no microphone, networking, filesystem, subprocess,
persistence, database, AI model, cloud or external service, Android API, clock or randomness, no module-level mutable state. It defines no new
request or profile model and changes no earlier module. Not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or any other section.
"""

from .voice_identity_profile import VoiceIdentityProfile
from .voice_verification_registry import VoiceVerificationLookupResult, VoiceVerificationRegistry
from .voice_verification_request import VoiceVerificationRequest
from .voice_verification_request_validator import validate_voice_verification_request

FAILURE_INVALID_REQUEST = "VOICE_VERIFICATION_PROFILE_RESOLVER_INVALID_REQUEST"
FAILURE_INVALID_REGISTRY = "VOICE_VERIFICATION_PROFILE_RESOLVER_INVALID_REGISTRY"
FAILURE_PROFILE_NOT_FOUND = "VOICE_VERIFICATION_PROFILE_RESOLVER_PROFILE_NOT_FOUND"
FAILURE_CODES = (FAILURE_INVALID_REQUEST, FAILURE_INVALID_REGISTRY, FAILURE_PROFILE_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class VoiceVerificationProfileResolutionResult:
    """Immutable outcome of `resolve_voice_verification_profile()`. Obtain it only from that function."""

    __slots__ = ("_profile", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationProfileResolutionResult cannot be subclassed.")

    def __init__(self, _token, profile, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use resolve_voice_verification_profile() to obtain a VoiceVerificationProfileResolutionResult.")
        object.__setattr__(self, "_profile", profile)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationProfileResolutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationProfileResolutionResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def profile(self):
        """The registry's own `VoiceIdentityProfile` (same object) when resolved, otherwise None."""
        return self._profile

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "profile", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "profile": self._profile.to_dict() if self._profile is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._profile, self._failures)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationProfileResolutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationProfileResolutionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationProfileResolutionResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def _rejected(failures):
    return VoiceVerificationProfileResolutionResult(_CREATE_TOKEN, None, failures)


def resolve_voice_verification_profile(request, registry):
    """Resolve the `VoiceIdentityProfile` that `request.profile_id` names in `registry`, using only `registry.lookup()`.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, changes nothing it is given.
    Returns a `VoiceVerificationProfileResolutionResult`."""
    failures = []
    if type(request) is not VoiceVerificationRequest or not validate_voice_verification_request(request).ok:
        failures.append(_failure(FAILURE_INVALID_REQUEST, "request must be a valid VoiceVerificationRequest.", "request"))
    if type(registry) is not VoiceVerificationRegistry:
        failures.append(_failure(FAILURE_INVALID_REGISTRY, "registry must be exactly a VoiceVerificationRegistry.", "registry"))
    if failures:
        return _rejected(failures)
    profile_id = request.profile_id
    found = registry.lookup(profile_id)
    if type(found) is VoiceVerificationLookupResult and found.found is True and type(found.profile) is VoiceIdentityProfile:
        return VoiceVerificationProfileResolutionResult(_CREATE_TOKEN, found.profile, ())
    return _rejected([_failure(FAILURE_PROFILE_NOT_FOUND,
                               "No voice verification profile is registered with profile_id %r." % profile_id, "profile_id")])
