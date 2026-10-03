"""
Caller-side Tool Step Intent Adapter (Prompt 719-A, Section 6)
================================================================
A small, PURE, data-only adapter that validates ONE explicit Section 6 tool-step intent and builds its `ToolRequest`:

    build_tool_step_intent(intent) -> ToolStepIntentResult
        (ok, plan_id, step_id, request, max_attempts, required_capabilities, capability_mapping, failures)

INPUT CONTRACT (exactly these keys; nothing is inferred, defaulted, renamed or repaired)
    {
        "plan_id": str,                       # exact str, not blank
        "step_id": str,                       # exact str, not blank
        "tool_request": {                     # exactly these five keys, ALL required
            "name": str,
            "tool_input": JSON-safe value,    # plain JSON data of exact types (see below)
            "granted_permissions": list/tuple of str,
            "granted_capabilities": list/tuple of str,
            "confirmed": bool,                # a real bool
        },
        "max_attempts": int,                  # a real int (not bool), greater than 0
        "required_capabilities": list/tuple of str,   # OPTIONAL key; if present it must be valid (None is not "absent")
        "capability_mapping": list/tuple,             # OPTIONAL key; if present it must be plain data (see below)
    }
  - Any missing required key, any extra key (top level or inside `tool_request`), any alternate key name, and any wrong type is
    rejected. A set/frozenset is NOT accepted for grants here (the contract says list/tuple), `None` is never a default.
  - "Exact" types means `type(x) is T`: subclasses (OrderedDict, str/int subclasses, ...) are rejected, never coerced.
  - JSON-safe = None, bool, int, finite float, str, list, dict with exact-str keys (tuples are NOT JSON data). Depth is limited to
    MAX_INTENT_DEPTH and size to MAX_INTENT_NODES, so cycles and pathological inputs are rejected instead of recursing. Rejected
    values are never `repr()`'d, hashed or compared, and none of their methods is called.
  - `capability_mapping` is only checked to be plain structured data (list/tuple, dicts with str keys, JSON scalars). Its ENTRIES are
    not interpreted: entry rules, duplicates, conflicts and translation belong to the Prompt 710 capability-mapping module.
    `required_capabilities` items are only checked to be `str`; emptiness/whitespace/mapping rules belong to Prompt 710 too. The
    "both or neither" pairing of the two optional fields is enforced by Prompt 711 at use time, not here.

TOOLREQUEST BOUNDARY
  After the WHOLE structure is valid, the existing `create_tool_request(name, tool_input, granted_permissions, granted_capabilities,
  confirmed)` (Prompt 703) is called exactly once with ONLY the five explicit caller values (fresh copies). Its verdict is propagated
  unchanged: its failures appear verbatim in `failures` (same `code` and `message`, plus `field="tool_request"`). `ToolRequest` and
  `create_tool_request` are not modified. If the structure is invalid, `create_tool_request` is not called at all (no partial result).

FAILURE CODES (stable; all problems at once, in a fixed field order; strings below are the complete vocabulary of this module)
    INTENT_NOT_A_DICT, INTENT_MISSING_FIELD, INTENT_UNEXPECTED_FIELD, INTENT_INVALID_FIELD_NAME,
    INTENT_INVALID_PLAN_ID, INTENT_INVALID_STEP_ID,
    INTENT_INVALID_TOOL_REQUEST, INTENT_TOOL_REQUEST_MISSING_FIELD, INTENT_TOOL_REQUEST_UNEXPECTED_FIELD,
    INTENT_TOOL_REQUEST_INVALID_FIELD_NAME, INTENT_INVALID_TOOL_NAME, INTENT_INVALID_TOOL_INPUT,
    INTENT_INVALID_GRANTED_PERMISSIONS, INTENT_INVALID_GRANTED_CAPABILITIES, INTENT_INVALID_CONFIRMED,
    INTENT_INVALID_MAX_ATTEMPTS, INTENT_INVALID_REQUIRED_CAPABILITIES, INTENT_INVALID_CAPABILITY_MAPPING
  plus, verbatim, the `INVALID_TOOL_REQUEST_*` codes of `create_tool_request` when it rejects well-formed values (for example a tool
  name outside `^[a-z][a-z0-9_]{0,63}$`, an unsupported permission, or a `tool_input` that is JSON-safe but not a dict).

RESULT
  `ToolStepIntentResult` is immutable and data-only: read-only slots, no `__dict__`, not subclassable, obtainable only from
  `build_tool_step_intent()`, copy/deepcopy return the same object, pickling is refused, `==` compares data, unhashable.
  On failure `ok` is False, `failures` is non-empty and every other field is None. On success `failures` is empty and
  `request` is the immutable `ToolRequest`; `required_capabilities` / `capability_mapping` are None when the caller omitted them.
  Every read of a mutable value (`failures`, `required_capabilities` list, `capability_mapping`) returns a FRESH copy, and the
  caller's intent is never mutated or retained: later edits of the caller's data cannot reach the result and vice versa.

WHAT THIS MODULE DOES NOT DO
  It does not execute anything, resolve routes, read or inspect a Plan/PlanStep, touch AgentLoop/`process_input`/Core, look up or
  call a registry or handler, map capabilities, retry, authorize, grant, infer or default any value, mutate project state, or keep
  module-level state. Whether the named plan/step exists, whether the tool exists, and whether the grants suffice stay with the
  existing Section 4/5/6 modules. It is not wired into any caller yet.

Imports only `tools.tool_request` (the existing Prompt 703 factory) and stdlib `math`.
"""

