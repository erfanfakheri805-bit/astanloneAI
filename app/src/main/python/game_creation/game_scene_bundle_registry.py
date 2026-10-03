"""
Game Scene Bundle Registry (Prompt 733, Section 7 - Professional Game Creation)
===============================================================================
A small, immutable, in-memory collection of already-built `GameSceneBundle` objects (Prompt 732) with lookup by exact `scene_id`. It only
STORES and FINDS bundles; it never checks their contents against anything else.

    create_game_scene_bundle_registry(bundles) -> GameSceneBundleRegistryResult(ok, registry, failures)
    GameSceneBundleRegistryResult.codes()      -> [code, ...]
    GameSceneBundleRegistryResult.to_dict()    -> {"ok", "registry", "failures"}
    GameSceneBundleRegistry.bundles            -> tuple of GameSceneBundle, in input order
    GameSceneBundleRegistry.scene_ids          -> tuple of scene ids, in input order
    GameSceneBundleRegistry.lookup(scene_id)   -> GameSceneBundleLookupResult(found, bundle, code)
    GameSceneBundleRegistry.to_dict()          -> {"bundles": [GameSceneBundle.to_dict(), ...]}

INPUT RULES
- `bundles` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced).
  An empty collection is valid.
- Every item must be exactly a `GameSceneBundle` (Prompt 732). `bundle.scene_id` values must be unique by exact comparison. Input order is preserved.
- Scene ids are NEVER normalized, trimmed, case-folded or coerced. "Arena", "arena" and "arena " are three different ids.
- The scene and composition inside each bundle are accepted as they are: this module does NOT validate scenes, compositions, characters, assets,
  gameplay systems or project structure, and does NOT call the composition validator or the composition registry.
- The supplied bundles (already immutable) and the supplied collection are only read, never changed or stored by reference.

FAILURES
`create_game_scene_bundle_registry()` never raises for bad input. All problems are reported together in input order, using the stable codes
below: GAME_SCENE_BUNDLE_REGISTRY_INVALID_COLLECTION (top-level input is not exactly a list/tuple; nothing else is checked),
GAME_SCENE_BUNDLE_REGISTRY_INVALID_BUNDLE (an item is not exactly a `GameSceneBundle`; never counted as a duplicate) and
GAME_SCENE_BUNDLE_REGISTRY_DUPLICATE_SCENE_ID (an item repeats the `scene_id` of an earlier valid item; the first one is kept as the reference).
GAME_SCENE_BUNDLE_REGISTRY_SCENE_NOT_FOUND is produced by `lookup()` only, never by the factory.

LOOKUP
`lookup(scene_id)` never raises and performs exact matching only. It returns a `GameSceneBundleLookupResult` with `found=True` and the bundle,
or `found=False`, `bundle=None` and the SCENE_NOT_FOUND code (also for a `scene_id` that is not exactly a `str`).

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple; `bundles` and `scene_ids` return tuples. All three classes use `__slots__`, refuse assignment and deletion, cannot be
subclassed and cannot be constructed directly (TypeError). Equal contents mean equal objects and equal hashes (a different order is a different
registry). `failures`, `to_dict()` and `codes()` return FRESH plain data on every call. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
No scene, composition, character, asset, gameplay-system or project checks, no filesystem, network, database, AI model or external service, no
clock or randomness, no module-level mutable state, no global registry. Its only import is the Prompt 732 bundle module. It is not wired into
`process_input()`, Core, the Planner, the Agent Loop or any runtime.
"""

from .game_scene_bundle import GameSceneBundle

FAILURE_INVALID_COLLECTION = "GAME_SCENE_BUNDLE_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_BUNDLE = "GAME_SCENE_BUNDLE_REGISTRY_INVALID_BUNDLE"
FAILURE_DUPLICATE_SCENE_ID = "GAME_SCENE_BUNDLE_REGISTRY_DUPLICATE_SCENE_ID"
FAILURE_SCENE_NOT_FOUND = "GAME_SCENE_BUNDLE_REGISTRY_SCENE_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_BUNDLE, FAILURE_DUPLICATE_SCENE_ID, FAILURE_SCENE_NOT_FOUND)

_CREATE_TOKEN = object()


