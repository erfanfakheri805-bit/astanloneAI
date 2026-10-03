"""
Voice Verification Registry (Prompt 807, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
================================================================================================================
A small, immutable, in-memory, ordered collection of the EXISTING `VoiceIdentityProfile` objects (Prompt 787) that the verification chain
(Prompts 798-806) refers to by `profile_id`, with lookup by exact `profile_id`. No second profile model is introduced: the verification chain only
ever carries a `profile_id` string, and `VoiceIdentityProfile` is the established contract that identifies a profile.

    create_voice_verification_registry(profiles)   -> VoiceVerificationRegistryResult(ok, registry, failures)
    VoiceVerificationRegistry.lookup(profile_id)   -> VoiceVerificationLookupResult(found, profile, failures)
    VoiceVerificationRegistry.to_dict()            -> {"profiles": [VoiceIdentityProfile.to_dict(), ...]}

INPUT RULES (same contract as the Prompt 788 `VoiceIdentityProfileRegistry`)
- `profiles` must be exactly a `tuple` (lists, sets, dicts, generators, strings, `None` and tuple subclasses are rejected - nothing is coerced).
  An empty tuple is valid.
- Every item must be exactly a `VoiceIdentityProfile`. The check uses `type(item) is VoiceIdentityProfile`, never `isinstance` and never `__class__`,
  so look-alikes, dicts, `None` and objects that spoof `__class__` are rejected. `profile_id` values must be unique by exact comparison (no trimming,
  no case folding). Input order is preserved and never sorted.
- `create_voice_verification_registry()` never raises for bad input: it reports every problem at once, in input order, using stable codes from
  `FAILURE_CODES`. A bad item is reported once and never also counted as a duplicate. The caller's tuple and the profiles are only read.
- Direct `VoiceVerificationRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(profile_id)` never raises and returns a `VoiceVerificationLookupResult`:
- an exact `str` that matches a registered `profile_id` exactly: `found=True`, `profile` is the very registered object, `failures=[]`;
- an exact `str` with no exact match (including a differently-cased or padded id, and the empty string): `found=False`, `profile=None`, code `PROFILE_NOT_FOUND`;
- anything that is not exactly a `str` (None, bytes, a `str` subclass, an int, ...): `found=False`, `profile=None`, code `INVALID_PROFILE_ID`.
No trimming, case folding, normalization or coercion, and no search by `display_name`, `enabled` or `enrollment_status`. A `str` subclass is never
compared, so none of its methods are run.

IMMUTABLE AND DETERMINISTIC
The registry stores a fresh tuple of the (already immutable) profiles, never the caller's tuple. `profiles` returns that tuple; `profile_ids` returns a
fresh tuple on every access. `__slots__`, assignment / deletion raises, not subclassable. Equal profiles in the same order mean equal registries and
equal hashes (a different order is a different registry); `to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy
return the same object; pickling is refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
It stores NO raw audio, embeddings, biometric samples or external-service data - only `VoiceIdentityProfile` metadata objects - and performs no voice
recognition, verification, matching or audio processing. No microphone, networking, filesystem, persistence, database, AI model, cloud or external
service, Android API, clock or randomness, no module-level mutable state, no global registry. Its only import is the Prompt 787 `VoiceIdentityProfile`
module. It does not change the profile contract or any earlier verification module, and it is not wired into `process_input()`, Core, the Agent Loop,
Android or any other section.
"""

from .voice_identity_profile import VoiceIdentityProfile

FAILURE_INVALID_COLLECTION = "VOICE_VERIFICATION_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_PROFILE = "VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE"
FAILURE_DUPLICATE_PROFILE_ID = "VOICE_VERIFICATION_REGISTRY_DUPLICATE_PROFILE_ID"
FAILURE_PROFILE_NOT_FOUND = "VOICE_VERIFICATION_REGISTRY_PROFILE_NOT_FOUND"      # lookup only; never produced by the factory
FAILURE_INVALID_PROFILE_ID = "VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE_ID"    # lookup only; never produced by the factory

