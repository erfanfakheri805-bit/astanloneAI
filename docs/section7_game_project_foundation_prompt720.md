# Prompt 720 - Section 7: Game Project Foundation

Status: **implemented.** `game_creation/game_project.py`, pinned by `tests/test_game_project_prompt720.py`.

## What GameProject represents
The basic identity and configuration of one game project, nothing more: `project_id`, `name`, `description`, `genre`, `target_platform`,
`version`. It is a small immutable in-memory value object built only by `create_game_project(data)`, which returns a
`GameProjectResult(ok, project, failures)`. It follows the same pattern as the Section 5/6 data records (token-guarded construction,
`__slots__`, read-only, not subclassable, fresh `to_dict()`), but lives in its own package `game_creation/` so Section 7 work stays separate
from Sections 1-6 (no existing module was changed).

## Validation
| field | rule |
|---|---|
| `project_id`, `name`, `version` | exactly `str`, not empty and not blank |
| `description`, `genre`, `target_platform` | exactly `str`, may be empty |
| anything else | rejected as an unexpected field (`GAME_PROJECT_UNEXPECTED_FIELD`) |

All six fields must be present (no defaults are invented). `data` must be a plain `dict`; `str` and `dict` subclasses are rejected. Values are
stored exactly as given (never trimmed). The factory never raises for bad data: it reports all problems at once, in a fixed order, with stable
codes. Equal data gives equal objects and hashes; `to_dict()` is the deterministic serialization; pickling is refused.

## What it intentionally does NOT do yet
No game engine, no code or asset generation, no rendering/audio/video, no Unity/Godot dependency, no AI model, no filesystem, network or
database access, no project registry or persistence, no fixed genre/platform/version vocabulary, no wiring into `process_input`, Core, the
Planner or the Agent Loop, no automatic execution or self-modification.

## How future stages can build on it
Later Section 7 capabilities can take a `GameProject` (or its `to_dict()`) as their identity input - for example a design document, a scene or
level description, or a build configuration can reference `project_id` and `version` and reuse the same validated-factory pattern - without
changing this record. Any vocabulary for genres or platforms, persistence, or links to the Section 6 tool-step path would be added by those
stages explicitly, each as its own small prompt.

## Limitations noted
- `genre` and `target_platform` accept any string (including empty) because no vocabulary exists yet.
- "Blank" (whitespace-only) is rejected for the three required fields as a reading of "non-empty"; other fields are not checked for blankness.
