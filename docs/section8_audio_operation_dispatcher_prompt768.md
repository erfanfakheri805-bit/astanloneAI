# Prompt 768 - Section 8: Multimedia - Audio Operation Dispatcher

Status: **implemented.** `multimedia/audio_operation_dispatcher.py` (pinned by `tests/test_audio_operation_dispatcher_prompt768.py`).

## What it does
`dispatch_audio_operation(plan)` routes an `AudioOperationPlan` (Prompt 763) to the one operation implementation that exists: the metadata-only executor
`execute_audio_operation_metadata(plan)` (Prompt 767). It selects nothing automatically, reimplements nothing, processes no audio and touches no file. It
mirrors `dispatch_image_operation()` (Prompt 755) as a separate, unrelated type. Prompt 767 and earlier modules, including the generic Prompt 764 executor,
are unchanged and unaware of the dispatcher.

## Result
`AudioOperationDispatchResult` exposes `ok`, `plan`, `result`, `failures`, `codes()` and `to_dict()` (`{"ok", "plan", "result", "failures"}`; `result` is the
executor result's own `to_dict()`). Each failure is `{"code", "field", "message"}`.

## Order of checks
1. `plan` is not exactly an `AudioOperationPlan`: `ok=False`, `plan=None`, `result=None`, `AUDIO_OPERATION_DISPATCHER_INVALID_PLAN` (field `plan`).
   The object is never read.
2. `plan.operation != "metadata"` (exact match; no trimming, case-folding or aliases): `ok=False`, the exact valid plan preserved, `result=None`,
   `AUDIO_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION` (field `operation`). The executor is not called.
3. `"metadata"`: `execute_audio_operation_metadata(plan)` is called exactly once and the `AudioOperationMetadataExecutionResult` it returns is held
   unchanged (same object) in `result`. The plan identity is preserved.

`ok` mirrors the executor result's `ok`. Whatever the executor reports (for example `AUDIO_OPERATION_METADATA_EXECUTOR_OUTPUT_CREATION_FAILED`) stays inside
`result.codes()`; it is never copied, renamed or re-coded, and the dispatcher's own `failures` is then empty. Only the two dispatcher codes exist.

## Immutability
The result uses `__slots__`; assignment and deletion raise `AttributeError`; direct construction and subclassing raise `TypeError`; equality and hashing
are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises `TypeError`. `failures`, `codes()` and `to_dict()` return fresh
data on every call. The function never raises for bad inputs, never mutates the plan and is deterministic.

## What this module does NOT do
- It does NOT process, decode, encode or inspect audio, support any operation other than `"metadata"`, or choose operations automatically.
- It does NOT build outputs itself (no `create_audio_operation_output`) and does NOT touch the filesystem, network, a database, an AI model or any API.
- It does NOT use a clock or randomness or keep module-level mutable state. Its only imports are the plan type and the metadata executor function.
- It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.

## Limitations
- Only `"metadata"` is routed; every other operation is rejected with `UNSUPPORTED_OPERATION`.
- The dispatcher does not validate the produced output; use the Prompt 766 validator for that.
- Prompt 769 has NOT been started.
