# Section 7 - Game Definition Summary (Prompt 737)

Module: `app/src/main/python/game_creation/game_definition_summary.py`

A small read-only summary of one `GameDefinition` (Prompt 734): its project plus how many entries each registry holds.

## Public API

```python
build_game_definition_summary(game_definition) -> GameDefinitionSummaryResult
```

`GameDefinitionSummaryResult` exposes `ok`, `summary`, `failures` and `to_dict()`.

## Summary behavior

For a valid `GameDefinition`, `summary` is a FRESH dict on every access with exactly these keys:

| Key | Value |
| --- | --- |
| `project` | the `GameDefinition.project` object itself (identity preserved) |
| `scene_count` | `len(scene_registry.scenes)` |
| `character_count` | `len(character_registry.characters)` |
| `gameplay_system_count` | `len(gameplay_system_registry.gameplay_system_ids)` |
| `asset_count` | `len(asset_registry.assets)` |
| `composition_count` | `len(composition_registry.compositions)` |
| `bundle_count` | `len(bundle_registry.bundles)` |

- Counts are taken only from the public tuple properties the registries already expose. Nothing is scanned, sorted, re-validated or copied,
  and no registry internals are accessed. Empty registries give zero counts.
- `to_dict()` returns `{"ok", "summary", "failures"}` as fresh plain data; the project appears as `project.to_dict()`.
- The project object is the one intentional shared reference in `summary`; it is itself immutable.

## Failure

One stable code: `GAME_DEFINITION_SUMMARY_INVALID_GAME_DEFINITION`. A `game_definition` that is not exactly a `GameDefinition` gives
`ok=False`, `summary=None` and one `{"code", "field": "game_definition", "message"}` failure. The function never raises for an invalid argument.

## Immutability and determinism

The result uses `__slots__`, refuses assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`). Equal
contents mean equal results and equal hashes. `summary`, `failures` and `to_dict()` return fresh containers on every call. `copy` and
`deepcopy` return the same object; pickling is refused with `TypeError`. The module is stateless and deterministic.

## What this module does NOT do

It does NOT modify `GameDefinition`, any registry, validator or query function, and does not validate or re-check any contents. It adds no
runtime, rendering, audio, asset loading, execution, networking, external AI API, filesystem generation, code generation or build/export
behavior, and is not wired into `process_input()`, Core, the Planner or the Agent Loop. No existing production file was modified.

## Scope note

Builds on Prompt 734. Later Section 7 prompts (Prompt 738 onward) are not part of it.
