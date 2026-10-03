# Prompt 775 - Section 9: Web Request Contract

Status: **implemented.** `web/web_request.py` (pinned by `tests/test_web_request_prompt775.py`). Third Section 9 module, after the Web Resource
(773) and Web Resource Registry (774).

## What it represents
`WebRequest` is an immutable DESCRIPTION of one controlled web request: `request_id`, `url`, `method`, `resource_type`, `timeout_ms`.
It only describes a request. Nothing is executed, fetched or sent, and it holds no response.

## Public API
- `create_web_request(data)` returns a `WebRequestResult` with `ok`, `request` (`None` unless `ok`), `failures`, `codes()` and `to_dict()`.
  It never raises for bad data and never changes the caller's dict.
- `WebRequest`: read-only properties `request_id`, `url`, `method`, `resource_type`, `timeout_ms`; `to_dict()` returns a FRESH plain dict in
  the fixed field order on every call; deterministic equality and hashing (exact type only); direct construction and subclassing refused
  (`TypeError`); `copy`/`deepcopy` return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.
- `WebRequestResult.to_dict()` returns `{"ok", "request", "failures"}` with fresh nested data.

## Validation rules
1. `data` must be exactly a plain `dict` (a dict subclass is rejected) with exactly the five keys; missing and unexpected keys are rejected.
2. `request_id`, `url`, `method` and `resource_type` must be exactly `str` (no subclass, no coercion) and non-empty. "Non-empty" means exactly
   `value != ""`: a whitespace-only value is accepted, because nothing is trimmed or normalized.
3. `timeout_ms` must be exactly `int` and greater than zero. `bool`, `int` subclasses, floats and numeric strings are rejected; nothing is converted.
4. Nothing is trimmed, normalized, case-folded, coerced, mutated or reordered. The same `str` objects are stored (identity preserved).

Failures are reported together, in a fixed order: input, unexpected fields sorted by name, then the five fields in declared order.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `WEB_REQUEST_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `WEB_REQUEST_UNEXPECTED_FIELD` |
| missing field | `WEB_REQUEST_MISSING_FIELD` |
| bad `request_id` | `WEB_REQUEST_INVALID_REQUEST_ID` |
| bad `url` | `WEB_REQUEST_INVALID_URL` |
| bad `method` | `WEB_REQUEST_INVALID_METHOD` |
| bad `resource_type` | `WEB_REQUEST_INVALID_RESOURCE_TYPE` |
| bad `timeout_ms` | `WEB_REQUEST_INVALID_TIMEOUT_MS` |

Each failure is `{"code", "field", "message"}`; `field` is `None` for input-level and non-`str`-key problems.

## What this module does NOT do
- It does NOT execute a request, perform networking, or import any networking library.
- It does NOT parse, validate or resolve `url`, does NOT check `method` against known HTTP methods, and does NOT validate `resource_type`.
- It does NOT read or write the filesystem, use a database, subprocesses, an AI model, any API, a clock or randomness.
- It imports nothing, adds no dependency and keeps no module-level mutable state.
- It is NOT wired into Core, `process_input()`, the Planner or the Agent Loop, and no existing section was modified.

## Limitations
- `url` and `method` are opaque text: no scheme/host check, no allow-list, no safety policy yet.
- There is no request/response pairing, request registry or executor yet.

## Section 9 position
Prompt 775 is the third Section 9 prompt. Prompt 776 has NOT been started.
