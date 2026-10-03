# Prompt 754 - Section 8: Multimedia - Image Operation Metadata Executor

Status: **implemented.** `multimedia/image_operation_metadata_executor.py` (pinned by `tests/test_image_operation_metadata_executor_prompt754.py`).

## What it does
`execute_image_operation_metadata(plan)` runs one safe, metadata-only operation, `"metadata"`, and returns a real `ImageOperationOutput` (Prompt 752).
It only copies five plan values into an output. No image is read, written, decoded or modified, and no file, path or external resource is touched.
The Prompt 751 `execute_image_operation()` is **unchanged** and still reports "not implemented" for every plan. The Prompt 746-753 production modules
and Section 7 are unchanged and unaware of this module. It is not wired into `process_input()`, Core, the Planner or the Agent Loop.

## Behaviour (in order)
1. `plan` must be exactly an `ImageOperationPlan`, otherwise `ok=False`, `plan=None`, `output=None`, `INVALID_PLAN`. The object is never read.
2. `plan.operation` must equal exactly `"metadata"` (no trimming, case-folding or aliases), otherwise `ok=False`, the **same plan object**, `output=None`,
   `UNSUPPORTED_OPERATION`. No other operation is silently supported.
3. The output is created **only through the public `create_image_operation_output()` factory**, never by direct construction:

| output field | value |
|---|---|
| `image_id` | `plan.image_id` |
| `operation` | `plan.operation` |
| `output_format` | `plan.target_format` |
| `width` | `plan.width` |
| `height` | `plan.height` |

   Values are passed through unchanged (identical `str` / `int` objects), never normalized. The factory enforces a non-empty `target_format` and
   positive `width` / `height`. If it unexpectedly fails or raises, the result is `ok=False`, the same plan, `output=None`, `OUTPUT_CREATION_FAILED`.
4. Success: `ok=True`, the exact plan object (identity preserved), the created exact `ImageOperationOutput`, empty `failures`.

`quality` is not part of the output model and is ignored. The generated output passes `validate_image_operation_output(plan, output)` (Prompt 753).

## Failure codes
Only these three, prefix `IMAGE_OPERATION_METADATA_EXECUTOR_`; each failure is `{"code", "field", "message"}`.

| code | field |
|---|---|
| `INVALID_PLAN` | `plan` |
| `UNSUPPORTED_OPERATION` | `operation` |
| `OUTPUT_CREATION_FAILED` | `output` |

## Result: `ImageOperationMetadataExecutionResult`
Members: `ok`, `plan`, `output`, `failures`, `codes()`, `to_dict()` (`{"ok", "plan", "output", "failures"}`). Immutable (`__slots__`, read-only);
direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only); `copy()` / `deepcopy()` return the same object;
pickling is refused; `failures`, `codes()` and `to_dict()` are fresh on every call. The plan is never mutated; repeated execution gives equal results.

## What this module does NOT do
No resize / convert / crop / decoding or any other image processing, no image bytes, paths, filesystem, network, database, AI model or external service,
no clock or randomness, no module-level mutable state, no image library. Its only imports are the Prompt 750 plan type and the Prompt 752 output type
and factory.

## Test housekeeping
The earlier Section 8 tests (and the Prompt 718 frozen-tree exemption list) that pin the exact file list of the `multimedia` package now also list the
new module; no production module changed. Prompt 755 has **not** been started.
