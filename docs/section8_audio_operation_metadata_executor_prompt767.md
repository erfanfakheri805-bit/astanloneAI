# Prompt 767 - Section 8: Multimedia - Audio Operation Metadata Executor

Status: **implemented.** `multimedia/audio_operation_metadata_executor.py` (pinned by `tests/test_audio_operation_metadata_executor_prompt767.py`).

## What it does
`execute_audio_operation_metadata(plan)` is the first audio operation that really produces an `AudioOperationOutput` (Prompt 765): the safe,
metadata-only operation `"metadata"`. It only copies five plan values into an output. No audio is read, decoded, encoded, trimmed or written and no file is
touched. It mirrors `execute_image_operation_metadata()` (Prompt 754) as a separate, unrelated type. The Prompt 764 executor is unchanged and still returns
`not_implemented` for every plan; the Prompt 766 validator is unchanged.

## Result
`AudioOperationMetadataExecutionResult` exposes `ok`, `plan`, `output`, `failures`, `codes()` and `to_dict()` (`{"ok", "plan", "output", "failures"}`).
Each failure is `{"code", "field", "message"}`.

## Order of checks
1. `plan` is not exactly an `AudioOperationPlan`: `ok=False`, `plan=None`, `output=None`, `AUDIO_OPERATION_METADATA_EXECUTOR_INVALID_PLAN`
   (field `plan`). The object is never read.
2. `plan.operation != "metadata"` (exact match; no trimming, case-folding or aliases): `ok=False`, the exact valid plan preserved, `output=None`,
   `AUDIO_OPERATION_METADATA_EXECUTOR_UNSUPPORTED_OPERATION` (field `operation`).
3. The output is built only through the public `create_audio_operation_output()` factory, never by direct construction:

| output field | taken from |
|---|---|
| `audio_id` | `plan.audio_id` |
| `operation` | `plan.operation` |
| `output_format` | `plan.target_format` |
| `duration_ms` | `plan.duration_ms` |
| `sample_rate` | `plan.sample_rate` |

   Values are passed through unchanged (same `str`/`int` objects). If the factory fails, raises, or does not yield an exact `AudioOperationOutput`:
   `ok=False`, the exact valid plan preserved, `output=None`, `AUDIO_OPERATION_METADATA_EXECUTOR_OUTPUT_CREATION_FAILED` (field `output`).
4. Success: `ok=True`, the exact plan object (identity preserved), the created `AudioOperationOutput`, no failures.

Only these three executor-specific codes exist. `quality` is not part of the output model and is ignored. A successful output passes
`validate_audio_operation_output(plan, output)` (Prompt 766), which is covered by a test; this module does not import the validator.

## Immutability
The result uses `__slots__`; assignment and deletion raise `AttributeError`; direct construction and subclassing raise `TypeError`; equality and hashing
are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises `TypeError`. `failures`, `codes()` and `to_dict()` return fresh
data on every call. The function never raises for bad inputs, never mutates the plan and is deterministic.

## What this module does NOT do
- It does NOT process, decode, encode, trim, convert or mix audio, and does NOT touch the filesystem, network, subprocesses, a database, an AI model or any API.
- It does NOT use a clock or randomness or keep module-level mutable state. Its only imports are the plan type and the output type and factory.
- It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.

## Limitations
- Only `"metadata"` is supported; every other operation is rejected with `UNSUPPORTED_OPERATION`.
- The output reports the plan's values as-is; nothing checks them against a real asset or real audio.
- Prompt 768 has NOT been started.
