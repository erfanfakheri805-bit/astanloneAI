"""
Web Resource Registry (Prompt 774, Section 9 - Web / Service Work)
==================================================================
A small, immutable, in-memory, ordered collection of `WebResource` objects with lookup by exact `resource_id`:

    create_web_resource_registry(resources)  -> WebResourceRegistryResult(ok, registry, failures)
    WebResourceRegistry.lookup(resource_id)  -> WebResourceLookupResult(found, resource, failures)
    WebResourceRegistry.to_dict()            -> {"resources": [WebResource.to_dict(), ...]}

INPUT RULES
- `resources` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and an
  unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly a `WebResource` (Prompt 773). `resource_id` values must be unique by exact comparison (no trimming, no case
  folding). Input order is preserved.
- `create_web_resource_registry()` never raises for bad input: it reports every problem at once, in input order, using stable codes from
  `FAILURE_CODES`. A bad item is reported once and never also counted as a duplicate. The caller's collection and the resources are only read.
- Direct `WebResourceRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(resource_id)` never raises and returns a `WebResourceLookupResult`:
- an exact `str` that matches a registered `resource_id` exactly: `found=True`, `resource` is the very registered object, `failures=[]`;
- an exact `str` with no exact match (including a differently-cased or padded id): `found=False`, `resource=None`, code `RESOURCE_NOT_FOUND`;
- anything that is not exactly a `str` (None, bytes, a `str` subclass, an int, ...): `found=False`, `resource=None`, code `INVALID_RESOURCE_ID`.
No trimming, case folding, normalization or coercion, and no search by `url`, `title` or `resource_type`. A `str` subclass is never compared,
so none of its methods are run.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) resources; `resources` and `resource_ids` return tuples. `__slots__`, assignment /
deletion raises, not subclassable. Equal resources in the same order mean equal registries and equal hashes (a different order is a different
registry); `to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
No networking and no HTTP request, no url parsing or resolution, no filesystem, persistence, database, AI model or external service, no clock or
randomness, no module-level mutable state, no global registry. Its only import is the Prompt 773 `WebResource` module. It is not wired into
`process_input()`, Core, the Planner or the Agent Loop and has no link to any other section.
"""

from .web_resource import WebResource

FAILURE_INVALID_COLLECTION = "WEB_RESOURCE_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_RESOURCE = "WEB_RESOURCE_REGISTRY_INVALID_RESOURCE"
FAILURE_DUPLICATE_RESOURCE_ID = "WEB_RESOURCE_REGISTRY_DUPLICATE_RESOURCE_ID"
FAILURE_RESOURCE_NOT_FOUND = "WEB_RESOURCE_REGISTRY_RESOURCE_NOT_FOUND"      # lookup only; never produced by the factory
FAILURE_INVALID_RESOURCE_ID = "WEB_RESOURCE_REGISTRY_INVALID_RESOURCE_ID"    # lookup only; never produced by the factory

FACTORY_FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_RESOURCE, FAILURE_DUPLICATE_RESOURCE_ID)
LOOKUP_FAILURE_CODES = (FAILURE_RESOURCE_NOT_FOUND, FAILURE_INVALID_RESOURCE_ID)
FAILURE_CODES = FACTORY_FAILURE_CODES + LOOKUP_FAILURE_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class WebResourceLookupResult:
    """Outcome of `WebResourceRegistry.lookup()`: `resource` is set only when `found`; otherwise `failures` holds exactly one failure."""

    __slots__ = ("found", "resource", "failures")

    def __init__(self, found=False, resource=None, failures=None):
        self.found = found
        self.resource = resource
        self.failures = [] if failures is None else failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"found": self.found, "resource": self.resource.to_dict() if self.resource is not None else None,
                "failures": [dict(f) for f in self.failures]}


class WebResourceRegistry:
    """Immutable, ordered collection of `WebResource` objects with unique ids. Obtain it only from `create_web_resource_registry()`."""

    __slots__ = ("_resources",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebResourceRegistry cannot be subclassed.")

    def __init__(self, _token, resources):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_resource_registry() to build a WebResourceRegistry.")
        object.__setattr__(self, "_resources", tuple(resources))

    def __setattr__(self, key, value):
        raise AttributeError("WebResourceRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebResourceRegistry is immutable.")

    @property
    def resources(self):
        """Tuple of the registered `WebResource` objects, in registration order."""
        return self._resources

    @property
    def resource_ids(self):
        """Tuple of the registered resource ids, in registration order."""
        return tuple(r.resource_id for r in self._resources)

    def lookup(self, resource_id):
        """Find a resource by exact `resource_id`. Never raises; returns a `WebResourceLookupResult`."""
        if type(resource_id) is not str:
            return WebResourceLookupResult(False, None, [_failure(FAILURE_INVALID_RESOURCE_ID, "resource_id must be a str.", "resource_id")])
        for resource in self._resources:
            if resource.resource_id == resource_id:
                return WebResourceLookupResult(True, resource)
        return WebResourceLookupResult(False, None, [_failure(
            FAILURE_RESOURCE_NOT_FOUND, "No web resource is registered with resource_id %r." % resource_id, "resource_id")])

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"resources": [r.to_dict() for r in self._resources]}

    def __eq__(self, other):
        if type(other) is not WebResourceRegistry:
            return NotImplemented
        return self._resources == other._resources

    def __hash__(self):
        return hash(self._resources)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebResourceRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebResourceRegistry(resource_ids=%r)" % (self.resource_ids,)


class WebResourceRegistryResult:
    """Outcome of `create_web_resource_registry()`: `registry` is set only when `ok`."""

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


def create_web_resource_registry(resources):
    """Validate `resources` (a list or tuple of `WebResource`, unique resource ids) and build an immutable `WebResourceRegistry`.
    Deterministic, never raises for bad input, changes nothing it is given. Returns a `WebResourceRegistryResult`."""
    if type(resources) not in (list, tuple):
        return WebResourceRegistryResult(failures=[_failure(
            FAILURE_INVALID_COLLECTION, "resources must be a list or a tuple of WebResource objects.", "resources")])
    failures = []
    valid = []
    seen = set()
    for index, item in enumerate(resources):
        if type(item) is not WebResource:
            failures.append(_failure(FAILURE_INVALID_RESOURCE, "resources[%d] must be a WebResource." % index, "resources"))
        elif item.resource_id in seen:
            failures.append(_failure(FAILURE_DUPLICATE_RESOURCE_ID,
                                     "resources[%d] duplicates an earlier resource_id: %r." % (index, item.resource_id), "resources"))
        else:
            seen.add(item.resource_id)
            valid.append(item)
    if failures:
        return WebResourceRegistryResult(failures=failures)
    return WebResourceRegistryResult(registry=WebResourceRegistry(_CREATE_TOKEN, valid))
