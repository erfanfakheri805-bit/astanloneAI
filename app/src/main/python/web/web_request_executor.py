"""
Web Request Executor (Prompt 778, Section 9 - Web / Service Work)
=================================================================
The next small layer after `WebRequestPlan` (Prompt 777). It is a deliberate PLACEHOLDER: it accepts a plan and reports, deterministically, that
web request execution is NOT IMPLEMENTED. It never executes anything.

    execute_web_request_plan(plan) -> WebRequestExecutionResult(ok, status, code, executed, metadata)

BEHAVIOR
1. `plan` must be exactly a `WebRequestPlan` (None, a dict, a look-alike, ... is not). Anything else gives a REJECTED result with code
   `WEB_REQUEST_EXECUTOR_INVALID_PLAN`; nothing is read from the input and `metadata` is None.
2. A valid plan gives a NOT_IMPLEMENTED result with code `WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED`. No request is made.
3. The plan's five values are copied into the result's metadata exactly (the very same `str` / `int` objects), in the fixed order request_id, url,
   method, resource_type, timeout_ms. Nothing is normalized, trimmed, parsed or coerced. The plan object itself is NOT retained.

RESULT
`WebRequestExecutionResult` has exactly these values: `status` ("REJECTED" or "NOT_IMPLEMENTED"), `code`, and the five metadata values. Derived:
`ok` (always False - nothing was executed successfully), `executed` (always False), `metadata` (a FRESH dict of the five values, or None when rejected).
`to_dict()` returns FRESH plain data {"ok", "status", "code", "executed", "metadata"}. The result is immutable (`__slots__`, assignment/deletion raises),
cannot be constructed directly or subclassed, compares and hashes by value (exact type only), returns itself from copy/deepcopy (so the copy is equal)
and refuses pickling (`TypeError`).

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call. It does not parse or resolve the
`url`, does not check `method` or `timeout_ms`, and does not look at a registry. No clock or randomness, no module-level mutable state. Its only import is
the Prompt 777 plan type. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_plan import WebRequestPlan

FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")

STATUS_REJECTED = "REJECTED"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
STATUSES = (STATUS_REJECTED, STATUS_NOT_IMPLEMENTED)

CODE_INVALID_PLAN = "WEB_REQUEST_EXECUTOR_INVALID_PLAN"
CODE_NOT_IMPLEMENTED = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
CODES = (CODE_INVALID_PLAN, CODE_NOT_IMPLEMENTED)

_CREATE_TOKEN = object()


class WebRequestExecutionResult:
    """Immutable outcome of `execute_web_request_plan()`. Obtain it only from that function."""

    __slots__ = ("_status", "_code", "_request_id", "_url", "_method", "_resource_type", "_timeout_ms")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestExecutionResult cannot be subclassed.")

    def __init__(self, _token, status, code, request_id, url, method, resource_type, timeout_ms):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_web_request_plan() to obtain a WebRequestExecutionResult.")
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_url", url)
        object.__setattr__(self, "_method", method)
        object.__setattr__(self, "_resource_type", resource_type)
        object.__setattr__(self, "_timeout_ms", timeout_ms)

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestExecutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestExecutionResult is immutable.")

    @property
    def ok(self):
        return False

    @property
    def executed(self):
        return False

    @property
    def status(self):
        return self._status

    @property
    def code(self):
        return self._code

    @property
    def metadata(self):
        """A FRESH dict of the five plan values, or None when the input was rejected."""
        if self._status == STATUS_REJECTED:
            return None
        return {"request_id": self._request_id, "url": self._url, "method": self._method,
                "resource_type": self._resource_type, "timeout_ms": self._timeout_ms}

    def to_dict(self):
        """Fresh plain data: {"ok", "status", "code", "executed", "metadata"}. Mutating it never affects this result."""
        return {"ok": False, "status": self._status, "code": self._code, "executed": False, "metadata": self.metadata}

    def _key(self):
        return (self._status, self._code, self._request_id, self._url, self._method, self._resource_type, self._timeout_ms)

    def __eq__(self, other):
        if type(other) is not WebRequestExecutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestExecutionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestExecutionResult(status=%r, code=%r)" % (self._status, self._code)


def execute_web_request_plan(plan):
    """Report that executing `plan` (an exact `WebRequestPlan`) is not implemented. Performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `WebRequestExecutionResult`."""
    if type(plan) is not WebRequestPlan:
        return WebRequestExecutionResult(_CREATE_TOKEN, STATUS_REJECTED, CODE_INVALID_PLAN, None, None, None, None, None)
    return WebRequestExecutionResult(_CREATE_TOKEN, STATUS_NOT_IMPLEMENTED, CODE_NOT_IMPLEMENTED,
                                     plan.request_id, plan.url, plan.method, plan.resource_type, plan.timeout_ms)
