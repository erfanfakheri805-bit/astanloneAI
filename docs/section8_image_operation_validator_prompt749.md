# Prompt 749 - Section 8: Multimedia - Image Operation Request Registry Validation

Status: **implemented.** `multimedia/image_operation_validator.py` (pinned by `tests/test_image_operation_validator_prompt749.py`).

## What it does
`validate_image_operation_request(request, image_registry)` checks one thing: does an `ImageOperationRequest` (Prompt 748) name an image that is
registered in an `ImageAssetRegistry` (Prompt 747)? It returns an immutable `ImageOperationValidationResult`. It is a pure in-memory bridge between
two existing contracts. `image_asset.py`, `image_asset_registry.py`, `image_operation_request.py` and Section 7 are unchanged.

## Validation order
1. `request` must be exactly an `ImageOperationRequest`.
2. `image_registry` must be exactly an `ImageAssetRegistry`.
3. If either top-level input is invalid, NO cross-validation is done (the registry is never asked anything). Both top-level problems are reported
   together, request first.
4. `request.image_id` is resolved only through the registry's public `lookup()`. The lookup logic is not duplicated and no private registry state
   is read.
5. Not registered: `IMAGE_NOT_FOUND`.
6. Registered: `ok`, and `asset` is the exact registered `ImageAsset` object (same identity, not a copy).
7. The request, registry and asset are only read, never changed.

| problem | code |
|---|---|
| `request` is not exactly an `ImageOperationRequest` (subclass-like, `None`, `dict`, ...) | `IMAGE_OPERATION_VALIDATION_INVALID_REQUEST` |
| `image_registry` is not exactly an `ImageAssetRegistry` | `IMAGE_OPERATION_VALIDATION_INVALID_IMAGE_REGISTRY` |
| `request.image_id` is not registered (exact comparison) | `IMAGE_OPERATION_VALIDATION_IMAGE_NOT_FOUND` |

Each failure is `{"code", "field", "message"}` with `field` one of `request`, `image_registry`, `image_id`.

## Result: `ImageOperationValidationResult`
- Read-only properties `ok`, `request`, `asset`, `failures`; methods `codes()` and `to_dict()`.
- `ok` is true exactly when there are no failures.
- `request` is the validated request (the same object) whenever the request input was a valid `ImageOperationRequest`, including when the image was
  not found; it is `None` when the request input was invalid. `asset` is set only when found. Invalid inputs are never stored, so every result stays
  hashable and holds nothing unsafe.
- `failures` is a tuple of fresh dicts on every access; `to_dict()` returns `{"ok", "request", "asset", "failures"}` as fresh plain data.
- Deterministic equality and hashing by value (exact type only). Direct construction and subclassing raise `TypeError`; `copy`/`deepcopy` return the
  same object; pickling raises `TypeError`; attribute assignment/deletion raises `AttributeError`.

## Rules
- Exact types only. No normalization, trimming, case folding, coercion or alternate lookup: `"Hero"` and `"hero"` are different ids.
- `operation`, `target_format`, `width`, `height` and `quality` are not examined beyond Prompt 748.
- The function never raises for bad inputs and never calls anything on a caller-supplied object that is not an exact expected type.

## What this module does NOT do
- It does NOT process, decode, resize, convert or inspect images, and it does NOT touch the filesystem, network, a database, an AI model or any API.
- It does NOT check that the requested `width`/`height` suit the real image, or that `target_format`/`operation` are known or compatible with the
  asset's format; that belongs to a future processing layer.
- It does NOT use a clock, randomness or module-level mutable state. It is NOT wired into Core, `process_input()`, the Planner, the Agent Loop or
  Section 7.

## Limitations
- Only the first failure of the lookup step exists (`IMAGE_NOT_FOUND`); there is no separate code for a registry that misbehaves.
- No batch validation of several requests, and no link from a result to any later processing step. Prompt 750 has NOT been started.
