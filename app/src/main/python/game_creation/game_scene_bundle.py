"""
Game Scene Bundle (Prompt 732, Section 7 - Professional Game Creation)
======================================================================
A small, immutable, in-memory pairing of ONE `GameScene` (Prompt 722) with the `GameSceneComposition` (Prompt 729) that describes it. The only
thing it checks is that the two belong together: their `scene_id` values must be exactly equal.

    create_game_scene_bundle(scene, composition) -> GameSceneBundleResult(ok, bundle, failures)
    GameSceneBundleResult.codes()                -> [code, ...]
    GameSceneBundleResult.to_dict()              -> {"ok", "bundle", "failures"}
    GameSceneBundle.scene                        -> the supplied GameScene (same object)
    GameSceneBundle.composition                  -> the supplied GameSceneComposition (same object)
    GameSceneBundle.scene_id                     -> str, derived from the scene
    GameSceneBundle.to_dict()                    -> {"scene_id", "scene": GameScene.to_dict(), "composition": GameSceneComposition.to_dict()}

RULES (exact types - a subclass or look-alike is rejected, nothing is coerced)
1. `scene` must be exactly a `GameScene`.
2. `composition` must be exactly a `GameSceneComposition`.
3. `scene.scene_id` must exactly equal `composition.scene_id`. Matching is exact: no trimming, case folding, normalization or coercion.
4. `scene_id` is derived from the scene and exposed read-only as a `str`; it is not an independent input.
5. The original objects are stored as they are (same identity): never copied, rebuilt or changed. Both are already immutable.
6. Nothing else is checked. No registry lookup is performed, and characters, assets, gameplay systems and other project references are NOT
   resolved - a composition with arbitrary character / asset / gameplay-system ids is accepted. Resolving them belongs to the Prompt 730 validator.

FAILURES
`create_game_scene_bundle()` never raises for bad input. Problems are reported together in this fixed order, using stable codes prefixed
GAME_SCENE_BUNDLE_: 1. INVALID_SCENE; 2. INVALID_COMPOSITION; 3. SCENE_ID_MISMATCH. The id comparison runs only when BOTH objects are valid,
so one bad input never hides or invents the mismatch failure.

IMMUTABLE AND DETERMINISTIC
`GameSceneBundle` and `GameSceneBundleResult` use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed
directly (TypeError). Equal scene and composition mean equal bundles and hashes; equal failures and bundles mean equal results and hashes.
`to_dict()`, `failures` and `codes()` return FRESH plain data on every call; the nested scene and composition data are fresh copies too, so
nothing returned ever aliases the bundle. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
No registry, project, project validator or composition validator is imported or used; no scene loading, rendering, audio, execution or
engine; no filesystem, network, database, AI model or external service; no clock or randomness, no module-level mutable state. Its only imports
are the Prompt 722 and Prompt 729 record modules. It is not wired into `process_input()`, Core, the Planner, the Agent Loop or any runtime.
"""

from .game_scene import GameScene
from .game_scene_composition import GameSceneComposition

FAILURE_INVALID_SCENE = "GAME_SCENE_BUNDLE_INVALID_SCENE"
FAILURE_INVALID_COMPOSITION = "GAME_SCENE_BUNDLE_INVALID_COMPOSITION"
FAILURE_SCENE_ID_MISMATCH = "GAME_SCENE_BUNDLE_SCENE_ID_MISMATCH"

FAILURE_CODES = (FAILURE_INVALID_SCENE, FAILURE_INVALID_COMPOSITION, FAILURE_SCENE_ID_MISMATCH)

_CREATE_TOKEN = object()


class GameSceneBundle:
    """Immutable pairing of one `GameScene` with its matching `GameSceneComposition`. Obtain it only from `create_game_scene_bundle()`."""

    __slots__ = ("_scene", "_composition")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundle cannot be subclassed.")

    def __init__(self, _token, scene, composition):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_bundle() to build a GameSceneBundle.")
        object.__setattr__(self, "_scene", scene)
        object.__setattr__(self, "_composition", composition)

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundle is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundle is immutable.")

    @property
    def scene(self):
        """The supplied `GameScene`, by identity."""
        return self._scene

    @property
    def composition(self):
        """The supplied `GameSceneComposition`, by identity."""
        return self._composition

    @property
    def scene_id(self):
        """The scene id, derived from the scene (it equals the composition's by construction)."""
        return self._scene.scene_id

    def to_dict(self):
        """Fresh plain data with fresh nested scene and composition data. Mutating it never affects this bundle."""
        return {"scene_id": self._scene.scene_id, "scene": self._scene.to_dict(), "composition": self._composition.to_dict()}

    def _key(self):
        return (self._scene, self._composition)

    def __eq__(self, other):
        if type(other) is not GameSceneBundle:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundle is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundle(scene_id=%r)" % (self._scene.scene_id,)


class GameSceneBundleResult:
    """Immutable outcome of `create_game_scene_bundle()`: `bundle` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_bundle", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneBundleResult cannot be subclassed.")

    def __init__(self, _token, bundle, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_bundle() to get a GameSceneBundleResult.")
        object.__setattr__(self, "_bundle", bundle)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneBundleResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneBundleResult is immutable.")

    @property
    def ok(self):
        return self._bundle is not None and not self._failures

    @property
    def bundle(self):
        return self._bundle

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "bundle": self._bundle.to_dict() if self._bundle is not None else None, "failures": self.failures}

    def _key(self):
        return (self._bundle, self._failures)

    def __eq__(self, other):
        if type(other) is not GameSceneBundleResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneBundleResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneBundleResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_scene_bundle(scene, composition):
    """Check that `scene` is exactly a `GameScene`, `composition` is exactly a `GameSceneComposition` and their scene ids are exactly equal,
    then pair the two original objects in an immutable `GameSceneBundle`. No registry lookup and no reference resolution. Deterministic,
    never raises for bad input, changes nothing it is given. Returns a `GameSceneBundleResult`."""
    failures = []
    scene_ok = type(scene) is GameScene
    composition_ok = type(composition) is GameSceneComposition
    if not scene_ok:
        failures.append((FAILURE_INVALID_SCENE, "scene", "scene must be exactly a GameScene."))
    if not composition_ok:
        failures.append((FAILURE_INVALID_COMPOSITION, "composition", "composition must be exactly a GameSceneComposition."))
    if scene_ok and composition_ok and scene.scene_id != composition.scene_id:
        failures.append((FAILURE_SCENE_ID_MISMATCH, "composition.scene_id",
                         "composition.scene_id %r does not equal scene.scene_id %r." % (composition.scene_id, scene.scene_id)))
    if failures:
        return GameSceneBundleResult(_CREATE_TOKEN, None, failures)
    return GameSceneBundleResult(_CREATE_TOKEN, GameSceneBundle(_CREATE_TOKEN, scene, composition), [])