import math

from tools.tool_request import create_tool_request

MAX_INTENT_DEPTH = 32
MAX_INTENT_NODES = 100000

INTENT_FIELDS = ("plan_id", "step_id", "tool_request", "max_attempts", "required_capabilities", "capability_mapping")
INTENT_REQUIRED_FIELDS = ("plan_id", "step_id", "tool_request", "max_attempts")
INTENT_OPTIONAL_FIELDS = ("required_capabilities", "capability_mapping")
TOOL_REQUEST_FIELDS = ("name", "tool_input", "granted_permissions", "granted_capabilities", "confirmed")

INTENT_NOT_A_DICT = "INTENT_NOT_A_DICT"
INTENT_MISSING_FIELD = "INTENT_MISSING_FIELD"
INTENT_UNEXPECTED_FIELD = "INTENT_UNEXPECTED_FIELD"
INTENT_INVALID_FIELD_NAME = "INTENT_INVALID_FIELD_NAME"
INTENT_INVALID_PLAN_ID = "INTENT_INVALID_PLAN_ID"
INTENT_INVALID_STEP_ID = "INTENT_INVALID_STEP_ID"
INTENT_INVALID_TOOL_REQUEST = "INTENT_INVALID_TOOL_REQUEST"
INTENT_TOOL_REQUEST_MISSING_FIELD = "INTENT_TOOL_REQUEST_MISSING_FIELD"
INTENT_TOOL_REQUEST_UNEXPECTED_FIELD = "INTENT_TOOL_REQUEST_UNEXPECTED_FIELD"
INTENT_TOOL_REQUEST_INVALID_FIELD_NAME = "INTENT_TOOL_REQUEST_INVALID_FIELD_NAME"
INTENT_INVALID_TOOL_NAME = "INTENT_INVALID_TOOL_NAME"
INTENT_INVALID_TOOL_INPUT = "INTENT_INVALID_TOOL_INPUT"
INTENT_INVALID_GRANTED_PERMISSIONS = "INTENT_INVALID_GRANTED_PERMISSIONS"
INTENT_INVALID_GRANTED_CAPABILITIES = "INTENT_INVALID_GRANTED_CAPABILITIES"
INTENT_INVALID_CONFIRMED = "INTENT_INVALID_CONFIRMED"
INTENT_INVALID_MAX_ATTEMPTS = "INTENT_INVALID_MAX_ATTEMPTS"
INTENT_INVALID_REQUIRED_CAPABILITIES = "INTENT_INVALID_REQUIRED_CAPABILITIES"
INTENT_INVALID_CAPABILITY_MAPPING = "INTENT_INVALID_CAPABILITY_MAPPING"

