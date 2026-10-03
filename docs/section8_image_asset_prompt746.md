# Prompt 746 - Section 8: Multimedia - Image Foundation

Status: **implemented.** `multimedia/image_asset.py` (pinned by `tests/test_image_asset_prompt746.py`). This is the first Section 8 module.

## What it represents
`ImageAsset` is an immutable record of the BASIC METADATA of one image asset: `image_id`, `name`, `description`, `format`, `width`, `height`.
It follows the same shape and conventions as `GameAsset` (Prompt 727) but is a separate, unrelated type. It holds no pixels and no location.

## Public API
- `create_image_asset(data)` returns an `ImageAssetResult` with `ok`, `asset` (`None` unless `ok`), `failures`, `codes()` and `to_dict()`.
  It never raises for bad data and never changes the caller's dict.
- `ImageAsset`: read-only properties `image_id`, `name`, `description`, `format`, `width`, `height`; `to_dict()` returns a FRESH plain dict in
  the fixed field order on every call; deterministic equality and hashing (exact type only); direct construction and subclassing refused
  (`TypeError`); `copy`/`deepcopy` return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises
  `AttributeError`.
- `ImageAssetResult.to_dict()` returns `{"ok", "asset", "failures"}` with fresh nested data.

## Validation rules
1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All six fields are required; nothing is defaulted.
3. `image_id`, `name`, `description` and `format` must be exactly `str` (no `str` subclass).
4. `image_id`, `name` and `format` must be nonblank (`value.strip() != ""`).
5. `description` may be empty (or blank).
6. `width` and `height` must be exactly `int` and greater than zero. `bool`, `int` subclasses, `float`, `str` and everything else are rejected.
7. Missing and unexpected fields are rejected (an unexpected field is never ignored; a non-`str` or `str`-subclass key is unexpected).
8. Nothing is trimmed, normalized, coerced or mutated. The same `str` objects are stored (identity preserved). The caller's dict is only read.

Failures are reported together, in a fixed order: input, unexpected fields sorted by name, then the six fields in declared order.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `IMAGE_ASSET_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `IMAGE_ASSET_UNEXPECTED_FIELD` |
| missing field | `IMAGE_ASSET_MISSING_FIELD` |
| bad `image_id` | `IMAGE_ASSET_INVALID_IMAGE_ID` |
| bad `name` | `IMAGE_ASSET_INVALID_NAME` |
| bad `description` | `IMAGE_ASSET_INVALID_DESCRIPTION` |
| bad `format` | `IMAGE_ASSET_INVALID_FORMAT` |
| bad `width` | `IMAGE_ASSET_INVALID_WIDTH` |
| bad `height` | `IMAGE_ASSET_INVALID_HEIGHT` |

Each failure is `{"code", "field", "message"}`; `field` is `None` for input-level and non-`str`-key problems.

## What this module does NOT do
- It does NOT process, decode, resize or inspect images, detect or check the `format`, or validate it against a list of known formats.
- It does NOT read or write files, use the network, a database, subprocesses, an AI model or any API, a clock or randomness.
- It imports nothing (not even the standard library) and keeps no module-level mutable state.
- It is NOT linked to any Section 7 module (`GameAsset`, registries, `GameProject`), Game Creation, Core, `process_input()`, the Planner or the
  Agent Loop. No existing module was modified.

## Limitations
- `format` is free text; `width`/`height` have no upper bound; there is no aspect-ratio, size-in-bytes, color or location metadata.
- There is no image registry yet and no way to relate an `ImageAsset` to a game asset.

## Section 8 position
Prompt 746 is the first Section 8 prompt (Multimedia - Image Foundation). Prompt 747 has NOT been started.
