# Prompt 759 - Section 8: Multimedia - Audio Asset Contract

Status: **implemented.** `multimedia/audio_asset.py` (pinned by `tests/test_audio_asset_prompt759.py`). This starts the Audio portion of Section 8.

## What it represents
`AudioAsset` is an immutable record of the BASIC METADATA of one audio asset: `audio_id`, `name`, `description`, `format`, `duration_ms`, `sample_rate`.
It follows the public API and immutable-model conventions of `ImageAsset` (Prompt 746) but is a separate, unrelated type. It holds no samples and no location.

## Public API
- `create_audio_asset(data)` returns an `AudioAssetResult` with `ok`, `asset` (`None` unless `ok`), `failures`, `codes()` and `to_dict()`.
  It never raises for bad data and never changes the caller's dict.
- `AudioAsset`: read-only properties `audio_id`, `name`, `description`, `format`, `duration_ms`, `sample_rate`; `to_dict()` returns a FRESH plain dict in
  the fixed field order on every call; deterministic equality and hashing (exact type only); direct construction and subclassing refused
  (`TypeError`); `copy`/`deepcopy` return the same object; pickling refused (`TypeError`, as for `ImageAsset`); attribute assignment/deletion raises `AttributeError`.
- `AudioAssetResult.to_dict()` returns `{"ok", "asset", "failures"}` with fresh nested data.

## Validation rules
1. `data` must be exactly a plain `dict` (a dict subclass is rejected) with exactly the six keys.
2. All six fields are required; nothing is defaulted.
3. `audio_id`, `name`, `description` and `format` must be exactly `str` (no `str` subclass).
4. `audio_id`, `name` and `format` must be nonblank (`value.strip() != ""`).
5. `description` may be empty (or blank).
6. `duration_ms` and `sample_rate` must be exactly `int` and greater than zero. `bool`, `int` subclasses, `float`, `str` and everything else are rejected.
7. Missing and unexpected fields are rejected (an unexpected field is never ignored; a non-`str` or `str`-subclass key is unexpected).
8. Nothing is trimmed, normalized, coerced, reordered or mutated. The same `str` objects are stored (identity preserved). The caller's dict is only read.

Failures are reported together, in a fixed order: input, unexpected fields sorted by name, then the six fields in declared order.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `AUDIO_ASSET_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `AUDIO_ASSET_UNEXPECTED_FIELD` |
| missing field | `AUDIO_ASSET_MISSING_FIELD` |
| bad `audio_id` | `AUDIO_ASSET_INVALID_AUDIO_ID` |
| bad `name` | `AUDIO_ASSET_INVALID_NAME` |
| bad `description` | `AUDIO_ASSET_INVALID_DESCRIPTION` |
| bad `format` | `AUDIO_ASSET_INVALID_FORMAT` |
| bad `duration_ms` | `AUDIO_ASSET_INVALID_DURATION_MS` |
| bad `sample_rate` | `AUDIO_ASSET_INVALID_SAMPLE_RATE` |

Each failure is `{"code", "field", "message"}`; `field` is `None` for input-level and non-`str`-key problems. These nine are the only codes.

## What this module does NOT do
- It does NOT decode, play, process or inspect audio, detect or check the `format`, or validate `format`, `duration_ms` or `sample_rate` against known values.
- It has NO registry, request, executor, decoder or playback system.
- It does NOT read or write files, use the network, a database, subprocesses, an AI model or any API, a clock or randomness.
- It imports nothing (not even the standard library) and keeps no module-level mutable state.
- It is NOT linked to `ImageAsset`, to any Section 7 module (`GameAsset`, registries, `GameProject`), Core, `process_input()`, the Planner or the Agent Loop.
  No existing production module was modified.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-758) and the Prompt 718 frozen-tree exemption list now also list
the new module; no production module changed. Prompt 760 has **not** been started.
