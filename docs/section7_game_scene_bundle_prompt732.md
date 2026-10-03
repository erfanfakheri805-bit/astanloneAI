# Section 7 - Game Scene Bundle (Prompt 732)

Module: `app/src/main/python/game_creation/game_scene_bundle.py`

A small, immutable pairing of one `GameScene` (Prompt 722) with its matching `GameSceneComposition` (Prompt 729). The only thing it checks is
that the two belong together: their `scene_id` values must be exactly equal.

## Public API

```python
create_game_scene_bundle(scene, composition) -> GameSceneBundleResult
```

`GameSceneBundleResult` exposes:

- `ok` - `True` when a bundle was built and there are no failures.
- `bundle` - the `GameSceneBundle`, or `None` when not `ok`.
- `failures` - a FRESH list of FRESH `{"code", "field", "message"}` dicts on every access.
- `codes()` - a fresh list of the failure codes, in order.
- `to_dict()` - a FRESH `{"ok", "bundle", "failures"}`.

`GameSceneBundle` exposes exactly:

- `scene` - the supplied `GameScene`, by identity.
- `composition` - the supplied `GameSceneComposition`, by identity.
- `scene_id` - a read-only `str` derived from the scene.
- `to_dict()` - a FRESH `{"scene_id", "scene", "composition"}` holding fresh `GameScene.to_dict()` and `GameSceneComposition.to_dict()` data.

## Rules

1. `scene` must be exactly a `GameScene` (no subclass or look-alike).
2. `composition` must be exactly a `GameSceneComposition`.
3. `scene.scene_id` must exactly equal `composition.scene_id`. Matching is exact: no trimming, case folding, normalization or coercion, so
   `"Arena"` / `"arena"` and `"arena"` / `"arena "` do not match.
4. `scene_id` is derived from the scene; it is not an input.
5. The original objects are stored as they are. They are never copied, rebuilt or changed, so `bundle.scene is scene` and
   `bundle.composition is composition`.
6. Nothing else is checked. No registry lookup is performed and characters, assets, gameplay systems and other references are not resolved, so a
   composition with arbitrary ids is accepted.

## Failures and ordering

`create_game_scene_bundle()` never raises for bad input. All problems are reported together, in this fixed order, with stable codes prefixed
`GAME_SCENE_BUNDLE_`:

1. `INVALID_SCENE` (field `scene`)
2. `INVALID_COMPOSITION` (field `composition`)
3. `SCENE_ID_MISMATCH` (field `composition.scene_id`)

The id comparison runs only when both objects are valid, so one bad input never hides or invents the mismatch failure.

## Immutability and determinism

`GameSceneBundle` and `GameSceneBundleResult` use `__slots__`, refuse attribute assignment and deletion, cannot be subclassed and cannot be
constructed directly (`TypeError`). Equal scene and composition mean equal bundles and equal hashes. `to_dict()`, `failures` and `codes()` return
fresh plain data on every call, including fresh nested scene and composition dicts and fresh id lists, so nothing returned aliases the bundle.
`copy` and `deepcopy` return the same object; pickling is refused with `TypeError`.

## What this module does NOT do

It does NOT perform a registry lookup, and it does NOT validate characters, assets, gameplay systems or any other project reference; that remains the
job of the Prompt 730 composition validator and the Prompt 731 registry is not consulted either. It imports only `GameScene` and
`GameSceneComposition`, and never a registry, `GameProject`, `GameProjectValidator`, `GameSceneCompositionValidator`, Core, the Planner, the Agent Loop
or any runtime or execution system. It has no rendering, audio, filesystem, network, database, clock or randomness, and no module-level mutable
state. No existing production file was modified.

## Scope note

This prompt is only about pairing a scene with its matching composition. Later Section 7 prompts (Prompt 733 onward) are not part of it.
