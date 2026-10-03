# Prompt 784 - Section 9 Web Request Batch

**Module:** `app/src/main/python/web/web_request_batch.py`
**Tests:** `app/src/main/python/tests/test_web_request_batch_prompt784.py`

## Purpose
A small immutable batch layer on top of the existing Web Request pipeline (Prompt 783). It accepts an exact tuple of exact `WebRequestPlan` objects
(Prompt 777), calls the public `run_web_request_pipeline(plan)` exactly once per plan, in input order, and keeps every `WebRequestOutput` (Prompt 779)
in an immutable result. No request is ever performed.

```
run_web_request_batch(plans) -> WebRequestBatchResult(ok, outputs, failures)
```

## Input contract (exact types only)
- `plans` must be exactly a `tuple`. Lists, sets, dicts, generators, strings, tuple subclasses (including named tuples) and everything else are rejected;
  nothing is coerced, sorted, de-duplicated or copied. An empty tuple is valid. (This is deliberately narrower than the Prompt 774 registry, which
  accepts a list or a tuple: a tuple is ordered and immutable, so the batch cannot be reordered or changed while it runs.)
- Every item must be exactly a `WebRequestPlan`. Look-alikes, dicts, objects that merely fake `__class__`, and the chain's own outputs are rejected.

## Failure codes
Stable, prefix `WEB_REQUEST_BATCH_`; each failure is `{"code", "field", "message"}` (the Section 9 result shape).

| Code | Field | When |
|---|---|---|
| `WEB_REQUEST_BATCH_INVALID_COLLECTION` | `plans` | `plans` is not exactly a tuple. Its items are not examined. |
| `WEB_REQUEST_BATCH_INVALID_PLAN` | `plans[<index>]` | One failure per item that is not exactly a `WebRequestPlan`, in input order; all bad items are reported in one call. |

A rejected batch has `ok=False`, `outputs=()` and **`run_web_request_pipeline()` is not called at all**, not even for the valid items, so a rejected
batch has no partial effect. The offending object is never read, compared, hashed, repr'd or kept: the message names only the index.

## Valid input
| Input | Result |
|---|---|
| `()` | `ok=True`, `outputs=()`, no failures. The pipeline is not called. |
| a tuple of valid plans | The pipeline is called exactly once per plan item, in input order, with that very plan object. `outputs` holds the exact `WebRequestOutput` objects it returned, in the same order and length. Today each is status `"NOT_IMPLEMENTED"`, code `"WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"`, metadata = the plan's five values. |

The same plan object appearing twice is two items and gives two calls. Outputs are propagated as they are returned (identity preserved): never re-coded,
re-validated, copied or interpreted, and the batch never reads their status, code or metadata. Consequently `ok` means "the batch input was valid and
was run", **not** "every plan succeeded"; per-plan status is read from `outputs`.

## No duplicated logic
The batch does not import or call the dispatcher, the executor or the output factory and never reads a plan's values. Dispatch, execution and output
creation stay in Prompts 782 / 778 / 779; the single-plan pipeline stays Prompt 783.

## No retention
Neither the input tuple nor any plan is kept; they exist only inside the call. The result holds only the outputs the pipeline returned and, when
rejected, plain `str` failure triples. Unlike the Prompt 770 audio batch, failures carry no `context` object, so not even a rejected item is retained.
The module has no module-level state.

## Result
`WebRequestBatchResult` is immutable (`__slots__`, assignment and deletion raise `AttributeError`), cannot be built directly or subclassed (`TypeError`),
compares and hashes by value (exact type only; same outputs and failures in the same order), returns itself from copy/deepcopy and refuses pickling.
`outputs` is a tuple; `failures`, `codes()` and `to_dict()` (`{"ok", "outputs", "failures"}`, outputs as a list of each output's own `to_dict()`) are fresh
on every call. The function never raises for bad inputs, only reads the tuple and the plans, and is deterministic.

## What it does not do
No networking, filesystem, subprocess, persistence, database, AI model or external service. No clock, randomness, concurrency, retries or scheduling, and
no short-circuiting. Imports only the Prompt 777 plan type and the Prompt 783 pipeline function. Not wired into `process_input()`, Core, the Planner, the
Agent Loop or any earlier section. No existing production module was modified.

## Frozen-tree / file-list updates
Only exact file-list assertions were extended with the one new file `web/web_request_batch.py`: the web-package file lists in the Prompt 773-783 tests
and the Prompt 718 exact-path exemptions. No frozen hash or check was weakened.
