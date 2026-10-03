# Prompt 723 - Section 7: Game Character Foundation

Status: **implemented.** `game_creation/game_character.py`, pinned by `tests/test_game_character_prompt723.py`.

## What GameCharacter represents
The basic metadata of one game character and nothing more: `character_id`, `name`, `description`, `role`. It is a small immutable in-memory
value object built only by `create_game_character(data)`, which returns a `GameCharacterResult(ok, character, failures)`. It follows the same
pattern as `GameProject` (720), `GameProjectStructure` (721) and `GameScene` (722): token-guarded construction, `__slots__`, read-only, not
subclassable, fresh `to_dict()`, pickling refused. The three existing records are unchanged.

## Validation
| field | rule |
|---|---|
| `character_id`, `name`, `role` | exactly `str`, not empty and not blank (`strip() != ""`) |
| `description` | exactly `str`, may be empty |
| anything else | rejected as an unexpected field (`GAME_CHARACTER_UNEXPECTED_FIELD`) |

`data` must be a plain `dict` (dict and `str` subclasses are rejected) and all four fields must be present; nothing is defaulted, coerced or
trimmed. The factory never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by name,
then the fields in declared order), with stable codes (`FAILURE_CODES`). Equal data gives equal objects and hashes; `to_dict()` is the
deterministic, fresh serialization.

## What it intentionally does NOT represent yet
No health, stats, abilities, inventory, weapons, AI behavior, dialogue, animation, skeletal data, 2D/3D models, textures, audio or rendering,
and nothing engine-specific. `role` is free text with no fixed vocabulary (for example "protagonist" or "merchant" are just strings). A
`GameCharacter` is not linked to `GameProject`, `GameProjectStructure` or `GameScene`: nothing checks that its `character_id` appears in a
structure's `characters`, or places it in a scene, and no registry or persistence exists. It is not wired into `process_input`, Core, the
Planner or the Agent Loop, and uses no filesystem, network, subprocess or AI access.

## How later prompts can build on it
Later Section 7 prompts can add richer character capabilities as separate small validated models that refer to a `character_id`: for example
attributes, appearance, or behavior descriptions, each with its own factory. A later step can check that character ids match the `characters`
identifiers of a `GameProjectStructure`, or relate characters to scenes by id. Because identity is just `character_id`, these additions do not
need to change this record.

## Limitations noted
- `role` accepts any non-blank string; no vocabulary exists yet.
- A whitespace-only `description` is accepted (only the three required fields are checked for blankness).
- Values are stored exactly as given, so `"Hero"` and `"hero"` are different ids.
