# Prompt 766 - Section 8: Multimedia - Audio Operation Output Validator

Status: **implemented.** `multimedia/audio_operation_output_validator.py` (pinned by `tests/test_audio_operation_output_validator_prompt766.py`).

## What it does
`validate_audio_operation_output(plan, output)` checks that an `AudioOperationOutput` (Prompt 765) matches an `AudioOperationPlan` (Prompt 763). It only
compares metadata values. No audio is processed, decoded or encoded and no file is touched. It is the audio counterpart of
`validate_image_operation_output()` (Prompt 753), as a separate, unrelated type. No other production module was changed or made aware of it.

## Result
`AudioOperationOutputValidationResult` exposes `ok`, `plan`, `output`, `failures`, `codes()` and `to_dict()` (`{"ok", "plan", "output", "failures"}`).
Each failure is `{"code", "field", "message"}`.

## Order of checks
1. `plan` is not exactly an `AudioOperationPlan`: `ok=False`, `plan=None`, `output=None`, code `AUDIO_OPERATION_OUTPUT_VALIDATION_INVALID_PLAN`.
   `output` is not examined and nothing is cross-validated (even a valid output is not retained).
2. `output` is not exactly an `AudioOperationOutput`: `ok=False`, the exact valid `plan` is preserved, `output=None`, code
   `AUDIO_OPERATION_OUTPUT_VALIDATION_INVALID_OUTPUT`. Nothing is cross-validated.
3. Otherwise five pairs are compared, always in this fixed order, and every mismatch is reported:

| # | plan | output | code (prefix `AUDIO_OPERATION_OUTPUT_VALIDATION_`) |
|---|---|---|---|
| 1 | `audio_id` | `audio_id` | `AUDIO_ID_MISMATCH` |
| 2 | `operation` | `operation` | `OPERATION_MISMATCH` |
| 3 | `target_format` | `output_format` | `FORMAT_MISMATCH` |
| 4 | `duration_ms` | `duration_ms` | `DURATION_MS_MISMATCH` |
| 5 | `sample_rate` | `sample_rate` | `SAMPLE_RATE_MISMATCH` |

All five equal gives `ok=True`.

## Exactness and identity
Values are compared with `==` only: never trimmed, case-folded, coerced or aliased (`"WAV"` != `"wav"`, `"mp3 "` != `"mp3"`). Two different but equal
objects match. For valid supplied objects the result holds the very same objects (identity preserved), also when mismatches are reported.

## quality
`quality` exists only on the plan; the output model does not represent it, so it is neither validated nor inferred. Plans that differ only in
`quality` give the same outcome.

## Immutability
The result uses `__slots__`; assignment and deletion raise `AttributeError`; direct construction and subclassing raise `TypeError`; equality and hashing
are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises `TypeError`. `failures`, `codes()` and `to_dict()` return fresh
data on every call. The validator never raises for bad inputs and mutates neither input.

## What this module does NOT do
- It does NOT process, decode, encode or inspect audio, and does NOT touch the filesystem, network, a database, an AI model or any API.
- It does NOT validate `quality`, check the plan against an asset or registry, use a clock or randomness, or keep module-level mutable state.
- Its only imports are the plan and output types. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.

## Limitations
- The Prompt 764 executor still returns `not_implemented` and does not produce or validate outputs yet.
- Both-invalid input reports only `INVALID_PLAN` (plan takes precedence), unlike the image validator which reports both.
- Prompt 767 has NOT been started.
