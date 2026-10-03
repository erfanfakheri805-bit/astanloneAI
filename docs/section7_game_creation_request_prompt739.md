# Section 7 - Game Creation Request (Prompt 739)

Module: `app/src/main/python/game_creation/game_creation_request.py`

A small, immutable request model: the structured input a caller hands over when asking for a new game project. It checks and holds six
fields; it creates no project and no other state.

## Public API

```python
create_game_creation_request(data) -> GameCreationRequestResult
```

- `GameCreationRequestResult` exposes `ok`, `request` (`None` unless `ok`), `failures` (a FRESH list of FRESH `{"code", "field", "message"}`
  dicts), `codes()` and a FRESH `to_dict()` of `{"ok", "request", "failures"}`.
- `GameCreationRequest` exposes exactly the six read-only fields `project_id`, `name`, `description`, `genre`, `target_platform`, `version`
  and a FRESH `to_dict()` in that field order.

## Request behavior

| Field | Rule |
| --- | --- |
| `project_id` | exact `str`, not empty and not whitespace-only |
| `name` | exact `str`, not empty and not whitespace-only |
| `description` | exact `str`, may be empty |
| `genre` | exact `str`, may be empty |
| `target_platform` | exact `str`, may be empty |
| `version` | exact `str`, not empty and not whitespace-only |

- `data` must be an exact plain `dict`; dict subclasses and every other type are rejected.
- All six fields are required; missing and unexpected fields are rejected, never ignored or defaulted.
- Values are never trimmed, normalized, coerced or rewritten. The whitespace check only decides acceptance; the request holds the very string
  objects supplied (identity preserved). A `str` subclass is rejected.
- The caller's dict is only read, never changed. No `GameProject` is created or referenced.

## Failure codes

All prefixed `GAME_CREATION_REQUEST_`: `INVALID_INPUT`, `UNEXPECTED_FIELD`, `MISSING_FIELD`, `INVALID_PROJECT_ID`, `INVALID_NAME`,
`INVALID_DESCRIPTION`, `INVALID_GENRE`, `INVALID_TARGET_PLATFORM`, `INVALID_VERSION`.

All problems are reported together, in this fixed order: invalid input (alone, since nothing else can be checked); a non-`str` field name;
unexpected fields sorted by name; then the six fields in model order (missing, wrong type, or blank). `field` is `None` when no single field
applies. The factory never raises for bad data.

## Immutability and determinism

Both classes use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be constructed directly (`TypeError`). Equal
contents mean equal objects and equal hashes. `to_dict()`, `failures` and `codes()` return fresh plain data on every call. `copy` and
`deepcopy` return the same object; pickling is refused with `TypeError`. There is no module-level mutable state.

## Independence

The module imports nothing. It does not depend on the project model, the definition, registries, validators, queries, summaries or counts, so
it can serve as a future input boundary. It does NOT create a project, call any project factory, or mutate or create project state. It adds no
runtime, rendering, audio, asset loading, execution, networking, external AI API, filesystem generation, code generation or build/export
behavior, and is not wired into `process_input()`, Core, the Planner or the Agent Loop. No existing production file was modified.

## Scope note

Later Section 7 prompts (Prompt 740 onward) are not part of this one.
