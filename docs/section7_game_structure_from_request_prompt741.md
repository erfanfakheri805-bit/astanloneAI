# Section 7 - Game Structure From Request (Prompt 741)

## Purpose

A small, explicit, caller-driven, read-only bridge from a `GameCreationRequest` (Prompt 739) to the existing `GameProjectStructure` factory layer
(Prompt 721).

```
GameCreationRequest -> bridge -> create_game_project_structure()
```

Module: `app/src/main/python/game_creation/game_structure_from_request.py`

## Public API

```python
create_game_project_structure_from_request(request) -> GameStructureFromRequestResult
GameStructureFromRequestResult.ok          # bool
GameStructureFromRequestResult.structure   # GameProjectStructure or None
GameStructureFromRequestResult.failures    # fresh list of {"code", "field", "message"}
GameStructureFromRequestResult.codes()     # fresh list of failure codes, in order
GameStructureFromRequestResult.to_dict()   # fresh {"ok", "structure", "failures"}
```

Constants: `FAILURE_PREFIX = "GAME_STRUCTURE_FROM_REQUEST_"`, `FAILURE_INVALID_REQUEST`, `FAILURE_CODES`.

## What the request contributes

A `GameCreationRequest` has six project fields (`project_id`, `name`, `description`, `genre`, `target_platform`, `version`). A `GameProjectStructure`
has four identifier collections (`scenes`, `characters`, `gameplay_systems`, `assets`). The request carries no structural information and this bridge
invents none: the request is never read beyond its exact type. A valid request is treated as the caller's go-ahead for a new, empty structure, so the
factory is called with exactly:

```python
create_game_project_structure({"scenes": [], "characters": [], "gameplay_systems": [], "assets": []})
```

Empty lists are valid factory input (its documented shape), so no rule is added or relaxed. Nothing is derived from the request's name, genre,
description or any other value; equal-typed requests with different values give equal results. Fresh lists are built on every call.

## Behavior and failure codes

1. `request` must be exactly a `GameCreationRequest`. A subclass, look-alike, dict, `None` or any other object gives `ok=False`, `structure=None`
   and one failure, `GAME_STRUCTURE_FROM_REQUEST_INVALID_REQUEST` (field `"request"`). The factory is not called.
2. For a valid request the factory is called once, through its public name only. The bridge does no validation, trimming, normalization or coercion.
3. If the factory succeeds, the `GameProjectStructure` it returned is exposed as-is: object identity is preserved.
4. If the factory reports failures they are exposed unchanged (codes, fields, messages, order) with `ok=False`, `structure=None`. They keep the
   factory's `GAME_PROJECT_STRUCTURE_` prefix; no failure is invented or re-coded. With the fixed empty input this path cannot occur today, so it is
   a defensive guarantee covered by tests that replace the factory.

## Result conventions

The factory's own `GameProjectStructureResult` is a plain mutable holder, so it is not handed out; its content is copied into
`GameStructureFromRequestResult`, which follows the immutable Section 7 conventions: `__slots__`, read-only attributes, not subclassable, direct
construction refused (`TypeError`), deterministic equality and hash, fresh `failures` / `to_dict()` / `codes()` on every call, copy and deepcopy return
the same object, pickling is refused.

## Dependency direction

The bridge imports `GameCreationRequest` (exact-type check only) and `create_game_project_structure`. `game_creation_request.py`,
`game_project_structure.py` and the earlier bridge do not know it; none of them was modified.

## What this does NOT do

No runtime execution, no registry, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state. It is not
wired into `process_input()`, Core, the Planner or the Agent Loop and runs only when a caller calls it. It does not link the structure to a
`GameProject` and does not fill any collection.

## Files

Added: the bridge module, `tests/test_game_structure_from_request_prompt741.py` and this document. Updated (test-only): the Section 7 package
file-list pins, the Prompt 739 "unaware of the request" skip list (the bridge necessarily names `GameCreationRequest`), and the Prompt 718 guard's
exact-path exemption (one more exact path, same pattern as Prompts 720-740).

## Limitations

The structure is always empty: populating scenes, characters, gameplay systems or assets from a request needs a request model that carries them,
which does not exist yet. Prompt 742 has NOT been started.
