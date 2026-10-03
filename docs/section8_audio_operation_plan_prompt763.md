# Prompt 763 - Section 8: Multimedia - Audio Operation Plan

Status: **implemented.** `multimedia/audio_operation_plan.py` (pinned by `tests/test_audio_operation_plan_prompt763.py`).

## What it does
`create_audio_operation_plan(validation_result)` converts a successful `AudioOperationValidationResult` (Prompt 762) into an immutable
`AudioOperationPlan`: an execution description of one future audio operation. It only describes. Nothing is executed, decoded, encoded or
converted, and no file is touched. The Prompt 759-762 production modules and Section 7 are unchanged and unaware of it. It follows the
architecture of `ImageOperationPlan` (Prompt 750) as a separate, unrelated type.

## Public API
- `create_audio_operation_plan(validation_result)` returns an `AudioOperationPlanResult` with `ok`, `plan` (`None` unless `ok`), `failures`,
  `codes()` and `to_dict()`. It never raises for bad inputs and never changes what it is given.
- `AudioOperationPlan` holds exactly six values, in this fixed order: `audio_id`, `operation`, `target_format`, `duration_ms`, `sample_rate`,
  `quality`. Read-only properties and a fresh `to_dict()`; nothing else.

## Rules
1. `validation_result` must be exactly an `AudioOperationValidationResult`. A subclass-like object, `None`, a `dict` or the request itself is
   rejected without being read: `AUDIO_OPERATION_PLAN_INVALID_VALIDATION_RESULT`.
2. It must have `ok=True`; otherwise `AUDIO_OPERATION_PLAN_VALIDATION_FAILED` (the message names the validation codes) and no plan is created.
   This also holds for an `AUDIO_NOT_FOUND` result that still carries a request.
3. On success the six values are copied exactly from the validated request: the same `str` and `int` objects (identity preserved). Nothing is
   normalized, trimmed, case-folded, coerced, reordered or reinterpreted. `operation` and `target_format` stay free text.
4. The plan does not keep the `AudioAsset`, the registry, the request or the validation result, so it has no link back to any of them.

| problem | code |
|---|---|
| `validation_result` is not exactly an `AudioOperationValidationResult` | `AUDIO_OPERATION_PLAN_INVALID_VALIDATION_RESULT` |
| `validation_result.ok` is false | `AUDIO_OPERATION_PLAN_VALIDATION_FAILED` |

Each failure is `{"code", "field", "message"}` with `field` always `validation_result`.

## Immutability
`AudioOperationPlan` and `AudioOperationPlanResult` use `__slots__`; assignment and deletion raise `AttributeError`; direct construction and
subclassing raise `TypeError`; equality and hashing are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises
`TypeError` (consistent with every other multimedia plan/result model). `to_dict()` and `failures` return fresh data on every call. Repeated
creation from the same validation result gives equal results (and hashes) but separate objects.

## What this module does NOT do
- It does NOT execute, process, decode, encode, trim, convert or inspect audio, and it does NOT touch the filesystem, network, a database, an AI
  model or any API.
- It does NOT re-validate the request, look anything up in a registry, or compare the requested duration, sample rate or format with the real asset.
- It does NOT interpret `operation` or `target_format`, use a clock or randomness, or keep module-level mutable state. Its only import is the
  Prompt 762 result type. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop or Section 7.

## Limitations
- The plan is deliberately the same six values as the request; it adds no steps, ordering, output name or capability checks.
- `ok` of the validation result is trusted as produced by Prompt 762; a validation result cannot be forged because it cannot be built directly.
- There is no executor: nothing consumes a plan yet. Prompt 764 has NOT been started.
