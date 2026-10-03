# Prompt 750 - Section 8: Multimedia - Image Operation Plan

Status: **implemented.** `multimedia/image_operation_plan.py` (pinned by `tests/test_image_operation_plan_prompt750.py`).

## What it does
`create_image_operation_plan(validation_result)` converts a successful `ImageOperationValidationResult` (Prompt 749) into an immutable
`ImageOperationPlan`: an execution description of one future image operation. It only describes. Nothing is executed, decoded, resized or
converted, and no file is touched. The Prompt 746-749 production modules and Section 7 are unchanged and unaware of it.

## Public API
- `create_image_operation_plan(validation_result)` returns an `ImageOperationPlanResult` with `ok`, `plan` (`None` unless `ok`), `failures`,
  `codes()` and `to_dict()`. It never raises for bad inputs and never changes what it is given.
- `ImageOperationPlan` holds exactly six values, in this fixed order: `image_id`, `operation`, `target_format`, `width`, `height`, `quality`.
  Read-only properties and a fresh `to_dict()`; nothing else.

## Rules
1. `validation_result` must be exactly an `ImageOperationValidationResult`. A subclass-like object, `None`, a `dict` or the request itself is
   rejected without being read: `IMAGE_OPERATION_PLAN_INVALID_VALIDATION_RESULT`.
2. It must have `ok=True`; otherwise `IMAGE_OPERATION_PLAN_VALIDATION_FAILED` (the message names the validation codes) and no plan is created.
   This also holds for an `IMAGE_NOT_FOUND` result that still carries a request.
3. On success the six values are copied exactly from the validated request: the same `str` and `int` objects (identity preserved). Nothing is
   normalized, trimmed, case-folded, coerced, reordered or reinterpreted. `operation` and `target_format` stay free text.
4. The plan does not keep the `ImageAsset`, the registry, the request or the validation result, so it has no link back to any of them.

| problem | code |
|---|---|
| `validation_result` is not exactly an `ImageOperationValidationResult` | `IMAGE_OPERATION_PLAN_INVALID_VALIDATION_RESULT` |
| `validation_result.ok` is false | `IMAGE_OPERATION_PLAN_VALIDATION_FAILED` |

Each failure is `{"code", "field", "message"}` with `field` always `validation_result`.

## Immutability
`ImageOperationPlan` and `ImageOperationPlanResult` use `__slots__`; assignment and deletion raise `AttributeError`; direct construction and
subclassing raise `TypeError`; equality and hashing are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises
`TypeError`. `to_dict()` and `failures` return fresh data on every call. Repeated creation from the same validation result gives equal results
(and hashes) but separate objects.

## What this module does NOT do
- It does NOT execute, process, decode, resize, convert or inspect images, and it does NOT touch the filesystem, network, a database, an AI model
  or any API.
- It does NOT re-validate the request, look anything up in a registry, or compare the requested size or format with the real asset.
- It does NOT interpret `operation` or `target_format`, use a clock or randomness, or keep module-level mutable state. Its only import is the
  Prompt 749 result type. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop or Section 7.

## Limitations
- The plan is deliberately the same six values as the request; it adds no steps, ordering, output name or capability checks.
- `ok` of the validation result is trusted as produced by Prompt 749; a validation result cannot be forged because it cannot be built directly.
- There is no executor: nothing consumes a plan yet. Prompt 751 has NOT been started.
