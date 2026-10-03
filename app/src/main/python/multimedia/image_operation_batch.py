"""
Image Operation Batch Pipeline (Prompt 757, Section 8 - Multimedia)
===================================================================
A small deterministic batch wrapper around the single-request pipeline of Prompt 756. It runs the existing public
`process_image_operation(request, image_registry)` once per request, in order, and keeps every result. It adds no image-operation semantics and
no per-request validation of its own: everything about one request (registry lookup, plan, dispatch, output validation) is decided by Prompt 756.

    process_image_operations(requests, image_registry) -> ImageOperationBatchResult(ok, results, failures)

INPUT CONTRACT (exact types only; nothing is coerced, normalized or sorted)
- `requests` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected). An empty collection is valid.
- every item must be exactly an `ImageOperationRequest` (Prompt 748).
- `image_registry` must be exactly an `ImageAssetRegistry` (Prompt 747).
These three type checks are the batch's only own checks; they must be made here because the single-request pipeline is only ever called with
inputs that already passed them.

ORDER AND FAILURE CODES (only these four; prefix IMAGE_OPERATION_BATCH_; each failure is `{"code", "field", "message"}`)
1. `INVALID_COLLECTION` (field "requests")            requests is not an exact list/tuple.
2. `INVALID_REGISTRY`   (field "image_registry")      image_registry is not an exact ImageAssetRegistry. Reported together with 1 (collection first),
                                                      exactly like the other multimedia validators report both top-level problems at once.
3. `INVALID_REQUEST`    (field "requests[<index>]")   one failure per item that is not an exact ImageOperationRequest, in input order. Items are only
                                                      examined when the collection is valid. The index is in the field (as in game_definition's
                                                      "bundles[<index>]"), and the message names the offending type.
   If ANY of 1-3 is reported: ok=False, results=() and `process_image_operation()` is NOT called at all (not even for the valid items).
4. `OPERATION_FAILED`   (field "results[<index>]")    only when all inputs are valid: one failure per result whose `ok` is False, in input order. The
                                                      message quotes the pipeline's own codes, e.g. "[IMAGE_OPERATION_PIPELINE_DISPATCH_FAILED]". The
                                                      pipeline codes are never copied, renamed or hidden; the full detail stays in the preserved result.

VALID INPUT
`process_image_operation()` is called exactly once per request, in input order, and processing NEVER stops at the first failing operation. The
exact returned result objects (identity preserved) are stored, in order, in an immutable tuple `results` (same length as `requests`, also when
some operations failed). `ok=True` only when there are no failures, i.e. every individual result is ok (an empty batch is ok with `results=()`).

RESULT
`ImageOperationBatchResult` is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by
value (exact type only), returns itself from copy/deepcopy and refuses pickling (like the other multimedia results). `results` is a tuple of the
exact `ImageOperationPipelineResult` objects; `failures`, `codes()` and `to_dict()` ({"ok", "results", "failures"}, `results` as a list of each
result's own `to_dict()`) are fresh on every call. The function never raises for bad inputs, only reads the collection and the requests, and is
deterministic.

WHAT THIS MODULE DOES NOT DO
No filesystem, image decoding or pixels, network, database, AI model or external service, no clock or randomness, no concurrency, threading,
retries or scheduling, no automatic operation selection, no module-level mutable state. Imports only the Prompt 747 and 748 types and the
Prompt 756 pipeline function. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .image_asset_registry import ImageAssetRegistry
from .image_operation_pipeline import process_image_operation
from .image_operation_request import ImageOperationRequest

_PREFIX = "IMAGE_OPERATION_BATCH_"
FAILURE_INVALID_COLLECTION = _PREFIX + "INVALID_COLLECTION"
FAILURE_INVALID_REQUEST = _PREFIX + "INVALID_REQUEST"
FAILURE_INVALID_REGISTRY = _PREFIX + "INVALID_REGISTRY"
FAILURE_OPERATION_FAILED = _PREFIX + "OPERATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_REQUEST, FAILURE_INVALID_REGISTRY, FAILURE_OPERATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class ImageOperationBatchResult:
    """Immutable outcome of `process_image_operations()`. Obtain it only from that function."""

    __slots__ = ("_results", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationBatchResult cannot be subclassed.")

    def __init__(self, _token, results, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use process_image_operations() to obtain an ImageOperationBatchResult.")
        object.__setattr__(self, "_results", tuple(results))
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationBatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationBatchResult is immutable.")

    @property
    def ok(self):
        """True only when there are no failures, i.e. every individual pipeline result is ok (an empty valid batch is ok)."""
        return not self._failures and all(r.ok for r in self._results)

    @property
    def results(self):
        """Tuple of the exact `ImageOperationPipelineResult` objects, in input order (empty when the input was invalid)."""
        return self._results

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "results", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "results": [r.to_dict() for r in self._results],
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._results, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationBatchResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationBatchResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationBatchResult(ok=%r, results=%d, codes=%r)" % (self.ok, len(self._results), self.codes())


def process_image_operations(requests, image_registry):
    """Run `process_image_operation()` once per request, in order, and return an `ImageOperationBatchResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given, never stops at the first failing operation."""
    collection_ok = type(requests) is list or type(requests) is tuple
    failures = []
    if not collection_ok:
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "requests", "requests must be exactly a list or a tuple of ImageOperationRequest objects."))
    if type(image_registry) is not ImageAssetRegistry:
        failures.append(_failure(FAILURE_INVALID_REGISTRY, "image_registry", "image_registry must be exactly an ImageAssetRegistry."))
    if collection_ok:
        for index, item in enumerate(requests):
            if type(item) is not ImageOperationRequest:
                failures.append(_failure(FAILURE_INVALID_REQUEST, "requests[%d]" % index,
                                         "requests[%d] must be exactly an ImageOperationRequest (got %s)." % (index, type(item).__name__)))
    if failures:
        return ImageOperationBatchResult(_CREATE_TOKEN, (), failures)

    results = tuple(process_image_operation(request, image_registry) for request in requests)
    failed = [(i, r) for i, r in enumerate(results) if not r.ok]
    return ImageOperationBatchResult(_CREATE_TOKEN, results, [
        _failure(FAILURE_OPERATION_FAILED, "results[%d]" % i, "Operation %d failed [%s]." % (i, ", ".join(r.codes()) or "no pipeline code"))
        for i, r in failed])
