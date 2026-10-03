"""
Web Request Plan (Prompt 777, Section 9 - Web / Service Work)
=============================================================
A small deterministic planner that turns a VALIDATED web request into an immutable EXECUTION DESCRIPTION. It only describes; it executes nothing,
performs no networking and touches no file. It mirrors the architecture of `AudioOperationPlan` / `ImageOperationPlan` (Prompts 763 / 750) as a
separate, unrelated type.

    create_web_request_plan(validation_result) -> WebRequestPlanResult(ok, plan, failures)
    WebRequestPlan.to_dict() -> {"request_id", "url", "method", "resource_type", "timeout_ms"}

INPUT AND ORDER
1. `validation_result` must be exactly a `WebRequestValidationResult` (Prompt 776). Anything else (None, a dict, a subclass-free look-alike) gives
   `WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT`; nothing is read from it.
2. It must have `ok=True`. A failed validation gives `WEB_REQUEST_PLAN_VALIDATION_FAILED`; no plan is created.
3. On success the five request values are copied exactly from `validation_result.request`: the very same `str` and `int` objects (identity
   preserved), in the fixed order request_id, url, method, resource_type, timeout_ms. Nothing is normalized, trimmed, case-folded, coerced,
   reordered, parsed or reinterpreted.

THE PLAN HOLDS ONLY THE FIVE VALUES
It does not keep the `WebRequest`, the `WebResourceRegistry` or the validation result, so it carries no link back to any of them. `url`, `method`
and `resource_type` stay free text; nothing about them is interpreted or checked here.

IMMUTABLE AND DETERMINISTIC
`WebRequestPlan` and `WebRequestPlanResult` use `__slots__`, refuse assignment/deletion, direct construction and subclassing (`TypeError`),
compare and hash by value (exact type only), return themselves from copy/deepcopy and refuse pickling. `to_dict()` returns FRESH plain data on
every call. The factory never raises for bad inputs and only reads what it is given.

WHAT THIS MODULE DOES NOT DO
It executes no request, performs no networking, does not parse or resolve the `url`, and does no filesystem access, persistence, subprocess,
database, AI model or external service work. No clock or randomness, no module-level mutable state. Its only import is the Prompt 776 result
type. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_validator import WebRequestValidationResult

FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")

FAILURE_INVALID_VALIDATION_RESULT = "WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT"
FAILURE_VALIDATION_FAILED = "WEB_REQUEST_PLAN_VALIDATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_VALIDATION_RESULT, FAILURE_VALIDATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, message):
    return (code, "validation_result", message)


class WebRequestPlan:
    """Immutable execution description of one web request. Obtain it only from `create_web_request_plan()`."""

    __slots__ = ("_request_id", "_url", "_method", "_resource_type", "_timeout_ms")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestPlan cannot be subclassed.")

    def __init__(self, _token, request_id, url, method, resource_type, timeout_ms):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_request_plan() to build a WebRequestPlan.")
        object.__setattr__(self, "_request_id", request_id)
        object.__setattr__(self, "_url", url)
        object.__setattr__(self, "_method", method)
        object.__setattr__(self, "_resource_type", resource_type)
        object.__setattr__(self, "_timeout_ms", timeout_ms)

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestPlan is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestPlan is immutable.")

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
        """A fresh plain dict (fixed field order). Mutating it never affects this plan."""
        return {"request_id": self._request_id, "url": self._url, "method": self._method,
                "resource_type": self._resource_type, "timeout_ms": self._timeout_ms}

    def _key(self):
        return (self._request_id, self._url, self._method, self._resource_type, self._timeout_ms)

    def __eq__(self, other):
        if type(other) is not WebRequestPlan:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestPlan is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestPlan(request_id=%r, url=%r, method=%r, resource_type=%r, timeout_ms=%r)" % self._key()


class WebRequestPlanResult:
    """Immutable outcome of `create_web_request_plan()`: `plan` is set only when `ok`."""

    __slots__ = ("_plan", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestPlanResult cannot be subclassed.")

    def __init__(self, _token, plan, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_request_plan() to obtain a WebRequestPlanResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestPlanResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestPlanResult is immutable.")

    @property
    def ok(self):
        return self._plan is not None and not self._failures

    @property
    def plan(self):
        return self._plan

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "plan": self._plan.to_dict() if self._plan is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._failures)

    def __eq__(self, other):
        if type(other) is not WebRequestPlanResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestPlanResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestPlanResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def create_web_request_plan(validation_result):
    """Build an immutable `WebRequestPlan` from an exact, successful `WebRequestValidationResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `WebRequestPlanResult`."""
    if type(validation_result) is not WebRequestValidationResult:
        return WebRequestPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_VALIDATION_RESULT, "validation_result must be exactly a WebRequestValidationResult.")])
    if not validation_result.ok:
        return WebRequestPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_VALIDATION_FAILED, "The web request did not pass validation (codes: %s)." % ", ".join(validation_result.codes()))])
    request = validation_result.request
    plan = WebRequestPlan(_CREATE_TOKEN, request.request_id, request.url, request.method, request.resource_type, request.timeout_ms)
    return WebRequestPlanResult(_CREATE_TOKEN, plan, ())
