# Prompt 724 - Section 7: Game Character Registry

Status: **implemented.** `game_creation/game_character_registry.py`, pinned by `tests/test_game_character_registry_prompt724.py`.

## What GameCharacterRegistry represents
An immutable, ordered collection of `GameCharacter` definitions (Prompt 723) with lookup by exact `character_id`, optionally checked against
the character identifiers listed by a `GameProjectStructure` (Prompt 721). It is the first relationship layer in Section 7: the structure names
which characters a project has, and the registry holds their definitions. Both existing records are unchanged and remain unaware of it.

## API
- `create_game_character_registry(characters, structure=None)` returns a `GameCharacterRegistryResult` with `ok`, `registry`, `failures`,
  `codes()` and `to_dict()`. It never raises for bad input.
- `GameCharacterRegistry`: `characters` and `character_ids` (tuples, registration order), `lookup(character_id)`, `to_dict()` (fresh data),
  deterministic equality and hashing. Direct construction and subclassing are refused; attributes are read-only; pickling is refused.
- `lookup()` returns a `GameCharacterLookupResult(found, character, code)`. A missing id (or a non-`str` id) gives `found=False` and the stable
  code `GAME_CHARACTER_REGISTRY_CHARACTER_NOT_FOUND`; it never raises.

## Validation and failure codes
| problem | code |
|---|---|
| `characters` is not exactly a `list` or `tuple` | `..._INVALID_COLLECTION` |
| an item is not exactly a `GameCharacter` | `..._INVALID_CHARACTER` |
| a `character_id` repeats (exact comparison) | `..._DUPLICATE_CHARACTER_ID` |
| `structure` is neither `None` nor a `GameProjectStructure` | `..._INVALID_STRUCTURE` |
| an id in `structure.characters` has no registered character | `..._MISSING_CHARACTER_REFERENCE` |

All codes are prefixed `GAME_CHARACTER_REGISTRY_`. Problems are reported together, in a fixed order: collection problems by position, then the
structure, then missing references in `structure.characters` order. The reference check runs only for a valid structure. Nothing is coerced,
trimmed or reordered; input order is kept. Unused definitions (registered characters the structure does not list) are allowed. The structure is
used only for validation and is not stored, so a registry built with and without a structure is equal.

## What it intentionally does NOT do yet
No scene, asset or gameplay-system relationships; no character content (health, stats, abilities, inventory, weapons, AI, dialogue,
animation, models, audio); no global registry, persistence, filesystem, network, database or AI access; no wiring into `process_input`, Core,
the Planner or the Agent Loop. It does not check the other structure collections (`scenes`, `gameplay_systems`, `assets`).

## How later prompts can build on it
Later Section 7 prompts can follow the same pattern for other collections (for example a scene registry checked against
`structure.scenes`) and a later step can combine the registries into one validated project view. Richer character capabilities can refer to
registered characters by `character_id`. Because the registry only holds immutable `GameCharacter` objects and exposes exact-id lookup, such
additions do not need to change this module.

## Limitations noted
- Only `list` and `tuple` inputs are accepted (an unordered collection cannot give a deterministic order).
- Lookup is a linear scan; the registry is meant for small collections.
- Ids are compared exactly, so `"Hero"` and `"hero"` are different characters.
- Referenced-but-missing characters are the only structure check; unused registered characters are not reported.
