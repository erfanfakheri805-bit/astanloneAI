# Prompt 751 - Section 8: Multimedia - Image Operation Executor Boundary

Status: **implemented as a boundary only.** `multimedia/image_operation_executor.py` (pinned by `tests/test_image_operation_executor_prompt751.py`).

## What it does
`execute_image_operation(plan)` is the single, safe entry point a future image executor will sit behind. It defines the execution result
contract (`ImageOperationExecutionResult`) and nothing else. **Execution is deliberately not implemented**: no operation is performed, no image is
decoded or modified, and no file is touched. A valid plan is never reported as a success. The Prompt 746-750 production modules and Section 7 are
unchanged and unaware of it.

## Public API
- `execute_image_operation(plan)` returns an `ImageOperationExecutionResult`. It never raises for bad inputs and never changes what it is given.
- `ImageOperationExecutionResult` exposes `ok`, `plan`, `status`, `failures`, `codes()` and `to_dict()`; nothing else.

## Behaviour
| input | ok | plan | status | failure code |
|---|---|---|---|---|
| not exactly an `ImageOperationPlan` | `False` | `None` | `"rejected"` | `IMAGE_OPERATION_EXECUTOR_INVALID_PLAN` |
| exact `ImageOperationPlan` | `False` | the same object (identity) | `"not_implemented"` | `IMAGE_OPERATION_EXECUTOR_NOT_IMPLEMENTED` |

1. `plan` must be exactly an `ImageOperationPlan` (Prompt 750). `None`, a `dict`, a look-alike or a subclass-like object is rejected without being read.
2. A valid plan is preserved by identity, with its six values untouched (nothing normalized, coerced or reinterpreted).
3. `ok` is always `False` in this prompt. `status` is an exact `str`, only `"rejected"` or `"not_implemented"`. Only the two failure codes above exist.
4. Each failure is `{"code", "field", "message"}` with `field` always `plan`. `to_dict()` is `{"ok", "plan", "status", "failures"}` where `plan` is
   `plan.to_dict()` or `None`.

## Immutability
`ImageOperationExecutionResult` uses `__slots__`; assignment and deletion raise `AttributeError`; direct construction and subclassing raise
`TypeError`; equality and hashing are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises `TypeError`.
`to_dict()` and `failures` return fresh data on every call. Repeated execution of the same plan gives equal results (and hashes) but separate objects.

## What this module does NOT do
- It does NOT execute, process, decode, resize, convert, crop or inspect images, and it does NOT touch the filesystem, network, a database, an AI model
  or any API.
- It does NOT mutate the supplied plan, interpret `operation` or `target_format`, use a clock or randomness, or keep module-level mutable state. Its
  only import is the Prompt 750 plan type. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop or Section 7.

## Limitations
- There is no real executor: every valid plan returns `not_implemented`, so no caller can obtain a successful result yet.
- The result carries no output image, path or metrics; those belong to a later prompt.
- This is an execution boundary, not image processing. Prompt 752 has NOT been started.