INTENT_FAILURE_CODES = (
    INTENT_NOT_A_DICT, INTENT_MISSING_FIELD, INTENT_UNEXPECTED_FIELD, INTENT_INVALID_FIELD_NAME, INTENT_INVALID_PLAN_ID,
    INTENT_INVALID_STEP_ID, INTENT_INVALID_TOOL_REQUEST, INTENT_TOOL_REQUEST_MISSING_FIELD, INTENT_TOOL_REQUEST_UNEXPECTED_FIELD,
    INTENT_TOOL_REQUEST_INVALID_FIELD_NAME, INTENT_INVALID_TOOL_NAME, INTENT_INVALID_TOOL_INPUT, INTENT_INVALID_GRANTED_PERMISSIONS,
    INTENT_INVALID_GRANTED_CAPABILITIES, INTENT_INVALID_CONFIRMED, INTENT_INVALID_MAX_ATTEMPTS, INTENT_INVALID_REQUIRED_CAPABILITIES,
    INTENT_INVALID_CAPABILITY_MAPPING,
)

_CREATE_TOKEN = object()


class _Unsafe(Exception):
    """Internal signal: the value is not plain data of exact types within the limits. Never escapes this module."""


def _copy_plain(value, allow_tuples, depth=0, budget=None):
    """Fresh copy of plain data built from EXACT types only (None, bool, int, finite float, str, list, dict with exact-str keys and,
    when `allow_tuples`, tuple). Raises `_Unsafe` for anything else, too-deep nesting or too many nodes. Runs no code supplied by
    the value (exact builtin types only) and never mutates it."""
    if budget is None:
        budget = [MAX_INTENT_NODES]
    if depth > MAX_INTENT_DEPTH:
        raise _Unsafe()
    budget[0] -= 1
    if budget[0] < 0:
        raise _Unsafe()
    kind = type(value)
    if value is None or kind is bool or kind is int or kind is str:
        return value
    if kind is float:
        if not math.isfinite(value):
            raise _Unsafe()
        return value
    if kind is list:
        return [_copy_plain(item, allow_tuples, depth + 1, budget) for item in value]
    if kind is tuple and allow_tuples:
        return tuple(_copy_plain(item, allow_tuples, depth + 1, budget) for item in value)
    if kind is dict:
        out = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _Unsafe()
            out[key] = _copy_plain(item, allow_tuples, depth + 1, budget)
        return out
    raise _Unsafe()


def _failure(code, field, message):
    return {"code": code, "field": field, "message": message}


def _is_id(value):
    return type(value) is str and bool(value.strip())


def _str_sequence(value):
    """Fresh list/tuple copy (same container kind) of an exact list/tuple of exact str, or None when malformed."""
    kind = type(value)
    if kind is not list and kind is not tuple:
        return None
    for item in value:
        if type(item) is not str:
            return None
    return kind(value)


def _key_failures(data, required, optional, prefix, code_missing, code_unexpected, code_bad_name):
    """Missing required keys (contract order), unexpected str keys (sorted) and non-str keys (one entry)."""
    failures = []
    for name in required:
        if name not in data:
            failures.append(_failure(code_missing, prefix + name, "Required field is missing; nothing is defaulted."))
    allowed = set(required) | set(optional)
    extras = sorted(k for k in data if type(k) is str and k not in allowed)
    for name in extras:
        failures.append(_failure(code_unexpected, prefix + name,
                                 "Unexpected field; alternate or extra field names are not accepted."))
    if any(type(k) is not str for k in data):
        failures.append(_failure(code_bad_name, prefix.rstrip(".") or None, "Field names must be exact str."))
    return failures


