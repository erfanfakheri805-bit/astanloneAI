# Prompt 760 - Section 8: Multimedia - Audio Asset Registry

Status: **implemented.** `multimedia/audio_asset_registry.py` (pinned by `tests/test_audio_asset_registry_prompt760.py`).

## What it represents
`AudioAssetRegistry` is an immutable, ordered collection of `AudioAsset` objects (Prompt 759) with exact-id lookup. It follows the registry pattern of
`ImageAssetRegistry` (Prompt 747) but is a separate type with no link to `ImageAsset` or Section 7. `audio_asset.py` is unchanged (its SHA-256 is pinned
by the tests) and unaware of the registry.

## Public API
- `create_audio_asset_registry(assets)` returns an `AudioAssetRegistryResult` with `ok`, `registry` (`None` unless `ok`), `failures`, `codes()` and
  `to_dict()`. It never raises for bad input and never changes what it is given.
- `AudioAssetRegistry`: `assets` and `audio_ids` (tuples, registration order), `lookup(audio_id)`, `to_dict()`. There are no mutating methods.
- `lookup(audio_id)` returns an `AudioAssetLookupResult` with `found`, `asset`, `failures`, `codes()` and `to_dict()`.
- All three classes are immutable (`__slots__`, assignment/deletion raises `AttributeError`), cannot be built directly or subclassed (`TypeError`),
  compare and hash by value (exact type only), return themselves from `copy`/`deepcopy`, and refuse pickling (`TypeError`), as `ImageAssetRegistry` does.
- `failures` is a tuple of FRESH `{"code", "field", "message"}` dicts; `codes()` and every `to_dict()` return fresh data on each call.

## Registry behavior
1. `assets` must be exactly a `list` or a `tuple` (subclasses, sets, dicts, generators, strings and everything else are rejected).
2. An empty list or tuple is valid and gives an empty registry.
3. Every item must be exactly an `AudioAsset` (a dict, a look-alike, an `ImageAsset`, a Section 7 `GameAsset` or a subclass is rejected; nothing is coerced).
4. `audio_id` values must be unique by exact comparison: no trimming, no case folding, no Unicode normalization.
5. Input order is preserved (never sorted); a different order is a different registry.
6. The registry stores its own tuple of the very same `AudioAsset` objects (identity preserved), so later edits to the caller's list have no effect.
7. All problems are reported together, in input order. A bad item is reported once and is never also counted as a duplicate.

## Lookup behavior
- Exact `str` that matches a registered `audio_id` exactly: `found=True`, `asset` is the registered object, no failures.
- Exact `str` with no exact match (including different case, padding or Unicode form, and `""`): `found=False`, `asset=None`, `AUDIO_NOT_FOUND`.
- Anything that is not exactly a `str` (`None`, `bytes`, `int`, `bool`, a `str` subclass, an `AudioAsset`, ...): `found=False`, `asset=None`,
  `INVALID_AUDIO_ID`. A `str` subclass is never compared, so none of its methods run.
- Lookup never raises, never changes the registry, and the not-found result is deterministic (equal and equal-hash on repeat).

## Failure codes
Each failure is `{"code", "field", "message"}`. These five are the only codes.

| problem | code | produced by |
|---|---|---|
| `assets` is not exactly a `list` or `tuple` | `AUDIO_ASSET_REGISTRY_INVALID_COLLECTION` | factory |
| an item is not exactly an `AudioAsset` | `AUDIO_ASSET_REGISTRY_INVALID_ASSET` | factory |
| an `audio_id` repeats (exact comparison) | `AUDIO_ASSET_REGISTRY_DUPLICATE_AUDIO_ID` | factory |
| `lookup()` of an unregistered `str` | `AUDIO_ASSET_REGISTRY_AUDIO_NOT_FOUND` | lookup |
| `lookup()` of a non-`str` | `AUDIO_ASSET_REGISTRY_INVALID_AUDIO_ID` | lookup |

## Difference from the Prompt 747 image registry
The Prompt 747 result classes (`ImageAssetRegistryResult`, `ImageAssetLookupResult`) are plain slot holders whose attributes can be reassigned and
whose `failures` is a list. Prompt 760 required immutable results, so the audio result classes follow the immutable-result pattern of the Prompt 757
batch result instead: read-only members, `failures` as a tuple of fresh dicts, value equality/hash, no direct construction. Member names are the same.

## What this module does NOT do
- It does NOT hold audio content or file paths, read or write files, decode, play or process audio, or use the network, a database, subprocesses,
  an AI model or any external service.
- It does NOT use a clock or randomness, keep module-level mutable state, or offer a global registry.
- Its only import is `AudioAsset` from the Prompt 759 module. It is NOT linked to `ImageAsset`, Section 7 (`GameAsset`, registries, `GameProject`), Core,
  `process_input()`, the Planner or the Agent Loop. No existing production module was modified.

## Limitations
- `lookup()` is a linear scan (the registry keeps only a tuple); fine for small collections.
- No add/remove/merge operations: a different registry means building a new one.
- No lookup by name, format, duration or sample rate.

## Section 8 position
Prompt 760 follows the Audio asset contract (Prompt 759). Prompt 761 has **not** been started.
