# Prompt 773 - Section 9: Web Resource Contract

Status: **implemented.** `web/web_resource.py` (pinned by `tests/test_web_resource_prompt773.py`). This is the first Section 9 module.

## What it represents
`WebResource` is an immutable record of the BASIC METADATA of one web resource: `resource_id`, `url`, `title`, `resource_type`.
It follows the same shape and conventions as `ImageAsset` (Prompt 746) but is a separate, unrelated type. It holds no content and never touches the network.

## Public API
- `create_web_resource(data)` returns a `WebResourceResult` with `ok`, `resource` (`None` unless `ok`), `failures`, `codes()` and `to_dict()`.
  It never raises for bad data and never changes the caller's dict.
- `WebResource`: read-only properties `resource_id`, `url`, `title`, `resource_type`; `to_dict()` returns a FRESH plain dict in the fixed field
  order on every call; deterministic equality and hashing (exact type only); direct construction and subclassing refused (`TypeError`);
  `copy`/`deepcopy` return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.
- `WebResourceResult.to_dict()` returns `{"ok", "resource", "failures"}` with fresh nested data.

## Validation rules
1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All four fields are required; nothing is defaulted.
3. Every value must be exactly `str` (no `str` subclass, no coercion).
4. `resource_id`, `url` and `resource_type` must be non-empty. "Non-empty" means exactly `value != ""`: a whitespace-only value is accepted,
   because nothing is trimmed or normalized. (This differs deliberately from `ImageAsset`, which also rejects blank text.)
5. `title` may be empty.
6. Missing and unexpected fields are rejected (an unexpected field is never ignored; a non-`str` or `str`-subclass key is unexpected).
7. Nothing is trimmed, normalized, coerced or mutated. The same `str` objects are stored (identity preserved). The caller's dict is only read.

Failures are reported together, in a fixed order: input, unexpected fields sorted by name, then the four fields in declared order.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `WEB_RESOURCE_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `WEB_RESOURCE_UNEXPECTED_FIELD` |
| missing field | `WEB_RESOURCE_MISSING_FIELD` |
| bad `resource_id` | `WEB_RESOURCE_INVALID_RESOURCE_ID` |
| bad `url` | `WEB_RESOURCE_INVALID_URL` |
| bad `title` | `WEB_RESOURCE_INVALID_TITLE` |
| bad `resource_type` | `WEB_RESOURCE_INVALID_RESOURCE_TYPE` |

Each failure is `{"code", "field", "message"}`; `field` is `None` for input-level and non-`str`-key problems.

## What this module does NOT do
- It does NOT perform networking or any HTTP request, and does NOT parse, validate, normalize or resolve the `url` (any non-empty text is accepted).
- It does NOT validate `resource_type` against a list of known types.
- It does NOT read or write the filesystem, use a database, subprocesses, an AI model, any API, a clock or randomness.
- It imports nothing (not even the standard library), adds no external dependency and keeps no module-level mutable state.
- It is NOT wired into Core, `process_input()`, the Planner or the Agent Loop, and no existing section was modified.

## Limitations
- `url` is opaque text; there is no scheme/host check, no allow-list and no safety policy yet.
- There is no web resource registry and no request/response contract yet.

## Section 9 position
Prompt 773 is the first Section 9 prompt (Web Resource Contract). Prompt 774 has NOT been started.