class GameSceneBundleLookupResult:
    """Immutable outcome of `GameSceneBundleRegistry.lookup()`: `bundle` is set only when `found`; otherwise `code` is
    FAILURE_SCENE_NOT_FOUND. Obtain it only from `lookup()`."""

    __slots__ = ("_found", "_bundle", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundleLookupResult cannot be subclassed.")

    def __init__(self, _token, found, bundle, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use GameSceneBundleRegistry.lookup() to get a GameSceneBundleLookupResult.")
        object.__setattr__(self, "_found", found)
        object.__setattr__(self, "_bundle", bundle)
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundleLookupResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundleLookupResult is immutable.")

    @property
    def found(self):
        return self._found

    @property
    def bundle(self):
        return self._bundle

    @property
    def code(self):
        return self._code

    def to_dict(self):
        """Fresh plain data. Mutating it never affects this result."""
        return {"found": self._found, "bundle": self._bundle.to_dict() if self._bundle is not None else None, "code": self._code}

    def _key(self):
        return (self._found, self._bundle, self._code)

    def __eq__(self, other):
        if type(other) is not GameSceneBundleLookupResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundleLookupResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundleLookupResult(found=%r, code=%r)" % (self._found, self._code)


class GameSceneBundleRegistry:
    """Immutable, ordered collection of `GameSceneBundle` objects with unique scene ids. Obtain it only from
    `create_game_scene_bundle_registry()`."""

    __slots__ = ("_bundles",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundleRegistry cannot be subclassed.")

    def __init__(self, _token, bundles):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_bundle_registry() to build a GameSceneBundleRegistry.")
        object.__setattr__(self, "_bundles", tuple(bundles))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundleRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundleRegistry is immutable.")

    @property
    def bundles(self):
        """Tuple of the registered `GameSceneBundle` objects, in input order."""
        return self._bundles

    @property
    def scene_ids(self):
        """Tuple of the registered scene ids, in input order."""
        return tuple(b.scene_id for b in self._bundles)

    def lookup(self, scene_id):
        """Find a bundle by exact `scene_id`. Never raises; returns a `GameSceneBundleLookupResult`."""
        if type(scene_id) is str:
            for bundle in self._bundles:
                if bundle.scene_id == scene_id:
                    return GameSceneBundleLookupResult(_CREATE_TOKEN, True, bundle, None)
        return GameSceneBundleLookupResult(_CREATE_TOKEN, False, None, FAILURE_SCENE_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in input order. Mutating it never affects this registry."""
        return {"bundles": [b.to_dict() for b in self._bundles]}

    def __eq__(self, other):
        if type(other) is not GameSceneBundleRegistry:
            return NotImplemented
        return self._bundles == other._bundles

    def __hash__(self):
        return hash(self._bundles)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundleRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundleRegistry(scene_ids=%r)" % (self.scene_ids,)


class GameSceneBundleRegistryResult:
    """Immutable outcome of `create_game_scene_bundle_registry()`: `registry` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_registry", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundleRegistryResult cannot be subclassed.")

    def __init__(self, _token, registry, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_bundle_registry() to get a GameSceneBundleRegistryResult.")
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundleRegistryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundleRegistryResult is immutable.")

    @property
    def ok(self):
        return self._registry is not None and not self._failures

    @property
    def registry(self):
        return self._registry

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "registry": self._registry.to_dict() if self._registry is not None else None, "failures": self.failures}

    def _key(self):
        return (self._registry, self._failures)

    def __eq__(self, other):
        if type(other) is not GameSceneBundleRegistryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundleRegistryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundleRegistryResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_scene_bundle_registry(bundles):
    """Check that `bundles` is exactly a list or tuple of `GameSceneBundle` objects with unique scene ids (exact comparison) and build an
    immutable `GameSceneBundleRegistry` that keeps the input order. Nothing inside a bundle is validated or resolved. Deterministic, never
    raises for bad input, changes nothing it is given. Returns a `GameSceneBundleRegistryResult`."""
    if type(bundles) not in (list, tuple):
        return GameSceneBundleRegistryResult(_CREATE_TOKEN, None, [
            (FAILURE_INVALID_COLLECTION, "bundles", "bundles must be a list or a tuple of GameSceneBundle objects.")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(bundles):
        if type(item) is not GameSceneBundle:
            failures.append((FAILURE_INVALID_BUNDLE, "bundles", "bundles[%d] must be a GameSceneBundle." % index))
        elif item.scene_id in seen:
            failures.append((FAILURE_DUPLICATE_SCENE_ID, "bundles", "bundles[%d] duplicates an earlier scene_id: %r." % (index, item.scene_id)))
        else:
            seen.add(item.scene_id)
            valid.append(item)
    if failures:
        return GameSceneBundleRegistryResult(_CREATE_TOKEN, None, failures)
    return GameSceneBundleRegistryResult(_CREATE_TOKEN, GameSceneBundleRegistry(_CREATE_TOKEN, valid), [])
