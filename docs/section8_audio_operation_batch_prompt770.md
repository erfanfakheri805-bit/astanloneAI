# Prompt 770 - Section 8: Multimedia - Audio Operation Batch

Status: **implemented.** `multimedia/audio_operation_batch.py` (pinned by `tests/test_audio_operation_batch_prompt770.py`).

## What it does
`process_audio_operations(requests, audio_registry)` is a small deterministic wrapper around the single-request pipeline of Prompt 769, the audio
counterpart of `process_image_operations()` (Prompt 757). It calls the existing public `process_audio_operation(request, audio_registry)` once per
request, in input order, and keeps every returned result. It adds no audio-operation semantics and does **no per-request validation** of its own:
registry lookup, planning, dispatch and output validation for one request are all decided by Prompt 769. The Prompt 761-769 production modules are
**unchanged** and unaware of the batch. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Input contract (exact types only; nothing is coerced, normalized or sorted)
- `requests`: exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected). An empty collection is valid.
- every item: exactly an `AudioOperationRequest` (Prompt 761).
- `audio_registry`: exactly an `AudioAssetRegistry` (Prompt 760).

These three type checks are the batch's only own checks. They are made here so that the pipeline is only ever called with inputs that already passed them.

## Failure codes (only these four; prefix `AUDIO_OPERATION_BATCH_`)
Each failure is `{"code", "field", "message", "context"}`.

| code | field | context | when |
|---|---|---|---|
| `AUDIO_OPERATION_BATCH_INVALID_COLLECTION` | `requests` | `None` | `requests` is not an exact list/tuple |
| `AUDIO_OPERATION_BATCH_INVALID_REGISTRY` | `audio_registry` | `None` | `audio_registry` is not an exact `AudioAssetRegistry` |
| `AUDIO_OPERATION_BATCH_INVALID_REQUEST` | `requests[<index>]` | the **exact invalid item** | the item at that original index is not an exact `AudioOperationRequest` |
| `AUDIO_OPERATION_BATCH_OPERATION_FAILED` | `results[<index>]` | `None` | all inputs were valid, but the pipeline result at that index has `ok=False` |

The failing index is in the **field** (as `game_definition` does with `bundles[<index>]`); the message repeats it and names the offending type.

## Failure context (`INVALID_REQUEST`)
`context` is the very object the caller put in the collection: identity preserved, never copied, inspected or called. It is available through
`failures` only. `to_dict()` stays plain data and leaves `context` out (the message names the offending type). Equality compares contexts by
identity, so a caller object's own `__eq__`/`__hash__` is never invoked (unhashable items are fine); the hash ignores contexts.

## Behaviour (in order)
1. **Invalid input.** The collection check and the registry check are both reported if both fail (collection first). Items are examined only when
   the collection is valid, and **every** invalid item is reported, in input order. If anything is reported: `ok=False`, `results=()` and
   `process_audio_operation()` is **not called at all**, not even for the valid items.
2. **Valid input.** `process_audio_operation()` is called exactly once per request, in order, and processing **never stops at the first failing
   operation**. The exact returned `AudioOperationPipelineResult` objects (identity preserved) are stored in an immutable tuple `results`, with the
   same length and order as `requests`, also when some operations failed. An empty batch is valid: `ok=True`, `results=()`.
3. **`ok`** is `True` only when there are no failures, i.e. every individual result has `ok=True`.
4. **Failed operations.** One `OPERATION_FAILED` failure per failing result, in input order. The message quotes that result's own pipeline codes
   (e.g. `[AUDIO_OPERATION_PIPELINE_DISPATCH_FAILED]`); pipeline codes are never copied, renamed or hidden, and the full detail stays in the
   preserved result.

## Result: `AudioOperationBatchResult`
Members: `ok`, `results`, `failures`, `codes()`, `to_dict()` (`{"ok", "results", "failures"}`; `results` is a list of each result's own `to_dict()`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only, order matters);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `failures`, `codes()` and `to_dict()` are
fresh on every call. The input collection is only read and is not retained (`results` is a new tuple); no request is mutated; repeated calls give
equal results.

## What this module does NOT do
No filesystem, audio decoding or samples, network, subprocess, database, AI model or external service, no clock or randomness, no concurrency,
threading, retries, scheduling or deduplication, no automatic operation selection, no module-level mutable state. It never reads a request's
fields. Its only imports are the Prompt 760 and 761 types and the Prompt 769 pipeline function.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-769), the hard-coded file counts in the Prompt 767/768
tests and the Prompt 718 frozen-tree exemption list now also account for the new module; no production module changed. Prompt 771 has **not** been started.
