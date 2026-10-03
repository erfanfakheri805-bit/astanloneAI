"""
Image Operation Request Registry Validation (Prompt 749, Section 8 - Multimedia)
================================================================================
A small deterministic bridge that answers one question: does an `ImageOperationRequest` (Prompt 748) refer to an image that is registered in an
`ImageAssetRegistry` (Prompt 747)?

    validate_image_operation_request(request, image_registry) -> ImageOperationValidationResult(ok, request, asset, failures)

ORDER
1. `request` must be exactly an `ImageOperationRequest` (a subclass, None, a dict, ... is `INVALID_REQUEST`).
2. `image_registry` must be exactly an `ImageAssetRegistry` (otherwise `INVALID_IMAGE_REGISTRY`).
3. If either top-level input is invalid, NO cross-validation happens: the registry is not asked anything. Both top-level problems are reported
   together (request first), so one call shows everything that is wrong with the inputs.
4. Otherwise `request.image_id` is resolved ONLY through the registry's public `lookup()`. The lookup logic is not duplicated here and no private
   registry state is read.
5. Not registered -> `IMAGE_NOT_FOUND`. Registered -> `ok` and `asset` is the very registered `ImageAsset` object (identity preserved).

FAILURE CODES (stable, prefix `IMAGE_OPERATION_VALIDATION_`): `INVALID_REQUEST`, `INVALID_IMAGE_REGISTRY`, `IMAGE_NOT_FOUND`.

RULES
- Exact types only. Nothing is normalized, trimmed, case-folded, coerced, or looked up under an alternate id.
- `operation`, `target_format`, `width`, `height` and `quality` are NOT examined beyond Prompt 748; whether the requested size suits the real image
  is a job for a future processing layer.
- The request, the registry and the asset are only read, never changed. Never raises for bad inputs.

RESULT
`ImageOperationValidationResult` is immutable, compares and hashes by value (ok, request, asset, failures), builds a FRESH plain dict in
`to_dict()`, cannot be constructed directly or subclassed, returns itself from copy/deepcopy, and refuses pickling. `request` holds the request
only when it was a valid `ImageOperationRequest` (also when the image was not found); `asset` holds the asset only when found. Anything that was
an invalid input is never stored, so the result stays hashable and safe. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts.

WHAT THIS MODULE DOES NOT DO
No image processing, decoding, file paths, filesystem, network, database, AI model or external service, no clock or randomness, no module-level
mutable state. Imports only Prompts 746-748 modules. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .image_asset import ImageAsset
from .image_asset_registry import ImageAssetRegistry
from .image_operation_request import ImageOperationRequest

FAILURE_INVALID_REQUEST = "IMAGE_OPERATION_VALIDATION_INVALID_REQUEST"
FAILURE_INVALID_IMAGE_REGISTRY = "IMAGE_OPERATION_VALIDATION_INVALID_IMAGE_REGISTRY"
FAILURE_IMAGE_NOT_FOUND = "IMAGE_OPERATION_VALIDATION_IMAGE_NOT_FOUND"
FAILURE_CODES = (FAILURE_INVALID_REQUEST, FAILURE_INVALID_IMAGE_REGISTRY, FAILURE_IMAGE_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class ImageOperationValidationResult:
    """Immutable outcome of `validate_image_operation_request()`. Obtain it only from that function."""

    __slots__ = ("_request", "_asset", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationValidationResult cannot be subclassed.")

    def __init__(self, _token, request, asset, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_image_operation_request() to obtain an ImageOperationValidationResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_asset", asset)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def request(self):
        """The validated `ImageOperationRequest` (the same object that was passed in), or None if the request input was invalid."""
        return self._request

    @property
    def asset(self):
        """The exact registered `ImageAsset` object when the image was found, otherwise None."""
        return self._asset

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "request", "asset", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "request": self._request.to_dict() if self._request is not None else None,
                "asset": self._asset.to_dict() if self._asset is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._request, self._asset, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_image_operation_request(request, image_registry):
    """Check that `request` (an exact `ImageOperationRequest`) names an image registered in `image_registry` (an exact `ImageAssetRegistry`).
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns an `ImageOperationValidationResult`."""
    request_ok = type(request) is ImageOperationRequest
    registry_ok = type(image_registry) is ImageAssetRegistry
    failures = []
    if not request_ok:
        failures.append(_failure(FAILURE_INVALID_REQUEST, "request must be exactly an ImageOperationRequest.", "request"))
    if not registry_ok:
        failures.append(_failure(FAILURE_INVALID_IMAGE_REGISTRY, "image_registry must be exactly an ImageAssetRegistry.", "image_registry"))
    if failures:
        return ImageOperationValidationResult(_CREATE_TOKEN, request if request_ok else None, None, failures)
    lookup = image_registry.lookup(request.image_id)
    if lookup.found and type(lookup.asset) is ImageAsset:
        return ImageOperationValidationResult(_CREATE_TOKEN, request, lookup.asset, ())
    return ImageOperationValidationResult(_CREATE_TOKEN, request, None, [_failure(
        FAILURE_IMAGE_NOT_FOUND, "No image asset is registered with image_id %r." % request.image_id, "image_id")])
