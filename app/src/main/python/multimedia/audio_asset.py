"""
Audio Asset Contract (Prompt 759, Section 8 - Multimedia)
=========================================================
A small, immutable, in-memory record of the BASIC METADATA of one audio asset. It follows the public API and the immutable-model conventions of
`ImageAsset` (Prompt 746) but is a separate, unrelated type:

    create_audio_asset(data) -> AudioAssetResult(ok, asset, failures)
    AudioAsset.to_dict()     -> {"audio_id", "name", "description", "format", "duration_ms", "sample_rate"}

`data` is an exact plain `dict` holding exactly the six fields below. Nothing else is accepted.

    audio_id     str, not empty / not blank
    name         str, not empty / not blank
    description  str, may be empty
    format       str, not empty / not blank (any text; no fixed format list)
    duration_ms  int, exactly `int` (never bool), > 0
    sample_rate  int, exactly `int` (never bool), > 0

RULES
- All six fields must be present (no defaults are invented). The four text fields must be exactly `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run); `duration_ms` and `sample_rate` must be exactly `int` (`bool`, an `int` subclass, `float`,
  `str` and every other type are rejected) and greater than zero. "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased,
  coerced or otherwise changed - what the caller supplied is what is stored, and the very same `str` objects are kept (identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_audio_asset()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the six fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read, never changed.
- Direct `AudioAsset(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization), exactly as for `ImageAsset`.

WHAT THIS MODULE DOES NOT DO
It holds no samples and no location: no file paths, no decoding, no playback, no audio processing, no format detection or checking, no duration or
sample-rate plausibility checks. It has no registry, request or executor. It is not linked to Section 7 (`GameAsset` and friends), to `ImageAsset` or
to any other module. No filesystem, network, subprocess, database, AI model or external service, no clock or randomness, no module-level mutable
state. Imports nothing at all and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("audio_id", "name", "description", "format", "duration_ms", "sample_rate")
REQUIRED_NON_BLANK = ("audio_id", "name", "format")
STRING_FIELDS = ("audio_id", "name", "description", "format")
NUMERIC_FIELDS = ("duration_ms", "sample_rate")

FAILURE_INVALID_INPUT = "AUDIO_ASSET_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "AUDIO_ASSET_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "AUDIO_ASSET_MISSING_FIELD"
FAILURE_INVALID_AUDIO_ID = "AUDIO_ASSET_INVALID_AUDIO_ID"
FAILURE_INVALID_NAME = "AUDIO_ASSET_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "AUDIO_ASSET_INVALID_DESCRIPTION"
FAILURE_INVALID_FORMAT = "AUDIO_ASSET_INVALID_FORMAT"
FAILURE_INVALID_DURATION_MS = "AUDIO_ASSET_INVALID_DURATION_MS"
FAILURE_INVALID_SAMPLE_RATE = "AUDIO_ASSET_INVALID_SAMPLE_RATE"

_INVALID_CODES = (FAILURE_INVALID_AUDIO_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION, FAILURE_INVALID_FORMAT,
                  FAILURE_INVALID_DURATION_MS, FAILURE_INVALID_SAMPLE_RATE)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class AudioAsset:
    """Immutable data record of one audio asset's basic metadata. Obtain it only from `create_audio_asset()`."""

    __slots__ = ("_audio_id", "_name", "_description", "_format", "_duration_ms", "_sample_rate")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioAsset cannot be subclassed.")

    def __init__(self, _token, audio_id, name, description, format, duration_ms, sample_rate):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_asset() to build an AudioAsset.")
        object.__setattr__(self, "_audio_id", audio_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_format", format)
        object.__setattr__(self, "_duration_ms", duration_ms)
        object.__setattr__(self, "_sample_rate", sample_rate)

    def __setattr__(self, key, value):
        raise AttributeError("AudioAsset is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioAsset is immutable.")

    @property
    def audio_id(self):
        return self._audio_id

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def format(self):
        return self._format

    @property
    def duration_ms(self):
        return self._duration_ms

    @property
    def sample_rate(self):
        return self._sample_rate

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this asset."""
        return {"audio_id": self._audio_id, "name": self._name, "description": self._description, "format": self._format,
                "duration_ms": self._duration_ms, "sample_rate": self._sample_rate}

    def _key(self):
        return (self._audio_id, self._name, self._description, self._format, self._duration_ms, self._sample_rate)

    def __eq__(self, other):
        if type(other) is not AudioAsset:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioAsset is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioAsset(audio_id=%r, name=%r, format=%r, duration_ms=%r, sample_rate=%r)" % (
            self._audio_id, self._name, self._format, self._duration_ms, self._sample_rate)


class AudioAssetResult:
    """Outcome of `create_audio_asset()`: `asset` is set only when `ok`."""

    __slots__ = ("asset", "failures")

    def __init__(self, asset=None, failures=None):
        self.asset = asset
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.asset is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "asset": self.asset.to_dict() if self.asset is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_audio_asset(data):
    """Validate `data` (a plain dict with exactly the six AudioAsset fields) and build an immutable `AudioAsset`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns an `AudioAssetResult`."""
    if type(data) is not dict:
        return AudioAssetResult(failures=[_failure(FAILURE_INVALID_INPUT, "Audio asset data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Audio asset data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected audio asset field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing audio asset field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field in NUMERIC_FIELDS:
            if type(value) is not int:
                failures.append(_failure(code, "%s must be an int." % field, field))
            elif value <= 0:
                failures.append(_failure(code, "%s must be greater than zero." % field, field))
        elif type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append(_failure(code, "%s must not be empty or blank." % field, field))
    if failures:
        return AudioAssetResult(failures=failures)
    return AudioAssetResult(asset=AudioAsset(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
