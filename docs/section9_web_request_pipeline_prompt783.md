# Prompt 783 - Section 9 Web Request Pipeline

**Module:** `app/src/main/python/web/web_request_pipeline.py`
**Tests:** `app/src/main/python/tests/test_web_request_pipeline_prompt783.py`

## Purpose
A small pipeline around the existing Web Request dispatcher (Prompt 782). It accepts one `WebRequestPlan` (Prompt 777), calls the public
`dispatch_web_request(plan)` and returns the dispatched `WebRequestOutput` (Prompt 779) unchanged. No request is ever performed.

```
run_web_request_pipeline(plan) -> WebRequestOutput(status, code, metadata)
```

## Behavior
| Input | Result |
|---|---|
| anything that is not exactly a `WebRequestPlan` (None, dict, look-alike, chain result/output objects, ...) | `WebRequestOutput` with status `"REJECTED"`, code `"WEB_REQUEST_PIPELINE_INVALID_PLAN"`, metadata `None`. The dispatcher is not called and the input is never read. |
| an exact `WebRequestPlan` | `dispatch_web_request(plan)` is called exactly once and its `WebRequestOutput` is returned as the same object (so unchanged by value). Today: status `"NOT_IMPLEMENTED"`, code `"WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"`, metadata = the plan's five values (same `str` / `int` objects, same key order). |

Whatever the dispatcher returns is propagated as is; the pipeline never re-codes, copies or re-validates it.

## No duplicated logic
The pipeline does not import or call `execute_web_request_plan` or `create_web_request_output` and never reads the plan's values. Execution and output
creation stay inside the dispatcher (Prompt 782), which uses the executor (Prompt 778) and the output factory (Prompt 779).

## No retention
The plan and the dispatched output exist only inside the call. The module has no module-level state, and the returned output holds only the status, the
code and a tuple of the metadata pairs.

## The rejected output
As in Prompt 782, the pipeline's own rejection is a real `WebRequestOutput` built with the Prompt 779 module's private creation token
(`web_request_output._CREATE_TOKEN`), so the chain keeps one output type and no existing production module is modified.

## Returned output
The Prompt 779 `WebRequestOutput`: immutable, value-comparable, `metadata` and `to_dict()` fresh on every access, copy/deepcopy return the same object,
pickling raises `TypeError`. Repeated runs of the same plan are deterministic.

## What it does not do
No networking, filesystem, subprocess, persistence, database, AI model or external service. No clock, no randomness. Imports only the Prompt 777 plan
type, the Prompt 782 dispatcher function and the Prompt 779 output type and creation token. Not wired into `process_input()`, Core, the Planner, the
Agent Loop or any earlier section. No existing production module was modified.

## Frozen-tree / file-list updates
Only exact file-list assertions were extended with the one new file `web/web_request_pipeline.py`: the web-package file lists in the Prompt 773-782
tests and the Prompt 718 exact-path exemptions. No frozen hash or check was weakened.
