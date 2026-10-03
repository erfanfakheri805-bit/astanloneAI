"""
Game Definition (Prompt 734, Section 7 - Professional Game Creation)
====================================================================
A small, immutable, in-memory GROUPING of the eight validated Section 7 foundation objects that describe one game project, plus a thin
orchestration layer that checks they agree with each other by calling the EXISTING public validators. It adds no runtime behavior.

    create_game_definition(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry,
                           composition_registry, bundle_registry) -> GameDefinitionResult(ok, definition, failures)
    GameDefinitionResult.codes()   -> [code, ...]
    GameDefinitionResult.to_dict() -> {"ok", "definition", "failures"}
    GameDefinition.project / structure / scene_registry / character_registry / gameplay_system_registry / asset_registry /
        composition_registry / bundle_registry -> the supplied objects, by identity
    GameDefinition.to_dict()       -> one key per attribute, each the object's own public to_dict()

INPUT RULES (exact types - a subclass or look-alike is rejected, nothing is coerced)
GameProject, GameProjectStructure, GameSceneRegistry, GameCharacterRegistry, GameplaySystemRegistry, GameAssetRegistry,
GameSceneCompositionRegistry, GameSceneBundleRegistry - checked in exactly that argument order.

CROSS-CHECKS (only when ALL eight arguments are valid; if any argument is invalid no cross-object validation is performed at all)
a. `validate_game_project(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry)` (Prompt 728).
b. For every composition in `composition_registry.compositions` (registry order): its scene is found with `scene_registry.lookup()`; then
   `validate_game_scene_composition(composition, scene, character_registry, asset_registry, gameplay_system_registry)` (Prompt 730).
   A composition whose scene is missing is reported and NOT passed to the validator (there is no scene to pass).
c. For every bundle in `bundle_registry.bundles` (registry order): `bundle.scene_id` must resolve in `scene_registry`; the bundle's composition
   `scene_id` must resolve in `composition_registry`; and the bundle's own scene and composition must EQUAL the registered ones.
   The validators' logic is reused, never reimplemented; registries are read only through their public properties and `lookup()`.
Registry entries nobody references are allowed, exactly as in the delegated validators. Empty registries are valid. Ids are compared exactly.

FAILURES
`create_game_definition()` never raises. Stable codes (prefix GAME_DEFINITION_), reported together in this order:
1. INVALID_PROJECT, INVALID_STRUCTURE, INVALID_SCENE_REGISTRY, INVALID_CHARACTER_REGISTRY, INVALID_GAMEPLAY_SYSTEM_REGISTRY,
   INVALID_ASSET_REGISTRY, INVALID_COMPOSITION_REGISTRY, INVALID_BUNDLE_REGISTRY (argument order);
2. INVALID_PROJECT_STRUCTURE - one per failure of the Prompt 728 validator, in its order;
3. INVALID_SCENE_COMPOSITION - composition-registry order; its own missing-scene failure first, then one per Prompt 730 failure;
4. INVALID_SCENE_BUNDLE - bundle-registry order: missing scene, missing composition, scene mismatch, composition mismatch.
Every failure is {"code", "field", "message", "source"}. For a delegated failure `source` is the underlying validator's
{"code", "field", "message"} unchanged (no new code is invented per nested failure); for our own failures `source` is None.

IMMUTABLE AND DETERMINISTIC
`GameDefinition` and `GameDefinitionResult` use `__slots__`, refuse assignment and deletion, cannot be subclassed or constructed directly
(TypeError). Equal objects mean equal definitions/results and hashes. `to_dict()`, `failures` and `codes()` return FRESH plain data; nothing
returned aliases internal state. copy/deepcopy return the same object; pickling is refused. Nothing supplied is changed.

WHAT THIS MODULE DOES NOT DO
No runtime, rendering, audio, asset loading, engine behavior, filesystem project generation, code generation or build/export; no filesystem,
network, database, AI model or external service; no clock, randomness or module-level mutable state. It changes no model, registry or
validator and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_asset_registry import GameAssetRegistry
from .game_character_registry import GameCharacterRegistry
from .game_project import GameProject
from .game_project_structure import GameProjectStructure
from .game_project_validator import validate_game_project
from .game_scene_bundle_registry import GameSceneBundleRegistry
from .game_scene_composition_registry import GameSceneCompositionRegistry
from .game_scene_composition_validator import validate_game_scene_composition
from .game_scene_registry import GameSceneRegistry
from .gameplay_system_registry import GameplaySystemRegistry

FAILURE_INVALID_PROJECT = "GAME_DEFINITION_INVALID_PROJECT"
FAILURE_INVALID_STRUCTURE = "GAME_DEFINITION_INVALID_STRUCTURE"
FAILURE_INVALID_SCENE_REGISTRY = "GAME_DEFINITION_INVALID_SCENE_REGISTRY"
FAILURE_INVALID_CHARACTER_REGISTRY = "GAME_DEFINITION_INVALID_CHARACTER_REGISTRY"
FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY = "GAME_DEFINITION_INVALID_GAMEPLAY_SYSTEM_REGISTRY"
FAILURE_INVALID_ASSET_REGISTRY = "GAME_DEFINITION_INVALID_ASSET_REGISTRY"
FAILURE_INVALID_COMPOSITION_REGISTRY = "GAME_DEFINITION_INVALID_COMPOSITION_REGISTRY"
FAILURE_INVALID_BUNDLE_REGISTRY = "GAME_DEFINITION_INVALID_BUNDLE_REGISTRY"
FAILURE_INVALID_PROJECT_STRUCTURE = "GAME_DEFINITION_INVALID_PROJECT_STRUCTURE"
FAILURE_INVALID_SCENE_COMPOSITION = "GAME_DEFINITION_INVALID_SCENE_COMPOSITION"
FAILURE_INVALID_SCENE_BUNDLE = "GAME_DEFINITION_INVALID_SCENE_BUNDLE"

FAILURE_CODES = (FAILURE_INVALID_PROJECT, FAILURE_INVALID_STRUCTURE, FAILURE_INVALID_SCENE_REGISTRY, FAILURE_INVALID_CHARACTER_REGISTRY,
                 FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, FAILURE_INVALID_ASSET_REGISTRY, FAILURE_INVALID_COMPOSITION_REGISTRY,
                 FAILURE_INVALID_BUNDLE_REGISTRY, FAILURE_INVALID_PROJECT_STRUCTURE, FAILURE_INVALID_SCENE_COMPOSITION,
                 FAILURE_INVALID_SCENE_BUNDLE)

_CREATE_TOKEN = object()


def _source_dict(source):
    return None if source is None else {"code": source[0], "field": source[1], "message": source[2]}


class GameDefinition:
    """Immutable grouping of the eight validated Section 7 objects. Obtain it only from `create_game_definition()`."""

    __slots__ = ("_project", "_structure", "_scene_registry", "_character_registry", "_gameplay_system_registry", "_asset_registry",
                 "_composition_registry", "_bundle_registry")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameDefinition cannot be subclassed.")

    def __init__(self, _token, project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry,
                 composition_registry, bundle_registry):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_definition() to build a GameDefinition.")
        object.__setattr__(self, "_project", project)
        object.__setattr__(self, "_structure", structure)
        object.__setattr__(self, "_scene_registry", scene_registry)
        object.__setattr__(self, "_character_registry", character_registry)
        object.__setattr__(self, "_gameplay_system_registry", gameplay_system_registry)
        object.__setattr__(self, "_asset_registry", asset_registry)
        object.__setattr__(self, "_composition_registry", composition_registry)
        object.__setattr__(self, "_bundle_registry", bundle_registry)

    def __setattr__(self, key, value):
        raise AttributeError("GameDefinition is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameDefinition is immutable.")

    @property
    def project(self):
        return self._project

    @property
    def structure(self):
        return self._structure

    @property
    def scene_registry(self):
        return self._scene_registry

    @property
    def character_registry(self):
        return self._character_registry

    @property
    def gameplay_system_registry(self):
        return self._gameplay_system_registry

    @property
    def asset_registry(self):
        return self._asset_registry

    @property
    def composition_registry(self):
        return self._composition_registry

    @property
    def bundle_registry(self):
        return self._bundle_registry

    def to_dict(self):
        """Fresh plain data built from each contained object's public `to_dict()`. Mutating it never affects this definition."""
        return {"project": self._project.to_dict(), "structure": self._structure.to_dict(), "scene_registry": self._scene_registry.to_dict(),
                "character_registry": self._character_registry.to_dict(),
                "gameplay_system_registry": self._gameplay_system_registry.to_dict(),
                "asset_registry": self._asset_registry.to_dict(), "composition_registry": self._composition_registry.to_dict(),
                "bundle_registry": self._bundle_registry.to_dict()}

    def _key(self):
        return (self._project, self._structure, self._scene_registry, self._character_registry, self._gameplay_system_registry,
                self._asset_registry, self._composition_registry, self._bundle_registry)

    def __eq__(self, other):
        if type(other) is not GameDefinition:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameDefinition is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameDefinition(project=%r)" % (self._project,)


