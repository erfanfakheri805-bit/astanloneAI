"""
Web Resource Contract (Prompt 773, Section 9 - Web / Service Work)
==================================================================
A small, immutable, in-memory record of the BASIC METADATA of one web resource:

    create_web_resource(data) -> WebResourceResult(ok, resource, failures)
    WebResource.to_dict()     -> {"resource_id", "url", "title", "resource_type"}

`data` is an exact plain `dict` holding exactly the four fields below. Nothing else is accepted.

    resource_id    str, not empty
    url            str, not empty (any text; it is NOT parsed, checked or fetched)
    title          str, may be empty
    resource_type  str, not empty (any text; no fixed type list)

RULES
- All four fields must be present (no defaults are invented) and each must be exactly `str` (a `str` subclass or any other type is rejected, so
  no caller-supplied method is ever run). "Not empty" means `value != ""` - exactly that, nothing more. Values are NEVER trimmed, lower-cased,
  normalized, coerced or otherwise changed: what the caller supplied is what is stored, and the very same `str` objects are kept (identity
  preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_web_resource()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the four fields in the order above), using stable `WEB_RESOURCE_*` codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `WebResource(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It performs no networking and no HTTP request, does not parse, validate or resolve the `url`, and does not read or write the filesystem. No
database, subprocess, AI model, external service or external dependency, no clock or randomness, no module-level mutable state. Imports nothing
at all and is not wired into `process_input()`, Core, the Planner, the Agent Loop or any existing section.
"""

FIELDS = ("resource_id", "url", "title", "resource_type")
REQUIRED_NON_EMPTY = ("resource_id", "url", "resource_type")

FAILURE_INVALID_INPUT = "WEB_RESOURCE_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "WEB_RESOURCE_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "WEB_RESOURCE_MISSING_FIELD"
FAILURE_INVALID_RESOURCE_ID = "WEB_RESOURCE_INVALID_RESOURCE_ID"
FAILURE_INVALID_URL = "WEB_RESOURCE_INVALID_URL"
FAILURE_INVALID_TITLE = "WEB_RESOURCE_INVALID_TITLE"
FAILURE_INVALID_RESOURCE_TYPE = "WEB_RESOURCE_INVALID_RESOURCE_TYPE"

_INVALID_CODES = (FAILURE_INVALID_RESOURCE_ID, FAILURE_INVALID_URL, FAILURE_INVALID_TITLE,
                  FAILURE_INVALID_RESOURCE_TYPE)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class WebResource:
    """Immutable data record of one web resource's basic metadata. Obtain it only from `create_web_resource()`."""

    __slots__ = ("_resource_id", "_url", "_title", "_resource_type")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebResource cannot be subclassed.")

    def __init__(self, _token, resource_id, url, title, resource_type):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_resource() to build a WebResource.")
        object.__setattr__(self, "_resource_id", resource_id)
        object.__setattr__(self, "_url", url)
        object.__setattr__(self, "_title", title)
        object.__setattr__(self, "_resource_type", resource_type)

    def __setattr__(self, key, value):
        raise AttributeError("WebResource is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebResource is immutable.")

    @property
    def resource_id(self):
        return self._resource_id

    @property
    def url(self):
        return self._url

    @property
    def title(self):
        return self._title

    @property
    def resource_type(self):
        return self._resource_type

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this resource."""
        return {"resource_id": self._resource_id, "url": self._url, "title": self._title,
                "resource_type": self._resource_type}

    def _key(self):
        return (self._resource_id, self._url, self._title, self._resource_type)

    def __eq__(self, other):
        if type(other) is not WebResource:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebResource is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebResource(resource_id=%r, url=%r, title=%r, resource_type=%r)" % (
            self._resource_id, self._url, self._title, self._resource_type)


class WebResourceResult:
    """Outcome of `create_web_resource()`: `resource` is set only when `ok`."""

    __slots__ = ("resource", "failures")

    def __init__(self, resource=None, failures=None):
        self.resource = resource
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.resource is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "resource": self.resource.to_dict() if self.resource is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_web_resource(data):
    """Validate `data` (a plain dict with exactly the four WebResource fields) and build an immutable `WebResource`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `WebResourceResult`."""
    if type(data) is not dict:
        return WebResourceResult(failures=[_failure(FAILURE_INVALID_INPUT, "Web resource data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Web resource data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected web resource field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing web resource field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif field in REQUIRED_NON_EMPTY and len(value) == 0:
            failures.append(_failure(code, "%s must not be empty." % field, field))
    if failures:
        return WebResourceResult(failures=failures)
    return WebResourceResult(resource=WebResource(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
