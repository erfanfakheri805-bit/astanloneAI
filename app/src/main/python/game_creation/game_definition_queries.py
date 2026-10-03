"""
Game Definition Queries (Prompt 735, Section 7 - Professional Game Creation)
============================================================================
A tiny read-only query layer over one `GameDefinition` (Prompt 734): resolve a scene, or the bundle of a scene, by exact `scene_id` through
ONE public API, without touching or repeating registry internals.

    lookup_game_scene(game_definition, scene_id)        -> GameSceneQueryResult(found, scene, code)
    lookup_game_scene_bundle(game_definition, scene_id) -> GameSceneBundleQueryResult(found, bundle, code)
    <result>.to_dict() -> {"found", "scene" | "bundle" (that object's own to_dict() or None), "code"}

RULES
1. `game_definition` must be exactly a `GameDefinition` (no subclass or look-alike).
2. `scene_id` must be exactly a `str` (a `str` subclass is not accepted).
3. Matching is exact: no trimming, case-folding, normalization or coercion.
4. The scene query delegates to `game_definition.scene_registry.lookup(scene_id)`; the bundle query delegates to
   `game_definition.bundle_registry.lookup(scene_id)`. Nothing else is read from a registry: no private attribute, no id list, no scanning,
   no second implementation of lookup.
5. The object the registry returns is preserved BY IDENTITY in the result. It is not validated, copied or changed.
6. Nothing supplied (the definition or its registries) is mutated.

CODES (stable, prefix GAME_DEFINITION_QUERY_)
INVALID_GAME_DEFINITION (checked first), INVALID_SCENE_ID, SCENE_NOT_FOUND (scene query miss), BUNDLE_NOT_FOUND (bundle query miss).
On any failure `found` is False and the scene/bundle is None; on success `code` is None. Invalid arguments never raise.

IMMUTABLE AND DETERMINISTIC
Both result types use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed directly (TypeError). Equal
fields mean equal results and equal hashes. `to_dict()` returns FRESH plain data on every call. copy/deepcopy return the same object; pickling
is refused.

WHAT THIS MODULE DOES NOT DO
No validators, no composition lookup, no new registry, no runtime, rendering, audio, asset loading, execution, filesystem, code generation or
build/export behavior. Its only import is the Prompt 734 `GameDefinition`. It is not wired into `process_input()`, Core, the Planner or the
Agent Loop.
"""

from .game_definition import GameDefinition

FAILURE_INVALID_GAME_DEFINITION = "GAME_DEFINITION_QUERY_INVALID_GAME_DEFINITION"
FAILURE_INVALID_SCENE_ID = "GAME_DEFINITION_QUERY_INVALID_SCENE_ID"
FAILURE_SCENE_NOT_FOUND = "GAME_DEFINITION_QUERY_SCENE_NOT_FOUND"
FAILURE_BUNDLE_NOT_FOUND = "GAME_DEFINITION_QUERY_BUNDLE_NOT_FOUND"

FAILURE_CODES = (FAILURE_INVALID_GAME_DEFINITION, FAILURE_INVALID_SCENE_ID, FAILURE_SCENE_NOT_FOUND, FAILURE_BUNDLE_NOT_FOUND)

_CREATE_TOKEN = object()


class GameSceneQueryResult:
    """Immutable outcome of `lookup_game_scene()`: `scene` is set only when `found`. Obtain it only from that function."""

    __slots__ = ("_found", "_scene", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneQueryResult cannot be subclassed.")

    def __init__(self, _token, found, scene, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use lookup_game_scene() to get a GameSceneQueryResult.")
        object.__setattr__(self, "_found", found)
        object.__setattr__(self, "_scene", scene)
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneQueryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneQueryResult is immutable.")

    @property
    def found(self):
        return self._found

    @property
    def scene(self):
        return self._scene

    @property
    def code(self):
        return self._code

    def to_dict(self):
        """Fresh plain data. Mutating it never affects this result."""
        return {"found": self._found, "scene": self._scene.to_dict() if self._scene is not None else None, "code": self._code}

    def _key(self):
        return (self._found, self._scene, self._code)

    def __eq__(self, other):
        if type(other) is not GameSceneQueryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneQueryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneQueryResult(found=%r, code=%r)" % (self._found, self._code)


class GameSceneBundleQueryResult:
    """Immutable outcome of `lookup_game_scene_bundle()`: `bundle` is set only when `found`. Obtain it only from that function."""

    __slots__ = ("_found", "_bundle", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundleQueryResult cannot be subclassed.")

    def __init__(self, _token, found, bundle, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use lookup_game_scene_bundle() to get a GameSceneBundleQueryResult.")
        object.__setattr__(self, "_found", found)
        object.__setattr__(self, "_bundle", bundle)
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundleQueryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundleQueryResult is immutable.")

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
        if type(other) is not GameSceneBundleQueryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundleQueryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundleQueryResult(found=%r, code=%r)" % (self._found, self._code)


def lookup_game_scene(game_definition, scene_id):
    """Find a scene by exact `scene_id` through `game_definition.scene_registry.lookup()`. Never raises; returns a `GameSceneQueryResult`
    that holds the registry's own scene object."""
    if type(game_definition) is not GameDefinition:
        return GameSceneQueryResult(_CREATE_TOKEN, False, None, FAILURE_INVALID_GAME_DEFINITION)
    if type(scene_id) is not str:
        return GameSceneQueryResult(_CREATE_TOKEN, False, None, FAILURE_INVALID_SCENE_ID)
    looked_up = game_definition.scene_registry.lookup(scene_id)
    if not looked_up.found:
        return GameSceneQueryResult(_CREATE_TOKEN, False, None, FAILURE_SCENE_NOT_FOUND)
    return GameSceneQueryResult(_CREATE_TOKEN, True, looked_up.scene, None)


def lookup_game_scene_bundle(game_definition, scene_id):
    """Find a bundle by exact `scene_id` through `game_definition.bundle_registry.lookup()`. Never raises; returns a
    `GameSceneBundleQueryResult` that holds the registry's own bundle object."""
    if type(game_definition) is not GameDefinition:
        return GameSceneBundleQueryResult(_CREATE_TOKEN, False, None, FAILURE_INVALID_GAME_DEFINITION)
    if type(scene_id) is not str:
        return GameSceneBundleQueryResult(_CREATE_TOKEN, False, None, FAILURE_INVALID_SCENE_ID)
    looked_up = game_definition.bundle_registry.lookup(scene_id)
    if not looked_up.found:
        return GameSceneBundleQueryResult(_CREATE_TOKEN, False, None, FAILURE_BUNDLE_NOT_FOUND)
    return GameSceneBundleQueryResult(_CREATE_TOKEN, True, looked_up.bundle, None)
