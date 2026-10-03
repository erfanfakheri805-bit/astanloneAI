"""
Image Asset Foundation (Prompt 746, Section 8 - Multimedia)
===========================================================
A small, immutable, in-memory record of the BASIC METADATA of one image asset:

    create_image_asset(data) -> ImageAssetResult(ok, asset, failures)
    ImageAsset.to_dict()     -> {"image_id", "name", "description", "format", "width", "height"}

`data` is an exact plain `dict` holding exactly the six fields below. Nothing else is accepted.

    image_id     str, not empty / not blank
    name         str, not empty / not blank
    description  str, may be empty
    format       str, not empty / not blank (any text; no fixed format list)
    width        int, exactly `int` (never bool), > 0
    height       int, exactly `int` (never bool), > 0

RULES
- All six fields must be present (no defaults are invented). The four text fields must be exactly `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run); `width` and `height` must be exactly `int` (`bool`, an `int` subclass, `float`, `str`
  and every other type are rejected) and greater than zero. "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased,
  coerced or otherwise changed - what the caller supplied is what is stored, and the very same `str` objects are kept (identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_image_asset()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the six fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read, never changed.
- Direct `ImageAsset(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It holds no pixels and no location: no file paths, no decoding, no image processing, no format detection or checking, no resizing, no color
data. It is not linked to Section 7 (`GameAsset` and friends) or to any other module. No filesystem, network, subprocess, database, AI model or
external service, no clock or randomness, no module-level mutable state. Imports nothing at all and is not wired into `process_input()`, Core,
the Planner or the Agent Loop.
"""

FIELDS = ("image_id", "name", "description", "format", "width", "height")
REQUIRED_NON_BLANK = ("image_id", "name", "format")
STRING_FIELDS = ("image_id", "name", "description", "format")
DIMENSION_FIELDS = ("width", "height")

FAILURE_INVALID_INPUT = "IMAGE_ASSET_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "IMAGE_ASSET_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "IMAGE_ASSET_MISSING_FIELD"
FAILURE_INVALID_IMAGE_ID = "IMAGE_ASSET_INVALID_IMAGE_ID"
FAILURE_INVALID_NAME = "IMAGE_ASSET_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "IMAGE_ASSET_INVALID_DESCRIPTION"
FAILURE_INVALID_FORMAT = "IMAGE_ASSET_INVALID_FORMAT"
FAILURE_INVALID_WIDTH = "IMAGE_ASSET_INVALID_WIDTH"
FAILURE_INVALID_HEIGHT = "IMAGE_ASSET_INVALID_HEIGHT"

_INVALID_CODES = (FAILURE_INVALID_IMAGE_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION, FAILURE_INVALID_FORMAT,
                  FAILURE_INVALID_WIDTH, FAILURE_INVALID_HEIGHT)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class ImageAsset:
    """Immutable data record of one image asset's basic metadata. Obtain it only from `create_image_asset()`."""

    __slots__ = ("_image_id", "_name", "_description", "_format", "_width", "_height")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageAsset cannot be subclassed.")

    def __init__(self, _token, image_id, name, description, format, width, height):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_image_asset() to build an ImageAsset.")
        object.__setattr__(self, "_image_id", image_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_format", format)
        object.__setattr__(self, "_width", width)
        object.__setattr__(self, "_height", height)

    def __setattr__(self, key, value):
        raise AttributeError("ImageAsset is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageAsset is immutable.")

    @property
    def image_id(self):
        return self._image_id

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def format(self):
        return self._format

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this asset."""
        return {"image_id": self._image_id, "name": self._name, "description": self._description, "format": self._format,
                "width": self._width, "height": self._height}

    def _key(self):
        return (self._image_id, self._name, self._description, self._format, self._width, self._height)

    def __eq__(self, other):
        if type(other) is not ImageAsset:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageAsset is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageAsset(image_id=%r, name=%r, format=%r, width=%r, height=%r)" % (
            self._image_id, self._name, self._format, self._width, self._height)


class ImageAssetResult:
    """Outcome of `create_image_asset()`: `asset` is set only when `ok`."""

    __slots__ = ("asset", "failures")

    def __init__(self, asset=None, failures=None):
        self.asset = asset
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.asset is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "asset": self.asset.to_dict() if self.asset is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_image_asset(data):
    """Validate `data` (a plain dict with exactly the six ImageAsset fields) and build an immutable `ImageAsset`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns an `ImageAssetResult`."""
    if type(data) is not dict:
        return ImageAssetResult(failures=[_failure(FAILURE_INVALID_INPUT, "Image asset data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Image asset data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected image asset field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing image asset field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field in DIMENSION_FIELDS:
            if type(value) is not int:
                failures.append(_failure(code, "%s must be an int." % field, field))
            elif value <= 0:
                failures.append(_failure(code, "%s must be greater than zero." % field, field))
        elif type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append(_failure(code, "%s must not be empty or blank." % field, field))
    if failures:
        return ImageAssetResult(failures=failures)
    return ImageAssetResult(asset=ImageAsset(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
