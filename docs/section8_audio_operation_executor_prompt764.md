# Prompt 764 - Section 8: Multimedia - Audio Operation Executor Boundary

Status: **implemented as a boundary only.** `multimedia/audio_operation_executor.py` (pinned by `tests/test_audio_operation_executor_prompt764.py`).

## What it does
`execute_audio_operation(plan)` is the single, safe entry point a future audio executor will sit behind. It defines the execution result
contract (`AudioOperationExecutionResult`) and nothing else. **Execution is deliberately not implemented**: no operation is performed, no audio is
decoded, encoded or modified, and no file is touched. A valid plan is never reported as a success. The Prompt 759-763 production modules, the image
executor (Prompt 751) and Section 7 are unchanged and unaware of it. It follows the architecture of `ImageOperationExecutionResult` as a separate type.

## Public API
- `execute_audio_operation(plan)` returns an `AudioOperationExecutionResult`. It never raises for bad inputs and never changes what it is given.
- `AudioOperationExecutionResult` exposes `ok`, `plan`, `status`, `failures`, `codes()` and `to_dict()`; nothing else.

## Behaviour
| input | ok | plan | status | failure code |
|---|---|---|---|---|
| not exactly an `AudioOperationPlan` | `False` | `None` | `"rejected"` | `AUDIO_OPERATION_EXECUTOR_INVALID_PLAN` |
| exact `AudioOperationPlan` | `False` | the same object (identity) | `"not_implemented"` | `AUDIO_OPERATION_EXECUTOR_NOT_IMPLEMENTED` |

1. `plan` must be exactly an `AudioOperationPlan` (Prompt 763). `None`, a `dict`, a look-alike or a subclass-like object is rejected without being read.
2. A valid plan is preserved by identity, with its six values untouched (nothing normalized, coerced or reinterpreted).
3. `ok` is always `False` in this prompt. `status` is an exact `str`, only `"rejected"` or `"not_implemented"`. Only the two failure codes above exist.
4. Each failure is `{"code", "field", "message"}` with `field` always `plan`. `to_dict()` is `{"ok", "plan", "status", "failures"}` where `plan` is
   `plan.to_dict()` or `None`.

## Immutability
`AudioOperationExecutionResult` uses `__slots__`; assignment and deletion raise `AttributeError`; direct construction and subclassing raise
`TypeError`; equality and hashing are by value (exact type only); `copy`/`deepcopy` return the same object; pickling raises `TypeError`.
`to_dict()` and `failures` return fresh data on every call. Repeated execution of the same plan gives equal results (and hashes) but separate objects.

## What this module does NOT do
- It does NOT execute, process, decode, encode, trim, convert or inspect audio, and it does NOT touch the filesystem, network, a database, an AI
  model or any API.
- It does NOT mutate the supplied plan, interpret `operation` or `target_format`, use a clock or randomness, or keep module-level mutable state. Its
  only import is the Prompt 763 plan type. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop or Section 7.

## Limitations
- There is no real executor: every valid plan returns `not_implemented`, so no caller can obtain a successful result yet.
- The result carries no output audio, path or metrics; those belong to a later prompt.
- This is an execution boundary, not audio processing. Prompt 765 has NOT been started.
