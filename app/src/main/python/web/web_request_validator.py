"""
Web Request Registry Validation (Prompt 776, Section 9 - Web / Service Work)
============================================================================
A small deterministic bridge that answers one question: does a `WebRequest` (Prompt 775) name a resource type that is registered in a
`WebResourceRegistry` (Prompt 774)? It follows the architecture of the image/audio operation validators (Prompts 749 / 762) as a separate,
unrelated type.

    validate_web_request(request, resource_registry) -> WebRequestValidationResult(ok, request, registry, failures)

ORDER
1. `request` must be exactly a `WebRequest` (a subclass, None, a dict, ... is `INVALID_REQUEST`).
2. `resource_registry` must be exactly a `WebResourceRegistry` (otherwise `INVALID_REGISTRY`).
3. If either top-level input is invalid, NO cross-validation happens: the registry is not asked anything. Both top-level problems are reported
   together (request first), so one call shows everything that is wrong with the inputs.
4. Otherwise `request.resource_type` is resolved ONLY through the registry's public `lookup()`: the request's `resource_type` is matched, by exact
   comparison, against the registered `resource_id` values. The lookup logic is not duplicated here and no private registry state is read.
5. Not registered -> `RESOURCE_NOT_FOUND`. Registered -> `ok`.

FAILURE CODES (stable, prefix `WEB_REQUEST_VALIDATION_`): `INVALID_REQUEST`, `INVALID_REGISTRY`, `RESOURCE_NOT_FOUND`.

RULES
- Exact types only. Nothing is normalized, trimmed, case-folded, coerced, or looked up under an alternate id.
- `request_id`, `url`, `method` and `timeout_ms` are NOT examined beyond Prompt 775, and nothing is compared with the registered resource (the
  resource's `url`, `title` and `resource_type` are not checked against the request); that is for a future layer.
- The request and the registry are only read, never changed. Never raises for bad inputs.

RESULT
`WebRequestValidationResult` is immutable, compares and hashes by value (request, registry, failures), builds a FRESH plain dict in `to_dict()`,
cannot be constructed directly or subclassed, returns itself from copy/deepcopy, and refuses pickling. `request` and `registry` hold the very objects
that were passed in, each only when it was a valid input of the exact type (so the registry is also kept when the resource was not found). An
invalid input is never stored, so the result stays hashable and safe. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts.

WHAT THIS MODULE DOES NOT DO
It executes no request, performs no networking, does not parse or resolve the `url`, and does not touch the filesystem, database, subprocesses,
AI models or external services. No clock or randomness, no module-level mutable state. Imports only the Prompt 773-775 web modules. Not wired
into `process_input()`, Core, the Planner, the Agent Loop or any other section.
"""

from .web_request import WebRequest
from .web_resource import WebResource
from .web_resource_registry import WebResourceRegistry

FAILURE_INVALID_REQUEST = "WEB_REQUEST_VALIDATION_INVALID_REQUEST"
FAILURE_INVALID_REGISTRY = "WEB_REQUEST_VALIDATION_INVALID_REGISTRY"
FAILURE_RESOURCE_NOT_FOUND = "WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND"
FAILURE_CODES = (FAILURE_INVALID_REQUEST, FAILURE_INVALID_REGISTRY, FAILURE_RESOURCE_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class WebRequestValidationResult:
    """Immutable outcome of `validate_web_request()`. Obtain it only from that function."""

    __slots__ = ("_request", "_registry", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestValidationResult cannot be subclassed.")

    def __init__(self, _token, request, registry, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_web_request() to obtain a WebRequestValidationResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def request(self):
        """The `WebRequest` that was passed in (same object), or None if the request input was invalid."""
        return self._request

    @property
    def registry(self):
        """The `WebResourceRegistry` that was passed in (same object), or None if the registry input was invalid."""
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
        if type(other) is not WebRequestValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_web_request(request, resource_registry):
    """Check that `request` (an exact `WebRequest`) names a resource type registered in `resource_registry` (an exact `WebResourceRegistry`).
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `WebRequestValidationResult`."""
    request_ok = type(request) is WebRequest
    registry_ok = type(resource_registry) is WebResourceRegistry
    failures = []
    if not request_ok:
        failures.append(_failure(FAILURE_INVALID_REQUEST, "request must be exactly a WebRequest.", "request"))
    if not registry_ok:
        failures.append(_failure(FAILURE_INVALID_REGISTRY, "resource_registry must be exactly a WebResourceRegistry.", "resource_registry"))
    kept_request = request if request_ok else None
    kept_registry = resource_registry if registry_ok else None
    if failures:
        return WebRequestValidationResult(_CREATE_TOKEN, kept_request, kept_registry, failures)
    lookup = resource_registry.lookup(request.resource_type)
    if lookup.found and type(lookup.resource) is WebResource:
        return WebRequestValidationResult(_CREATE_TOKEN, request, resource_registry, ())
    return WebRequestValidationResult(_CREATE_TOKEN, request, resource_registry, [_failure(
        FAILURE_RESOURCE_NOT_FOUND, "No web resource is registered for resource_type %r." % request.resource_type, "resource_type")])
