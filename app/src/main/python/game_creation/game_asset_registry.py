"""
Game Asset Registry (Prompt 727, Section 7 - Professional Game Creation)
============================================================================
A small, immutable, in-memory collection of `GameAsset` definitions with lookup by exact `asset_id`, optionally checked against the
asset identifiers listed by a `GameProjectStructure`:

    create_game_asset_registry(assets, structure=None) -> GameAssetRegistryResult(ok, registry, failures)
    GameAssetRegistry.lookup(asset_id)                 -> GameAssetLookupResult(found, asset, code)
    GameAssetRegistry.to_dict()                            -> {"assets": [GameAsset.to_dict(), ...]}

INPUT RULES
- `assets` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and
  an unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly a `GameAsset` (Prompt 727). `asset_id` values must be unique (exact comparison). Input order is preserved.
- `structure` is `None` (no structure check) or exactly a `GameProjectStructure` (Prompt 721). When given, EVERY identifier in
  `structure.assets` must have a registered asset; a registered asset that the structure does not list is allowed (unused
  definitions are fine). Neither the structure nor the assets are changed.
- `create_game_asset_registry()` never raises for bad input: it reports every problem at once in a fixed order (collection problems by
  position, then the structure, then missing references in `structure.assets` order), using stable codes from `FAILURE_CODES`. The reference
  check runs only when `structure` is valid, against the valid assets found.
- Direct `GameAssetRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(asset_id)` never raises: it returns a `GameAssetLookupResult` with `found=True` and the `GameAsset`, or `found=False`,
`asset=None` and code `FAILURE_ASSET_NOT_FOUND` (also for a `asset_id` that is not exactly a `str`). No trimming or case folding.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) assets; `assets` and `asset_ids` return tuples. `__slots__`, assignment /
deletion raises, not subclassable. Equal assets in the same order mean equal registries and hashes (a different order is a different
registry); `to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy return the same object; pickling is refused.
The structure is used only for validation and is not stored.

WHAT THIS MODULE DOES NOT DO
No character, scene or gameplay-system relationships, no asset content or file paths (textures, models, animation, audio, shaders,
rendering, loading, ...), no filesystem, network, database, AI model or external service, no clock or randomness, no module-level mutable state, no global registry. Its only imports are the two Section 7
record modules. It is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_asset import GameAsset
from .game_project_structure import GameProjectStructure

FAILURE_INVALID_COLLECTION = "GAME_ASSET_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_ASSET = "GAME_ASSET_REGISTRY_INVALID_ASSET"
FAILURE_DUPLICATE_ASSET_ID = "GAME_ASSET_REGISTRY_DUPLICATE_ASSET_ID"
FAILURE_INVALID_STRUCTURE = "GAME_ASSET_REGISTRY_INVALID_STRUCTURE"
FAILURE_MISSING_ASSET_REFERENCE = "GAME_ASSET_REGISTRY_MISSING_ASSET_REFERENCE"
FAILURE_ASSET_NOT_FOUND = "GAME_ASSET_REGISTRY_ASSET_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_ASSET, FAILURE_DUPLICATE_ASSET_ID, FAILURE_INVALID_STRUCTURE,
                 FAILURE_MISSING_ASSET_REFERENCE, FAILURE_ASSET_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameAssetLookupResult:
    """Outcome of `GameAssetRegistry.lookup()`: `asset` is set only when `found`; otherwise `code` is FAILURE_ASSET_NOT_FOUND."""

    __slots__ = ("found", "asset", "code")

    def __init__(self, found, asset=None, code=None):
        self.found = found
        self.asset = asset
        self.code = code

    def to_dict(self):
        return {"found": self.found, "asset": self.asset.to_dict() if self.asset is not None else None, "code": self.code}


class GameAssetRegistry:
    """Immutable, ordered collection of `GameAsset` objects with unique ids. Obtain it only from `create_game_asset_registry()`."""

    __slots__ = ("_assets",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameAssetRegistry cannot be subclassed.")

    def __init__(self, _token, assets):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_asset_registry() to build a GameAssetRegistry.")
        object.__setattr__(self, "_assets", tuple(assets))

    def __setattr__(self, key, value):
        raise AttributeError("GameAssetRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameAssetRegistry is immutable.")

    @property
    def assets(self):
        """Tuple of the registered `GameAsset` objects, in registration order."""
        return self._assets

    @property
    def asset_ids(self):
        """Tuple of the registered asset ids, in registration order."""
        return tuple(c.asset_id for c in self._assets)

    def lookup(self, asset_id):
        """Find a asset by exact `asset_id`. Never raises; returns a `GameAssetLookupResult`."""
        if type(asset_id) is str:
            for asset in self._assets:
                if asset.asset_id == asset_id:
                    return GameAssetLookupResult(True, asset)
        return GameAssetLookupResult(False, None, FAILURE_ASSET_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"assets": [c.to_dict() for c in self._assets]}

    def __eq__(self, other):
        if type(other) is not GameAssetRegistry:
            return NotImplemented
        return self._assets == other._assets

    def __hash__(self):
        return hash(self._assets)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameAssetRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameAssetRegistry(asset_ids=%r)" % (self.asset_ids,)


class GameAssetRegistryResult:
    """Outcome of `create_game_asset_registry()`: `registry` is set only when `ok`."""

    __slots__ = ("registry", "failures")

    def __init__(self, registry=None, failures=None):
        self.registry = registry
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.registry is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "registry": self.registry.to_dict() if self.registry is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_game_asset_registry(assets, structure=None):
    """Validate `assets` (a list or tuple of `GameAsset`, unique ids) and, when given, `structure` (a `GameProjectStructure` whose
    asset ids must all be registered), then build an immutable `GameAssetRegistry`. Deterministic, never raises for bad input, changes
    nothing it is given. Returns a `GameAssetRegistryResult`."""
    failures = []
    valid = []
    if type(assets) not in (list, tuple):
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "assets must be a list or a tuple of GameAsset objects.", "assets"))
    else:
        seen = set()
        for index, item in enumerate(assets):
            if type(item) is not GameAsset:
                failures.append(_failure(FAILURE_INVALID_ASSET, "assets[%d] must be a GameAsset." % index, "assets"))
            elif item.asset_id in seen:
                failures.append(_failure(FAILURE_DUPLICATE_ASSET_ID,
                                         "assets[%d] duplicates an earlier asset_id: %r." % (index, item.asset_id), "assets"))
            else:
                seen.add(item.asset_id)
                valid.append(item)
    if structure is not None:
        if type(structure) is not GameProjectStructure:
            failures.append(_failure(FAILURE_INVALID_STRUCTURE, "structure must be None or a GameProjectStructure.", "structure"))
        else:
            known = set(c.asset_id for c in valid)
            for asset_id in structure.assets:
                if asset_id not in known:
                    failures.append(_failure(FAILURE_MISSING_ASSET_REFERENCE,
                                             "structure.assets lists %r but no such asset is registered." % asset_id, "structure"))
    if failures:
        return GameAssetRegistryResult(failures=failures)
    return GameAssetRegistryResult(registry=GameAssetRegistry(_CREATE_TOKEN, valid))
