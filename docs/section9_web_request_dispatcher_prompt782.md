# Prompt 782 - Section 9 Web Request Dispatcher

**Module:** `app/src/main/python/web/web_request_dispatcher.py`
**Tests:** `app/src/main/python/tests/test_web_request_dispatcher_prompt782.py`

## Purpose
A small dispatcher for the Web Request execution chain. It runs one `WebRequestPlan` (Prompt 777) through the existing placeholder executor
`execute_web_request_plan` (Prompt 778) and returns the existing `WebRequestOutput` (Prompt 779). No request is ever performed.

```
dispatch_web_request(plan) -> WebRequestOutput(status, code, metadata)
```

## Behavior
| Input | Result |
|---|---|
| anything that is not exactly a `WebRequestPlan` (None, dict, look-alike, result/output objects, ...) | `WebRequestOutput` with status `"REJECTED"`, code `"WEB_REQUEST_DISPATCHER_INVALID_PLAN"`, metadata `None`. The executor is not called and the input is never read. |
| an exact `WebRequestPlan` | `execute_web_request_plan(plan)` is called once; its `WebRequestExecutionResult` is converted by `create_web_request_output(...)` and returned unchanged. Today this is status `"NOT_IMPLEMENTED"`, code `"WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"` and the plan's five values (`request_id`, `url`, `method`, `resource_type`, `timeout_ms`) as metadata - the very same `str` / `int` objects, same key order. |

Status, code and metadata are never re-coded, re-interpreted or normalized by the dispatcher.

## No retention
The plan and the execution result exist only as local variables of the call. The module has no module-level state, and the returned output holds
only the status, the code and a tuple of the metadata key/value pairs - no reference to the plan or the execution result.

## The rejected output
The existing output factory can only build its own invalid-execution-result rejection (`WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT`). To return the
dispatcher's own rejection as the same single `WebRequestOutput` type, the dispatcher uses the `WebRequestOutput` class with the Prompt 779 module's
private creation token (`web_request_output._CREATE_TOKEN`). This was chosen over modifying an existing production module. It is the only place the
dispatcher reaches into another module's private name; a later prompt may replace it with a public rejected-output factory if one is added.

## Returned output
The Prompt 779 `WebRequestOutput`: immutable (`__slots__`, assignment/deletion raises), cannot be built directly or subclassed, compares and hashes by
value, `metadata` and `to_dict()` are fresh on every access, copy/deepcopy return the same object, pickling raises `TypeError`. Repeated dispatch
of the same plan is deterministic.

## What it does not do
No networking, filesystem, subprocess, persistence, database, AI model or external service. No URL parsing, no method/timeout checks, no registry
lookup, no clock, no randomness. Imports only the Prompt 777 plan type and the Prompt 778 / 779 public chain pieces (plus the Prompt 779 creation
token). Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section. No existing production module was modified.

## Frozen-tree / file-list updates
Only exact file-list assertions were extended with the one new file `web/web_request_dispatcher.py`: the web-package file lists in the Prompt
773-781 tests and the Prompt 718 exact-path exemptions. No frozen hash or check was weakened.
