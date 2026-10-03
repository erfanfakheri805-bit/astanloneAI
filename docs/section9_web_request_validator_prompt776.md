# Prompt 776 - Section 9: Web Request Validation

Status: **implemented.** `web/web_request_validator.py` (pinned by `tests/test_web_request_validator_prompt776.py`). Fourth Section 9 module. It
bridges `WebRequest` (Prompt 775) and `WebResourceRegistry` (Prompt 774) and follows the Image/Audio operation validators (Prompts 749 / 762).

## Public API
`validate_web_request(request, resource_registry)` returns a `WebRequestValidationResult` with `ok`, `request`, `registry`, `failures`,
`codes()` and `to_dict()`. It never raises for bad inputs and never changes what it is given.

## Order of checks
1. `request` must be exactly a `WebRequest` (subclasses, `None`, dicts, look-alikes are refused).
2. `resource_registry` must be exactly a `WebResourceRegistry`.
3. If either top-level input is invalid, NO cross-validation happens: the registry's `lookup()` is never called. Both top-level problems are reported
   together, request first.
4. Otherwise `request.resource_type` is resolved ONLY through the registry's public `lookup()`. The request's `resource_type` is matched by exact
   comparison against registered `resource_id` values. No private registry state is read and the lookup logic is not duplicated.
5. Not registered gives `RESOURCE_NOT_FOUND`; registered gives `ok`.

| problem | code | field |
|---|---|---|
| request is not exactly a `WebRequest` | `WEB_REQUEST_VALIDATION_INVALID_REQUEST` | `request` |
| registry is not exactly a `WebResourceRegistry` | `WEB_REQUEST_VALIDATION_INVALID_REGISTRY` | `resource_registry` |
| `resource_type` is not registered | `WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND` | `resource_type` |

## Result object
Immutable (`__slots__`, assignment/deletion raises), not subclassable, direct construction refused, equality and hash by value
(request, registry, failures), `to_dict()` returns FRESH plain data (`ok`, `request`, `registry`, `failures`), `failures` is a tuple of fresh
`{"code", "field", "message"}` dicts, `copy`/`deepcopy` return the same object, pickling is refused. `request` and `registry` are the very objects
passed in, each kept only when it was a valid exact-type input (so the registry is kept when the resource is not found). An invalid input is never stored.

## What this module does NOT do
- It does NOT validate `url`, `method`, `timeout_ms` or `request_id` beyond the Prompt 775 contract, and does NOT compare the request with the
  registered resource's `url`, `title` or `resource_type`.
- It does NOT execute a request or perform networking, and does NOT touch the filesystem, database, subprocesses, AI models or external services.
- It does NOT normalize, trim, case-fold or coerce anything; matching is exact.
- It does NOT modify Core, the Planner, the Agent Loop, earlier sections or the `WebResource` / `WebResourceRegistry` / `WebRequest` modules.

## Limitations
`resource_type` is matched against `resource_id` because the registry's only public lookup is by id. There is no URL policy, allow-list or executor yet.

## Section 9 position
Prompt 776 is the fourth Section 9 prompt. Prompt 777 has NOT been started.
