# Prompt 725 - Section 7: Game Scene Registry

Status: **implemented.** `game_creation/game_scene_registry.py`, pinned by `tests/test_game_scene_registry_prompt725.py`.

## What GameSceneRegistry represents
An immutable, ordered collection of `GameScene` definitions (Prompt 722) with lookup by exact `scene_id`, optionally checked against
the scene identifiers listed by a `GameProjectStructure` (Prompt 721). It follows the `GameCharacterRegistry` pattern (Prompt 724): the structure names
which scenes a project has, and the registry holds their definitions. Both existing records are unchanged and remain unaware of it.

## API
- `create_game_scene_registry(scenes, structure=None)` returns a `GameSceneRegistryResult` with `ok`, `registry`, `failures`,
  `codes()` and `to_dict()`. It never raises for bad input.
- `GameSceneRegistry`: `scenes` and `scene_ids` (tuples, registration order), `lookup(scene_id)`, `to_dict()` (fresh data),
  deterministic equality and hashing. Direct construction and subclassing are refused; attributes are read-only; pickling is refused.
- `lookup()` returns a `GameSceneLookupResult(found, scene, code)`. A missing id (or a non-`str` id) gives `found=False` and the stable
  code `GAME_SCENE_REGISTRY_SCENE_NOT_FOUND`; it never raises.

## Validation and failure codes
| problem | code |
|---|---|
| `scenes` is not exactly a `list` or `tuple` | `..._INVALID_COLLECTION` |
| an item is not exactly a `GameScene` | `..._INVALID_SCENE` |
| a `scene_id` repeats (exact comparison) | `..._DUPLICATE_SCENE_ID` |
| `structure` is neither `None` nor a `GameProjectStructure` | `..._INVALID_STRUCTURE` |
| an id in `structure.scenes` has no registered scene | `..._MISSING_SCENE_REFERENCE` |

All codes are prefixed `GAME_SCENE_REGISTRY_`. Problems are reported together, in a fixed order: collection problems by position, then the
structure, then missing references in `structure.scenes` order. The reference check runs only for a valid structure. Nothing is coerced,
trimmed or reordered; input order is kept. Unused definitions (registered scenes the structure does not list) are allowed. The structure is
used only for validation and is not stored, so a registry built with and without a structure is equal.

## What it intentionally does NOT do yet
No character, asset or gameplay-system relationships; no scene content (objects, maps, lighting, physics, AI, dialogue, animation, rendering,
audio, assets); no scene loading, global registry, persistence, filesystem, network, database or AI access; no game-engine dependency; no
wiring into `process_input`, Core, the Planner or the Agent Loop. It does not check the other structure collections (`characters`,
`gameplay_systems`, `assets`).

## How later prompts can build on it
A later step can combine the character and scene registries into one validated project view. Richer scene capabilities can refer to
registered scenes by `scene_id`. Because the registry only holds immutable `GameScene` objects and exposes exact-id lookup, such additions
do not need to change this module.

## Limitations noted
- Only `list` and `tuple` inputs are accepted (an unordered collection cannot give a deterministic order).
- Lookup is a linear scan; the registry is meant for small collections.
- Ids are compared exactly, so `"Intro"` and `"intro"` are different scenes.
- Referenced-but-missing scenes are the only structure check; unused registered scenes are not reported.
