# Section 7 - Game Definition Counts Query (Prompt 738)

Module: `app/src/main/python/game_creation/game_definition_counts.py`

A small read-only count query over one `GameDefinition` (Prompt 734): how many entries each of its six registries holds.

## Public API

```python
get_game_definition_counts(game_definition) -> GameDefinitionCountsResult
```

`GameDefinitionCountsResult` exposes `ok`, `counts`, `failures` and `to_dict()`.

## Count behavior

For a valid `GameDefinition`, `counts` is a FRESH dict on every access with exactly these keys, in this order:

| Key | Value |
| --- | --- |
| `scene_count` | `len(scene_registry.scenes)` |
| `character_count` | `len(character_registry.characters)` |
| `gameplay_system_count` | `len(gameplay_system_registry.gameplay_system_ids)` |
| `asset_count` | `len(asset_registry.assets)` |
| `composition_count` | `len(composition_registry.compositions)` |
| `bundle_count` | `len(bundle_registry.bundles)` |

- Counts come only from the public tuple properties the registries already expose. Nothing is scanned, sorted, normalized, validated, copied
  or mutated, and no registry internals are accessed. Empty registries give zero counts.
- This layer is independent: it does not call the Prompt 737 summary API or any other query API, and it duplicates no `GameDefinition`
  validation (only the argument type is checked).
- `to_dict()` returns `{"ok", "counts", "failures"}` as fresh plain data.

## Failure

One stable code: `GAME_DEFINITION_COUNTS_INVALID_GAME_DEFINITION`. A `game_definition` that is not exactly a `GameDefinition` gives `ok=False`,
`counts=None` and one `{"code", "field": "game_definition", "message"}` failure. The function never raises for an invalid argument.

## Immutability and determinism

The result uses `__slots__`, refuses assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`). Equal
contents mean equal results and equal hashes. `counts`, `failures` and `to_dict()` return fresh containers on every call. `copy` and
`deepcopy` return the same object; pickling is refused with `TypeError`. The module is stateless and deterministic.

## What this module does NOT do

It does NOT modify `GameDefinition`, any registry, validator, query or summary function. It adds no runtime, rendering, audio, asset loading,
execution, networking, external AI API, filesystem generation, code generation or build/export behavior, and is not wired into
`process_input()`, Core, the Planner or the Agent Loop. No existing production file was modified.

## Scope note

Builds on Prompt 734. Later Section 7 prompts (Prompt 739 onward) are not part of it.
