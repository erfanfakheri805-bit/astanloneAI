# Section 7 - Game Structure Request Bridge (Prompt 744)

Module: `app/src/main/python/game_creation/game_structure_request_bridge.py`

A small, explicit, caller-driven, read-only bridge from a `GameStructureRequest` (Prompt 743) to the existing `GameProjectStructure` factory
(Prompt 721).

```
GameStructureRequest -> bridge -> create_game_project_structure()
```

## Public API

```python
create_game_project_structure_from_request(request) -> GameStructureRequestBridgeResult
```

- `GameStructureRequestBridgeResult` exposes `ok`, `structure` (`None` unless `ok`), `failures` (a FRESH list of FRESH
  `{"code", "field", "message"}` dicts), `codes()` and a FRESH `to_dict()` of `{"ok", "structure", "failures"}`.
- Note: the Prompt 741 bridge (`game_structure_from_request`, from `GameCreationRequest`) has a function with the same name. They live in
  different modules, are unrelated, and neither imports the other. This prompt's function is imported from
  `game_creation.game_structure_request_bridge`.

## Behavior

1. `request` must be exactly a `GameStructureRequest`. Subclass, look-alike, mock, dict, `None`, a `GameCreationRequest`, a
   `GameProjectStructure` or any other object is rejected and nothing is coerced. The result is `ok=False`, `structure=None` and one failure
   `GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST` (field `"request"`). The factory is NOT called.
2. For a valid request only the four public properties `scenes`, `characters`, `gameplay_systems`, `assets` are read (in that order, once each).
   No private attribute is read.
3. The factory `create_game_project_structure` is called exactly once through its public name with a plain dict of those four values.
4. No validation is duplicated. The bridge has no comparison, no rule and no failure of its own except the invalid-request one above.
5. Items are never normalized, trimmed, casefolded, reordered, deduplicated, filtered or rewritten. The structure holds the very string
   objects the request held, in the same order.
6. If the factory succeeds, the `GameProjectStructure` it returned is exposed as-is (same object, identity preserved).
7. If the factory reports failures, they are exposed unchanged (same codes, fields, messages, order) with `ok=False` and `structure=None`.
   They keep the factory's `GAME_PROJECT_STRUCTURE_` prefix; they are not re-coded and none is invented.
8. The request is never changed.

### Container adaptation (the one non-passthrough step)

The factory accepts only an exact `list` for a collection (a tuple is rejected), while `GameStructureRequest` stores each collection as a
`tuple`. Passing the tuples straight through would make every request fail. So the bridge hands the factory a FRESH `list` of each tuple's
items. This changes the container only: same items, same objects, same order. Neither the factory nor the request was modified to avoid it.

## Failure codes

Bridge-owned (prefix `GAME_STRUCTURE_REQUEST_BRIDGE_`): `GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST`. Everything else is a factory code
passed through unchanged. Because a `GameStructureRequest` is already validated at construction, the factory normally accepts what the
bridge gives it; propagation is exercised in tests by replacing the factory.

## Result protections

`GameStructureRequestBridgeResult` follows the Section 7 result conventions: `__slots__`, read-only attributes, not subclassable, direct
construction refused (`TypeError`), equal contents mean equal objects and equal hashes, `failures`, `codes()` and `to_dict()` return fresh
plain data on every call, `copy`/`deepcopy` return the same object, pickling is refused. The factory's own mutable
`GameProjectStructureResult` is not handed out.

## What this module does NOT do

It does NOT modify `GameStructureRequest`, `GameProjectStructure`, `GameCreationRequest`, any registry or the Prompt 741 bridge. It has no
runtime execution, no registry, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state, and
no wiring into `process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it. No existing production file was
modified. (Existing tests that pin the exact `game_creation/` package listing, the Prompt 718 exact-path exemption list, and two
"nothing else mentions this name" scans from Prompts 741/743 were updated only to name the one new module.)

## Scope note

Prompt 745 is not part of this one and was not started.
