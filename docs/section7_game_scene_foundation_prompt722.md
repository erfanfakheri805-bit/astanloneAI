# Prompt 722 - Section 7: Game Scene Foundation

Status: **implemented.** `game_creation/game_scene.py`, pinned by `tests/test_game_scene_prompt722.py`.

## What GameScene represents
The basic metadata of one game scene and nothing more: `scene_id`, `name`, `description`, `scene_type`. It is a small immutable in-memory
value object built only by `create_game_scene(data)`, which returns a `GameSceneResult(ok, scene, failures)`. It follows the same pattern as
`GameProject` (Prompt 720) and `GameProjectStructure` (Prompt 721): token-guarded construction, `__slots__`, read-only, not subclassable,
fresh `to_dict()`, pickling refused. Both existing records are unchanged.

## Validation
| field | rule |
|---|---|
| `scene_id`, `name`, `scene_type` | exactly `str`, not empty and not blank (`strip() != ""`) |
| `description` | exactly `str`, may be empty |
| anything else | rejected as an unexpected field (`GAME_SCENE_UNEXPECTED_FIELD`) |

`data` must be a plain `dict` (dict and `str` subclasses are rejected) and all four fields must be present; nothing is defaulted, coerced or
trimmed. The factory never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by name,
then the fields in declared order), with stable codes (`FAILURE_CODES`). Equal data gives equal objects and hashes; `to_dict()` is the
deterministic, fresh serialization.

## What it intentionally does NOT represent yet
No scene objects or entities, transforms, maps, lighting, physics, AI, scripting, rendering or assets, and nothing engine-specific (no
Unity/Godot concepts). `scene_type` is free text with no fixed vocabulary. A `GameScene` is not linked to `GameProject` or
`GameProjectStructure`: nothing checks that its `scene_id` appears in a structure's `scenes`, and no registry or persistence exists. It is not
wired into `process_input`, Core, the Planner or the Agent Loop, and uses no filesystem, network, subprocess or AI access.

## How later prompts can build on it
Later Section 7 prompts can attach richer scene capabilities by taking a `GameScene` (or its `scene_id`) as their key, each as its own small
validated model: for example scene contents, layout, or lighting described as separate records that refer to a `scene_id`. A later step can
check that scene ids match the `scenes` identifiers of a `GameProjectStructure`, or assemble scenes into a project. Because the identity is
just `scene_id`, these additions do not need to change this record.

## Limitations noted
- `scene_type` accepts any non-blank string; no vocabulary exists yet.
- A whitespace-only `description` is accepted (only the three required fields are checked for blankness).
- Values are stored exactly as given, so `"Level"` and `"level"` are different ids.
