# Prompt 777 - Section 9: Web Request Plan

Status: **implemented.** `web/web_request_plan.py` (pinned by `tests/test_web_request_plan_prompt777.py`). Fifth Section 9 module. It turns a
validated `WebRequest` (Prompts 775 / 776) into an immutable **execution description** and follows the Image/Audio operation plans (Prompts 750 / 763).
It only describes; nothing is executed.

## Public API
`create_web_request_plan(validation_result)` returns a `WebRequestPlanResult` with `ok`, `plan`, `failures`, `codes()` and `to_dict()`.
`WebRequestPlan.to_dict()` returns `{"request_id", "url", "method", "resource_type", "timeout_ms"}`. The factory never raises for bad inputs and
never changes what it is given.

## Order of checks
1. `validation_result` must be exactly a `WebRequestValidationResult`. Anything else (None, a dict, a look-alike) gives
   `WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT`; nothing is read from it.
2. It must have `ok=True`; otherwise `WEB_REQUEST_PLAN_VALIDATION_FAILED` and no plan is created (even if the failed result still carries a request).
3. On success the five values are copied exactly from `validation_result.request`: the very same `str` / `int` objects, in the fixed order above.

| problem | code | field |
|---|---|---|
| not exactly a `WebRequestValidationResult` | `WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT` | `validation_result` |
| validation result has `ok=False` | `WEB_REQUEST_PLAN_VALIDATION_FAILED` | `validation_result` |

## Plan object
`WebRequestPlan` holds ONLY the five values. It does not keep the `WebRequest`, the `WebResourceRegistry` or the validation result, and the registry
is never queried. `url`, `method` and `resource_type` stay free text: nothing is normalized, trimmed, case-folded, coerced, parsed or compared
with the registered resource. Immutable (`__slots__`, assignment/deletion raises), not subclassable, direct construction refused, equality and hash
by value (exact type only), `to_dict()` returns FRESH plain data on every call, `copy`/`deepcopy` return the same object, pickling raises `TypeError`.
`WebRequestPlanResult` follows the same contract; `failures` is a tuple of fresh `{"code", "field", "message"}` dicts.

## What this module does NOT do
- It does NOT execute the request or perform networking, and does NOT parse, resolve or check the `url` or `method`.
- It does NOT touch the filesystem, persistence, subprocesses, databases, AI models or external services; no clock or randomness.
- It does NOT modify the `WebResource`, `WebResourceRegistry`, `WebRequest` or `WebRequestValidator` modules, Core, the Planner, the Agent Loop
  or earlier sections, and is not wired into `process_input()`.
- Its only import is the Prompt 776 result type.

## Limitations
There is no URL policy, allow-list, executor or output type yet; the plan is a description only.

## Section 9 position
Prompt 777 is the fifth Section 9 prompt. Prompt 778 has NOT been started.
