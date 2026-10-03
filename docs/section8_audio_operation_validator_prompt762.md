# Prompt 762 - Section 8: Multimedia - Audio Operation Validator

Status: **implemented.** `multimedia/audio_operation_validator.py` (pinned by `tests/test_audio_operation_validator_prompt762.py`).

## What it answers
One question: does an `AudioOperationRequest` (Prompt 761) name an audio asset that is registered in an `AudioAssetRegistry` (Prompt 760)? It mirrors the
architecture of the image operation validator (Prompt 749) but is a separate type with no link to any image module. Prompts 759-761 are unchanged and
unaware of it.

## Public API
- `validate_audio_operation_request(request, audio_registry)` returns an `AudioOperationValidationResult`. It never raises for bad inputs and changes
  nothing it is given.
- `AudioOperationValidationResult` has `ok`, `request`, `registry`, `failures`, `codes()` and `to_dict()`.
  - `ok` is derived from `failures` (true only when there are none).
  - `request` / `registry` hold the very objects that were passed in (identity preserved), each only when it was a valid input of the exact type;
    otherwise `None`. An invalid input is never stored, so a result is always hashable.
  - `failures` is a tuple of FRESH `{"code", "field", "message"}` dicts; `codes()` and `to_dict()` return fresh data on every call.
  - `to_dict()` is `{"ok", "request", "registry", "failures"}` with the request and registry converted through their own `to_dict()` (or `None`).

## Order of checks
1. `request` must be exactly an `AudioOperationRequest` (a subclass, `None`, a dict, an `AudioAsset`, an image request ... is rejected).
2. `audio_registry` must be exactly an `AudioAssetRegistry`.
3. If either is invalid, NO cross-validation happens: the registry's `lookup()` is never called. Both top-level problems are reported together,
   request first.
4. Otherwise `request.audio_id` is resolved ONLY through the registry's public `lookup()`; no lookup logic is duplicated and no private state is read.
   A `found` result whose asset is not exactly an `AudioAsset` is not trusted.
5. Not registered -> `AUDIO_NOT_FOUND`. Registered -> `ok`.

## Failure codes
These three are the only codes (prefix `AUDIO_OPERATION_VALIDATION_`).

| problem | code | field |
|---|---|---|
| `request` is not exactly an `AudioOperationRequest` | `AUDIO_OPERATION_VALIDATION_INVALID_REQUEST` | `request` |
| `audio_registry` is not exactly an `AudioAssetRegistry` | `AUDIO_OPERATION_VALIDATION_INVALID_AUDIO_REGISTRY` | `audio_registry` |
| `request.audio_id` is not registered | `AUDIO_OPERATION_VALIDATION_AUDIO_NOT_FOUND` | `audio_id` |

## Rules
- Exact types and exact id matching only: nothing is trimmed, case-folded, normalized or coerced.
- `operation`, `target_format`, `duration_ms`, `sample_rate` and `quality` are NOT examined beyond Prompt 761, and nothing is compared with the registered
  asset. Format, duration, sample-rate and quality validation are left to a future layer.
- The result is immutable (`__slots__`, assignment/deletion raises), cannot be built directly or subclassed (`TypeError`), compares and hashes by value
  (`request`, `registry`, `failures`; exact type only), returns itself from `copy`/`deepcopy`, and refuses pickling (`TypeError`), as the image
  validation result does.

## What this module does NOT do
It does NOT decode, encode or process audio, touch the filesystem, use the network, a database, an AI model or any external service, check any
audio property against the asset, execute anything, or integrate with Core, the Planner, the Agent Loop or Section 7. It imports only the Prompt
759-761 modules. Prompt 763 is NOT part of this prompt and was not started.
