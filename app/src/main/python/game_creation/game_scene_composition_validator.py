"""
Game Scene Composition Validator (Prompt 730, Section 7 - Professional Game Creation)
=====================================================================================
A pure, deterministic check that one `GameSceneComposition` is structurally compatible with an existing `GameScene` and the existing
character, asset and gameplay-system registries.

    validate_game_scene_composition(composition, scene, character_registry, asset_registry, gameplay_system_registry)
        -> GameSceneCompositionValidationResult(ok, failures)
    GameSceneCompositionValidationResult.codes()   -> [code, ...]
    GameSceneCompositionValidationResult.to_dict() -> {"ok": bool, "failures": [{"code", "field", "message"}, ...]}

INPUT RULES (exact types - a subclass or look-alike is rejected, nothing is coerced)
- `composition` exactly a `GameSceneComposition`; `scene` exactly a `GameScene`; `character_registry` exactly a `GameCharacterRegistry`;
  `asset_registry` exactly a `GameAssetRegistry`; `gameplay_system_registry` exactly a `GameplaySystemRegistry`.
- Invalid top-level inputs produce deterministic failures and never raise.

CROSS-CHECKS
- `composition.scene_id` must exactly equal `scene.scene_id`.
- Every id in `composition.character_ids` must resolve through `character_registry.lookup()`; every id in `composition.asset_ids` through
  `asset_registry.lookup()`; every id in `composition.gameplay_system_ids` through `gameplay_system_registry.lookup()`. The validator uses those
  public lookup APIs only and never reads or duplicates registry internals or id lists.
- Comparison is exact: no normalization, trimming, coercion, case-folding or implicit id matching.
- Registry entries the composition does not reference are valid (unused entries are fine).
- A check runs only when every input it needs is valid, so one bad input never hides or invents other failures: the scene-id check needs
  `composition` and `scene`; each reference group needs `composition` and its registry.

FAILURES
All problems are reported together, never raised, using stable codes from `FAILURE_CODES` (prefix GAME_SCENE_COMPOSITION_VALIDATION_), in this
fixed order: 1. invalid top-level inputs, in argument order; 2. scene-id mismatch; 3. missing character references in composition order;
4. missing asset references in composition order; 5. missing gameplay-system references in composition order.

RESULT
`GameSceneCompositionValidationResult` is immutable (`__slots__`, read-only, stored as a tuple of tuples); `failures` and `to_dict()` return FRESH
plain data on every call. Equal failures mean equal results and equal hashes. Direct construction and subclassing are refused, copy/deepcopy
return the same object, pickling is refused. Nothing passed in is changed or stored.

WHAT THIS MODULE DOES NOT DO
It does not change `GameSceneComposition`, `GameScene` or any registry, adds no lookup behavior elsewhere, and creates no registry or persistent
object. No loading, rendering, audio, engine, gameplay execution, filesystem, network, database, AI or external service; no clock or randomness,
no module-level mutable state. Its only imports are the Section 7 record and registry modules. It is not wired into `process_input()`, Core, the
Planner, the Agent Loop, the runtime or any automation.
"""

from .game_asset_registry import GameAssetRegistry
from .game_character_registry import GameCharacterRegistry
from .game_scene import GameScene
from .game_scene_composition import GameSceneComposition
from .gameplay_system_registry import GameplaySystemRegistry

FAILURE_INVALID_COMPOSITION = "GAME_SCENE_COMPOSITION_VALIDATION_INVALID_COMPOSITION"
FAILURE_INVALID_SCENE = "GAME_SCENE_COMPOSITION_VALIDATION_INVALID_SCENE"
FAILURE_INVALID_CHARACTER_REGISTRY = "GAME_SCENE_COMPOSITION_VALIDATION_INVALID_CHARACTER_REGISTRY"
FAILURE_INVALID_ASSET_REGISTRY = "GAME_SCENE_COMPOSITION_VALIDATION_INVALID_ASSET_REGISTRY"
FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY = "GAME_SCENE_COMPOSITION_VALIDATION_INVALID_GAMEPLAY_SYSTEM_REGISTRY"
FAILURE_SCENE_ID_MISMATCH = "GAME_SCENE_COMPOSITION_VALIDATION_SCENE_ID_MISMATCH"
FAILURE_CHARACTER_NOT_FOUND = "GAME_SCENE_COMPOSITION_VALIDATION_CHARACTER_NOT_FOUND"
FAILURE_ASSET_NOT_FOUND = "GAME_SCENE_COMPOSITION_VALIDATION_ASSET_NOT_FOUND"
FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND = "GAME_SCENE_COMPOSITION_VALIDATION_GAMEPLAY_SYSTEM_NOT_FOUND"

