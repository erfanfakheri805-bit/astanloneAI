"""
Audio Asset Registry (Prompt 760, Section 8 - Multimedia)
=========================================================
A small, immutable, in-memory, ordered collection of `AudioAsset` objects with lookup by exact `audio_id`. It follows the registry pattern of
`ImageAssetRegistry` (Prompt 747) but is a separate type:

    create_audio_asset_registry(assets)  -> AudioAssetRegistryResult(ok, registry, failures)
    AudioAssetRegistry.lookup(audio_id)  -> AudioAssetLookupResult(found, asset, failures)
    AudioAssetRegistry.to_dict()         -> {"assets": [AudioAsset.to_dict(), ...]}

INPUT RULES
- `assets` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and an
  unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly an `AudioAsset` (Prompt 759). `audio_id` values must be unique by exact comparison (no trimming, no case folding).
  Input order is preserved.
- `create_audio_asset_registry()` never raises for bad input: it reports every problem at once, in input order, using stable codes from
  `FAILURE_CODES`. A bad item is reported once and never also counted as a duplicate. The caller's collection and the assets are only read.
- Direct `AudioAssetRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(audio_id)` never raises and returns an `AudioAssetLookupResult`:
- an exact `str` that matches a registered `audio_id` exactly: `found=True`, `asset` is the very registered object, no failures;
- an exact `str` with no exact match (including a differently-cased or padded id, and ""): `found=False`, `asset=None`, code `AUDIO_NOT_FOUND`;
- anything that is not exactly a `str` (None, bytes, a `str` subclass, an int, ...): `found=False`, `asset=None`, code `INVALID_AUDIO_ID`.
No trimming, case folding, normalization or coercion. A `str` subclass is never compared, so none of its methods are run.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) assets; `assets` and `audio_ids` return tuples. All three classes (`AudioAssetRegistry`,
`AudioAssetRegistryResult`, `AudioAssetLookupResult`) use `__slots__`, refuse assignment / deletion, cannot be built directly or subclassed, compare
and hash by value (exact type only), return themselves from copy/deepcopy and refuse pickling. (The Prompt 747 result classes are plain mutable slot
holders; here the results are immutable, as the Prompt 757 batch result is, and expose the same members.) Equal assets in the same order mean equal
registries and equal hashes (a different order is a different registry). `failures` is a tuple of FRESH `{"code", "field", "message"}` dicts;
`codes()` and `to_dict()` return FRESH data on every call.

WHAT THIS MODULE DOES NOT DO
No audio content, no file paths, no decoding, playback or audio processing, no filesystem, network, database, AI model or external service, no clock
or randomness, no module-level mutable state, no global registry. Its only import is the Prompt 759 `AudioAsset` module. It has no link to
`ImageAsset`, to Section 7 (`GameAsset` and friends) and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .audio_asset import AudioAsset

FAILURE_INVALID_COLLECTION = "AUDIO_ASSET_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_ASSET = "AUDIO_ASSET_REGISTRY_INVALID_ASSET"
FAILURE_DUPLICATE_AUDIO_ID = "AUDIO_ASSET_REGISTRY_DUPLICATE_AUDIO_ID"
FAILURE_AUDIO_NOT_FOUND = "AUDIO_ASSET_REGISTRY_AUDIO_NOT_FOUND"      # lookup only; never produced by the factory
FAILURE_INVALID_AUDIO_ID = "AUDIO_ASSET_REGISTRY_INVALID_AUDIO_ID"    # lookup only; never produced by the factory

FACTORY_FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_ASSET, FAILURE_DUPLICATE_AUDIO_ID)
LOOKUP_FAILURE_CODES = (FAILURE_AUDIO_NOT_FOUND, FAILURE_INVALID_AUDIO_ID)
FAILURE_CODES = FACTORY_FAILURE_CODES + LOOKUP_FAILURE_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return (code, field, message)


def _fresh(failures):
    return tuple({"code": c, "field": f, "message": m} for c, f, m in failures)


class AudioAssetLookupResult:
    """Immutable outcome of `AudioAssetRegistry.lookup()`: `asset` is set only when `found`; otherwise `failures` holds exactly one failure."""

    __slots__ = ("_found", "_asset", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioAssetLookupResult cannot be subclassed.")

    def __init__(self, _token, found, asset, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use AudioAssetRegistry.lookup() to obtain an AudioAssetLookupResult.")
        object.__setattr__(self, "_found", found)
        object.__setattr__(self, "_asset", asset)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioAssetLookupResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioAssetLookupResult is immutable.")

    @property
    def found(self):
        return self._found

    @property
    def asset(self):
        """The very registered `AudioAsset` when `found`, otherwise None."""
        return self._asset

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return _fresh(self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"found", "asset", "failures"}."""
        return {"found": self._found, "asset": self._asset.to_dict() if self._asset is not None else None,
                "failures": list(_fresh(self._failures))}

    def _key(self):
        return (self._found, self._asset, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioAssetLookupResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioAssetLookupResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioAssetLookupResult(found=%r, audio_id=%r, codes=%r)" % (
            self._found, self._asset.audio_id if self._asset is not None else None, self.codes())


