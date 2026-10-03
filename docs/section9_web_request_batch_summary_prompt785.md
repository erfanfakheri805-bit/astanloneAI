# Prompt 785 - Section 9 Web Request Batch Summary

**Module:** `app/src/main/python/web/web_request_batch_summary.py`
**Tests:** `app/src/main/python/tests/test_web_request_batch_summary_prompt785.py`

## Purpose
A small immutable summary of a completed web request batch (Prompt 784). It accepts one exact `WebRequestBatchResult` and exposes deterministic
aggregate counts only: how many outputs and failures the batch result holds, and how often each exact output status and each exact output code occurs.
It runs nothing, re-runs nothing and re-interprets nothing.

```
create_web_request_batch_summary(batch_result)
    -> WebRequestBatchSummary(total_count, output_count, failure_count, status_counts, code_counts, success)
```

It follows the Prompt 771 batch-summary convention: one immutable summary object with `success` and `codes()`; rejected input gives a deterministic
all-zero summary with a stable code.

## Input contract
`batch_result` must be exactly a `WebRequestBatchResult` (Prompt 784). Nothing is coerced.

## Codes
Stable, prefix `WEB_REQUEST_BATCH_SUMMARY_`.

| Code | When |
|---|---|
| `WEB_REQUEST_BATCH_SUMMARY_INVALID_RESULT` | `batch_result` is not exactly a `WebRequestBatchResult` (None, dict, look-alike, a plan, an output, a summary, ...). Nothing is read from it. |
| `WEB_REQUEST_BATCH_SUMMARY_MALFORMED_RESULT` | It is the exact type, but its content is not what a real batch produces: an output that is not exactly a `WebRequestOutput` or whose `status` / `code` is not exactly a `str`; outputs **and** failures together; failures that cannot be read. The first problem rejects the whole summary; nothing is repaired, skipped or partially counted. |

Either code gives the **rejected summary**: `success=False`, all counts `0`, both mappings empty, `codes() == [that code]`. It is the same value for every
input of that kind.

## Valid input (`codes() == []`)
| Field | Meaning |
|---|---|
| `output_count` | Number of outputs the batch result holds. |
| `failure_count` | Number of failures it holds (0 for a run batch; one per reported failure for a rejected batch). |
| `total_count` | `output_count + failure_count`: the number of entries the batch result recorded. A rejected batch records its failures only (the valid items beside a bad one are not recorded), so for it this equals the failure count, not the size of the caller's tuple. |
| `status_counts` | `{exact output status: count}`. |
| `code_counts` | `{exact output code: count}`. |
| `success` | `batch_result.ok is True`: the batch input was valid and was run. It says **nothing** about output statuses (today every output of a valid batch is `NOT_IMPLEMENTED`); read `status_counts` for that. |

Keys are compared exactly (no trimming, case folding or grouping); every count is at least 1, so each mapping adds up to `output_count`. An empty valid
batch gives all counts `0`, empty mappings and `success=True`. A rejected batch (for example an invalid collection) is a valid summary input and gives
`output_count=0`, `failure_count>=1`, `success=False`, `codes() == []`.

## Ordering
Both mappings are ordered by key, ascending (plain string order), regardless of the order of the outputs; first-seen order is never used. The same
multiset of outputs always gives the same summary. `to_dict()` has a fixed key order:
`total_count, output_count, failure_count, status_counts, code_counts, success, codes`.

## No reinterpretation
Outputs are read only through their public `status` and `code`; `metadata` is never read. The batch result's failure codes and messages are never read.
Nothing is modified, re-coded, re-validated or executed.

## No retention
Neither the batch result nor any output is kept. The summary holds only `int`, `bool` and `str` values and tuples of them.

## No duplicate execution, no chain dependency
The module imports only the Prompt 784 batch result type and the Prompt 779 output type. It imports and calls no pipeline, dispatcher, executor or
output factory, so summarising never runs a plan again (a test counts the chain's calls before and after summarising and runs the summary with the
whole chain disabled).

## Result
`WebRequestBatchSummary` is immutable (`__slots__`, assignment and deletion raise `AttributeError`), cannot be built directly or subclassed (`TypeError`),
compares and hashes by value (exact type only), returns itself from copy/deepcopy and refuses pickling. `status_counts`, `code_counts`, `codes()` and
`to_dict()` are fresh plain data on every call. The function never raises for bad inputs and is deterministic.

## What it does not do
No networking, filesystem, subprocess, persistence, database, AI model or external service. No clock, randomness or concurrency, no module-level state.
Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section. No existing production module was modified.

## Frozen-tree / file-list updates
Only exact file-list assertions were extended with the one new file `web/web_request_batch_summary.py`: the web-package file lists in the Prompt 773-784
tests and the Prompt 718 exact-path exemptions. No frozen hash or check was weakened.
