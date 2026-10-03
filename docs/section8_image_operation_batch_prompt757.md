# Prompt 757 - Section 8: Multimedia - Image Operation Batch Pipeline

Status: **implemented.** `multimedia/image_operation_batch.py` (pinned by `tests/test_image_operation_batch_prompt757.py`).

## What it does
`process_image_operations(requests, image_registry)` is a small deterministic wrapper around the single-request pipeline of Prompt 756. It calls the
existing public `process_image_operation(request, image_registry)` once per request, in input order, and keeps every returned result. It adds no
image-operation semantics and does **no per-request validation** of its own: registry lookup, planning, dispatch and output validation for one
request are all decided by Prompt 756. The Prompt 748-756 production modules are **unchanged** and unaware of the batch. Not wired into
`process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Input contract (exact types only; nothing is coerced, normalized or sorted)
- `requests`: exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected). An empty collection is valid.
- every item: exactly an `ImageOperationRequest` (Prompt 748).
- `image_registry`: exactly an `ImageAssetRegistry` (Prompt 747).

These three type checks are the batch's only own checks. They are made here so that the pipeline is only ever called with inputs that already passed them.

## Failure codes (only these four; prefix `IMAGE_OPERATION_BATCH_`)
Each failure is `{"code", "field", "message"}`.

| code | field | when |
|---|---|---|
| `IMAGE_OPERATION_BATCH_INVALID_COLLECTION` | `requests` | `requests` is not an exact list/tuple |
| `IMAGE_OPERATION_BATCH_INVALID_REGISTRY` | `image_registry` | `image_registry` is not an exact `ImageAssetRegistry` |
| `IMAGE_OPERATION_BATCH_INVALID_REQUEST` | `requests[<index>]` | the item at that index is not an exact `ImageOperationRequest` |
| `IMAGE_OPERATION_BATCH_OPERATION_FAILED` | `results[<index>]` | all inputs were valid, but the pipeline result at that index has `ok=False` |

The failing index is in the **field** (as `game_definition` does with `bundles[<index>]`); the message repeats it and names the offending type.

## Behaviour (in order)
1. **Invalid input.** The collection check and the registry check are both reported if both fail (collection first, like the other multimedia
   validators report both top-level problems at once). Items are examined only when the collection is valid, and **every** invalid item is reported, in
   input order. If anything is reported: `ok=False`, `results=()` and `process_image_operation()` is **not called at all**, not even for the valid items.
2. **Valid input.** `process_image_operation()` is called exactly once per request, in order, and processing **never stops at the first failing
   operation**. The exact returned result objects (identity preserved) are stored in an immutable tuple `results`, with the same length and order as
   `requests`, also when some operations failed. An empty batch is valid: `ok=True`, `results=()`.
3. **`ok`** is `True` only when there are no failures, i.e. every individual result has `ok=True`.
4. **Failed operations.** One `OPERATION_FAILED` failure per failing result, in input order. The message quotes that result's own pipeline codes
   (e.g. `[IMAGE_OPERATION_PIPELINE_DISPATCH_FAILED]`); pipeline codes are never copied, renamed or hidden, and the full detail (plan, dispatch result,
   output validation) stays in the preserved result.

## Result: `ImageOperationBatchResult`
Members: `ok`, `results`, `failures`, `codes()`, `to_dict()` (`{"ok", "results", "failures"}`; `results` is a list of each result's own `to_dict()`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only, order matters);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `failures`, `codes()` and `to_dict()` are
fresh on every call. The input collection is only read and is not retained (`results` is a new tuple); no request is mutated; repeated calls give equal results.

## What this module does NOT do
No filesystem, image decoding or pixels, network, database, AI model or external service, no clock or randomness, no concurrency, threading, retries
or scheduling, no automatic operation selection, no module-level mutable state. It never reads a request's fields. Its only imports are the Prompt 747
and 748 types and the Prompt 756 pipeline function.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-756) and the Prompt 718 frozen-tree exemption list now also list
the new module; no production module changed. Prompt 758 has **not** been started.