class GameDefinitionResult:
    """Immutable outcome of `create_game_definition()`: `definition` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_definition", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameDefinitionResult cannot be subclassed.")

    def __init__(self, _token, definition, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_definition() to get a GameDefinitionResult.")
        object.__setattr__(self, "_definition", definition)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameDefinitionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameDefinitionResult is immutable.")

    @property
    def ok(self):
        return self._definition is not None and not self._failures

    @property
    def definition(self):
        return self._definition

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message", "source"}` dicts (`source` is None or a fresh dict). Mutating it never
        affects this result."""
        return [{"code": c, "field": f, "message": m, "source": _source_dict(s)} for c, f, m, s in self._failures]

    def codes(self):
        return [c for c, _f, _m, _s in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "definition": self._definition.to_dict() if self._definition is not None else None, "failures": self.failures}

    def _key(self):
        return (self._definition, self._failures)

    def __eq__(self, other):
        if type(other) is not GameDefinitionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameDefinitionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameDefinitionResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def _wrap(validation_result):
    return [(f["code"], f["field"], f["message"]) for f in validation_result.failures]


def create_game_definition(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry,
                           composition_registry, bundle_registry):
    """Check the exact types of the eight arguments (in argument order); if all are valid, cross-check them with the existing Prompt 728 and
    Prompt 730 validators and the public registry lookups, then group the original objects in an immutable `GameDefinition`. Deterministic,
    never raises for bad input, changes nothing it is given. Returns a `GameDefinitionResult`."""
    inputs = ((project, GameProject, FAILURE_INVALID_PROJECT, "project", "GameProject"),
              (structure, GameProjectStructure, FAILURE_INVALID_STRUCTURE, "structure", "GameProjectStructure"),
              (scene_registry, GameSceneRegistry, FAILURE_INVALID_SCENE_REGISTRY, "scene_registry", "GameSceneRegistry"),
              (character_registry, GameCharacterRegistry, FAILURE_INVALID_CHARACTER_REGISTRY, "character_registry", "GameCharacterRegistry"),
              (gameplay_system_registry, GameplaySystemRegistry, FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, "gameplay_system_registry",
               "GameplaySystemRegistry"),
              (asset_registry, GameAssetRegistry, FAILURE_INVALID_ASSET_REGISTRY, "asset_registry", "GameAssetRegistry"),
              (composition_registry, GameSceneCompositionRegistry, FAILURE_INVALID_COMPOSITION_REGISTRY, "composition_registry",
               "GameSceneCompositionRegistry"),
              (bundle_registry, GameSceneBundleRegistry, FAILURE_INVALID_BUNDLE_REGISTRY, "bundle_registry", "GameSceneBundleRegistry"))
    failures = []
    for value, expected, code, name, label in inputs:
        if type(value) is not expected:
            failures.append((code, name, "%s must be exactly a %s." % (name, label), None))
    if failures:
        return GameDefinitionResult(_CREATE_TOKEN, None, failures)

    for source in _wrap(validate_game_project(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry)):
        failures.append((FAILURE_INVALID_PROJECT_STRUCTURE, "structure", "project structure failed validation: " + source[2], source))

    for index, composition in enumerate(composition_registry.compositions):
        field = "composition_registry.compositions[%d]" % index
        found = scene_registry.lookup(composition.scene_id)
        if not found.found:
            failures.append((FAILURE_INVALID_SCENE_COMPOSITION, field + ".scene_id",
                             "%s.scene_id %r is not registered in scene_registry." % (field, composition.scene_id), None))
            continue
        for source in _wrap(validate_game_scene_composition(composition, found.scene, character_registry, asset_registry,
                                                            gameplay_system_registry)):
            failures.append((FAILURE_INVALID_SCENE_COMPOSITION, field, "%s failed validation: %s" % (field, source[2]), source))

    for index, bundle in enumerate(bundle_registry.bundles):
        field = "bundle_registry.bundles[%d]" % index
        scene_found = scene_registry.lookup(bundle.scene_id)
        composition_found = composition_registry.lookup(bundle.composition.scene_id)
        if not scene_found.found:
            failures.append((FAILURE_INVALID_SCENE_BUNDLE, field + ".scene_id",
                             "%s.scene_id %r is not registered in scene_registry." % (field, bundle.scene_id), None))
        if not composition_found.found:
            failures.append((FAILURE_INVALID_SCENE_BUNDLE, field + ".composition.scene_id",
                             "%s.composition.scene_id %r is not registered in composition_registry." % (field, bundle.composition.scene_id), None))
        if scene_found.found and scene_found.scene != bundle.scene:
            failures.append((FAILURE_INVALID_SCENE_BUNDLE, field + ".scene",
                             "%s.scene differs from the scene registered as %r." % (field, bundle.scene_id), None))
        if composition_found.found and composition_found.composition != bundle.composition:
            failures.append((FAILURE_INVALID_SCENE_BUNDLE, field + ".composition",
                             "%s.composition differs from the composition registered as %r." % (field, bundle.composition.scene_id), None))

    if failures:
        return GameDefinitionResult(_CREATE_TOKEN, None, failures)
    return GameDefinitionResult(_CREATE_TOKEN, GameDefinition(_CREATE_TOKEN, project, structure, scene_registry, character_registry,
                                                              gameplay_system_registry, asset_registry, composition_registry,
                                                              bundle_registry), [])
