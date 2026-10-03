# Prompt 761 - Section 8: Multimedia - Audio Operation Request

Status: **implemented.** `multimedia/audio_operation_request.py` (pinned by `tests/test_audio_operation_request_prompt761.py`).

## What it represents
`AudioOperationRequest` is a small, immutable, in-memory record describing ONE future audio operation. It only describes and validates; it does NOT
perform any operation. It follows the conventions of `ImageOperationRequest` (Prompt 748) but is a separate type with no link to it, to `AudioAsset`
(Prompt 759) or to `AudioAssetRegistry` (Prompt 760), which are unchanged and unaware of it.

## Public API
- `create_audio_operation_request(data)` returns an `AudioOperationRequestResult` with `ok`, `request` (`None` unless `ok`), `failures`, `codes()` and
  `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `AudioOperationRequest` has exactly six read-only fields in this fixed order: `audio_id`, `operation`, `target_format`, `duration_ms`, `sample_rate`,
  `quality`, plus `to_dict()`, which returns a FRESH plain dict on every call.

## Field rules (`data` must be an exact `dict` with exactly these six keys)
| field | rule |
|---|---|
| `audio_id` | exact `str`, not empty (`""` rejected) |
| `operation` | exact `str`, not empty; validated free text, no list of allowed operations yet |
| `target_format` | exact `str`; the empty string IS allowed; any text, no fixed format list |
| `duration_ms` | exact `int` (never `bool`), greater than zero |
| `sample_rate` | exact `int` (never `bool`), greater than zero |
| `quality` | exact `int` (never `bool`), 1 through 100 inclusive |

"Not empty" means `value != ""`. Values are never trimmed, case-folded, coerced, reordered or otherwise changed, so a whitespace-only `audio_id` or
`operation` is accepted exactly as given. The very same `str` objects are stored (identity preserved). `str` and `int` subclasses, `float`, `bool`,
`None` and every other type are rejected, so no caller-supplied method is ever run. Unexpected keys (including non-`str` keys) are rejected, never
ignored; a missing key is never defaulted.

## Failure codes
Each failure is `{"code", "field", "message"}`. These nine are the only codes.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `AUDIO_OPERATION_REQUEST_INVALID_INPUT` |
| a required key is missing | `AUDIO_OPERATION_REQUEST_MISSING_FIELD` |
| an unexpected key is present | `AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD` |
| bad `audio_id` | `AUDIO_OPERATION_REQUEST_INVALID_AUDIO_ID` |
| bad `operation` | `AUDIO_OPERATION_REQUEST_INVALID_OPERATION` |
| bad `target_format` | `AUDIO_OPERATION_REQUEST_INVALID_TARGET_FORMAT` |
| bad `duration_ms` | `AUDIO_OPERATION_REQUEST_INVALID_DURATION_MS` |
| bad `sample_rate` | `AUDIO_OPERATION_REQUEST_INVALID_SAMPLE_RATE` |
| bad `quality` | `AUDIO_OPERATION_REQUEST_INVALID_QUALITY` |

All problems are reported together in a fixed order: input, unexpected keys sorted by name, then the six fields in field order.

## Immutability and determinism
`__slots__`; attribute assignment/deletion raises `AttributeError`; direct construction and subclassing raise `TypeError`; equality and hashing are by
value (exact type only); `copy`/`deepcopy` return the same object; pickling is refused (`TypeError`), exactly as for `ImageOperationRequest`.
Repeated calls with equal input give equal results.

## What this module does NOT do
It does NOT decode, encode, process or inspect audio, handle waveforms, touch the filesystem, use the network, a database, an AI model or any external
service, check that `audio_id` names a registered asset, know which operations or formats exist, or check that `duration_ms`/`sample_rate` fit any
asset. It has no executor, no automatic execution and no Core, Planner or Agent Loop integration, and it imports nothing. Prompt 762 is NOT part of
this prompt and was not started.
