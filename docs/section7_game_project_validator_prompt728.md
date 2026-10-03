# Prompt 728 - Section 7: Game Project Validator

Status: **implemented.** `game_creation/game_project_validator.py`, pinned by `tests/test_game_project_validator_prompt728.py`.

## What it does
`validate_game_project(project, structure, scene_registry, character_registry, gameplay_system_registry, asset_registry)` is a pure function that
checks one game-project definition for internal consistency: the six inputs must be exactly the expected types, and every id listed by the
`GameProjectStructure` must be registered in the matching registry (Prompts 724-727). It returns a `GameProjectValidationResult`; it creates no
registry or persistent object and never raises for bad input.

## API
- `validate_game_project(...)` returns a `GameProjectValidationResult` with `ok`, `failures` (a fresh list of `{code, field, message}` dicts on
  every access), `codes()` and `to_dict()` (fresh `{"ok", "failures"}` data).
- The result is immutable (failures stored as a tuple of tuples), has deterministic equality and hashing, refuses direct construction,
  subclassing and pickling, and copy/deepcopy return the same object.

## Validation rules and failure codes
| problem | code |
|---|---|
| `project` is not exactly a `GameProject` | `GAME_PROJECT_VALIDATION_INVALID_PROJECT` |
| `structure` is not exactly a `GameProjectStructure` | `..._INVALID_STRUCTURE` |
| `scene_registry` is not exactly a `GameSceneRegistry` | `..._INVALID_SCENE_REGISTRY` |
| `character_registry` is not exactly a `GameCharacterRegistry` | `..._INVALID_CHARACTER_REGISTRY` |
| `gameplay_system_registry` is not exactly a `GameplaySystemRegistry` | `..._INVALID_GAMEPLAY_SYSTEM_REGISTRY` |
| `asset_registry` is not exactly a `GameAssetRegistry` | `..._INVALID_ASSET_REGISTRY` |
| an id in `structure.scenes` is not in `scene_registry` | `..._MISSING_SCENE_REFERENCE` |
| an id in `structure.characters` is not in `character_registry` | `..._MISSING_CHARACTER_REFERENCE` |
| an id in `structure.gameplay_systems` is not in `gameplay_system_registry` | `..._MISSING_GAMEPLAY_SYSTEM_REFERENCE` |
| an id in `structure.assets` is not in `asset_registry` | `..._MISSING_ASSET_REFERENCE` |

Failures are reported together in a fixed order: invalid top-level inputs (argument order), then scene, character, gameplay-system and asset
references, each in the exact order of the matching structure collection. A reference group is checked only when the structure and its registry
are both valid, so a bad input never hides or invents other failures. Comparison is exact. Registry entries the structure does not list (unused
entries) are allowed.

## Project identity: deferred
`GameProjectStructure` has no project-id field (only scenes, characters, gameplay_systems and assets), and it was intentionally not modified.
Cross-validating `project.project_id` against the structure is therefore deferred: `project` is checked for its exact type only, and only the
available structure relationships are validated. A later prompt can add the identity check if the structure ever carries an identity.

## What it intentionally does NOT do
No new registry or persistent object; no scene or asset loading, rendering, engine dependency, gameplay execution, filesystem, network, database,
AI or external-service access; no wiring into `process_input`, Core, the Planner or the Agent Loop. It does not inspect what a scene, character or
asset contains, and does not require every registry entry to be referenced.

## How later prompts can build on it
A later step can add cross-entity rules (for example a scene referring to characters or assets) or an identity check, reusing the same result
shape and code prefix, without changing the records or registries.

## Limitations noted
- Only id presence is checked; duplicate ids cannot occur because each structure collection and registry already rejects them.
- The exact-type rule means look-alike or wrapper objects are rejected even if they carry the same attributes.
- Failure messages are for humans; callers should rely on `code` and `field`.
