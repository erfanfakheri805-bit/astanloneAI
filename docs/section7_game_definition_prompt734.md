# Section 7 - Game Definition (Prompt 734)

Module: `app/src/main/python/game_creation/game_definition.py`

A small, immutable, in-memory GROUPING of the eight Section 7 foundation objects that describe one game project, plus a thin orchestration
layer that checks they agree with each other by calling the EXISTING public validators. It is a data-definition and validation layer only.

## Public API

```python
create_game_definition(project, structure, scene_registry, character_registry, gameplay_system_registry,
                       asset_registry, composition_registry, bundle_registry) -> GameDefinitionResult
```

`GameDefinitionResult` exposes `ok`, `definition` (`None` unless `ok`), `failures` (a FRESH list of FRESH
`{"code", "field", "message", "source"}` dicts), `codes()` and a FRESH `to_dict()` of `{"ok", "definition", "failures"}`.

`GameDefinition` exposes exactly eight read-only attributes, each the supplied object BY IDENTITY: `project`, `structure`, `scene_registry`,
`character_registry`, `gameplay_system_registry`, `asset_registry`, `composition_registry`, `bundle_registry`; plus `to_dict()`, which returns
one key per attribute built from that object's own public `to_dict()`.

## Validation

1. Each argument must be exactly `GameProject`, `GameProjectStructure`, `GameSceneRegistry`, `GameCharacterRegistry`, `GameplaySystemRegistry`,
   `GameAssetRegistry`, `GameSceneCompositionRegistry`, `GameSceneBundleRegistry` respectively, checked in that argument order.
2. If ANY argument is invalid, only the top-level failures are returned; no cross-object validation involving (or, in this implementation,
   following) an invalid argument is performed. Cross-checks run only when all eight arguments are valid.
3. Cross-checks, in this exact order:
   a. `validate_game_project(...)` (Prompt 728) over the project, structure and the four base registries.
   b. For every composition in `composition_registry` (registry order): its scene is found with `scene_registry.lookup()`, then
      `validate_game_scene_composition(...)` (Prompt 730) runs against that scene and the character, asset and gameplay-system registries.
      A composition whose scene is not registered is reported and is not passed to the validator.
   c. For every bundle in `bundle_registry` (registry order): `bundle.scene_id` must resolve in `scene_registry`; the bundle composition's
      `scene_id` must resolve in `composition_registry`; and the bundle's own scene and composition must EQUAL the registered ones.
4. Validator logic is reused, never duplicated. Registries are read only through public properties and `lookup()`.
5. Unused registry entries are allowed, empty registries are valid, ids are compared exactly and never normalized, and nothing supplied is mutated.

## Failure codes

All codes are stable and prefixed `GAME_DEFINITION_`:

| Code suffix | Meaning |
| --- | --- |
| `INVALID_PROJECT`, `INVALID_STRUCTURE`, `INVALID_SCENE_REGISTRY`, `INVALID_CHARACTER_REGISTRY`, `INVALID_GAMEPLAY_SYSTEM_REGISTRY`, `INVALID_ASSET_REGISTRY`, `INVALID_COMPOSITION_REGISTRY`, `INVALID_BUNDLE_REGISTRY` | the argument is not exactly the expected type (field is the argument name) |
| `INVALID_PROJECT_STRUCTURE` | one per failure reported by `validate_game_project` |
| `INVALID_SCENE_COMPOSITION` | a composition's scene is unregistered (own failure), or one per failure reported by `validate_game_scene_composition` |
| `INVALID_SCENE_BUNDLE` | a bundle's scene or composition is unregistered, or differs from the registered one |

Failure order: top-level arguments (argument order); project-structure failures; composition failures (registry order, the missing-scene
failure first, then the validator's own order); bundle failures (registry order: scene missing, composition missing, scene differs,
composition differs).

Delegated failures are NOT given a new code each: the underlying validator's `{"code", "field", "message"}` is carried unchanged in the
`source` entry of the wrapping failure. Failures produced by this module itself have `source` set to `None`.

## Immutability and determinism

Both classes use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`). Equal
contents mean equal objects and equal hashes. `to_dict()`, `failures` and `codes()` return fresh plain data on every call and never alias
internal state. `copy` and `deepcopy` return the same object; pickling is refused with `TypeError`. Invalid input never raises.

## What this module does NOT do

It does NOT modify any model, registry or validator (`GameProjectValidator` and `GameSceneCompositionValidator` included), and it adds no
runtime execution, rendering, audio, asset loading, game-engine behavior, filesystem project generation, code generation, or APK/build/export
functionality. It is not wired into `process_input()`, Core, the Planner or the Agent Loop. No existing production file was modified.

## Scope note

Builds on Prompt 733 (bundle registry), Prompt 728 (project validator) and Prompt 730 (composition validator). Later Section 7 prompts
(Prompt 735 onward) are not part of it.
