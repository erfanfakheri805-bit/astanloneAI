# Section 7 - Game Definition Query Helpers (Prompt 736)

Module: `app/src/main/python/game_creation/game_definition_query_helpers.py`

A tiny read-only helper layer above the Prompt 735 query API: two yes/no questions about a `GameDefinition`.

## Public API

```python
has_game_scene(game_definition, scene_id)        -> bool
has_game_scene_bundle(game_definition, scene_id) -> bool
```

## Behavior

- `has_game_scene()` delegates to `lookup_game_scene()`; `has_game_scene_bundle()` delegates to `lookup_game_scene_bundle()` (both from
  `game_definition_queries.py`). Each returns exactly the `found` field of the query result.
- Matching is exactly what Prompt 735 defines: exact only, no trimming, case-folding, normalization or coercion.
- Invalid arguments add no new exceptions: a `game_definition` that is not exactly a `GameDefinition`, or a `scene_id` that is not exactly a
  `str`, yields the query layer's not-found result, so the helper returns `False`. The specific query code is not exposed here; call the
  Prompt 735 functions when the reason matters.
- Registry internals are never accessed, no list is scanned, no lookup logic is duplicated, and nothing is validated, copied or mutated.
- The module is stateless and deterministic. Its only import is the Prompt 735 query module (relative import).

## What this module does NOT do

It does NOT modify `GameDefinition`, any registry, validator or query function, and adds no runtime, rendering, audio, asset loading,
execution, networking, external AI API, filesystem generation, code generation or build/export behavior. It is not wired into
`process_input()`, Core, the Planner or the Agent Loop. No existing production file was modified.

## Scope note

Builds on Prompt 735. Later Section 7 prompts (Prompt 737 onward) are not part of it.
