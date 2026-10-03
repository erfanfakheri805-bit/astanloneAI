# Section 7 - Game Structure Request (Prompt 743)

Module: `app/src/main/python/game_creation/game_structure_request.py`

A small, immutable request model: the actual game structure data a caller hands over (which scenes, characters, gameplay systems and assets a
game should contain). It checks and holds four collections; it creates no project, structure or definition.

## Public API

```python
create_game_structure_request(data) -> GameStructureRequestResult
```

- `GameStructureRequestResult` exposes `ok`, `request` (`None` unless `ok`), `failures` (a FRESH list of FRESH `{"code", "field", "message"}`
  dicts), `codes()` and a FRESH `to_dict()` of `{"ok", "request", "failures"}`.
- `GameStructureRequest` exposes exactly the four read-only fields `scenes`, `characters`, `gameplay_systems`, `assets` (each a `tuple`) and a
  FRESH `to_dict()` of fresh lists in that field order.

## Request behavior

| Field | Rule |
| --- | --- |
| `scenes` | exact `list` or exact `tuple` of unique, non-blank, exact `str` items; may be empty |
| `characters` | same |
| `gameplay_systems` | same |
| `assets` | same |

- `data` must be an exact plain `dict`; dict subclasses and every other type are rejected.
- All four fields are required; missing and unexpected fields are rejected, never ignored or defaulted.
- A collection must be exactly a `list` or exactly a `tuple`; list/tuple subclasses (including namedtuples) and every other type are rejected.
- Every item must be exactly a `str` that is not empty and not whitespace-only. A `str` subclass is rejected.
- Items must be unique within their own collection (exact comparison: `"A"` and `"a"`, or `"a"` and `" a"`, are different). The same item may
  appear in different collections.
- Input order is preserved. Nothing is trimmed, normalized, casefolded, coerced or deduplicated; the whitespace check only decides acceptance.
  The request holds the very string objects supplied (identity preserved), in a fresh tuple per field.
- The caller's dict and collections are only read, never changed, and later changes to them never affect the request.

## Failure codes

All prefixed `GAME_STRUCTURE_REQUEST_`: `INVALID_INPUT`, `UNEXPECTED_FIELD`, `MISSING_FIELD`, `INVALID_COLLECTION`, `INVALID_ITEM`,
`DUPLICATE_ITEM`.

All problems are reported together, in this fixed order: invalid input (alone, since nothing else can be checked); a non-`str` field name
(`UNEXPECTED_FIELD`, `field` None); unexpected fields sorted by name; then the four fields in model order (`scenes`, `characters`,
`gameplay_systems`, `assets`), each either `MISSING_FIELD`, or `INVALID_COLLECTION`, or its items in position order (`INVALID_ITEM` for a
non-`str` or blank item, `DUPLICATE_ITEM` for every later occurrence of an already-seen valid item). Item messages name the item position.
`field` is `None` when no single field applies. The factory never raises for bad data.

## Immutability and determinism

Both classes use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`). Equal
contents mean equal objects and equal hashes. `to_dict()`, `failures` and `codes()` return fresh plain data on every call. `copy` and
`deepcopy` return the same object; pickling is refused with `TypeError`. There is no module-level mutable state.

## Independence

The module imports nothing. It does NOT create or depend on `GameCreationRequest`, `GameProjectStructure`, `GameProject`, any definition,
registry, validator, query, summary or count object, and no existing module knows it. It does NOT modify `GameCreationRequest`,
`GameProjectStructure` or any existing registry, adds no runtime integration, and is not wired into `process_input()`, Core, the Planner or the
Agent Loop. No existing production file was modified. (Existing tests that pin the exact `game_creation/` package listing, and the Prompt 718
guard's exact-path exemption list, were updated only to name the one new module.)

## Scope note

Prompt 744 is not part of this one and was not started.
