"""
Game Scene Composition Registry (Prompt 731, Section 7 - Professional Game Creation)
=====================================================================================
A small, immutable, in-memory collection of already-built `GameSceneComposition` objects with lookup by exact `scene_id`. It only STORES and
FINDS composition definitions; it never checks them against anything else.

    create_game_scene_composition_registry(compositions) -> GameSceneCompositionRegistryResult(ok, registry, failures)
    GameSceneCompositionRegistryResult.codes()           -> [code, ...]
    GameSceneCompositionRegistryResult.to_dict()         -> {"ok", "registry", "failures"}
    GameSceneCompositionRegistry.compositions            -> tuple of GameSceneComposition, in input order
    GameSceneCompositionRegistry.scene_ids               -> tuple of scene ids, in input order
    GameSceneCompositionRegistry.lookup(scene_id)        -> GameSceneCompositionLookupResult(found, composition, code)
    GameSceneCompositionRegistry.to_dict()               -> {"compositions": [GameSceneComposition.to_dict(), ...]}

INPUT RULES
- `compositions` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced).
  An empty collection is valid.
- Every item must be exactly a `GameSceneComposition` (Prompt 729). `scene_id` values must be unique by exact comparison. Input order is preserved.
- Scene ids are NEVER normalized, trimmed, case-folded or coerced. "Arena", "arena" and "arena " are three different ids.
- Any `scene_id` the composition already carries is accepted as is: this module does NOT resolve it against a `GameScene`, `GameProject`, any
  character / asset / gameplay-system registry, or either validator. That is the job of the Prompt 730 validator.
- The supplied compositions (already immutable) and the supplied collection are only read, never changed or stored by reference.

FAILURES
`create_game_scene_composition_registry()` never raises for bad input. All problems are reported together in input order, using the stable codes
below: GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COLLECTION (top-level input is not exactly a list/tuple; nothing else is checked),
GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COMPOSITION (an item is not exactly a `GameSceneComposition`; never counted as a duplicate) and
GAME_SCENE_COMPOSITION_REGISTRY_DUPLICATE_SCENE_ID (an item repeats the `scene_id` of an earlier valid item; the first one is kept as the
reference). GAME_SCENE_COMPOSITION_REGISTRY_SCENE_NOT_FOUND is produced by `lookup()` only, never by the factory.

LOOKUP
`lookup(scene_id)` never raises and performs exact matching only. It returns a `GameSceneCompositionLookupResult` with `found=True` and the
composition, or `found=False`, `composition=None` and the SCENE_NOT_FOUND code (also for a `scene_id` that is not exactly a `str`).

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple; `compositions` and `scene_ids` return tuples. All three classes use `__slots__`, refuse assignment and deletion,
cannot be subclassed and cannot be constructed directly (TypeError). Equal contents mean equal objects and equal hashes (a different order is a
different registry). `failures`, `to_dict()` and `codes()` return FRESH plain data on every call. copy/deepcopy return the same object; pickling
is refused.

WHAT THIS MODULE DOES NOT DO
No scene, project, character, asset or gameplay-system relationships, no scene content, no filesystem, network, database, AI model or external
service, no clock or randomness, no module-level mutable state, no global registry. Its only import is the Prompt 729 record module. It is not
wired into `process_input()`, Core, the Planner, the Agent Loop or any runtime.
"""

from .game_scene_composition import GameSceneComposition

FAILURE_INVALID_COLLECTION = "GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_COMPOSITION = "GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COMPOSITION"
FAILURE_DUPLICATE_SCENE_ID = "GAME_SCENE_COMPOSITION_REGISTRY_DUPLICATE_SCENE_ID"
FAILURE_SCENE_NOT_FOUND = "GAME_SCENE_COMPOSITION_REGISTRY_SCENE_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_COMPOSITION, FAILURE_DUPLICATE_SCENE_ID, FAILURE_SCENE_NOT_FOUND)

_CREATE_TOKEN = object()


