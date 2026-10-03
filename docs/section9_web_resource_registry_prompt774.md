# Prompt 774 - Section 9: Web Resource Registry

Status: **implemented.** `web/web_resource_registry.py` (pinned by `tests/test_web_resource_registry_prompt774.py`). It follows the conventions of
the Prompt 747 `ImageAssetRegistry` and the Prompt 760 audio registry, applied to the Prompt 773 `WebResource`.

## Public API
- `create_web_resource_registry(resources)` returns a `WebResourceRegistryResult` with `ok`, `registry` (`None` unless `ok`), `failures`, `codes()`
  and `to_dict()`. It never raises for bad input and never changes what it is given.
- `WebResourceRegistry`: `.resources` (tuple, registration order), `.resource_ids` (tuple), `.lookup(resource_id)`, `.to_dict()` returning
  `{"resources": [WebResource.to_dict(), ...]}` (fresh on every call). Immutable (`__slots__`, assignment/deletion raises `AttributeError`), not
  subclassable, direct construction refused (`TypeError`), deterministic equality and hash (order matters), copy/deepcopy return the same object,
  pickling refused (`TypeError`).
- `.lookup()` returns a `WebResourceLookupResult` with `found`, `resource`, `failures`, `codes()` and `to_dict()`.

## Input rules
1. `resources` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected). An empty collection is valid.
2. Every item must be exactly a `WebResource`. Look-alikes, dicts and subclasses are rejected.
3. `resource_id` values must be unique by exact comparison (no trimming, no case folding).
4. Input order is preserved and never sorted; the same `WebResource` objects are stored (identity preserved) in an immutable tuple.
5. Every problem is reported at once, in input order. A bad item is reported once and never also counted as a duplicate.

## Lookup rules
- Exact `str` that matches a registered `resource_id` exactly: `found=True`, `resource` is the registered object.
- Exact `str` with no exact match (including differently cased or padded text, and the empty string): `found=False`, code `RESOURCE_NOT_FOUND`.
- Anything that is not exactly a `str` (None, bytes, int, a `str` subclass...): `found=False`, code `INVALID_RESOURCE_ID`. A `str` subclass is never
  compared, so none of its methods run.
- No trimming, case folding, normalization or coercion, and **no search by `url`, `title` or `resource_type`**.

## Codes
| problem | code |
|---|---|
| input is not exactly a list or tuple | `WEB_RESOURCE_REGISTRY_INVALID_COLLECTION` |
| item is not exactly a `WebResource` | `WEB_RESOURCE_REGISTRY_INVALID_RESOURCE` |
| repeated `resource_id` | `WEB_RESOURCE_REGISTRY_DUPLICATE_RESOURCE_ID` |
| lookup: no exact match | `WEB_RESOURCE_REGISTRY_RESOURCE_NOT_FOUND` |
| lookup: id is not exactly a `str` | `WEB_RESOURCE_REGISTRY_INVALID_RESOURCE_ID` |

The factory emits only the first three; `lookup()` emits only the last two. Each failure is `{"code", "field", "message"}`.

## What this module does NOT do
- It does NOT perform networking or any HTTP request, and does NOT parse, resolve or check any `url`.
- It does NOT read or write the filesystem, persist anything, use a database, an AI model, an external service or an external dependency.
- Its only import is `web.web_resource`. No module-level mutable state, no global registry, no clock or randomness.
- It is NOT wired into Core, `process_input()`, the Planner or the Agent Loop, and no multimedia, game or tool module was modified.

## Regression-guard change
The Prompt 718 frozen-production-tree test (`tests/test_section6_agent_loop_wiring_decision_prompt718.py`) now lists `web/__init__.py` and
`web/web_resource.py` (Prompt 773) as exact-path exemptions, plus `web/web_resource_registry.py` (this prompt) in the same style as every earlier
section. The frozen hash and count (294) and every other check are unchanged: the exemption is exact-path only, so any other new or modified
production file still fails that test.

## Section 9 position
Prompt 774 is the second Section 9 prompt (Web Resource Registry). Prompt 775 has NOT been started.
