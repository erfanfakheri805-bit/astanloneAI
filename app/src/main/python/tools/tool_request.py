"""
Explicit Tool Request Contract (Prompt 703, Section 5)
=========================================================
A small, immutable, in-memory record of ONE caller's explicit request to invoke ONE tool:

    create_tool_request(name, tool_input, granted_permissions=None, granted_capabilities=None, confirmed=False)
        -> ToolRequestResult(ok, request, failures)
    ToolRequest.to_registry_arguments() -> {"name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"}
        -> registry.preflight(**args) / registry.execute(**args) / registry.invoke(**args)

CONTRACT
- A `ToolRequest` is DATA ONLY: tool name, input, granted permissions, granted capabilities, confirmation state. It never holds
  or exposes a handler, a registry or any callable. Creating it, reading it and converting it never execute a tool, never touch
  a registry and never write anything anywhere.
- `create_tool_request()` never raises for bad data; it reports stable failure codes (in field order, all problems at once):
  `INVALID_TOOL_REQUEST_NAME`, `INVALID_TOOL_REQUEST_INPUT`, `INVALID_TOOL_REQUEST_PERMISSIONS`,
  `INVALID_TOOL_REQUEST_CAPABILITIES`, `INVALID_TOOL_REQUEST_CONFIRMATION`. The validation rules are the registry's own
  (`_NAME_RE`, `SUPPORTED_PERMISSIONS`, JSON-safe dict input, real-bool confirmation) applied to the caller's arguments (names via
  `fullmatch`; since Prompt 704 the registry's own pattern also uses a true end-of-string anchor, so a trailing newline is rejected everywhere).
  Direct `ToolRequest(...)` construction is refused (TypeError): the only way to get a request is a successful factory call.
- Caller intent is preserved exactly. Nothing is inferred, defaulted from a tool, trimmed, lower-cased, de-duplicated or granted.
  Omitted grants mean "no grants" and omitted confirmation means `False`. A list/tuple of grants keeps the caller's order and
  repeats; a set/frozenset has no order, so it is stored sorted (the only deterministic choice). The registry remains the only
  place that sorts/de-duplicates grants and decides authorization.
- Immutable: attribute assignment/deletion raises, the object has no `__dict__`, grants are stored as tuples, and the input is
  rebuilt through the registry's `normalize_tool_output()` (plain JSON only, runs no caller-supplied code) so later edits to the
  caller's dict/lists change nothing. `input` and `to_dict()` return FRESH deep copies on every read. copy/deepcopy return the
  same immutable object; pickling is refused (requests are never persisted). `==` compares data; requests are unhashable.
- A request grants nothing by itself: it merely CARRIES the authorization the caller supplied. `to_registry_arguments()` passes
  exactly those values (fresh copies) to the existing `preflight()`/`execute()`/`invoke()`, which still run the single `_evaluate()`
  check (unknown/disabled tool, authorization arguments, permissions, confirmation, capabilities, input) before any handler.
  Conversion never calls the registry and cannot bypass or weaken any of its checks. Since Prompt 704 the registry offers
  `execute_request(request)`, which is exactly `execute(**request.to_registry_arguments())` for a genuine request.
- No module-level state, no registry of requests, no selection/retry/scheduling/network/subprocess. Not wired into
  `process_input()`, the Planner or the Agent Loop.

Imports only `copy` and the existing registry module (which is unchanged).
"""

import copy

from tools.in_process_tool_registry import _NAME_RE, normalize_tool_output
from tools.tool_definition import SUPPORTED_PERMISSIONS

REQUEST_INVALID_NAME = "INVALID_TOOL_REQUEST_NAME"
REQUEST_INVALID_INPUT = "INVALID_TOOL_REQUEST_INPUT"
REQUEST_INVALID_PERMISSIONS = "INVALID_TOOL_REQUEST_PERMISSIONS"
REQUEST_INVALID_CAPABILITIES = "INVALID_TOOL_REQUEST_CAPABILITIES"
REQUEST_INVALID_CONFIRMATION = "INVALID_TOOL_REQUEST_CONFIRMATION"

_CREATE_TOKEN = object()


def _failure(code, message):
    return {"code": code, "message": message}


def _grant_items(value):
    """Items of an accepted grant collection, read with the base types' own iterators (no caller-supplied `__iter__`), or None
    when `value` is not a list/tuple/set/frozenset. Sets are returned sorted; lists/tuples keep order and repeats."""
    if isinstance(value, list):
        return list(list.__iter__(value)), False
    if isinstance(value, tuple):
        return list(tuple.__iter__(value)), False
    if isinstance(value, set):
        return list(set.__iter__(value)), True
    if isinstance(value, frozenset):
        return list(frozenset.__iter__(value)), True
    return None


