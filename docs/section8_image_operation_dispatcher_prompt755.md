# Prompt 755 - Section 8: Multimedia - Image Operation Dispatcher

Status: **implemented.** `multimedia/image_operation_dispatcher.py` (pinned by `tests/test_image_operation_dispatcher_prompt755.py`).

## What it does
`dispatch_image_operation(plan)` routes an `ImageOperationPlan` to the one operation implementation that exists, the Prompt 754 metadata executor.
It performs no image processing, decoding or file access, and it never chooses an operation automatically. The generic Prompt 751
`execute_image_operation()` and the Prompt 754 module are **unchanged** and unaware of the dispatcher. Not wired into `process_input()`, Core, the
Planner, the Agent Loop or Section 7.

## Behaviour (in order)
1. `plan` must be exactly an `ImageOperationPlan`, otherwise `ok=False`, `plan=None`, `result=None`, `IMAGE_OPERATION_DISPATCHER_INVALID_PLAN`.
   The object is never read.
2. Only the exact string `"metadata"` is supported (no trimming, case-folding or aliases). Any other operation gives `ok=False`, the **same plan
   object**, `result=None`, `IMAGE_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION`. The metadata executor is **not called**.
3. `"metadata"`: the plan is passed to the public `execute_image_operation_metadata(plan)` (Prompt 754) and the
   `ImageOperationMetadataExecutionResult` it returns is stored **unchanged** (the same object) in `result`. The plan identity is preserved.

## `ok` and failures
`ok` mirrors the routed result: it is `True` only when `result.ok` is `True`. The dispatcher defines only two failure codes, so a failure reported by the
executor (for example its `..._OUTPUT_CREATION_FAILED`) stays inside `result` (`result.codes()`) and is never copied or re-coded; the dispatcher's own
`failures` is then empty while `ok` is `False`. Callers should read `result` for executor-level detail.

| code | field |
|---|---|
| `IMAGE_OPERATION_DISPATCHER_INVALID_PLAN` | `plan` |
| `IMAGE_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION` | `operation` |

Each failure is `{"code", "field", "message"}`.

## Result: `ImageOperationDispatchResult`
Members: `ok`, `plan`, `result`, `failures`, `codes()`, `to_dict()` (`{"ok", "plan", "result", "failures"}`; `result` is the executor result's own
`to_dict()`). Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `failures`, `codes()` and `to_dict()` are
fresh on every call. The plan is never mutated; repeated calls give equal results.

## What this module does NOT do
No image processing or decoding, no operation other than `"metadata"`, no automatic operation selection, no image bytes, paths, filesystem, network,
database, AI model or external service, no clock or randomness, no module-level mutable state. Its only imports are the Prompt 750 plan type and the
Prompt 754 executor function.

## Test housekeeping
The earlier tests (Prompts 746-754 and the Prompt 718 frozen-tree exemption list) that pin the exact file list of the `multimedia` package now also
list the new module; no production module changed. Prompt 756 has **not** been started.
