# Prompt 781 - Section 9: Web Request Metadata Executor

Status: **implemented.** `web/web_request_metadata_executor.py` (pinned by `tests/test_web_request_metadata_executor_prompt781.py`). Ninth Section 9 module.
It follows `WebRequestOutput` (Prompt 779) and its validator (Prompt 780) and is **metadata-only**: it copies an output's values into an immutable result and
never executes a request.

## Public API
`execute_web_request_metadata(output)` returns a `WebRequestMetadataExecutionResult`. It never raises for bad inputs and never changes what it is given.

| input | status | code | metadata |
|---|---|---|---|
| not exactly a `WebRequestOutput`, or an exact one that fails `validate_web_request_output()` | `REJECTED` | `WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT` | `None` (nothing is retained from the input) |
| a valid `WebRequestOutput` | the output's `status` | the output's `code` | a copy of the output's metadata values, or `None` when it has none |

A valid output whose own status is `REJECTED` or `NOT_IMPLEMENTED` is copied as is; this module never reinterprets it. The Prompt 780 validator is the only
check applied to the input, so a malformed (exact-type) output is rejected like any other invalid input.

## Result object
`WebRequestMetadataExecutionResult` has exactly three fields: `status`, `code` and `metadata`. For a valid output the values are preserved exactly (same objects,
same key order, nothing normalized, interpreted or transformed). The metadata dict is copied (shallow copy of its key/value pairs); `metadata=None` stays `None`.
The `WebRequestOutput` object is NOT retained. `metadata` is a FRESH dict on every access (or None). `to_dict()` returns FRESH plain data
`{"status", "code", "metadata"}`. Immutable (`__slots__`, assignment/deletion raises), not subclassable, direct construction refused, equality and hash by value
(exact type only), `copy`/`deepcopy` return the same (therefore equal) object, pickling raises `TypeError`. Repeated execution is deterministic.

## What this module does NOT do
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls, and it does NOT
  execute any web request.
- It does NOT interpret, validate or transform the metadata contents (that is only the Prompt 780 shape check on the output).
- It does NOT modify any earlier Section 9 module, Core, the Planner, the Agent Loop or earlier sections, and is not wired into `process_input()`.
- Its only import is the Prompt 780 output validator.

## Limitations
Metadata values are copied shallowly, so a mutable value object inside the metadata would be shared (the current pipeline only produces `str` / `int` values).

## Section 9 position
Prompt 781 is the ninth Section 9 prompt. Prompt 782 has NOT been started.
