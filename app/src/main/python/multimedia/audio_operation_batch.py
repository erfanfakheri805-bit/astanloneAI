"""
Audio Operation Batch Pipeline (Prompt 770, Section 8 - Multimedia)
===================================================================
A small deterministic batch wrapper around the single-request pipeline of Prompt 769. It runs the existing public
`process_audio_operation(request, audio_registry)` once per request, in order, and keeps every result. It adds no audio-operation semantics and
no per-request validation of its own: everything about one request (registry lookup, plan, dispatch, output validation) is decided by Prompt 769.

    process_audio_operations(requests, audio_registry) -> AudioOperationBatchResult(ok, results, failures)

INPUT CONTRACT (exact types only; nothing is coerced, normalized or sorted)
- `requests` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected). An empty collection is valid.
- every item must be exactly an `AudioOperationRequest` (Prompt 761).
- `audio_registry` must be exactly an `AudioAssetRegistry` (Prompt 760).
These three type checks are the batch's only own checks; they must be made here because the single-request pipeline is only ever called with
inputs that already passed them.

ORDER AND FAILURE CODES (only these four; prefix AUDIO_OPERATION_BATCH_; each failure is `{"code", "field", "message", "context"}`)
1. `INVALID_COLLECTION` (field "requests")            requests is not an exact list/tuple.
2. `INVALID_REGISTRY`   (field "audio_registry")      audio_registry is not an exact AudioAssetRegistry. Reported together with 1 (collection first),
                                                      exactly like the other multimedia validators report both top-level problems at once.
3. `INVALID_REQUEST`    (field "requests[<index>]")   one failure per item that is not an exact AudioOperationRequest, in input order. Items are only
                                                      examined when the collection is valid. The index is in the field (as in game_definition's
                                                      "bundles[<index>]"), the message names the offending type, and `context` is the EXACT
                                                      offending object (identity preserved, never copied or inspected).
   If ANY of 1-3 is reported: ok=False, results=() and `process_audio_operation()` is NOT called at all (not even for the valid items).
4. `OPERATION_FAILED`   (field "results[<index>]")    only when all inputs are valid: one failure per result whose `ok` is False, in input order. The
                                                      message quotes the pipeline's own codes, e.g. "[AUDIO_OPERATION_PIPELINE_DISPATCH_FAILED]". The
                                                      pipeline codes are never copied, renamed or hidden; the full detail stays in the preserved result.

VALID INPUT
`process_audio_operation()` is called exactly once per request, in input order, and processing NEVER stops at the first failing operation. The
exact returned result objects (identity preserved) are stored, in order, in an immutable tuple `results` (same length as `requests`, also when
some operations failed). `ok=True` only when there are no failures, i.e. every individual result is ok (an empty batch is ok with `results=()`).

FAILURE CONTEXT
Every failure has a `context` key. For INVALID_REQUEST it is the exact invalid item from the caller's collection; for every other code it is None.
The context is available through `failures` only; `to_dict()` stays plain data and leaves it out (the message already names the offending type).
Equality compares contexts by identity (never calls the caller object's `__eq__` or `__hash__`), and the hash ignores them.

RESULT
`AudioOperationBatchResult` is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by
value (exact type only), returns itself from copy/deepcopy and refuses pickling (like the other multimedia results). `results` is a tuple of the
exact `AudioOperationPipelineResult` objects; `failures`, `codes()` and `to_dict()` ({"ok", "results", "failures"}, `results` as a list of each
result's own `to_dict()`) are fresh on every call. The function never raises for bad inputs, only reads the collection and the requests, and is
deterministic.

WHAT THIS MODULE DOES NOT DO
No filesystem, audio decoding or samples, network, database, AI model or external service, no clock or randomness, no concurrency, threading,
retries or scheduling, no automatic operation selection, no module-level mutable state. Imports only the Prompt 760 and 761 types and the
Prompt 769 pipeline function. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .audio_asset_registry import AudioAssetRegistry
from .audio_operation_pipeline import process_audio_operation
from .audio_operation_request import AudioOperationRequest

_PREFIX = "AUDIO_OPERATION_BATCH_"
FAILURE_INVALID_COLLECTION = _PREFIX + "INVALID_COLLECTION"
FAILURE_INVALID_REQUEST = _PREFIX + "INVALID_REQUEST"
FAILURE_INVALID_REGISTRY = _PREFIX + "INVALID_REGISTRY"
FAILURE_OPERATION_FAILED = _PREFIX + "OPERATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_REQUEST, FAILURE_INVALID_REGISTRY, FAILURE_OPERATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, field, message, context=None):
    return (code, field, message, context)


class AudioOperationBatchResult:
    """Immutable outcome of `process_audio_operations()`. Obtain it only from that function."""

    __slots__ = ("_results", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationBatchResult cannot be subclassed.")

    def __init__(self, _token, results, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use process_audio_operations() to obtain an AudioOperationBatchResult.")
        object.__setattr__(self, "_results", tuple(results))
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationBatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationBatchResult is immutable.")

    @property
    def ok(self):
        """True only when there are no failures, i.e. every individual pipeline result is ok (an empty valid batch is ok)."""
        return not self._failures and all(r.ok for r in self._results)

    @property
    def results(self):
        """Tuple of the exact `AudioOperationPipelineResult` objects, in input order (empty when the input was invalid)."""
        return self._results

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m, "context": x} for c, f, m, x in self._failures)

    def codes(self):
        return [c for c, _f, _m, _x in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "results", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "results": [r.to_dict() for r in self._results],
                "failures": [{"code": c, "field": f, "message": m} for c, f, m, _x in self._failures]}

    def _key(self):
        # The failure context is an arbitrary caller object (possibly unhashable, possibly with a hostile __eq__): it is compared by identity only
        # and never hashed or called.
        return (self._results, tuple((c, f, m) for c, f, m, _x in self._failures))

    def __eq__(self, other):
        if type(other) is not AudioOperationBatchResult:
            return NotImplemented
        return (self._key() == other._key() and len(self._failures) == len(other._failures)
                and all(a[3] is b[3] for a, b in zip(self._failures, other._failures)))

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationBatchResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationBatchResult(ok=%r, results=%d, codes=%r)" % (self.ok, len(self._results), self.codes())


def process_audio_operations(requests, audio_registry):
    """Run `process_audio_operation()` once per request, in order, and return an `AudioOperationBatchResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given, never stops at the first failing operation."""
    collection_ok = type(requests) is list or type(requests) is tuple
    failures = []
    if not collection_ok:
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "requests", "requests must be exactly a list or a tuple of AudioOperationRequest objects."))
    if type(audio_registry) is not AudioAssetRegistry:
        failures.append(_failure(FAILURE_INVALID_REGISTRY, "audio_registry", "audio_registry must be exactly an AudioAssetRegistry."))
    if collection_ok:
        for index, item in enumerate(requests):
            if type(item) is not AudioOperationRequest:
                failures.append(_failure(FAILURE_INVALID_REQUEST, "requests[%d]" % index,
                                         "requests[%d] must be exactly an AudioOperationRequest (got %s)." % (index, type(item).__name__), item))
    if failures:
        return AudioOperationBatchResult(_CREATE_TOKEN, (), failures)

    results = tuple(process_audio_operation(request, audio_registry) for request in requests)
    failed = [(i, r) for i, r in enumerate(results) if not r.ok]
    return AudioOperationBatchResult(_CREATE_TOKEN, results, [
        _failure(FAILURE_OPERATION_FAILED, "results[%d]" % i, "Operation %d failed [%s]." % (i, ", ".join(r.codes()) or "no pipeline code"))
        for i, r in failed])