class GameSceneCompositionLookupResult:
    """Immutable outcome of `GameSceneCompositionRegistry.lookup()`: `composition` is set only when `found`; otherwise `code` is
    FAILURE_SCENE_NOT_FOUND. Obtain it only from `lookup()`."""

    __slots__ = ("_found", "_composition", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneCompositionLookupResult cannot be subclassed.")

    def __init__(self, _token, found, composition, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use GameSceneCompositionRegistry.lookup() to get a GameSceneCompositionLookupResult.")
        object.__setattr__(self, "_found", found)
        object.__setattr__(self, "_composition", composition)
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneCompositionLookupResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneCompositionLookupResult is immutable.")

    @property
    def found(self):
        return self._found

    @property
    def composition(self):
        return self._composition

    @property
    def code(self):
        return self._code

    def to_dict(self):
        """Fresh plain data. Mutating it never affects this result."""
        return {"found": self._found, "composition": self._composition.to_dict() if self._composition is not None else None,
                "code": self._code}

    def _key(self):
        return (self._found, self._composition, self._code)

    def __eq__(self, other):
        if type(other) is not GameSceneCompositionLookupResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneCompositionLookupResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneCompositionLookupResult(found=%r, code=%r)" % (self._found, self._code)


class GameSceneCompositionRegistry:
    """Immutable, ordered collection of `GameSceneComposition` objects with unique scene ids. Obtain it only from
    `create_game_scene_composition_registry()`."""

    __slots__ = ("_compositions",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneCompositionRegistry cannot be subclassed.")

    def __init__(self, _token, compositions):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_composition_registry() to build a GameSceneCompositionRegistry.")
        object.__setattr__(self, "_compositions", tuple(compositions))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneCompositionRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneCompositionRegistry is immutable.")

    @property
    def compositions(self):
        """Tuple of the registered `GameSceneComposition` objects, in input order."""
        return self._compositions

    @property
    def scene_ids(self):
        """Tuple of the registered scene ids, in input order."""
        return tuple(c.scene_id for c in self._compositions)

    def lookup(self, scene_id):
        """Find a composition by exact `scene_id`. Never raises; returns a `GameSceneCompositionLookupResult`."""
        if type(scene_id) is str:
            for composition in self._compositions:
                if composition.scene_id == scene_id:
                    return GameSceneCompositionLookupResult(_CREATE_TOKEN, True, composition, None)
        return GameSceneCompositionLookupResult(_CREATE_TOKEN, False, None, FAILURE_SCENE_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in input order. Mutating it never affects this registry."""
        return {"compositions": [c.to_dict() for c in self._compositions]}

    def __eq__(self, other):
        if type(other) is not GameSceneCompositionRegistry:
            return NotImplemented
        return self._compositions == other._compositions

    def __hash__(self):
        return hash(self._compositions)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneCompositionRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneCompositionRegistry(scene_ids=%r)" % (self.scene_ids,)


class GameSceneCompositionRegistryResult:
    """Immutable outcome of `create_game_scene_composition_registry()`: `registry` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_registry", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneCompositionRegistryResult cannot be subclassed.")

    def __init__(self, _token, registry, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_composition_registry() to get a GameSceneCompositionRegistryResult.")
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneCompositionRegistryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneCompositionRegistryResult is immutable.")

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
        if type(other) is not GameSceneCompositionRegistryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneCompositionRegistryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneCompositionRegistryResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_scene_composition_registry(compositions):
    """Check that `compositions` is exactly a list or tuple of `GameSceneComposition` objects with unique scene ids (exact comparison) and build
    an immutable `GameSceneCompositionRegistry` that keeps the input order. Nothing is resolved against any scene or registry. Deterministic,
    never raises for bad input, changes nothing it is given. Returns a `GameSceneCompositionRegistryResult`."""
    if type(compositions) not in (list, tuple):
        return GameSceneCompositionRegistryResult(_CREATE_TOKEN, None, [
            (FAILURE_INVALID_COLLECTION, "compositions", "compositions must be a list or a tuple of GameSceneComposition objects.")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(compositions):
        if type(item) is not GameSceneComposition:
            failures.append((FAILURE_INVALID_COMPOSITION, "compositions", "compositions[%d] must be a GameSceneComposition." % index))
        elif item.scene_id in seen:
            failures.append((FAILURE_DUPLICATE_SCENE_ID, "compositions",
                             "compositions[%d] duplicates an earlier scene_id: %r." % (index, item.scene_id)))
        else:
            seen.add(item.scene_id)
            valid.append(item)
    if failures:
        return GameSceneCompositionRegistryResult(_CREATE_TOKEN, None, failures)
    return GameSceneCompositionRegistryResult(_CREATE_TOKEN, GameSceneCompositionRegistry(_CREATE_TOKEN, valid), [])
