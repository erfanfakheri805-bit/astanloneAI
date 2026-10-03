# Section 7 - Game Scene Bundle Registry (Prompt 733)

Module: `app/src/main/python/game_creation/game_scene_bundle_registry.py`

A small, immutable, in-memory registry that STORES `GameSceneBundle` objects (Prompt 732) and FINDS them by exact `scene_id`.
It is the bundle-level counterpart of the scene, character, asset, gameplay-system and composition registries (Prompts 724-727, 731).

## Public API

```python
create_game_scene_bundle_registry(bundles) -> GameSceneBundleRegistryResult
```

`GameSceneBundleRegistryResult` exposes:

- `ok` - `True` when a registry was built and there are no failures.
- `registry` - the `GameSceneBundleRegistry`, or `None` when not `ok`.
- `failures` - a FRESH list of FRESH `{"code", "field", "message"}` dicts on every access.
- `codes()` - a fresh list of the failure codes, in order.
- `to_dict()` - a FRESH `{"ok", "registry", "failures"}`.

`GameSceneBundleRegistry` exposes:

- `bundles` - tuple of `GameSceneBundle`, in input order.
- `scene_ids` - tuple of scene ids, in input order.
- `lookup(scene_id)` - returns a `GameSceneBundleLookupResult`.
- `to_dict()` - a FRESH `{"bundles": [GameSceneBundle.to_dict(), ...]}`.

`GameSceneBundleLookupResult` exposes `found`, `bundle` (`None` unless found), `code` (`None` unless not found) and `to_dict()`.

## Input rules

1. `bundles` must be exactly a `list` or a `tuple` (no subclass, set, dict, generator or string; nothing is coerced).
2. An empty collection is valid.
3. Every item must be exactly a `GameSceneBundle`.
4. `bundle.scene_id` must be unique by exact comparison.
5. Input order is preserved.
6. The exposed collections are immutable tuples.
7. Ids are never normalized, trimmed, case-folded, coerced or otherwise transformed.
8. Supplied bundles and the supplied collection are never mutated; the bundles are stored as the same objects.

## Failure codes

All codes are stable and prefixed `GAME_SCENE_BUNDLE_REGISTRY_`:

| Code suffix | Produced by | Meaning |
| --- | --- | --- |
| `INVALID_COLLECTION` | factory | the top-level input is not exactly a list/tuple (nothing else is checked) |
| `INVALID_BUNDLE` | factory | an item is not exactly a `GameSceneBundle` |
| `DUPLICATE_SCENE_ID` | factory | an item repeats the `scene_id` of an earlier valid item |
| `SCENE_NOT_FOUND` | `lookup()` only | no bundle has exactly that id |

The factory never raises for invalid input. Failures follow input order (one per offending item, by position); invalid items are never
counted as duplicates, and the first occurrence of an id is the one kept as the reference.

## Lookup

`lookup(scene_id)` performs exact matching only and never raises. A hit returns `found=True` with the stored bundle. A miss returns
`found=False`, `bundle=None` and `SCENE_NOT_FOUND`; so does any `scene_id` that is not exactly a `str` (including `str` subclasses).
`"Arena"`, `"arena"`, `"arena "` and `" arena"` are four different ids.

## Immutability and determinism

All three classes use `__slots__`, refuse attribute assignment and deletion, cannot be subclassed and cannot be constructed directly
(`TypeError`). Equal contents mean equal objects and equal hashes (a different order is a different registry). `copy` and `deepcopy`
return the same object; pickling is refused with `TypeError`. `to_dict()`, `failures` and `codes()` return fresh plain data on every call.

## What this module does NOT do

It does NOT validate scenes, compositions, characters, assets, gameplay systems or project structure, and it does NOT call
`GameSceneCompositionValidator` or `GameSceneCompositionRegistry` (Prompt 730 and Prompt 731). A bundle whose composition carries arbitrary
character / asset / gameplay-system ids is accepted and left untouched; resolving them is the job of the Prompt 730 validator. Its only
import is the Prompt 732 bundle module. It has no runtime integration, rendering, audio, execution, `process_input()`, Core, Planner or
Agent Loop wiring, and no filesystem, network, database, clock or randomness. No existing production file was modified.

## Scope note

This prompt is only about storing and looking up bundle definitions. Later Section 7 prompts (Prompt 734 onward) are not part of it.