def _clean_grants(value, is_valid_item):
    """Returns a tuple of exact `str` grants, or None if the collection or any item is malformed."""
    got = _grant_items(value)
    if got is None:
        return None
    items, unordered = got
    exact = []
    for item in items:
        if not isinstance(item, str):
            return None
        item = str.__str__(item)
        if not is_valid_item(item):
            return None
        exact.append(item)
    return tuple(sorted(exact)) if unordered else tuple(exact)


class ToolRequest:
    """Immutable data record of one explicit tool request. Obtain it only from `create_tool_request()`."""

    __slots__ = ("_name", "_input", "_granted_permissions", "_granted_capabilities", "_confirmed")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ToolRequest cannot be subclassed.")

    def __init__(self, _token, name, tool_input, granted_permissions, granted_capabilities, confirmed):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_tool_request() to build a ToolRequest.")
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_input", tool_input)
        object.__setattr__(self, "_granted_permissions", granted_permissions)
        object.__setattr__(self, "_granted_capabilities", granted_capabilities)
        object.__setattr__(self, "_confirmed", confirmed)

    def __setattr__(self, key, value):
        raise AttributeError("ToolRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ToolRequest is immutable.")

    @property
    def name(self):
        return self._name

    @property
    def input(self):
        """A fresh deep copy of the request input on every read."""
        return copy.deepcopy(self._input)

    @property
    def granted_permissions(self):
        return self._granted_permissions

    @property
    def granted_capabilities(self):
        return self._granted_capabilities

    @property
    def confirmed(self):
        return self._confirmed

    def to_dict(self):
        """Fresh plain-JSON view of the request (never contains a handler or any callable)."""
        return {"name": self._name, "input": copy.deepcopy(self._input),
                "granted_permissions": list(self._granted_permissions),
                "granted_capabilities": list(self._granted_capabilities), "confirmed": self._confirmed}

    def to_registry_arguments(self):
        """Keyword arguments for the existing `InProcessToolRegistry.preflight()/execute()/invoke()`, carrying exactly what the
        caller supplied (fresh copies). Does not call a registry, run a tool, or add/repair/grant anything."""
        return {"name": self._name, "tool_input": copy.deepcopy(self._input),
                "granted_permissions": list(self._granted_permissions), "confirmed": self._confirmed,
                "granted_capabilities": list(self._granted_capabilities)}

    def __eq__(self, other):
        if not isinstance(other, ToolRequest):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ToolRequest is never persisted or pickled.")

    def __repr__(self):
        return f"ToolRequest(name={self._name!r}, confirmed={self._confirmed!r})"


class ToolRequestResult:
    """Outcome of `create_tool_request()`: `request` is set only when `ok`."""
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


def create_tool_request(name, tool_input, granted_permissions=None, granted_capabilities=None, confirmed=False):
    """Validate the caller's arguments and build an immutable `ToolRequest`. Deterministic, never raises for bad data, never
    executes anything. Returns a `ToolRequestResult`."""
    failures = []
    if not (isinstance(name, str) and _NAME_RE.fullmatch(name)):
        failures.append(_failure(REQUEST_INVALID_NAME, "Tool name must match ^[a-z][a-z0-9_]{0,63}$ exactly."))
    input_ok, input_copy = normalize_tool_output(tool_input)
    if not (input_ok and isinstance(input_copy, dict)):
        failures.append(_failure(REQUEST_INVALID_INPUT, "Tool input must be a JSON-safe dict."))
    perms = _clean_grants(() if granted_permissions is None else granted_permissions,
                          lambda p: p in SUPPORTED_PERMISSIONS)
    if perms is None:
        failures.append(_failure(REQUEST_INVALID_PERMISSIONS,
                                 "Granted permissions must be a list/tuple/set/frozenset of SUPPORTED_PERMISSIONS names."))
    caps = _clean_grants(() if granted_capabilities is None else granted_capabilities,
                         lambda c: _NAME_RE.fullmatch(c) is not None)
    if caps is None:
        failures.append(_failure(REQUEST_INVALID_CAPABILITIES,
                                 "Granted capabilities must be a list/tuple/set/frozenset of names matching "
                                 "^[a-z][a-z0-9_]{0,63}$."))
    if not isinstance(confirmed, bool):
        failures.append(_failure(REQUEST_INVALID_CONFIRMATION, "Confirmation must be a real bool."))
    if failures:
        return ToolRequestResult(None, failures)
    request = ToolRequest(_CREATE_TOKEN, str.__str__(name), input_copy, perms, caps, confirmed)
    return ToolRequestResult(request, [])
