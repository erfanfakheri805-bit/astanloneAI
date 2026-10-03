# Prompt 765 - Section 8: Multimedia - Audio Operation Output Result Contract

Status: **implemented.** `multimedia/audio_operation_output.py` (pinned by `tests/test_audio_operation_output_prompt765.py`).

## What it represents
`AudioOperationOutput` is an immutable record of the **metadata of one future, successful audio operation output**. It only describes. No audio is
processed, decoded, encoded or written, and no file is touched. The Prompt 759-764 production modules, the image modules and Section 7 are unchanged and
unaware of it. It mirrors `ImageOperationOutput` (Prompt 752) as a separate, unrelated type.

## Public API
- `create_audio_operation_output(data)` returns an `AudioOperationOutputResult` with `ok`, `output` (`None` unless `ok`), `failures`, `codes()` and
  `to_dict()`. It never raises for bad data and never changes what it is given.
- `AudioOperationOutput` holds exactly five values, in this fixed order: `audio_id`, `operation`, `output_format`, `duration_ms`, `sample_rate`.
  Read-only properties and a fresh `to_dict()`; nothing else.

## Input rules
`data` must be an exact `dict` (a `dict` subclass is rejected) with exactly the five fields; all are required, none are defaulted.

| field | rule |
|---|---|
| `audio_id`, `operation`, `output_format` | exact `str`, not empty (`value != ""`) |
| `duration_ms`, `sample_rate` | exact `int`, greater than zero; `bool`, `int` subclasses, `float`, `str` and everything else are rejected |

Values are never normalized, trimmed, case-folded, coerced or reordered. A whitespace-only string is non-empty and is accepted unchanged. The very same
`str` and `int` objects are stored (identity preserved). `operation` and `output_format` are free text: there is no list of allowed operations or formats.

## Failure codes
All have the prefix `AUDIO_OPERATION_OUTPUT_`. Each failure is `{"code", "field", "message"}`; `field` is `None` for `INVALID_INPUT` and for a non-`str` field name.

| problem | code |
|---|---|
| `data` is not an exact `dict` | `INVALID_INPUT` |
| a required field is absent | `MISSING_FIELD` |
| a field name that is not one of the five (or not a `str`) | `UNEXPECTED_FIELD` |
| bad `audio_id` / `operation` / `output_format` | `INVALID_AUDIO_ID` / `INVALID_OPERATION` / `INVALID_OUTPUT_FORMAT` |
| bad `duration_ms` / `sample_rate` | `INVALID_DURATION_MS` / `INVALID_SAMPLE_RATE` |

Every problem is reported at once, in a fixed order: input, unexpected fields sorted by name, then the five fields in order.

## Immutability
`AudioOperationOutput` and `AudioOperationOutputResult` use `__slots__`; assignment and deletion raise `AttributeError`; direct construction and
subclassing raise `TypeError`; equality and hashing are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises
`TypeError`. `to_dict()` and `failures` return fresh data on every call. Repeated creation from equal data gives equal results (and hashes) but
separate objects.

## What this model does NOT contain or do
- It does NOT contain a file path, audio bytes, a filesystem object, an `AudioAsset`, an `AudioOperationPlan`, a registry or any external resource.
- It does NOT process, decode, encode, trim, convert or inspect audio, and does NOT touch the filesystem, network, a database, an AI model or any API.
- It does NOT check the values against any plan, asset or real audio, use a clock or randomness, or keep module-level mutable state. It imports nothing
  and is NOT wired into Core, `process_input()`, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.

## Limitations
- Nothing produces or consumes an output yet: the Prompt 764 executor still returns `not_implemented` and does not reference this model.
- The model says nothing about where audio lives or how it was produced; storage and linkage belong to later prompts.
- Prompt 766 has NOT been started.
