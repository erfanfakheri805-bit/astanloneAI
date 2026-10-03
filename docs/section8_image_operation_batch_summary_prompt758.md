# Prompt 758 - Section 8: Multimedia - Image Operation Batch Summary

Status: **implemented.** `multimedia/image_operation_batch_summary.py` (pinned by `tests/test_image_operation_batch_summary_prompt758.py`).

## What it does
`create_image_operation_batch_summary(batch_result)` returns a small immutable `ImageOperationBatchSummary` for a completed batch of Prompt 757.
It only **counts** success and failure over the result objects the batch preserved. It does not read a request, a plan, a dispatch result or any
pipeline failure code, does not reinterpret the Prompt 756/757 codes, and adds no image-operation semantics. The Prompt 746-757 production modules are
**unchanged** and unaware of the summary. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Input contract (exact type only; nothing is coerced)
`batch_result` must be exactly an `ImageOperationBatchResult` (Prompt 757). Subclasses cannot exist; look-alikes, mocks, dicts, `to_dict()` output,
tuples of results, single pipeline results and `None` are all invalid.

## Behaviour
| input | total | successful | failed | success | codes() |
|---|---|---|---|---|---|
| not an exact `ImageOperationBatchResult` | 0 | 0 | 0 | `False` | `["IMAGE_OPERATION_BATCH_SUMMARY_INVALID_RESULT"]` |
| valid, `results == ()` (empty batch) | 0 | 0 | 0 | `True` | `[]` |
| valid, `n` results | `len(batch_result.results)` | results whose `ok` is exactly `True` | `total - successful` | `failed == 0` | `[]` |

- "Successful" means `result.ok is True` (`ok` is exactly True). A truthy value such as `1` or `"yes"` is **not** counted as successful.
- Only `ok` is read from each result; `codes()`, `to_dict()` and every other member of the result are left alone.
- `batch_result.ok` and `batch_result.failures` are not consulted either: a valid batch that was itself rejected by Prompt 757 (for example `None` as the
  collection) has `results == ()` and therefore summarizes as an empty valid batch (`total=0`, `successful=0`, `failed=0`, `success=True`). Distinguish
  that case with the batch result's own `ok` / `failures`, which stay the authority for it.
- The summary-level code `IMAGE_OPERATION_BATCH_SUMMARY_INVALID_RESULT` is the **only** code this module defines. A valid summary has no codes.

## Result: `ImageOperationBatchSummary`
Members: `total`, `successful`, `failed`, `success`, `codes()`, `to_dict()` (`{"total", "successful", "failed", "success", "codes"}`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results, including `ImageOperationBatchResult`);
`codes()` and `to_dict()` are fresh on every call. The batch result and every contained result are only read, never mutated or retained; repeated calls
give equal summaries.

## What this module does NOT do
No filesystem, image decoding or pixels, network, database, AI model or external service, no clock or randomness, no concurrency, threading, retries
or scheduling, no automatic operation selection, no module-level mutable state, no Core / Planner / AgentLoop integration. Its only import is the
Prompt 757 `ImageOperationBatchResult` type.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-757) and the Prompt 718 frozen-tree exemption list now also list
the new module; no production module changed. Prompt 759 has **not** been started.
