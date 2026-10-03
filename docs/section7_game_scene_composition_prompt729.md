# Prompt 729 - Section 7: Game Scene Composition

Status: **implemented.** `game_creation/game_scene_composition.py`, pinned by `tests/test_game_scene_composition_prompt729.py`.

## What GameSceneComposition represents
An immutable record of WHICH characters, assets and gameplay systems belong to one scene, stored as plain string identifiers:
`scene_id`, `character_ids`, `asset_ids`, `gameplay_system_ids`. It only describes references. The identifiers are **not resolved**: nothing
checks that a scene, character, asset or gameplay system with that id exists, and the module imports no registry and not the project validator
(it imports nothing at all). All earlier Section 7 modules are unchanged and remain unaware of it.

## API
- `create_game_scene_composition(data)` returns a `GameSceneCompositionResult` with `ok`, `composition`, `failures`, `codes()` and
  `to_dict()`. It never raises for bad data.
- `GameSceneComposition` has read-only `scene_id`, `character_ids`, `asset_ids`, `gameplay_system_ids` (the last three are tuples) and
  `to_dict()` (fresh plain data, lists, fixed field order; `create_game_scene_composition(c.to_dict())` rebuilds an equal object).
  Equality and hashing are deterministic (a different order is a different composition). Direct construction, subclassing and pickling are
  refused; copy/deepcopy return the same object.

## Validation rules
- `data` must be exactly a plain `dict` (a dict subclass is rejected) with exactly the four fields; unexpected and missing fields are rejected.
- `scene_id` must be exactly a non-blank `str`.
- `character_ids`, `asset_ids` and `gameplay_system_ids` must each be exactly a `list` or `tuple` (empty is valid). Every item must be exactly a
  non-blank `str`. Duplicates are rejected within each collection by exact comparison; the same id may appear in different collections.
- Nothing is coerced, trimmed, case-folded or reordered. Caller-owned collections are copied, never retained.

## Failure codes
All codes are prefixed `GAME_SCENE_COMPOSITION_`: `INVALID_INPUT`, `UNEXPECTED_FIELD`, `MISSING_FIELD`, `INVALID_SCENE_ID`,
`INVALID_CHARACTER_IDS`, `INVALID_CHARACTER_ID`, `DUPLICATE_CHARACTER_ID`, `INVALID_ASSET_IDS`, `INVALID_ASSET_ID`, `DUPLICATE_ASSET_ID`,
`INVALID_GAMEPLAY_SYSTEM_IDS`, `INVALID_GAMEPLAY_SYSTEM_ID`, `DUPLICATE_GAMEPLAY_SYSTEM_ID`. The plural codes mean the collection itself is not a
list/tuple; the singular codes mean an item is not a `str` or is blank.

Failures are reported together in a fixed order: input, unexpected fields (sorted by name), missing fields (field order), `scene_id`,
`character_ids` and its items (by position), `asset_ids` and its items, `gameplay_system_ids` and its items. A missing field is reported once and
not checked further.

## What it intentionally does NOT do
No registry validation or id resolution; no scene loading, rendering, camera, physics, animation, audio, combat, AI, dialogue or inventory; no
engine, filesystem, network, database or external-service access; no wiring into `process_input`, Core, the Planner or the Agent Loop.

## How later prompts can build on it
A later prompt can validate a composition against the registries (for example that `scene_id` is a registered scene and every listed id exists),
possibly through the project validator, without changing this model. Richer scene behavior can build on the same identifiers.

## Limitations noted
- Only `list` and `tuple` collections are accepted (an unordered collection cannot give a deterministic order).
- A composition is not checked against any structure or registry; a scene may list ids that do not exist anywhere yet.
- Ids are compared exactly and kept as given (`"Hero"` and `"hero"` are different ids).
