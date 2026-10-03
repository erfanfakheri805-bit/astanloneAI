"""
Image Asset Registry (Prompt 747, Section 8 - Multimedia)
=========================================================
A small, immutable, in-memory, ordered collection of `ImageAsset` objects with lookup by exact `image_id`:

    create_image_asset_registry(assets)  -> ImageAssetRegistryResult(ok, registry, failures)
    ImageAssetRegistry.lookup(image_id)  -> ImageAssetLookupResult(found, asset, failures)
    ImageAssetRegistry.to_dict()         -> {"assets": [ImageAsset.to_dict(), ...]}

INPUT RULES
- `assets` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and an
  unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly an `ImageAsset` (Prompt 746). `image_id` values must be unique by exact comparison (no trimming, no case folding).
  Input order is preserved.
- `create_image_asset_registry()` never raises for bad input: it reports every problem at once, in input order, using stable codes from
  `FAILURE_CODES`. A bad item is reported once and never also counted as a duplicate. The caller's collection and the assets are only read.
- Direct `ImageAssetRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(image_id)` never raises and returns an `ImageAssetLookupResult`:
- an exact `str` that matches a registered `image_id` exactly: `found=True`, `asset` is the very registered object, `failures=[]`;
- an exact `str` with no exact match (including a differently-cased or padded id): `found=False`, `asset=None`, code `IMAGE_NOT_FOUND`;
- anything that is not exactly a `str` (None, bytes, a `str` subclass, an int, ...): `found=False`, `asset=None`, code `INVALID_IMAGE_ID`.
No trimming, case folding, normalization or coercion. A `str` subclass is never compared, so none of its methods are run.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) assets; `assets` and `image_ids` return tuples. `__slots__`, assignment / deletion
raises, not subclassable. Equal assets in the same order mean equal registries and equal hashes (a different order is a different registry);
`to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
No image content, no file paths, no decoding or image processing, no filesystem, network, database, AI model or external service, no clock or
randomness, no module-level mutable state, no global registry. Its only import is the Prompt 746 `ImageAsset` module. It has no link to
Section 7 (`GameAsset` and friends) and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .image_asset import ImageAsset

FAILURE_INVALID_COLLECTION = "IMAGE_ASSET_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_ASSET = "IMAGE_ASSET_REGISTRY_INVALID_ASSET"
FAILURE_DUPLICATE_IMAGE_ID = "IMAGE_ASSET_REGISTRY_DUPLICATE_IMAGE_ID"
FAILURE_IMAGE_NOT_FOUND = "IMAGE_ASSET_REGISTRY_IMAGE_NOT_FOUND"      # lookup only; never produced by the factory
FAILURE_INVALID_IMAGE_ID = "IMAGE_ASSET_REGISTRY_INVALID_IMAGE_ID"    # lookup only; never produced by the factory

FACTORY_FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_ASSET, FAILURE_DUPLICATE_IMAGE_ID)
LOOKUP_FAILURE_CODES = (FAILURE_IMAGE_NOT_FOUND, FAILURE_INVALID_IMAGE_ID)
FAILURE_CODES = FACTORY_FAILURE_CODES + LOOKUP_FAILURE_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class ImageAssetLookupResult:
    """Outcome of `ImageAssetRegistry.lookup()`: `asset` is set only when `found`; otherwise `failures` holds exactly one failure."""

    __slots__ = ("found", "asset", "failures")

    def __init__(self, found=False, asset=None, failures=None):
        self.found = found
        self.asset = asset
        self.failures = [] if failures is None else failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"found": self.found, "asset": self.asset.to_dict() if self.asset is not None else None,
                "failures": [dict(f) for f in self.failures]}


class ImageAssetRegistry:
    """Immutable, ordered collection of `ImageAsset` objects with unique ids. Obtain it only from `create_image_asset_registry()`."""

    __slots__ = ("_assets",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageAssetRegistry cannot be subclassed.")

    def __init__(self, _token, assets):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_asset_registry() to build an ImageAssetRegistry.")
        object.__setattr__(self, "_assets", tuple(assets))

    def __setattr__(self, key, value):
        raise AttributeError("ImageAssetRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageAssetRegistry is immutable.")

    @property
    def assets(self):
        """Tuple of the registered `ImageAsset` objects, in registration order."""
        return self._assets

    @property
    def image_ids(self):
        """Tuple of the registered image ids, in registration order."""
        return tuple(a.image_id for a in self._assets)

    def lookup(self, image_id):
        """Find an asset by exact `image_id`. Never raises; returns an `ImageAssetLookupResult`."""
        if type(image_id) is not str:
            return ImageAssetLookupResult(False, None, [_failure(FAILURE_INVALID_IMAGE_ID, "image_id must be a str.", "image_id")])
        for asset in self._assets:
            if asset.image_id == image_id:
                return ImageAssetLookupResult(True, asset)
        return ImageAssetLookupResult(False, None, [_failure(FAILURE_IMAGE_NOT_FOUND, "No image asset is registered with image_id %r." % image_id, "image_id")])

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"assets": [a.to_dict() for a in self._assets]}

    def __eq__(self, other):
        if type(other) is not ImageAssetRegistry:
            return NotImplemented
        return self._assets == other._assets

    def __hash__(self):
        return hash(self._assets)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageAssetRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageAssetRegistry(image_ids=%r)" % (self.image_ids,)


class ImageAssetRegistryResult:
    """Outcome of `create_image_asset_registry()`: `registry` is set only when `ok`."""

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


def create_image_asset_registry(assets):
    """Validate `assets` (a list or tuple of `ImageAsset`, unique image ids) and build an immutable `ImageAssetRegistry`.
    Deterministic, never raises for bad input, changes nothing it is given. Returns an `ImageAssetRegistryResult`."""
    if type(assets) not in (list, tuple):
        return ImageAssetRegistryResult(failures=[_failure(FAILURE_INVALID_COLLECTION,
                                                           "assets must be a list or a tuple of ImageAsset objects.", "assets")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(assets):
        if type(item) is not ImageAsset:
            failures.append(_failure(FAILURE_INVALID_ASSET, "assets[%d] must be an ImageAsset." % index, "assets"))
        elif item.image_id in seen:
            failures.append(_failure(FAILURE_DUPLICATE_IMAGE_ID, "assets[%d] duplicates an earlier image_id: %r." % (index, item.image_id), "assets"))
        else:
            seen.add(item.image_id)
            valid.append(item)
    if failures:
        return ImageAssetRegistryResult(failures=failures)
    return ImageAssetRegistryResult(registry=ImageAssetRegistry(_CREATE_TOKEN, valid))
