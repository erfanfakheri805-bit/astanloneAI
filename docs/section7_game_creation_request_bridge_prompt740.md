# Section 7 - Game Creation Request Bridge (Prompt 740)

## Purpose

A small, explicit, caller-driven bridge from the structured input (`GameCreationRequest`, Prompt 739) to the project record
(`GameProject`, Prompt 720). It converts one valid request into one project by calling the existing public factory. It adds no project rules.

```
GameCreationRequest -> bridge -> GameProject factory
```

Module: `app/src/main/python/game_creation/game_creation_request_bridge.py`

## Public API

```python
create_game_project_from_request(request) -> GameCreationRequestBridgeResult
GameCreationRequestBridgeResult.ok          # bool
GameCreationRequestBridgeResult.project     # GameProject or None
GameCreationRequestBridgeResult.failures    # fresh list of {"code", "field", "message"}
GameCreationRequestBridgeResult.codes()     # fresh list of failure codes, in order
GameCreationRequestBridgeResult.to_dict()   # fresh {"ok", "project", "failures"}
```

Constants: `FAILURE_PREFIX = "GAME_CREATION_REQUEST_BRIDGE_"`, `FAILURE_INVALID_REQUEST`, `FAILURE_CODES`.

## Behavior

1. `request` must be exactly a `GameCreationRequest`. A subclass, look-alike, dict, `None` or any other object is rejected and the project factory
   is not called. The result is `ok=False`, `project=None` and one failure:
   `GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST` (field `"request"`).
2. For a valid request the six fields (`project_id`, `name`, `description`, `genre`, `target_platform`, `version`) are read through the request's
   public properties and passed unchanged - the very same string objects - to `create_game_project(...)` in a fresh plain dict. Nothing is trimmed,
   normalized, coerced, rebuilt or re-validated by the bridge.
3. The `GameProject` returned by the factory is stored and exposed as-is: object identity is preserved (no copy, no rebuild).
4. The request is only read. No private attribute of `GameCreationRequest` or `GameProject` is accessed and no registry is used.

## Failure propagation

If the existing factory unexpectedly returns failures, the bridge exposes them unchanged (same codes, fields, messages and order) with `ok=False`
and `project=None`. It invents no project-validation rule and no replacement code, so these keep the factory's own prefix (`GAME_PROJECT_`).
Only the bridge's own failure uses the bridge prefix `GAME_CREATION_REQUEST_BRIDGE_`. Because every `GameCreationRequest` already satisfies the
factory's rules, this path is a defensive guarantee and is exercised in tests by replacing the factory.

## Result conventions

`GameCreationRequestBridgeResult` follows the established Section 7 result conventions: `__slots__`, read-only attributes, not subclassable, direct
construction refused (`TypeError`), deterministic equality and hash (over project and failures), fresh `failures` / `to_dict()` / `codes()` on every
call, copy and deepcopy return the same object, pickling is refused.

## Dependency direction

`game_creation_request_bridge.py` imports `GameCreationRequest` and `create_game_project`. `game_project.py` and `game_creation_request.py` were not
modified (their SHA-256 is pinned in the tests) and do not know the bridge; `GameProject` does not depend on `GameCreationRequest`.

## What this does NOT do

No runtime execution, no registry, no file, network, database or AI access, no clock or randomness, no module-level mutable state. It is not wired into
`process_input()`, Core, the Planner or the Agent Loop and runs only when a caller calls it.

## Files

Added: the bridge module, `tests/test_game_creation_request_bridge_prompt740.py`, and this document.
Updated (test-only): the Section 7 package file-list pins in the earlier Section 7 tests, and the Prompt 718 guard's exact-path exemption list
(one more exact path, same pattern as Prompts 720-739).

## Limitations

The bridge produces only the `GameProject` identity record. It does not build a structure, registries or a `GameDefinition`, and it does not register
or store the project anywhere. Prompt 741 has NOT been started.