FAILURE_CODES = (FAILURE_INVALID_COMPOSITION, FAILURE_INVALID_SCENE, FAILURE_INVALID_CHARACTER_REGISTRY, FAILURE_INVALID_ASSET_REGISTRY,
                 FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, FAILURE_SCENE_ID_MISMATCH, FAILURE_CHARACTER_NOT_FOUND, FAILURE_ASSET_NOT_FOUND,
                 FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND)

_CREATE_TOKEN = object()


class GameSceneCompositionValidationResult:
    """Immutable outcome of `validate_game_scene_composition()`. Obtain it only from that function."""

    __slots__ = ("_failures",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneCompositionValidationResult cannot be subclassed.")

    def __init__(self, _token, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_game_scene_composition() to get a GameSceneCompositionValidationResult.")
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneCompositionValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneCompositionValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "failures": self.failures}

    def __eq__(self, other):
        if type(other) is not GameSceneCompositionValidationResult:
            return NotImplemented
        return self._failures == other._failures

    def __hash__(self):
        return hash(self._failures)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneCompositionValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneCompositionValidationResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def validate_game_scene_composition(composition, scene, character_registry, asset_registry, gameplay_system_registry):
    """Check the exact types of the five inputs, that `composition.scene_id` equals `scene.scene_id`, and that every character, asset and
    gameplay-system id listed by `composition` resolves through the matching registry's `lookup()`. Pure and deterministic, never raises for
    bad input, changes and stores nothing it is given. Returns a `GameSceneCompositionValidationResult`."""
    failures = []
    inputs = ((composition, GameSceneComposition, FAILURE_INVALID_COMPOSITION, "composition", "GameSceneComposition"),
              (scene, GameScene, FAILURE_INVALID_SCENE, "scene", "GameScene"),
              (character_registry, GameCharacterRegistry, FAILURE_INVALID_CHARACTER_REGISTRY, "character_registry", "GameCharacterRegistry"),
              (asset_registry, GameAssetRegistry, FAILURE_INVALID_ASSET_REGISTRY, "asset_registry", "GameAssetRegistry"),
              (gameplay_system_registry, GameplaySystemRegistry, FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, "gameplay_system_registry",
               "GameplaySystemRegistry"))
    valid = {}
    for value, expected, code, name, label in inputs:
        if type(value) is expected:
            valid[name] = value
        else:
            failures.append((code, name, "%s must be exactly a %s." % (name, label)))
    if "composition" in valid:
        c = valid["composition"]
        if "scene" in valid and c.scene_id != valid["scene"].scene_id:
            failures.append((FAILURE_SCENE_ID_MISMATCH, "composition.scene_id",
                             "composition.scene_id %r does not equal scene.scene_id %r." % (c.scene_id, valid["scene"].scene_id)))
        groups = (("character_registry", "character_ids", c.character_ids, FAILURE_CHARACTER_NOT_FOUND, "character"),
                  ("asset_registry", "asset_ids", c.asset_ids, FAILURE_ASSET_NOT_FOUND, "asset"),
                  ("gameplay_system_registry", "gameplay_system_ids", c.gameplay_system_ids, FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND, "gameplay system"))
        for registry_name, collection, ids, code, label in groups:
            if registry_name not in valid:
                continue
            registry = valid[registry_name]
            for item in ids:
                if not registry.lookup(item).found:
                    failures.append((code, "composition." + collection,
                                     "composition.%s lists %r but no such %s is registered in %s." % (collection, item, label, registry_name)))
    return GameSceneCompositionValidationResult(_CREATE_TOKEN, failures)
