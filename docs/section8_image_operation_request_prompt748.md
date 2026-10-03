# Prompt 748 - Section 8: Multimedia - Image Operation Request Foundation

Status: **implemented.** `multimedia/image_operation_request.py` (pinned by `tests/test_image_operation_request_prompt748.py`).

## What it represents
`ImageOperationRequest` is an immutable record that DESCRIBES one future image operation: which image (`image_id`), which operation, the wanted
`target_format`, and the wanted `width`, `height` and `quality`. It is only a request contract that later image-processing code can consume.
Nothing is processed, looked up or executed here. `image_asset.py` and `image_asset_registry.py` are unchanged and unaware of it.

## Public API
- `create_image_operation_request(data)` returns an `ImageOperationRequestResult` with `ok`, `request` (`None` unless `ok`), `failures`,
  `codes()` and `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `ImageOperationRequest`: read-only properties `image_id`, `operation`, `target_format`, `width`, `height`, `quality`; `to_dict()` returns a
  FRESH plain dict in the fixed field order on every call; deterministic equality and hashing (exact type only); direct construction and
  subclassing refused (`TypeError`); `copy`/`deepcopy` return the same object; pickling refused (`TypeError`); attribute assignment/deletion
  raises `AttributeError`.
- `ImageOperationRequestResult.to_dict()` returns `{"ok", "request", "failures"}` with fresh nested data.

## Validation rules
1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All six fields are required; nothing is defaulted. Missing and unexpected fields are rejected (a non-`str` or `str`-subclass key is unexpected).
3. `image_id` and `operation` must be exactly `str` and not empty. "Not empty" is applied as NOT BLANK (`value.strip() != ""`), the same rule
   as `image_id`/`name`/`format` in Prompt 746, so `""`, `"   "` and `"\n"` are rejected.
4. `operation` is validated FREE TEXT: there is no list of allowed operations, so new operations need no change to this contract.
5. `target_format` must be exactly `str`; the empty string (and any blank string) is allowed.
6. `width` and `height` must be exactly `int` and greater than zero.
7. `quality` must be exactly `int` from 1 through 100 inclusive.
8. `bool`, `int` subclasses, `float`, `str` and every other type are rejected for the three numbers.
9. Nothing is trimmed, normalized, case-folded, coerced or reordered. The same `str` objects are stored (identity preserved). The caller's dict
   is only read.

Failures are reported together, in a fixed order: input, unexpected fields sorted by name, then the six fields in declared order.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `IMAGE_OPERATION_REQUEST_INVALID_INPUT` |
| missing field | `IMAGE_OPERATION_REQUEST_MISSING_FIELD` |
| unexpected field (or non-`str` field name) | `IMAGE_OPERATION_REQUEST_UNEXPECTED_FIELD` |
| bad `image_id` | `IMAGE_OPERATION_REQUEST_INVALID_IMAGE_ID` |
| bad `operation` | `IMAGE_OPERATION_REQUEST_INVALID_OPERATION` |
| bad `target_format` | `IMAGE_OPERATION_REQUEST_INVALID_TARGET_FORMAT` |
| bad `width` | `IMAGE_OPERATION_REQUEST_INVALID_WIDTH` |
| bad `height` | `IMAGE_OPERATION_REQUEST_INVALID_HEIGHT` |
| bad `quality` (wrong type, bool, below 1 or above 100) | `IMAGE_OPERATION_REQUEST_INVALID_QUALITY` |

Each failure is `{"code", "field", "message"}`; `field` is `None` for input-level and non-`str`-key problems.

## What this module does NOT do
- It does NOT process, decode, resize, convert or inspect images, and it does NOT run any operation.
- It does NOT check that `image_id` is registered, that `operation` or `target_format` is known, or that `width`/`height` suit any image.
- It does NOT read or write files, use the network, a database, subprocesses, an AI model or any API, a clock or randomness.
- It imports nothing and keeps no module-level mutable state. It is NOT linked to Section 7, Game Creation, Core, `process_input()`, the
  Planner or the Agent Loop. No existing production module was modified.

## Limitations
- `operation` and `target_format` are free text; there is no operation-specific rule (for example, quality is required even for an operation
  that would ignore it, and there is no "keep original size" value for width/height).
- No upper bound on `width` and `height`.
- No link to `ImageAsset` or `ImageAssetRegistry`.

## Section 8 position
Prompt 748 is the third Section 8 prompt (746 Image Foundation, 747 Image Registry, 748 Image Operation Request Foundation). Prompt 749 has
NOT been started.
