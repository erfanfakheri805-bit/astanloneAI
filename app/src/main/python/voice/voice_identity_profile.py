"""
Voice Identity Profile Contract (Prompt 787, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
===================================================================================================================
A small, immutable, in-memory record of the BASIC METADATA of one voice-identity profile. It is only the stable contract for the later
voice-identity pipeline; no voice recognition exists yet.

    create_voice_identity_profile(data) -> VoiceIdentityProfileResult(ok, profile, failures)
    VoiceIdentityProfile.to_dict()      -> {"profile_id", "display_name", "enabled", "enrollment_status"}

`data` is an exact plain `dict` holding exactly the four fields below. Nothing else is accepted.

    profile_id         str, not empty
    display_name       str, not empty
    enabled            bool (exactly `bool`; 0/1, "true" and every other type are rejected)
    enrollment_status  str, not empty (any text; no fixed status list)

RULES
- All four fields must be present (no defaults are invented) and each must have exactly its type: `str` fields reject `bool`, `int`, `None`, `str`
  subclasses and everything else; `enabled` rejects `str`, `int` and everything else. "Not empty" means `value != ""` - exactly that, nothing more.
  Values are NEVER trimmed, lower-cased, normalized, coerced or otherwise changed: what the caller supplied is what is stored (identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_voice_identity_profile()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the four fields in the order above), using stable `VOICE_IDENTITY_PROFILE_*` codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `VoiceIdentityProfile(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It stores NO raw audio, embeddings, biometric samples or external-service data - only the four fields above - and performs no voice recognition,
enrollment, matching or audio processing. No networking, filesystem, database, subprocess, AI model, external service or external dependency, no
clock or randomness, no module-level mutable state. Imports nothing at all and is not wired into `process_input()`, Core, the Planner, the Agent
Loop or any existing section.
"""

FIELDS = ("profile_id", "display_name", "enabled", "enrollment_status")
FIELD_TYPES = (str, str, bool, str)                      # aligned with FIELDS
REQUIRED_NON_EMPTY = ("profile_id", "display_name", "enrollment_status")

FAILURE_INVALID_INPUT = "VOICE_IDENTITY_PROFILE_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "VOICE_IDENTITY_PROFILE_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "VOICE_IDENTITY_PROFILE_MISSING_FIELD"
FAILURE_INVALID_PROFILE_ID = "VOICE_IDENTITY_PROFILE_INVALID_PROFILE_ID"
FAILURE_INVALID_DISPLAY_NAME = "VOICE_IDENTITY_PROFILE_INVALID_DISPLAY_NAME"
FAILURE_INVALID_ENABLED = "VOICE_IDENTITY_PROFILE_INVALID_ENABLED"
FAILURE_INVALID_ENROLLMENT_STATUS = "VOICE_IDENTITY_PROFILE_INVALID_ENROLLMENT_STATUS"

_INVALID_CODES = (FAILURE_INVALID_PROFILE_ID, FAILURE_INVALID_DISPLAY_NAME, FAILURE_INVALID_ENABLED,
                  FAILURE_INVALID_ENROLLMENT_STATUS)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class VoiceIdentityProfile:
    """Immutable data record of one voice-identity profile's basic metadata. Obtain it only from `create_voice_identity_profile()`."""

    __slots__ = ("_profile_id", "_display_name", "_enabled", "_enrollment_status")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceIdentityProfile cannot be subclassed.")

    def __init__(self, _token, profile_id, display_name, enabled, enrollment_status):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_identity_profile() to build a VoiceIdentityProfile.")
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_display_name", display_name)
        object.__setattr__(self, "_enabled", enabled)
        object.__setattr__(self, "_enrollment_status", enrollment_status)

    def __setattr__(self, key, value):
        raise AttributeError("VoiceIdentityProfile is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceIdentityProfile is immutable.")

    @property
    def profile_id(self):
        return self._profile_id

    @property
    def display_name(self):
        return self._display_name

    @property
    def enabled(self):
        return self._enabled

    @property
    def enrollment_status(self):
        return self._enrollment_status

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe, exactly the four fields). Mutating it never affects this profile."""
        return {"profile_id": self._profile_id, "display_name": self._display_name, "enabled": self._enabled,
                "enrollment_status": self._enrollment_status}

    def _key(self):
        return (self._profile_id, self._display_name, self._enabled, self._enrollment_status)

    def __eq__(self, other):
        if type(other) is not VoiceIdentityProfile:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceIdentityProfile is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceIdentityProfile(profile_id=%r, display_name=%r, enabled=%r, enrollment_status=%r)" % (
            self._profile_id, self._display_name, self._enabled, self._enrollment_status)


class VoiceIdentityProfileResult:
    """Outcome of `create_voice_identity_profile()`: `profile` is set only when `ok`."""

    __slots__ = ("profile", "failures")

    def __init__(self, profile=None, failures=None):
        self.profile = profile
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.profile is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "profile": self.profile.to_dict() if self.profile is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_voice_identity_profile(data):
    """Validate `data` (a plain dict with exactly the four VoiceIdentityProfile fields) and build an immutable `VoiceIdentityProfile`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `VoiceIdentityProfileResult`."""
    if type(data) is not dict:
        return VoiceIdentityProfileResult(failures=[_failure(FAILURE_INVALID_INPUT, "Voice identity profile data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Voice identity profile data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected voice identity profile field: %r." % key, key))
    for index, field in enumerate(FIELDS):
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing voice identity profile field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[index]
        if type(value) is not FIELD_TYPES[index]:
            failures.append(_failure(code, "%s must be a %s." % (field, FIELD_TYPES[index].__name__), field))
        elif field in REQUIRED_NON_EMPTY and len(value) == 0:
            failures.append(_failure(code, "%s must not be empty." % field, field))
    if failures:
        return VoiceIdentityProfileResult(failures=failures)
    return VoiceIdentityProfileResult(profile=VoiceIdentityProfile(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
