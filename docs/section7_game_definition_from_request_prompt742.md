# Section 7 - Game Definition From Request (Prompt 742)

## Purpose

A small, explicit, caller-driven, read-only bridge from a `GameCreationRequest` (Prompt 739) to the existing `GameDefinition` layer (Prompt 734).

```
GameCreationRequest -> bridge -> existing public factories -> GameDefinition
```

Module: `app/src/main/python/game_creation/game_definition_from_request.py`

## Public API

```python
create_game_definition_from_request(request) -> GameDefinitionFromRequestResult
GameDefinitionFromRequestResult.ok          # bool
GameDefinitionFromRequestResult.definition  # GameDefinition or None
GameDefinitionFromRequestResult.failures    # fresh list of {"code", "field", "message", "source"}
GameDefinitionFromRequestResult.codes()     # fresh list of failure codes, in order
GameDefinitionFromRequestResult.to_dict()   # fresh {"ok", "definition", "failures"}
```

Constants: `FAILURE_PREFIX = "GAME_DEFINITION_FROM_REQUEST_"`, `FAILURE_INVALID_REQUEST`, `FAILURE_CODES`.

## What the request contributes

A `GameCreationRequest` has six project fields and nothing else: no scenes, characters, gameplay systems, assets, compositions or bundles. This bridge
does not invent any. A valid request yields the minimum, deterministic, empty definition graph, built only through existing public factories, in
this order (each called exactly once, with fresh arguments on every call):

| Stage | Factory | Argument |
| --- | --- | --- |
| project | `create_game_project` | the six request fields, unchanged (same `str` objects) |
| structure | `create_game_project_structure` | `{"scenes": [], "characters": [], "gameplay_systems": [], "assets": []}` |
| scenes | `create_game_scene_registry` | `[]` |
| characters | `create_game_character_registry` | `[]` |
| gameplay systems | `create_gameplay_system_registry` | `[]` |
| assets | `create_game_asset_registry` | `[]` |
| compositions | `create_game_scene_composition_registry` | `[]` |
| bundles | `create_game_scene_bundle_registry` | `[]` |
| definition | `create_game_definition` | the project, the structure and the six registries above, in that order |

Only the six project fields are read, through the request's public properties. Nothing else is read and nothing is derived from any value, so two
requests that differ only in their values give definitions that differ only in the project.

## Behavior and failure codes

1. `request` must be exactly a `GameCreationRequest`. A subclass, look-alike, dict, `None` or any other object gives `ok=False`, `definition=None`
   and one failure, `GAME_DEFINITION_FROM_REQUEST_INVALID_REQUEST` (field `"request"`). No factory is called.
2. For a valid request the nine factories run in the order above. The bridge does no validation, trimming, normalization or coercion of its own.
3. The first stage that reports failures stops the chain. Its failures are exposed unchanged (codes, fields, messages, order; `source` kept when
   `create_game_definition()` supplied one) with `ok=False` and `definition=None`. They keep the producing factory's own prefix; no failure is
   invented or re-coded. With the fixed empty input this path cannot occur today; it is a defensive guarantee covered by tests that replace each
   factory in turn with a genuinely failing result.
4. If every stage succeeds, the `GameDefinition` returned by `create_game_definition()` is exposed as-is. The objects inside it are the very objects
   the factories returned: identity is preserved, nothing is copied or rebuilt.

## Result conventions

`GameDefinitionFromRequestResult` follows the immutable Section 7 conventions: `__slots__`, read-only attributes, not subclassable, direct
construction refused (`TypeError`), deterministic equality and hash, fresh `failures` / `to_dict()` / `codes()` on every call (a failure's `source` is
`None` or a fresh dict), copy and deepcopy return the same object, pickling is refused.

## Dependency direction

The bridge imports `GameCreationRequest` (exact-type check only) and the public factories above. None of those modules knows the bridge and none was
modified. The Prompt 740 and 741 bridges are deliberately not imported: the same public factories are called directly, so those bridges stay
unreferenced and their own isolation tests stay valid.

## What this does NOT do

No runtime execution, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state. It is not wired into
`process_input()`, Core, the Planner or the Agent Loop and runs only when a caller calls it. It does not populate any collection, does not validate
anything itself and does not change `GameCreationRequest` or `GameDefinition`.

## Files

Added: the bridge module, `tests/test_game_definition_from_request_prompt742.py` and this document. Updated (test-only): the Section 7 package
file-list pins in the earlier Section 7 tests, the Prompt 739 "unaware of the request" skip list (the bridge necessarily names `GameCreationRequest`)
and the Prompt 718 guard's exact-path exemption (one more exact path, same pattern as Prompts 720-741). No production file was modified.

## Limitations

The definition is always empty apart from its project: populating scenes, characters, gameplay systems, assets, compositions or bundles from a request
needs a request model that carries them, which does not exist yet. The `GameDefinition` factory validates the empty graph, which trivially passes.
Prompt 743 has NOT been started.
