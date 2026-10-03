# Prompt 753 - Section 8: Multimedia - Image Operation Output Validator

Status: **implemented.** `multimedia/image_operation_output_validator.py` (pinned by `tests/test_image_operation_output_validator_prompt753.py`).

## What it does
`validate_image_operation_output(plan, output)` checks whether an `ImageOperationOutput` (Prompt 752) matches an `ImageOperationPlan` (Prompt 750). It only
compares metadata values. No image is processed, decoded or read, and no file is touched. The Prompt 746-752 production modules and Section 7 are unchanged
and unaware of it. It is not wired into `process_input()`, Core, the Planner, the Agent Loop or the Prompt 751 executor.

## Validation order
1. `plan` must be exactly an `ImageOperationPlan`, otherwise `INVALID_PLAN`.
2. `output` must be exactly an `ImageOperationOutput`, otherwise `INVALID_OUTPUT`.
3. If either top-level input is invalid, **no cross-validation** is done (both top-level problems are reported, plan first).
4. Otherwise five pairs are compared in this fixed order and every mismatch is reported:

| comparison | code |
|---|---|
| `output.image_id == plan.image_id` | `IMAGE_ID_MISMATCH` |
| `output.operation == plan.operation` | `OPERATION_MISMATCH` |
| `output.output_format == plan.target_format` | `FORMAT_MISMATCH` |
| `output.width == plan.width` | `WIDTH_MISMATCH` |
| `output.height == plan.height` | `HEIGHT_MISMATCH` |

All codes have the prefix `IMAGE_OPERATION_OUTPUT_VALIDATION_` (for example `IMAGE_OPERATION_OUTPUT_VALIDATION_WIDTH_MISMATCH`). Each failure is
`{"code", "field", "message"}`; `field` is `plan` / `output` for the top-level codes and the output field name for mismatches.

## Exact comparison
Values are compared exactly: never trimmed, case-folded, coerced or converted (`"WEBP"` does not match `"webp"`, `" hero"` does not match `"hero"`).
Object identity is never the criterion; two different but equal objects match.

## quality
`quality` exists only on the plan. The output model does not represent it, so it is **intentionally not validated and not inferred**: plans that differ
only in `quality` give the same validation outcome.

## Result: `ImageOperationOutputValidationResult`
Members: `ok`, `plan`, `output`, `failures`, `codes()`, `to_dict()` (`{"ok", "plan", "output", "failures"}`).
- On success `ok=True`, `failures` is empty and `plan` / `output` are the very same objects that were passed in (identity preserved).
- `plan` / `output` hold the supplied object when it has the exact expected type (also when mismatches are reported) and `None` when that input was invalid.
- Immutable (`__slots__`, read-only, assignment/deletion raise `AttributeError`); direct construction and subclassing raise `TypeError`; equality and hash
  by value (exact type only); `copy()` / `deepcopy()` return the same object; pickling is refused; `failures`, `codes()` and `to_dict()` are fresh on every call.
- Neither `plan` nor `output` is ever mutated; repeated validation gives equal results.

## What this module does NOT do
No image processing, no file or image-byte access, no filesystem, network, database, AI model or external service, no clock or randomness, no
module-level mutable state, no image library. Its only imports are the Prompt 750 plan type and the Prompt 752 output type.

## Test housekeeping
The earlier Section 8 tests that pin the exact file list of the `multimedia` package (Prompts 746-752) now also list the new module; no production
module changed. Prompt 754 has **not** been started.