FACTORY_FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_PROFILE, FAILURE_DUPLICATE_PROFILE_ID)
LOOKUP_FAILURE_CODES = (FAILURE_PROFILE_NOT_FOUND, FAILURE_INVALID_PROFILE_ID)
FAILURE_CODES = FACTORY_FAILURE_CODES + LOOKUP_FAILURE_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class VoiceVerificationLookupResult:
    """Outcome of `VoiceVerificationRegistry.lookup()`: `profile` is set only when `found`; otherwise `failures` holds exactly one failure."""

    __slots__ = ("found", "profile", "failures")

    def __init__(self, found=False, profile=None, failures=None):
        self.found = found
        self.profile = profile
        self.failures = [] if failures is None else failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"found": self.found, "profile": self.profile.to_dict() if self.profile is not None else None,
                "failures": [dict(f) for f in self.failures]}


class VoiceVerificationRegistry:
    """Immutable, ordered collection of `VoiceIdentityProfile` objects with unique ids. Obtain it only from `create_voice_verification_registry()`."""

    __slots__ = ("_profiles",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationRegistry cannot be subclassed.")

    def __init__(self, _token, profiles):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_verification_registry() to build a VoiceVerificationRegistry.")
        object.__setattr__(self, "_profiles", tuple(profiles))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationRegistry is immutable.")

    @property
    def profiles(self):
        """Tuple of the registered `VoiceIdentityProfile` objects, in registration order."""
        return self._profiles

    @property
    def profile_ids(self):
        """A fresh tuple of the registered profile ids, in registration order."""
        return tuple(p.profile_id for p in self._profiles)

    def lookup(self, profile_id):
        """Find a profile by exact `profile_id`. Never raises; returns a `VoiceVerificationLookupResult`."""
        if type(profile_id) is not str:
            return VoiceVerificationLookupResult(False, None, [_failure(FAILURE_INVALID_PROFILE_ID, "profile_id must be a str.", "profile_id")])
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return VoiceVerificationLookupResult(True, profile)
        return VoiceVerificationLookupResult(False, None, [_failure(
            FAILURE_PROFILE_NOT_FOUND, "No voice verification profile is registered with profile_id %r." % profile_id, "profile_id")])

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"profiles": [p.to_dict() for p in self._profiles]}

    def __eq__(self, other):
        if type(other) is not VoiceVerificationRegistry:
            return NotImplemented
        return self._profiles == other._profiles

    def __hash__(self):
        return hash(self._profiles)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationRegistry(profile_ids=%r)" % (self.profile_ids,)


class VoiceVerificationRegistryResult:
    """Outcome of `create_voice_verification_registry()`: `registry` is set only when `ok`."""

    __slots__ = ("registry", "failures")

    def __init__(self, registry=None, failures=None):
        self.registry = registry
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.registry is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "registry": self.registry.to_dict() if self.registry is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_voice_verification_registry(profiles):
    """Validate `profiles` (an exact tuple of exact `VoiceIdentityProfile`, unique profile ids) and build an immutable `VoiceVerificationRegistry`.
    Deterministic, never raises for bad input, changes nothing it is given. Returns a `VoiceVerificationRegistryResult`."""
    if type(profiles) is not tuple:
        return VoiceVerificationRegistryResult(failures=[_failure(
            FAILURE_INVALID_COLLECTION, "profiles must be a tuple of VoiceIdentityProfile objects.", "profiles")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(profiles):
        if type(item) is not VoiceIdentityProfile:
            failures.append(_failure(FAILURE_INVALID_PROFILE, "profiles[%d] must be a VoiceIdentityProfile." % index, "profiles"))
        elif item.profile_id in seen:
            failures.append(_failure(FAILURE_DUPLICATE_PROFILE_ID,
                                     "profiles[%d] duplicates an earlier profile_id: %r." % (index, item.profile_id), "profiles"))
        else:
            seen.add(item.profile_id)
            valid.append(item)
    if failures:
        return VoiceVerificationRegistryResult(failures=failures)
    return VoiceVerificationRegistryResult(registry=VoiceVerificationRegistry(_CREATE_TOKEN, valid))
