# Prompt 771 - Section 8: Multimedia - Audio Operation Batch Summary

Status: **implemented.** `multimedia/audio_operation_batch_summary.py` (pinned by `tests/test_audio_operation_batch_summary_prompt771.py`).

## What it does
`create_audio_operation_batch_summary(batch_result)` returns an immutable `AudioOperationBatchSummary` with aggregate counts for a completed audio
batch (Prompt 770). It is the audio counterpart of the image batch summary (Prompt 758). It only counts; it never reads a request, a plan, a dispatch
result or any pipeline failure code, and it adds no audio-operation semantics. The Prompt 761-770 production modules are **unchanged** and unaware of
the summary. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Input contract (exact type only; nothing is coerced)
`batch_result` must be exactly an `AudioOperationBatchResult` (Prompt 770).

## Invalid input
`total=0`, `successful=0`, `failed=0`, `success=False` and the single summary-level code `AUDIO_OPERATION_BATCH_SUMMARY_INVALID_RESULT`.

## Valid input
| member | value |
|---|---|
| `total` | `len(batch_result.results)` |
| `successful` | number of results whose `ok` is **exactly True** (truthy but not `True` counts as failed) |
| `failed` | `total - successful` |
| `success` | `True` only when `batch_result.ok is True` **and** `failed == 0` |

An empty valid batch gives `total=0, successful=0, failed=0, success=True`. A valid summary has no codes (`codes()` is `[]`).

### Deliberate difference from Prompt 758
`success` reflects the batch result's overall `ok` state, as specified for this prompt. The image summary ignored `batch_result.ok` and used only
`failed == 0`. The two differ for a batch whose **own input was invalid** (invalid collection, registry or request item): such a batch has `ok=False`
and no results, so the audio summary reports `total=0, successful=0, failed=0, success=False` (the image summary reports `success=True`). An empty
**valid** batch is still a success. For every batch with results the two rules agree.

The summary reads `batch_result.results` and `batch_result.ok` (and each result's `ok`). It does **not** read `batch_result.failures`, `codes()` or
`to_dict()`, and it never inspects, copies or reinterprets individual pipeline failure codes.

## Result: `AudioOperationBatchSummary`
Members: `total`, `successful`, `failed`, `success`, `codes()`, `to_dict()` (`{"total", "successful", "failed", "success", "codes"}`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `codes()` and `to_dict()` are fresh on every
call. The batch result is not retained and not mutated; repeated calls give equal summaries.

## What this module does NOT do
No filesystem, audio decoding or samples, network, subprocess, database, AI model or external service, no clock or randomness, no concurrency,
threading, retries, scheduling or deduplication, no module-level mutable state. Its only import is the Prompt 770 batch result type.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-770), the hard-coded file counts in the Prompt 767/768 tests
and the Prompt 718 frozen-tree exemption list now also account for the new module; no production module changed. Prompt 772 has **not** been started.
