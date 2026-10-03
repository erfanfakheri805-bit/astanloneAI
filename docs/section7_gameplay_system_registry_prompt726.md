# Prompt 726 - Section 7: Gameplay System Registry

Status: **implemented.** `game_creation/gameplay_system_registry.py`, pinned by `tests/test_gameplay_system_registry_prompt726.py`.

## What GameplaySystemRegistry represents
An immutable, ordered collection of gameplay-system **identifiers** (plain strings) with lookup by exact id, optionally checked against the
gameplay-system identifiers listed by a `GameProjectStructure` (Prompt 721). It follows the registry pattern of Prompts 724 and 725, except that
a gameplay system has no record type yet, so the registry holds only names. No gameplay system is implemented. All earlier Section 7 modules
are unchanged and remain unaware of it.

## API
- `create_gameplay_system_registry(gameplay_systems, structure=None)` returns a `GameplaySystemRegistryResult` with `ok`, `registry`,
  `failures`, `codes()` and `to_dict()`. It never raises for bad input.
- `GameplaySystemRegistry`: `gameplay_system_ids` (tuple, registration order), `lookup(system_id)`, `to_dict()` (fresh
  `{"gameplay_systems": [...]}`), deterministic equality and hashing. Direct construction and subclassing are refused; attributes are read-only;
  copy returns the same object; pickling is refused.
- `lookup()` returns a `GameplaySystemLookupResult(found, system_id, code)`. A missing id (or a non-`str` id) gives `found=False` and the stable
  code `GAMEPLAY_SYSTEM_REGISTRY_GAMEPLAY_SYSTEM_NOT_FOUND`; it never raises.

## Validation and failure codes
| problem | code |
|---|---|
| `gameplay_systems` is not exactly a `list` or `tuple` | `..._INVALID_COLLECTION` |
| an item is not exactly a `str`, or is empty/blank | `..._INVALID_GAMEPLAY_SYSTEM` |
| an id repeats (exact comparison) | `..._DUPLICATE_GAMEPLAY_SYSTEM_ID` |
| `structure` is neither `None` nor a `GameProjectStructure` | `..._INVALID_STRUCTURE` |
| an id in `structure.gameplay_systems` is not registered | `..._MISSING_GAMEPLAY_SYSTEM_REFERENCE` |
| lookup of an unknown or non-string id (lookup only) | `..._GAMEPLAY_SYSTEM_NOT_FOUND` |

All codes are prefixed `GAMEPLAY_SYSTEM_REGISTRY_`. Problems are reported together, in a fixed order: collection problems by position, then the
structure, then missing references in `structure.gameplay_systems` order. The reference check runs only for a valid structure and counts only
ids that were accepted. Nothing is coerced, trimmed, case-folded or reordered: `"Combat"` and `"combat"` are distinct ids. Unused registered ids
are allowed. The structure is used only for validation and is not stored, so a registry built with and without a structure is equal.

## What it intentionally does NOT do yet
No gameplay-system implementation or content (combat, health, inventory, weapons, quests, progression, physics, AI, input handling, rendering,
animation, audio); no scene loading, game-engine dependency, persistence, filesystem, network, database or AI access; no wiring into
`process_input`, Core, the Planner or the Agent Loop. It does not check the other structure collections (`scenes`, `characters`, `assets`).

## How later prompts can build on it
A later step can check the asset identifiers the same way, or combine the character, scene and gameplay-system registries into one validated
project view. A later gameplay-system record type could be registered by id without changing the identifier rules here.

## Limitations noted
- Only `list` and `tuple` inputs are accepted (an unordered collection cannot give a deterministic order).
- Lookup is a linear scan; the registry is meant for small collections.
- Ids are compared exactly and kept as given.
- Blank and non-string items share one failure code (`INVALID_GAMEPLAY_SYSTEM`); the message tells them apart.
- Referenced-but-missing ids are the only structure check; unused registered ids are not reported.
