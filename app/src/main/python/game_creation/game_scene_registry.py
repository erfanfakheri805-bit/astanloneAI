"""
Game Scene Registry (Prompt 725, Section 7 - Professional Game Creation)
============================================================================
A small, immutable, in-memory collection of `GameScene` definitions with lookup by exact `scene_id`, optionally checked against the
scene identifiers listed by a `GameProjectStructure`:

    create_game_scene_registry(scenes, structure=None) -> GameSceneRegistryResult(ok, registry, failures)
    GameSceneRegistry.lookup(scene_id)                 -> GameSceneLookupResult(found, scene, code)
    GameSceneRegistry.to_dict()                            -> {"scenes": [GameScene.to_dict(), ...]}

INPUT RULES
- `scenes` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and
  an unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly a `GameScene` (Prompt 722). `scene_id` values must be unique (exact comparison). Input order is preserved.
- `structure` is `None` (no structure check) or exactly a `GameProjectStructure` (Prompt 721). When given, EVERY identifier in
  `structure.scenes` must have a registered scene; a registered scene that the structure does not list is allowed (unused
  definitions are fine). Neither the structure nor the scenes are changed.
- `create_game_scene_registry()` never raises for bad input: it reports every problem at once in a fixed order (collection problems by
  position, then the structure, then missing references in `structure.scenes` order), using stable codes from `FAILURE_CODES`. The reference
  check runs only when `structure` is valid, against the valid scenes found.
- Direct `GameSceneRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(scene_id)` never raises: it returns a `GameSceneLookupResult` with `found=True` and the `GameScene`, or `found=False`,
`scene=None` and code `FAILURE_SCENE_NOT_FOUND` (also for a `scene_id` that is not exactly a `str`). No trimming or case folding.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) scenes; `scenes` and `scene_ids` return tuples. `__slots__`, assignment /
deletion raises, not subclassable. Equal scenes in the same order mean equal registries and hashes (a different order is a different
registry); `to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy return the same object; pickling is refused.
The structure is used only for validation and is not stored.

WHAT THIS MODULE DOES NOT DO
No character, asset or gameplay-system relationships, no scene content (objects, maps, lighting, physics, AI, dialogue, animation, rendering, loading, ...), no filesystem, network, database, AI
model or external service, no clock or randomness, no module-level mutable state, no global registry. Its only imports are the two Section 7
record modules. It is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_scene import GameScene
from .game_project_structure import GameProjectStructure

FAILURE_INVALID_COLLECTION = "GAME_SCENE_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_SCENE = "GAME_SCENE_REGISTRY_INVALID_SCENE"
FAILURE_DUPLICATE_SCENE_ID = "GAME_SCENE_REGISTRY_DUPLICATE_SCENE_ID"
FAILURE_INVALID_STRUCTURE = "GAME_SCENE_REGISTRY_INVALID_STRUCTURE"
FAILURE_MISSING_SCENE_REFERENCE = "GAME_SCENE_REGISTRY_MISSING_SCENE_REFERENCE"
FAILURE_SCENE_NOT_FOUND = "GAME_SCENE_REGISTRY_SCENE_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_SCENE, FAILURE_DUPLICATE_SCENE_ID, FAILURE_INVALID_STRUCTURE,
                 FAILURE_MISSING_SCENE_REFERENCE, FAILURE_SCENE_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameSceneLookupResult:
    """Outcome of `GameSceneRegistry.lookup()`: `scene` is set only when `found`; otherwise `code` is FAILURE_SCENE_NOT_FOUND."""

    __slots__ = ("found", "scene", "code")

    def __init__(self, found, scene=None, code=None):
        self.found = found
        self.scene = scene
        self.code = code

    def to_dict(self):
        return {"found": self.found, "scene": self.scene.to_dict() if self.scene is not None else None, "code": self.code}


class GameSceneRegistry:
    """Immutable, ordered collection of `GameScene` objects with unique ids. Obtain it only from `create_game_scene_registry()`."""

    __slots__ = ("_scenes",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneRegistry cannot be subclassed.")

    def __init__(self, _token, scenes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_registry() to build a GameSceneRegistry.")
        object.__setattr__(self, "_scenes", tuple(scenes))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneRegistry is immutable.")

    @property
    def scenes(self):
        """Tuple of the registered `GameScene` objects, in registration order."""
        return self._scenes

    @property
    def scene_ids(self):
        """Tuple of the registered scene ids, in registration order."""
        return tuple(c.scene_id for c in self._scenes)

    def lookup(self, scene_id):
        """Find a scene by exact `scene_id`. Never raises; returns a `GameSceneLookupResult`."""
        if type(scene_id) is str:
            for scene in self._scenes:
                if scene.scene_id == scene_id:
                    return GameSceneLookupResult(True, scene)
        return GameSceneLookupResult(False, None, FAILURE_SCENE_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"scenes": [c.to_dict() for c in self._scenes]}

    def __eq__(self, other):
        if type(other) is not GameSceneRegistry:
            return NotImplemented
        return self._scenes == other._scenes

    def __hash__(self):
        return hash(self._scenes)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneRegistry(scene_ids=%r)" % (self.scene_ids,)


class GameSceneRegistryResult:
    """Outcome of `create_game_scene_registry()`: `registry` is set only when `ok`."""

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


def create_game_scene_registry(scenes, structure=None):
    """Validate `scenes` (a list or tuple of `GameScene`, unique ids) and, when given, `structure` (a `GameProjectStructure` whose
    scene ids must all be registered), then build an immutable `GameSceneRegistry`. Deterministic, never raises for bad input, changes
    nothing it is given. Returns a `GameSceneRegistryResult`."""
    failures = []
    valid = []
    if type(scenes) not in (list, tuple):
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "scenes must be a list or a tuple of GameScene objects.", "scenes"))
    else:
        seen = set()
        for index, item in enumerate(scenes):
            if type(item) is not GameScene:
                failures.append(_failure(FAILURE_INVALID_SCENE, "scenes[%d] must be a GameScene." % index, "scenes"))
            elif item.scene_id in seen:
                failures.append(_failure(FAILURE_DUPLICATE_SCENE_ID,
                                         "scenes[%d] duplicates an earlier scene_id: %r." % (index, item.scene_id), "scenes"))
            else:
                seen.add(item.scene_id)
                valid.append(item)
    if structure is not None:
        if type(structure) is not GameProjectStructure:
            failures.append(_failure(FAILURE_INVALID_STRUCTURE, "structure must be None or a GameProjectStructure.", "structure"))
        else:
            known = set(c.scene_id for c in valid)
            for scene_id in structure.scenes:
                if scene_id not in known:
                    failures.append(_failure(FAILURE_MISSING_SCENE_REFERENCE,
                                             "structure.scenes lists %r but no such scene is registered." % scene_id, "structure"))
    if failures:
        return GameSceneRegistryResult(failures=failures)
    return GameSceneRegistryResult(registry=GameSceneRegistry(_CREATE_TOKEN, valid))
