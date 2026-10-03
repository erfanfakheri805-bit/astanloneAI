# Prompt 721 - Section 7: Game Project Structure

Status: **implemented.** `game_creation/game_project_structure.py`, pinned by `tests/test_game_project_structure_prompt721.py`.

## What GameProjectStructure represents
The main structural components of one game project as four ordered collections of string identifiers: `scenes`, `characters`,
`gameplay_systems` and `assets`. It is a small immutable in-memory value object built only by `create_game_project_structure(data)`, which
returns a `GameProjectStructureResult(ok, structure, failures)`. It uses the same pattern as `GameProject` (Prompt 720): token-guarded
construction, `__slots__`, read-only, not subclassable, fresh `to_dict()`, pickling refused. The `GameProject` API is unchanged and the two
records are not linked yet.

## Validation
- `data` must be a plain `dict` (dict subclasses rejected) with exactly the four fields; missing fields are rejected (nothing is defaulted),
  unexpected fields are rejected (never ignored).
- Each field must be exactly a `list` (tuples, sets, generators, list subclasses are rejected, never coerced). An empty list is valid.
- Every item must be exactly a `str`, not blank (`strip() != ""`), and unique within its collection (exact comparison). Identifiers are never
  trimmed or case-folded; input order is preserved. The same identifier may appear in different collections.
- The factory never raises for bad data: it reports all problems at once in a fixed order with stable codes (`FAILURE_CODES`).

## Immutability
Collections are copied into tuples, so later edits to the caller's lists never reach the structure, and the accessors (`scenes`, `characters`,
`gameplay_systems`, `assets`) return those tuples. `to_dict()` returns a fresh dict of fresh lists in fixed field order and round-trips through
the factory. Equal data gives equal objects and equal hashes (order matters).

## Why identifiers only, for now
This step only fixes the shape of a project: what it is made of, and that every part has a unique, stable name. Deciding what a scene, character,
gameplay system or asset actually contains is a separate design question for each, so those objects are deliberately NOT defined yet. Storing
validated identifiers keeps this record small, deterministic and cheap to change, and gives later prompts stable names to refer to.

## How later Section 7 prompts can expand the identifiers
A future prompt can define a richer domain model for one kind (for example a scene description) with its own validated factory, and use an
identifier from this structure as its key. A later step can then check that every identifier in a structure has a matching detailed object, or
build the structure from those objects. Each expansion can be added on its own without changing this record, because the identifiers are the
only contract between them.

## What it does NOT do
No scene/character/gameplay-system/asset objects, no check that an identifier refers to anything, no game code or asset generation, no engine
(Unity/Godot) dependency, no filesystem, network, database or AI access, no registry or persistence, and no wiring into `process_input`, Core,
the Planner or the Agent Loop.

## Limitations noted
- Identifiers are free text (any non-blank string); no naming scheme is imposed.
- Duplicate detection is exact (`"a"` and `"A"` are different identifiers).
- The Prompt 720 test that listed the `game_creation/` files was updated to include the new module (test code only).
