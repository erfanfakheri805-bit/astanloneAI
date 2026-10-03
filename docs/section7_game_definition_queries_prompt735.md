# Section 7 - Game Definition Queries (Prompt 735)

Module: `app/src/main/python/game_creation/game_definition_queries.py`

A tiny read-only query layer over one `GameDefinition` (Prompt 734). Callers resolve a scene, or the bundle of a scene, by exact `scene_id`
through one public API, without touching or repeating registry internals.

## Public API

```python
lookup_game_scene(game_definition, scene_id)        -> GameSceneQueryResult
lookup_game_scene_bundle(game_definition, scene_id) -> GameSceneBundleQueryResult
```

- `GameSceneQueryResult` exposes `found`, `scene` (`None` unless found), `code` (`None` unless not found / invalid) and `to_dict()`.
- `GameSceneBundleQueryResult` exposes `found`, `bundle` (`None` unless found), `code` and `to_dict()`.
- `to_dict()` returns FRESH plain data: `{"found", "scene" | "bundle", "code"}` where the object is that object's own `to_dict()` or `None`.

## Lookup behavior

1. `game_definition` must be exactly a `GameDefinition`; it is checked first.
2. `scene_id` must be exactly a `str` (a `str` subclass is rejected).
3. Matching is exact: no trimming, case-folding, normalization or coercion. `"Arena"`, `"arena"` and `"arena "` are different ids.
4. The scene query delegates to `game_definition.scene_registry.lookup(scene_id)`; the bundle query to
   `game_definition.bundle_registry.lookup(scene_id)`. No registry internals are accessed, no list is scanned, and no lookup logic is duplicated.
5. The object returned by the registry is kept BY IDENTITY in the result. It is not validated, copied or mutated.
6. Nothing supplied is mutated, and invalid arguments never raise.

## Failure codes

Stable, prefixed `GAME_DEFINITION_QUERY_`:

| Code suffix | When |
| --- | --- |
| `INVALID_GAME_DEFINITION` | `game_definition` is not exactly a `GameDefinition` (checked first) |
| `INVALID_SCENE_ID` | `scene_id` is not exactly a `str` |
| `SCENE_NOT_FOUND` | scene query: the scene registry has no scene with that exact id |
| `BUNDLE_NOT_FOUND` | bundle query: the bundle registry has no bundle with that exact id |

On every failure `found` is `False` and the scene/bundle is `None`.

## Immutability and determinism

Both result types use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`).
Equal fields mean equal results and equal hashes. `copy` and `deepcopy` return the same object; pickling is refused with `TypeError`.

## What this module does NOT do

It does NOT modify `GameDefinition`, any registry or any validator, add registries, or use `GameProjectValidator`,
`GameSceneCompositionValidator` or `GameSceneCompositionRegistry`. There is no runtime, rendering, audio, asset loading, execution, filesystem
generation, code generation or build/export behavior, and no `process_input()`, Core, Planner or Agent Loop wiring. Its only import is the
Prompt 734 `GameDefinition`. No existing production file was modified.

## Scope note

Builds on Prompt 734 (`GameDefinition`). Later Section 7 prompts (Prompt 736 onward) are not part of it.
