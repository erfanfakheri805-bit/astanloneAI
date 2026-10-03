"""
Game Project Validator (Prompt 728, Section 7 - Professional Game Creation)
===========================================================================
A pure, deterministic check that one game-project definition is internally consistent: the project record, its `GameProjectStructure` and the
four registries built in Prompts 724-727 must agree.

    validate_game_project(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry)
        -> GameProjectValidationResult(ok, failures)
    GameProjectValidationResult.to_dict() -> {"ok": bool, "failures": [{"code", "field", "message"}, ...]}

INPUT RULES (exact types - a subclass or look-alike is rejected, nothing is coerced)
- `project` exactly a `GameProject`; `structure` exactly a `GameProjectStructure`; `scene_registry` exactly a `GameSceneRegistry`;
  `character_registry` exactly a `GameCharacterRegistry`; `gameplay_system_registry` exactly a `GameplaySystemRegistry`; `asset_registry`
  exactly a `GameAssetRegistry`.

CROSS-CHECKS
- Every id in `structure.scenes` must be a `scene_id` in `scene_registry`; every id in `structure.characters` a `character_id` in
  `character_registry`; every id in `structure.gameplay_systems` a registered gameplay-system id; every id in `structure.assets` an `asset_id` in
  `asset_registry`. Comparison is exact. A registry entry the structure does not list is allowed (unused entries are fine).
- A reference group is checked only when the structure AND its registry are both valid, so one bad input never hides or invents other failures.

PROJECT IDENTITY (deferred)
`GameProjectStructure` has no project-id field (its only fields are scenes, characters, gameplay_systems, assets), and it was intentionally not
changed. A project-id cross-check is therefore NOT performed: `project` is validated for its exact type only. Such a check can be added in a later
prompt if the structure ever carries an identity.

FAILURES
All problems are reported together, never raised, using stable codes from `FAILURE_CODES` (prefix GAME_PROJECT_VALIDATION_), in this fixed order:
1. invalid top-level inputs, in argument order; 2. scene references; 3. character references; 4. gameplay-system references; 5. asset
references - each group in the order of the matching `structure` collection.

RESULT
`GameProjectValidationResult` is immutable (`__slots__`, read-only, stored as a tuple of tuples); `failures` and `to_dict()` return FRESH plain data on
every call. Equal failures mean equal results and equal hashes. Direct construction and subclassing are refused, copy/deepcopy return the same
object, pickling is refused. Nothing passed in is changed or stored.

WHAT THIS MODULE DOES NOT DO
No registry or persistent object is created; no loading, rendering, engine, gameplay execution, filesystem, network, database, AI or external
service; no clock or randomness, no module-level mutable state. Its only imports are the Section 7 record and registry modules. It is not wired
into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_asset_registry import GameAssetRegistry
from .game_character_registry import GameCharacterRegistry
from .game_project import GameProject
from .game_project_structure import GameProjectStructure
from .game_scene_registry import GameSceneRegistry
from .gameplay_system_registry import GameplaySystemRegistry

FAILURE_INVALID_PROJECT = "GAME_PROJECT_VALIDATION_INVALID_PROJECT"
FAILURE_INVALID_STRUCTURE = "GAME_PROJECT_VALIDATION_INVALID_STRUCTURE"
FAILURE_INVALID_SCENE_REGISTRY = "GAME_PROJECT_VALIDATION_INVALID_SCENE_REGISTRY"
FAILURE_INVALID_CHARACTER_REGISTRY = "GAME_PROJECT_VALIDATION_INVALID_CHARACTER_REGISTRY"
FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY = "GAME_PROJECT_VALIDATION_INVALID_GAMEPLAY_SYSTEM_REGISTRY"
FAILURE_INVALID_ASSET_REGISTRY = "GAME_PROJECT_VALIDATION_INVALID_ASSET_REGISTRY"
FAILURE_MISSING_SCENE_REFERENCE = "GAME_PROJECT_VALIDATION_MISSING_SCENE_REFERENCE"
FAILURE_MISSING_CHARACTER_REFERENCE = "GAME_PROJECT_VALIDATION_MISSING_CHARACTER_REFERENCE"
FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE = "GAME_PROJECT_VALIDATION_MISSING_GAMEPLAY_SYSTEM_REFERENCE"
FAILURE_MISSING_ASSET_REFERENCE = "GAME_PROJECT_VALIDATION_MISSING_ASSET_REFERENCE"

FAILURE_CODES = (FAILURE_INVALID_PROJECT, FAILURE_INVALID_STRUCTURE, FAILURE_INVALID_SCENE_REGISTRY, FAILURE_INVALID_CHARACTER_REGISTRY,
                 FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, FAILURE_INVALID_ASSET_REGISTRY, FAILURE_MISSING_SCENE_REFERENCE,
                 FAILURE_MISSING_CHARACTER_REFERENCE, FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE, FAILURE_MISSING_ASSET_REFERENCE)

_CREATE_TOKEN = object()


class GameProjectValidationResult:
    """Immutable outcome of `validate_game_project()`. Obtain it only from that function."""

    __slots__ = ("_failures",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameProjectValidationResult cannot be subclassed.")

    def __init__(self, _token, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_game_project() to get a GameProjectValidationResult.")
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameProjectValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameProjectValidationResult is immutable.")

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
        if type(other) is not GameProjectValidationResult:
            return NotImplemented
        return self._failures == other._failures

    def __hash__(self):
        return hash(self._failures)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameProjectValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameProjectValidationResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def validate_game_project(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry):
    """Check the exact types of the six inputs and that every scene, character, gameplay-system and asset id listed by `structure` is present in
    the matching registry. Pure and deterministic, never raises for bad input, changes and stores nothing it is given. Returns a
    `GameProjectValidationResult`."""
    failures = []
    inputs = ((project, GameProject, FAILURE_INVALID_PROJECT, "project", "GameProject"),
              (structure, GameProjectStructure, FAILURE_INVALID_STRUCTURE, "structure", "GameProjectStructure"),
              (scene_registry, GameSceneRegistry, FAILURE_INVALID_SCENE_REGISTRY, "scene_registry", "GameSceneRegistry"),
              (character_registry, GameCharacterRegistry, FAILURE_INVALID_CHARACTER_REGISTRY, "character_registry", "GameCharacterRegistry"),
              (gameplay_system_registry, GameplaySystemRegistry, FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, "gameplay_system_registry",
               "GameplaySystemRegistry"),
              (asset_registry, GameAssetRegistry, FAILURE_INVALID_ASSET_REGISTRY, "asset_registry", "GameAssetRegistry"))
    valid = {}
    for value, expected, code, name, label in inputs:
        if type(value) is expected:
            valid[name] = value
        else:
            failures.append((code, name, "%s must be exactly a %s." % (name, label)))
    if "structure" in valid:
        s = valid["structure"]
        groups = (("scene_registry", "scenes", s.scenes, lambda r: r.scene_ids, FAILURE_MISSING_SCENE_REFERENCE, "scene"),
                  ("character_registry", "characters", s.characters, lambda r: r.character_ids, FAILURE_MISSING_CHARACTER_REFERENCE, "character"),
                  ("gameplay_system_registry", "gameplay_systems", s.gameplay_systems, lambda r: r.gameplay_system_ids,
                   FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE, "gameplay system"),
                  ("asset_registry", "assets", s.assets, lambda r: r.asset_ids, FAILURE_MISSING_ASSET_REFERENCE, "asset"))
        for registry_name, collection, ids, registered_ids, code, label in groups:
            if registry_name not in valid:
                continue
            known = set(registered_ids(valid[registry_name]))
            for item in ids:
                if item not in known:
                    failures.append((code, "structure." + collection,
                                     "structure.%s lists %r but no such %s is registered in %s." % (collection, item, label, registry_name)))
    return GameProjectValidationResult(_CREATE_TOKEN, failures)
