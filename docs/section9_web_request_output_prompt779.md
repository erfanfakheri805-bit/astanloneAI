# Prompt 779 - Section 9: Web Request Output

Status: **implemented.** `web/web_request_output.py` (pinned by `tests/test_web_request_output_prompt779.py`). Seventh Section 9 module. It follows
`WebRequestExecutionResult` (Prompt 778) and defines the immutable **output contract** of the Web Request execution layer. It executes nothing.

## Public API
`create_web_request_output(execution_result)` returns a `WebRequestOutput`. It never raises for bad inputs and never changes what it is given.

| input | status | code | metadata |
|---|---|---|---|
| not exactly a `WebRequestExecutionResult` (None, dict, look-alike, subclass-free types) | `REJECTED` | `WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT` | `None` (nothing is read from the input) |
| an exact `WebRequestExecutionResult` | the result's `status` | the result's `code` | the result's `metadata` values, or `None` when it has none |

## Output object
`WebRequestOutput` has exactly three fields: `status`, `code` and `metadata`. For a valid execution result the values are preserved exactly (same `str` / `int`
objects, same key order, nothing normalized, interpreted or coerced). `metadata=None` is preserved as `None`. The execution result object is NOT retained.
`metadata` is a FRESH dict on every access (or None). `to_dict()` returns FRESH plain data `{"status", "code", "metadata"}`. Immutable (`__slots__`,
assignment/deletion raises), not subclassable, direct construction refused, equality and hash by value (exact type only), `copy`/`deepcopy` return the same
(therefore equal) object, pickling raises `TypeError`. Repeated creation from the same input is deterministic.

## What this module does NOT do
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT interpret, validate or normalize the status, code or metadata values.
- It does NOT modify the `WebResource`, `WebResourceRegistry`, `WebRequest`, `WebRequestValidator`, `WebRequestPlan` or `WebRequestExecutor` modules, Core, the
  Planner, the Agent Loop or earlier sections, and is not wired into `process_input()`.
- Its only import is the Prompt 778 execution result type.

## Limitations
There is no real executor yet, so every valid output currently reports `NOT_IMPLEMENTED` (or the executor's `REJECTED`).

## Section 9 position
Prompt 779 is the seventh Section 9 prompt. Prompt 780 has NOT been started.
