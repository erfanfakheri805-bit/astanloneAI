# Section 7 - Game Structure Registries From Request (Prompt 745)

Module: `app/src/main/python/game_creation/game_structure_registries_from_request.py`

A small, explicit, caller-driven, read-only bridge from a `GameStructureRequest` (Prompt 743) to the four existing registry factories.

```
GameStructureRequest -> bridge -> create_game_scene_registry
                                  create_game_character_registry
                                  create_gameplay_system_registry
                                  create_game_asset_registry
```

## Public API

```python
create_game_structure_registries_from_request(request) -> GameStructureRegistriesFromRequestResult
```

- `GameStructureRegistriesFromRequestResult` exposes `ok`, `registries` (`None` unless `ok`), `failures` (a FRESH list of FRESH
  `{"code", "field", "message"}` dicts), `codes()` and a FRESH `to_dict()` of `{"ok", "registries", "failures"}`.
- `registries` is a FRESH dict with exactly these keys, in this order: `scene_registry`, `character_registry`,
  `gameplay_system_registry`, `asset_registry`. The values are the very registry objects the factories returned (identity preserved).
- `to_dict()["registries"]` maps the same four keys to each registry's own `to_dict()`.

## Behavior

1. `request` must be exactly a `GameStructureRequest`. Subclass, look-alike, mock, dict, `None`, a `GameCreationRequest`, a
   `GameProjectStructure` or any other object is rejected and nothing is coerced. The result is `ok=False`, `registries=None` and one failure
   `GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST` (field `"request"`). No factory is called.
2. For a valid request the four factories are called, each at most once, strictly in this order, each with ONE positional argument
   (the optional `structure` argument is never passed):
   `create_game_scene_registry(request.scenes)` -> `create_game_character_registry(request.characters)` ->
   `create_gameplay_system_registry(request.gameplay_systems)` -> `create_game_asset_registry(request.assets)`.
   Only the four public request properties are read, each right before its own factory call. No private attribute is read.
3. No validation is duplicated. The bridge has one comparison (the exact-type gate) and no rule of its own. Items are never normalized,
   trimmed, casefolded, reordered, deduplicated, filtered, coerced or rewritten.
4. **short-circuit**: the first factory that fails ends the run. Its failures are exposed unchanged (same codes, fields, messages, order) with
   `ok=False` and `registries=None`; later factories are NOT called and their properties are not read. If several factories would fail, only
   the first one is ever asked.
5. If all four succeed, the registry objects they returned are exposed as-is (same objects, identity preserved).
6. The request and the factories are never changed.

### Containers: no list adaptation is needed here

The Prompt 744 bridge had to build fresh lists because `create_game_project_structure` accepts only an exact `list`. All four registry
factories accept an exact `list` OR an exact `tuple`, so this bridge passes the request's own immutable tuples straight through. No `list` is
built and no item is copied; the factories only read the collection and store their own tuple. The same string objects reach the factories.

## Failure codes

Bridge-owned (prefix `GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_`): `GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST`.
Everything else is a factory code passed through unchanged (for example `GAME_SCENE_REGISTRY_INVALID_SCENE`,
`GAME_CHARACTER_REGISTRY_INVALID_CHARACTER`, `GAME_ASSET_REGISTRY_INVALID_ASSET`); none is re-coded or invented.

## Known limitation: identifier strings versus record objects

A `GameStructureRequest` holds identifier STRINGS. `create_gameplay_system_registry` is itself a registry of identifier strings, so any valid
gameplay-system identifiers build a registry. `create_game_scene_registry`, `create_game_character_registry` and `create_game_asset_registry`
instead require `GameScene`, `GameCharacter` and `GameAsset` record objects. The bridge deliberately turns no string into a record (that would
invent data), so a request with at least one scene, character or asset identifier makes the matching factory report its own
invalid-item failure, which is returned unchanged. Today a request builds all four registries only when its scenes, characters and assets are
empty. Resolving identifiers into records, if wanted, is a separate decision for a later prompt; nothing here prejudges it.

## Result protections

`GameStructureRegistriesFromRequestResult` follows the Section 7 result conventions: `__slots__`, read-only attributes, not subclassable, direct
construction refused (`TypeError`), equal contents mean equal objects and equal hashes, `registries`, `failures`, `codes()` and `to_dict()`
return fresh plain containers on every call, `copy`/`deepcopy` return the same object, pickling is refused. The factories' own mutable result
holders are not handed out.

## What this module does NOT do

It does NOT validate, compose, bundle, resolve or register anything beyond calling the four factories. It does NOT use
`GameProjectStructure`, `GameScene`, `GameCharacter` or `GameAsset`. It does NOT touch the filesystem, network, database, AI, clock or
randomness, keeps no module-level mutable state, and is NOT wired into `process_input()`, Core, the Planner or the Agent Loop. It does not
change `GameStructureRequest`, any registry or factory, or the Prompt 744 bridge (`create_game_project_structure_from_request`), which
neither imports nor knows it. Existing tests only gained the new module name in their package-listing pins (and Prompt 743's
sanctioned-consumer exclusion).

Prompt 746 has NOT been started.
