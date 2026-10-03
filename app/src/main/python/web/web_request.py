"""
Web Request Contract (Prompt 775, Section 9 - Web / Service Work)
=================================================================
A small, immutable, in-memory description of ONE controlled web request. It only DESCRIBES a request; nothing here ever executes one:

    create_web_request(data) -> WebRequestResult(ok, request, failures)
    WebRequest.to_dict()     -> {"request_id", "url", "method", "resource_type", "timeout_ms"}

`data` is an exact plain `dict` holding exactly the five fields below. Nothing else is accepted.

    request_id     str, not empty
    url            str, not empty (any text; it is NOT parsed, checked or fetched)
    method         str, not empty (any text; no fixed method list, no case folding)
    resource_type  str, not empty (any text; no fixed type list)
    timeout_ms     int, greater than zero (a `bool` or an `int` subclass is rejected; nothing is converted)

RULES
- All five fields must be present (no defaults are invented). The four text fields must be exactly `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run). "Not empty" means `value != ""` - exactly that, nothing more. `timeout_ms` must be
  exactly `int` and positive. Values are NEVER trimmed, lower-cased, normalized, coerced or otherwise changed: what the caller supplied is what
  is stored, and the very same objects are kept (string identity preserved).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_web_request()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the five fields in the order above), using stable `WEB_REQUEST_*` codes from `FAILURE_CODES`. The caller's dict is only read.
- Direct `WebRequest(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call. copy/deepcopy return the same object; pickling is refused (`to_dict()` is the only
  serialization).

WHAT THIS MODULE DOES NOT DO
It executes no request, performs no networking, does not parse, validate or resolve the `url`, does not check `method`, and does not read or
write the filesystem. No database, subprocess, AI model, external service or external dependency, no clock or randomness, no module-level
mutable state. Imports nothing at all and is not wired into `process_input()`, Core, the Planner, the Agent Loop or any existing section.
"""

FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
TEXT_FIELDS = ("request_id", "url", "method", "resource_type")

FAILURE_INVALID_INPUT = "WEB_REQUEST_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "WEB_REQUEST_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "WEB_REQUEST_MISSING_FIELD"
FAILURE_INVALID_REQUEST_ID = "WEB_REQUEST_INVALID_REQUEST_ID"
FAILURE_INVALID_URL = "WEB_REQUEST_INVALID_URL"
FAILURE_INVALID_METHOD = "WEB_REQUEST_INVALID_METHOD"
FAILURE_INVALID_RESOURCE_TYPE = "WEB_REQUEST_INVALID_RESOURCE_TYPE"
FAILURE_INVALID_TIMEOUT_MS = "WEB_REQUEST_INVALID_TIMEOUT_MS"

_INVALID_CODES = (FAILURE_INVALID_REQUEST_ID, FAILURE_INVALID_URL, FAILURE_INVALID_METHOD, FAILURE_INVALID_RESOURCE_TYPE,
                  FAILURE_INVALID_TIMEOUT_MS)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class WebRequest:
    """Immutable description of one controlled web request. Obtain it only from `create_web_request()`."""

    __slots__ = ("_request_id", "_url", "_method", "_resource_type", "_timeout_ms")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequest cannot be subclassed.")

    def __init__(self, _token, request_id, url, method, resource_type, timeout_ms):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_request() to build a WebRequest.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_url", url)
        object.__setattr__(self, "_method", method)
        object.__setattr__(self, "_resource_type", resource_type)
        object.__setattr__(self, "_timeout_ms", timeout_ms)

    def __setattr__(self, key, value):
        raise AttributeError("WebRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequest is immutable.")

    @property
    def request_id(self):
        return self._request_id

    @property
    def url(self):
        return self._url

    @property
    def method(self):
        return self._method

    @property
    def resource_type(self):
        return self._resource_type

    @property
    def timeout_ms(self):
        return self._timeout_ms

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this request."""
        return {"request_id": self._request_id, "url": self._url, "method": self._method,
                "resource_type": self._resource_type, "timeout_ms": self._timeout_ms}

    def _key(self):
        return (self._request_id, self._url, self._method, self._resource_type, self._timeout_ms)

    def __eq__(self, other):
        if type(other) is not WebRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequest(request_id=%r, url=%r, method=%r, resource_type=%r, timeout_ms=%r)" % (
            self._request_id, self._url, self._method, self._resource_type, self._timeout_ms)


class WebRequestResult:
    """Outcome of `create_web_request()`: `request` is set only when `ok`."""

    __slots__ = ("request", "failures")

    def __init__(self, request=None, failures=None):
        self.request = request
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.request is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "request": self.request.to_dict() if self.request is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_web_request(data):
    """Validate `data` (a plain dict with exactly the five WebRequest fields) and build an immutable `WebRequest`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `WebRequestResult`."""
    if type(data) is not dict:
        return WebRequestResult(failures=[_failure(FAILURE_INVALID_INPUT, "Web request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Web request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected web request field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing web request field: %s." % field, field))
            continue
        value = data[field]
        code = _INVALID_CODES[FIELDS.index(field)]
        if field == "timeout_ms":
            if type(value) is not int:
                failures.append(_failure(code, "timeout_ms must be an int.", field))
            elif value <= 0:
                failures.append(_failure(code, "timeout_ms must be greater than zero.", field))
        elif type(value) is not str:
            failures.append(_failure(code, "%s must be a str." % field, field))
        elif value == "":
            failures.append(_failure(code, "%s must not be empty." % field, field))
    if failures:
        return WebRequestResult(failures=failures)
    return WebRequestResult(request=WebRequest(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
