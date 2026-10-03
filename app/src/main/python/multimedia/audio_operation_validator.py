"""
Audio Operation Request Registry Validation (Prompt 762, Section 8 - Multimedia)
================================================================================
A small deterministic bridge that answers one question: does an `AudioOperationRequest` (Prompt 761) refer to an audio asset that is registered
in an `AudioAssetRegistry` (Prompt 760)? It mirrors the architecture of the image operation validator (Prompt 749) as a separate, unrelated type.

    validate_audio_operation_request(request, audio_registry) -> AudioOperationValidationResult(ok, request, registry, failures)

ORDER
1. `request` must be exactly an `AudioOperationRequest` (a subclass, None, a dict, ... is `INVALID_REQUEST`).
2. `audio_registry` must be exactly an `AudioAssetRegistry` (otherwise `INVALID_AUDIO_REGISTRY`).
3. If either top-level input is invalid, NO cross-validation happens: the registry is not asked anything. Both top-level problems are reported
   together (request first), so one call shows everything that is wrong with the inputs.
4. Otherwise `request.audio_id` is resolved ONLY through the registry's public `lookup()`. The lookup logic is not duplicated here and no private
   registry state is read.
5. Not registered -> `AUDIO_NOT_FOUND`. Registered -> `ok`.

FAILURE CODES (stable, prefix `AUDIO_OPERATION_VALIDATION_`): `INVALID_REQUEST`, `INVALID_AUDIO_REGISTRY`, `AUDIO_NOT_FOUND`.

RULES
- Exact types only. Nothing is normalized, trimmed, case-folded, coerced, or looked up under an alternate id.
- `operation`, `target_format`, `duration_ms`, `sample_rate` and `quality` are NOT examined beyond Prompt 761, and nothing is compared with the
  registered asset (no format, duration, sample-rate or quality checks); that is for a future layer.
- The request and the registry are only read, never changed. Never raises for bad inputs.

RESULT
`AudioOperationValidationResult` is immutable, compares and hashes by value (request, registry, failures), builds a FRESH plain dict in `to_dict()`,
cannot be constructed directly or subclassed, returns itself from copy/deepcopy, and refuses pickling. `request` and `registry` hold the very objects
that were passed in, each only when it was a valid input of the exact type (so the registry is also kept when the audio id was not found). An
invalid input is never stored, so the result stays hashable and safe. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts.

WHAT THIS MODULE DOES NOT DO
No audio decoding, encoding or processing, no file paths, filesystem, network, database, AI model or external service, no clock or randomness, no
module-level mutable state. Imports only Prompts 759-761 modules. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .audio_asset import AudioAsset
from .audio_asset_registry import AudioAssetRegistry
from .audio_operation_request import AudioOperationRequest

FAILURE_INVALID_REQUEST = "AUDIO_OPERATION_VALIDATION_INVALID_REQUEST"
FAILURE_INVALID_AUDIO_REGISTRY = "AUDIO_OPERATION_VALIDATION_INVALID_AUDIO_REGISTRY"
FAILURE_AUDIO_NOT_FOUND = "AUDIO_OPERATION_VALIDATION_AUDIO_NOT_FOUND"
FAILURE_CODES = (FAILURE_INVALID_REQUEST, FAILURE_INVALID_AUDIO_REGISTRY, FAILURE_AUDIO_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class AudioOperationValidationResult:
    """Immutable outcome of `validate_audio_operation_request()`. Obtain it only from that function."""

    __slots__ = ("_request", "_registry", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationValidationResult cannot be subclassed.")

    def __init__(self, _token, request, registry, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_audio_operation_request() to obtain an AudioOperationValidationResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def request(self):
        """The `AudioOperationRequest` that was passed in (same object), or None if the request input was invalid."""
        return self._request

    @property
    def registry(self):
        """The `AudioAssetRegistry` that was passed in (same object), or None if the registry input was invalid."""
        return self._registry

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "request", "registry", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "request": self._request.to_dict() if self._request is not None else None,
                "registry": self._registry.to_dict() if self._registry is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._request, self._registry, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioOperationValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_audio_operation_request(request, audio_registry):
    """Check that `request` (an exact `AudioOperationRequest`) names an audio asset registered in `audio_registry` (an exact `AudioAssetRegistry`).
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns an `AudioOperationValidationResult`."""
    request_ok = type(request) is AudioOperationRequest
    registry_ok = type(audio_registry) is AudioAssetRegistry
    failures = []
    if not request_ok:
        failures.append(_failure(FAILURE_INVALID_REQUEST, "request must be exactly an AudioOperationRequest.", "request"))
    if not registry_ok:
        failures.append(_failure(FAILURE_INVALID_AUDIO_REGISTRY, "audio_registry must be exactly an AudioAssetRegistry.", "audio_registry"))
    kept_request = request if request_ok else None
    kept_registry = audio_registry if registry_ok else None
    if failures:
        return AudioOperationValidationResult(_CREATE_TOKEN, kept_request, kept_registry, failures)
    lookup = audio_registry.lookup(request.audio_id)
    if lookup.found and type(lookup.asset) is AudioAsset:
        return AudioOperationValidationResult(_CREATE_TOKEN, request, audio_registry, ())
    return AudioOperationValidationResult(_CREATE_TOKEN, request, audio_registry, [_failure(
        FAILURE_AUDIO_NOT_FOUND, "No audio asset is registered with audio_id %r." % request.audio_id, "audio_id")])
