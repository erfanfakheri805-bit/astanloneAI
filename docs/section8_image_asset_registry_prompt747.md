# Prompt 747 - Section 8: Multimedia - Image Registry

Status: **implemented.** `multimedia/image_asset_registry.py` (pinned by `tests/test_image_asset_registry_prompt747.py`).

## What it represents
`ImageAssetRegistry` is an immutable, ordered collection of `ImageAsset` objects (Prompt 746) with exact-id lookup. It follows the registry
pattern of `GameAssetRegistry` (Prompt 727) but is a separate type with no link to Section 7. `image_asset.py` is unchanged and unaware of it.

## Public API
- `create_image_asset_registry(assets)` returns an `ImageAssetRegistryResult` with `ok`, `registry` (`None` unless `ok`), `failures`, `codes()`
  and `to_dict()`. It never raises for bad input and never changes what it is given.
- `ImageAssetRegistry`: `assets` and `image_ids` (tuples, registration order), `lookup(image_id)`, `to_dict()`. Deterministic equality and
  hashing, direct construction and subclassing refused (`TypeError`), `copy`/`deepcopy` return the same object, pickling refused
  (`TypeError`), attribute assignment/deletion raises `AttributeError`. There are no mutating methods.
- `lookup(image_id)` returns an `ImageAssetLookupResult` with `found`, `asset`, `failures`, `codes()` and `to_dict()`.

## Registry behavior
1. `assets` must be exactly a `list` or a `tuple` (subclasses, sets, dicts, generators, strings and everything else are rejected).
2. An empty list or tuple is valid and gives an empty registry.
3. Every item must be exactly an `ImageAsset` (a dict, a look-alike, a Section 7 `GameAsset` or a subclass is rejected; nothing is coerced).
4. `image_id` values must be unique by exact comparison: no trimming, no case folding, no Unicode normalization.
5. Input order is preserved (never sorted); a different order is a different registry.
6. The registry stores its own tuple of the very same `ImageAsset` objects (identity preserved), so later edits to the caller's list have no effect.
7. All problems are reported together, in input order. A bad item is reported once and is never also counted as a duplicate.

## Lookup behavior
- Exact `str` that matches a registered `image_id` exactly: `found=True`, `asset` is the registered object, `failures=[]`.
- Exact `str` with no exact match (including different case, padding or Unicode form, and `""`): `found=False`, `asset=None`, `IMAGE_NOT_FOUND`.
- Anything that is not exactly a `str` (`None`, `bytes`, `int`, `bool`, a `str` subclass, an `ImageAsset`, ...): `found=False`, `asset=None`,
  `INVALID_IMAGE_ID`. A `str` subclass is never compared, so none of its methods run.
- Lookup never raises, never changes the registry, and the not-found result is deterministic.
- `to_dict()` of a result is fresh: `{"found", "asset", "failures"}`.

## Failure codes
Each failure is `{"code", "field", "message"}`.

| problem | code | produced by |
|---|---|---|
| `assets` is not exactly a `list` or `tuple` | `IMAGE_ASSET_REGISTRY_INVALID_COLLECTION` | factory |
| an item is not exactly an `ImageAsset` | `IMAGE_ASSET_REGISTRY_INVALID_ASSET` | factory |
| an `image_id` repeats (exact comparison) | `IMAGE_ASSET_REGISTRY_DUPLICATE_IMAGE_ID` | factory |
| `lookup()` of an unregistered `str` | `IMAGE_ASSET_REGISTRY_IMAGE_NOT_FOUND` | lookup |
| `lookup()` of a non-`str` | `IMAGE_ASSET_REGISTRY_INVALID_IMAGE_ID` | lookup |

## What this module does NOT do
- It does NOT hold image content or file paths, read or write files, decode or process images, or use the network, a database, subprocesses,
  an AI model or any external service.
- It does NOT use a clock or randomness, keep module-level mutable state, or offer a global registry.
- Its only import is `ImageAsset` from the Prompt 746 module. It is NOT linked to Section 7 (`GameAsset`, registries, `GameProject`), Game
  Creation, Core, `process_input()`, the Planner or the Agent Loop. No existing production module was modified.

## Limitations
- `lookup()` is a linear scan (the registry keeps only a tuple); fine for small collections.
- No add/remove/merge operations: a different registry means building a new one.
- No lookup by name, format or size, and no relation to `GameAsset`.

## Section 8 position
Prompt 747 is the second Section 8 prompt (746 Image Foundation, 747 Image Registry). Prompt 748 has NOT been started.
