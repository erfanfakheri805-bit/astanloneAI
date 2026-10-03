# Prompt 727 - Section 7: Game Asset and Game Asset Registry

Status: **implemented.** `game_creation/game_asset.py` (pinned by `tests/test_game_asset_prompt727.py`) and `game_creation/game_asset_registry.py`
(pinned by `tests/test_game_asset_registry_prompt727.py`).

## What they represent
`GameAsset` is an immutable record of the BASIC METADATA of one game asset: `asset_id`, `name`, `description`, `asset_type`. It mirrors
`GameScene` (Prompt 722) and `GameCharacter` (Prompt 723). `GameAssetRegistry` is an immutable, ordered collection of `GameAsset` objects with
exact-id lookup, optionally checked against the asset identifiers listed by a `GameProjectStructure` (Prompt 721), following the registry pattern
of Prompts 724-726. All earlier Section 7 modules are unchanged and remain unaware of both new modules.

## GameAsset API
- `create_game_asset(data)` returns a `GameAssetResult` with `ok`, `asset`, `failures`, `codes()` and `to_dict()`. It never raises for bad data.
- `data` must be exactly a plain `dict` with exactly the four fields. Every value must be exactly a `str`. `asset_id`, `name` and `asset_type`
  must not be blank; `description` may be empty. Nothing is coerced, trimmed or normalized.
- `GameAsset` has read-only properties, deterministic equality and hashing, fresh `to_dict()` in fixed field order, refused direct construction
  and subclassing, copy returning the same object, and refused pickling.

| problem | code |
|---|---|
| `data` is not exactly a `dict` (including a dict subclass) | `GAME_ASSET_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `GAME_ASSET_UNEXPECTED_FIELD` |
| missing field | `GAME_ASSET_MISSING_FIELD` |
| bad `asset_id` / `name` / `description` / `asset_type` | `GAME_ASSET_INVALID_ASSET_ID` / `_INVALID_NAME` / `_INVALID_DESCRIPTION` / `_INVALID_ASSET_TYPE` |

Failures are reported together in a fixed order: input, unexpected fields sorted by name, then the four fields in declared order.

## GameAssetRegistry API
- `create_game_asset_registry(assets, structure=None)` returns a `GameAssetRegistryResult` with `ok`, `registry`, `failures`, `codes()` and
  `to_dict()`. It never raises for bad input.
- `GameAssetRegistry`: `assets` and `asset_ids` (tuples, registration order), `lookup(asset_id)`, `to_dict()` (fresh data), deterministic
  equality and hashing, refused construction, subclassing and pickling, copy returning the same object.
- `lookup()` returns a `GameAssetLookupResult(found, asset, code)`. A missing or non-`str` id gives `found=False` and
  `GAME_ASSET_REGISTRY_ASSET_NOT_FOUND`; it never raises.

| problem | code |
|---|---|
| `assets` is not exactly a `list` or `tuple` | `GAME_ASSET_REGISTRY_INVALID_COLLECTION` |
| an item is not exactly a `GameAsset` | `GAME_ASSET_REGISTRY_INVALID_ASSET` |
| an `asset_id` repeats (exact comparison) | `GAME_ASSET_REGISTRY_DUPLICATE_ASSET_ID` |
| `structure` is neither `None` nor a `GameProjectStructure` | `GAME_ASSET_REGISTRY_INVALID_STRUCTURE` |
| an id in `structure.assets` has no registered asset | `GAME_ASSET_REGISTRY_MISSING_ASSET_REFERENCE` |
| lookup of an unknown or non-string id (lookup only) | `GAME_ASSET_REGISTRY_ASSET_NOT_FOUND` |

Registry problems are reported in a fixed order: collection problems by position, then the structure, then missing references in
`structure.assets` order. The reference check runs only for a valid structure and counts only accepted assets. Unused registered assets are
allowed. The structure is validation-only: it is not stored or changed, so a registry built with and without it is equal.

## What it intentionally does NOT do yet
No asset loading, file paths, filesystem scanning, textures, models, animations, audio, shaders, rendering, engine integration, persistence,
database, network or AI access; no gameplay systems; no wiring into `process_input`, Core, the Planner or the Agent Loop. It does not check the
other structure collections (`scenes`, `characters`, `gameplay_systems`).

## How later prompts can build on it
A later step can combine the character, scene, gameplay-system and asset registries into one validated project view. Richer asset capabilities
can refer to registered assets by `asset_id`; because both modules hold only immutable metadata, such additions need not change them.

## Limitations noted
- Only `list` and `tuple` inputs are accepted; lookup is a linear scan meant for small collections.
- Ids are compared exactly and kept as given (`"Tree"` and `"tree"` are different assets).
- `asset_type` is any non-blank text; there is no fixed asset-type list.
- Referenced-but-missing assets are the only structure check; unused registered assets are not reported.