class ToolStepIntentResult:
    """Immutable data-only outcome of `build_tool_step_intent()`. Obtain it only from that function."""

    __slots__ = ("_ok", "_plan_id", "_step_id", "_request", "_max_attempts", "_required_capabilities", "_capability_mapping",
                 "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ToolStepIntentResult cannot be subclassed.")

    def __init__(self, _token, ok, plan_id, step_id, request, max_attempts, required_capabilities, capability_mapping, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use build_tool_step_intent() to obtain a ToolStepIntentResult.")
        for slot, value in (("_ok", ok), ("_plan_id", plan_id), ("_step_id", step_id), ("_request", request),
                            ("_max_attempts", max_attempts), ("_required_capabilities", required_capabilities),
                            ("_capability_mapping", capability_mapping), ("_failures", failures)):
            object.__setattr__(self, slot, value)

    def __setattr__(self, key, value):
        raise AttributeError("ToolStepIntentResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ToolStepIntentResult is immutable.")

    @property
    def ok(self):
        return self._ok

    @property
    def plan_id(self):
        return self._plan_id

    @property
    def step_id(self):
        return self._step_id

    @property
    def request(self):
        """The immutable `ToolRequest` (itself immutable, so sharing it exposes no mutable state); None when not ok."""
        return self._request

    @property
    def max_attempts(self):
        return self._max_attempts

    @property
    def required_capabilities(self):
        """A fresh copy (list stays list, tuple stays tuple) or None when the caller omitted it."""
        value = self._required_capabilities
        return None if value is None else _copy_plain(value, True)

    @property
    def capability_mapping(self):
        """A fresh deep copy of the caller's mapping value (container kinds preserved) or None when omitted."""
        value = self._capability_mapping
        return None if value is None else _copy_plain(value, True)

    @property
    def failures(self):
        """A fresh list of fresh dicts on every read."""
        return [dict(f) for f in self._failures]

    def codes(self):
        return [f["code"] for f in self._failures]

    def to_dict(self):
        """Fresh plain view of the result (the request is shown through `ToolRequest.to_dict()`)."""
        return {"ok": self._ok, "plan_id": self._plan_id, "step_id": self._step_id,
                "request": None if self._request is None else self._request.to_dict(),
                "max_attempts": self._max_attempts, "required_capabilities": self.required_capabilities,
                "capability_mapping": self.capability_mapping, "failures": self.failures}

    def __eq__(self, other):
        if not isinstance(other, ToolStepIntentResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ToolStepIntentResult is never persisted or pickled.")

    def __repr__(self):
        return f"ToolStepIntentResult(ok={self._ok!r}, codes={self.codes()!r})"


def _rejected(failures):
    return ToolStepIntentResult(_CREATE_TOKEN, False, None, None, None, None, None, None, tuple(failures))


def build_tool_step_intent(intent):
    """Validate one explicit tool-step intent and build its `ToolRequest`. Deterministic; never raises for bad data; executes,
    resolves, maps, retries and authorizes nothing; mutates nothing. Returns an immutable `ToolStepIntentResult`."""
    if type(intent) is not dict:
        return _rejected([_failure(INTENT_NOT_A_DICT, None, "The intent must be an exact dict.")])

    failures = _key_failures(intent, INTENT_REQUIRED_FIELDS, INTENT_OPTIONAL_FIELDS, "", INTENT_MISSING_FIELD,
                             INTENT_UNEXPECTED_FIELD, INTENT_INVALID_FIELD_NAME)

    plan_id = step_id = None
    if "plan_id" in intent:
        if _is_id(intent["plan_id"]):
            plan_id = intent["plan_id"]
        else:
            failures.append(_failure(INTENT_INVALID_PLAN_ID, "plan_id", "plan_id must be an exact, non-blank str."))
    if "step_id" in intent:
        if _is_id(intent["step_id"]):
            step_id = intent["step_id"]
        else:
            failures.append(_failure(INTENT_INVALID_STEP_ID, "step_id", "step_id must be an exact, non-blank str."))

    # tool_request: structure first (all five keys required, exactly those), then each value's type.
    name = tool_input = permissions = capabilities = confirmed = None
    tool_request_ok = False
    if "tool_request" in intent:
        raw = intent["tool_request"]
        if type(raw) is not dict:
            failures.append(_failure(INTENT_INVALID_TOOL_REQUEST, "tool_request", "tool_request must be an exact dict."))
        else:
            inner = _key_failures(raw, TOOL_REQUEST_FIELDS, (), "tool_request.", INTENT_TOOL_REQUEST_MISSING_FIELD,
                                  INTENT_TOOL_REQUEST_UNEXPECTED_FIELD, INTENT_TOOL_REQUEST_INVALID_FIELD_NAME)
            failures.extend(inner)
            checked = True
            if "name" in raw:
                if type(raw["name"]) is str:
                    name = raw["name"]
                else:
                    checked = False
                    failures.append(_failure(INTENT_INVALID_TOOL_NAME, "tool_request.name", "Tool name must be an exact str."))
            if "tool_input" in raw:
                try:
                    tool_input = _copy_plain(raw["tool_input"], False)
                except _Unsafe:
                    checked = False
                    failures.append(_failure(INTENT_INVALID_TOOL_INPUT, "tool_request.tool_input",
                                             "Tool input must be JSON-safe plain data of exact types within the size limits."))
            if "granted_permissions" in raw:
                permissions = _str_sequence(raw["granted_permissions"])
                if permissions is None:
                    checked = False
                    failures.append(_failure(INTENT_INVALID_GRANTED_PERMISSIONS, "tool_request.granted_permissions",
                                             "Granted permissions must be an exact list/tuple of exact str."))
            if "granted_capabilities" in raw:
                capabilities = _str_sequence(raw["granted_capabilities"])
                if capabilities is None:
                    checked = False
                    failures.append(_failure(INTENT_INVALID_GRANTED_CAPABILITIES, "tool_request.granted_capabilities",
                                             "Granted capabilities must be an exact list/tuple of exact str."))
            if "confirmed" in raw:
                if type(raw["confirmed"]) is bool:
                    confirmed = raw["confirmed"]
                else:
                    checked = False
                    failures.append(_failure(INTENT_INVALID_CONFIRMED, "tool_request.confirmed", "Confirmation must be a real bool."))
            tool_request_ok = checked and not inner

    max_attempts = None
    if "max_attempts" in intent:
        value = intent["max_attempts"]
        if type(value) is int and value > 0:
            max_attempts = value
        else:
            failures.append(_failure(INTENT_INVALID_MAX_ATTEMPTS, "max_attempts", "max_attempts must be an exact int greater than 0."))

    required = None
    if "required_capabilities" in intent:
        required = _str_sequence(intent["required_capabilities"])
        if required is None:
            failures.append(_failure(INTENT_INVALID_REQUIRED_CAPABILITIES, "required_capabilities",
                                     "required_capabilities, when present, must be an exact list/tuple of exact str."))

    mapping = None
    if "capability_mapping" in intent:
        value = intent["capability_mapping"]
        try:
            if type(value) is not list and type(value) is not tuple:
                raise _Unsafe()
            mapping = _copy_plain(value, True)
        except _Unsafe:
            failures.append(_failure(INTENT_INVALID_CAPABILITY_MAPPING, "capability_mapping",
                                     "capability_mapping, when present, must be a list/tuple of plain data."))

    if failures or not tool_request_ok:
        return _rejected(failures)

    # The whole structure is valid: hand ONLY the five explicit values (fresh copies) to the existing factory, once.
    created = create_tool_request(name, tool_input, list(permissions) if type(permissions) is list else permissions,
                                  list(capabilities) if type(capabilities) is list else capabilities, confirmed)
    if not created.ok:
        return _rejected([_failure(f["code"], "tool_request", f["message"]) for f in created.failures])

    return ToolStepIntentResult(_CREATE_TOKEN, True, plan_id, step_id, created.request, max_attempts,
                                required, mapping, ())
