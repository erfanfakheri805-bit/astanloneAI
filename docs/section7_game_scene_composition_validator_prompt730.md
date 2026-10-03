# Section 7 - Game Scene Composition Validator (Prompt 730)

Module: `app/src/main/python/game_creation/game_scene_composition_validator.py`

A small, pure validation layer that checks whether a `GameSceneComposition` is structurally compatible with an existing `GameScene` and the
existing Section 7 registries. It is the composition-level counterpart of the project validator from Prompt 728.

## Public API

```python
validate_game_scene_composition(composition, scene, character_registry, asset_registry, gameplay_system_registry)
    -> GameSceneCompositionValidationResult
```

`GameSceneCompositionValidationResult` exposes:

- `ok` - `True` when there are no failures.
- `failures` - a FRESH list of FRESH `{"code", "field", "message"}` dicts on every access.
- `codes()` - the failure codes, in order.
- `to_dict()` - a FRESH `{"ok": bool, "failures": [...]}`.

## Input rules

All five arguments are required and must be of the exact type (no subclasses, look-alikes or coercion):

| Argument | Required type | Failure code |
| --- | --- | --- |
| `composition` | `GameSceneComposition` | `INVALID_COMPOSITION` |
| `scene` | `GameScene` | `INVALID_SCENE` |
| `character_registry` | `GameCharacterRegistry` | `INVALID_CHARACTER_REGISTRY` |
| `asset_registry` | `GameAssetRegistry` | `INVALID_ASSET_REGISTRY` |
| `gameplay_system_registry` | `GameplaySystemRegistry` | `INVALID_GAMEPLAY_SYSTEM_REGISTRY` |

Invalid inputs produce deterministic failures and never raise.

## Cross-checks

1. `composition.scene_id` must exactly equal `scene.scene_id` (`SCENE_ID_MISMATCH`).
2. Every `composition.character_ids` entry must resolve through `character_registry.lookup()` (`CHARACTER_NOT_FOUND`).
3. Every `composition.asset_ids` entry must resolve through `asset_registry.lookup()` (`ASSET_NOT_FOUND`).
4. Every `composition.gameplay_system_ids` entry must resolve through `gameplay_system_registry.lookup()` (`GAMEPLAY_SYSTEM_NOT_FOUND`).

The validator uses the registries' public `lookup()` APIs and their `found` verdict. It does not read or duplicate registry internals or id
lists, and the tests pin this. Matching is exact: there is no normalization, trimming, coercion, case-folding or implicit id matching.

Registry contents are NOT required to be limited to the composition: unused registry entries are valid.

A check only runs when every input it needs is valid, so one bad input never hides or invents other failures. The scene-id check needs
`composition` and `scene`; each reference group needs `composition` and its own registry.

## Failure ordering

All failures are reported together, in this fixed order:

1. invalid top-level arguments, in argument order;
2. scene-id mismatch;
3. missing character references, in composition order;
4. missing asset references, in composition order;
5. missing gameplay-system references, in composition order.

All codes are prefixed `GAME_SCENE_COMPOSITION_VALIDATION_` and listed in `FAILURE_CODES`:
`INVALID_COMPOSITION`, `INVALID_SCENE`, `INVALID_CHARACTER_REGISTRY`, `INVALID_ASSET_REGISTRY`, `INVALID_GAMEPLAY_SYSTEM_REGISTRY`,
`SCENE_ID_MISMATCH`, `CHARACTER_NOT_FOUND`, `ASSET_NOT_FOUND`, `GAMEPLAY_SYSTEM_NOT_FOUND`.

## Result conventions

The result follows the established Section 7 immutable-result conventions: read-only attributes (`__slots__`, failures stored as a tuple of
tuples), deterministic equality and hashing, fresh `failures`/`to_dict()` on every call, direct construction and subclassing refused, `copy` and
`deepcopy` return the same object, pickling refused. The result stores only strings, never a caller object.

## What this layer does NOT do

- It does NOT modify `GameSceneComposition`, `GameScene` or any registry, and adds no lookup behavior elsewhere.
- It does NOT mutate or store any input; it creates no registry or persistent object.
- It does NOT normalize, trim, coerce or case-fold identifiers.
- It does NOT render, play audio, execute gameplay, touch the filesystem, network or database, or use the clock or randomness.
- It is NOT wired into `process_input()`, Core, the Planner, the Agent Loop, the runtime, rendering, audio, execution or automation.
- Its only imports are Section 7 modules (`GameScene`, `GameSceneComposition` and the three registry classes).

## Scope and future work

Only the validator was added in Prompt 730. Existing production files were not modified. The only edits to existing files are narrow
file-list test updates and the exact-path exemption in the Section 6 frozen-tree guard, following the pattern used for earlier Section 7 files.
Later Section 7 features, including anything planned for Prompt 731, are intentionally not part of this prompt.