class AudioAssetRegistry:
    """Immutable, ordered collection of `AudioAsset` objects with unique ids. Obtain it only from `create_audio_asset_registry()`."""

    __slots__ = ("_assets",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioAssetRegistry cannot be subclassed.")

    def __init__(self, _token, assets):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_asset_registry() to build an AudioAssetRegistry.")
        object.__setattr__(self, "_assets", tuple(assets))

    def __setattr__(self, key, value):
        raise AttributeError("AudioAssetRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioAssetRegistry is immutable.")

    @property
    def assets(self):
        """Tuple of the registered `AudioAsset` objects, in registration order."""
        return self._assets

    @property
    def audio_ids(self):
        """Tuple of the registered audio ids, in registration order."""
        return tuple(a.audio_id for a in self._assets)

    def lookup(self, audio_id):
        """Find an asset by exact `audio_id`. Never raises; returns an `AudioAssetLookupResult`."""
        if type(audio_id) is not str:
            return AudioAssetLookupResult(_CREATE_TOKEN, False, None, [_failure(FAILURE_INVALID_AUDIO_ID, "audio_id must be a str.", "audio_id")])
        for asset in self._assets:
            if asset.audio_id == audio_id:
                return AudioAssetLookupResult(_CREATE_TOKEN, True, asset, ())
        return AudioAssetLookupResult(_CREATE_TOKEN, False, None, [_failure(
            FAILURE_AUDIO_NOT_FOUND, "No audio asset is registered with audio_id %r." % audio_id, "audio_id")])

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"assets": [a.to_dict() for a in self._assets]}

    def __eq__(self, other):
        if type(other) is not AudioAssetRegistry:
            return NotImplemented
        return self._assets == other._assets

    def __hash__(self):
        return hash(self._assets)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioAssetRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioAssetRegistry(audio_ids=%r)" % (self.audio_ids,)


class AudioAssetRegistryResult:
    """Immutable outcome of `create_audio_asset_registry()`: `registry` is set only when `ok`."""

    __slots__ = ("_registry", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioAssetRegistryResult cannot be subclassed.")

    def __init__(self, _token, registry, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_asset_registry() to obtain an AudioAssetRegistryResult.")
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioAssetRegistryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioAssetRegistryResult is immutable.")

    @property
    def ok(self):
        return self._registry is not None and not self._failures

    @property
    def registry(self):
        """The `AudioAssetRegistry` when `ok`, otherwise None."""
        return self._registry

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return _fresh(self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "registry", "failures"}."""
        return {"ok": self.ok, "registry": self._registry.to_dict() if self._registry is not None else None,
                "failures": list(_fresh(self._failures))}

    def _key(self):
        return (self._registry, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioAssetRegistryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioAssetRegistryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioAssetRegistryResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def create_audio_asset_registry(assets):
    """Validate `assets` (a list or tuple of `AudioAsset`, unique audio ids) and build an immutable `AudioAssetRegistry`.
    Deterministic, never raises for bad input, changes nothing it is given. Returns an `AudioAssetRegistryResult`."""
    if type(assets) not in (list, tuple):
        return AudioAssetRegistryResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_COLLECTION, "assets must be a list or a tuple of AudioAsset objects.", "assets")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(assets):
        if type(item) is not AudioAsset:
            failures.append(_failure(FAILURE_INVALID_ASSET, "assets[%d] must be an AudioAsset." % index, "assets"))
        elif item.audio_id in seen:
            failures.append(_failure(FAILURE_DUPLICATE_AUDIO_ID, "assets[%d] duplicates an earlier audio_id: %r." % (index, item.audio_id), "assets"))
        else:
            seen.add(item.audio_id)
            valid.append(item)
    if failures:
        return AudioAssetRegistryResult(_CREATE_TOKEN, None, failures)
    return AudioAssetRegistryResult(_CREATE_TOKEN, AudioAssetRegistry(_CREATE_TOKEN, valid), ())
