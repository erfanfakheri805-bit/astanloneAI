"""
Tool-Step Dispatch Decision Layer (Prompt 717, Section 6)
==========================================================
The isolated dispatch-decision layer that sits directly on top of the Prompt 716 route resolver
(docs/section6_tool_step_dispatch_prompt717.md). It is a DATA-ONLY DECISION. It is NOT wired anywhere: not into `process_input()`, not into
`AgentLoop`, not into `execution/`, not into `Planner`, `PlanManager` or `ExecutionEngine`, not into the Section 6 adapter.

    resolve_tool_step_dispatch(declaration=None, legacy_input=None, tool_input=None) -> DispatchResolutionResult

  declaration   caller-provided routing metadata; handed unchanged to `planning.tool_step_route.resolve_execution_route()`, which is called
                exactly once. Explicit "section6_tool" -> tool dispatch. Explicit "legacy_capability" -> legacy dispatch. Absent / unknown /
                malformed -> legacy dispatch through the Prompt 716 fallback (never the tool route). Explicit vs fallback is preserved.
  legacy_input  caller-owned payload that belongs to the legacy route.
  tool_input    caller-owned payload that belongs to the Section 6 tool route.

The route is decided ONLY by the resolver. Payload contents, plan data, tool names, capabilities, permissions and object types are never
consulted to pick a route, and payload validity can never change it: a bad payload yields a REJECTED dispatch on the SAME route.

PAYLOAD RULES (only the payload of the selected route is looked at; the other one is never inspected, copied or returned):
  * `None` means "not provided". A selected route whose payload is `None` is rejected (DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT); no default is invented.
  * The payload must be JSON-safe structured data built from EXACT types only: None, bool, int, float (finite), str, list, dict (keys exactly
    `str`). Subclasses (str/int/dict/list subclasses, enums, OrderedDict ...), tuples, sets, bytes, NaN/inf, non-str keys, arbitrary objects,
    self-referencing containers, structures deeper than MAX_PAYLOAD_DEPTH or larger than MAX_PAYLOAD_NODES are rejected
    (DISPATCH_CODE_REJECTED_PAYLOAD_INVALID). Nothing is coerced. A rejected payload is never repr()'d, stringified, hashed or compared, and no
    method of a rejected object is called.
  * An accepted payload is DEEP-COPIED into the result; `payload` returns a fresh deep copy on every access. Caller inputs are never mutated and
    later mutation of them (or of a returned copy) cannot reach the result.

WHAT THIS MODULE DOES NOT DO: it constructs no ToolRequest, calls no registry, executes nothing, invokes no tool or handler, grants no
permission or capability, maps no capability, retries nothing, never reads `execution_authorized`, never reads a Plan or PlanStep, changes no
Plan/PlanStep, and keeps no module-level routing registry. The only project import is the Prompt 716 resolver.

RESULT: `DispatchResolutionResult` is immutable, data-only, cannot be subclassed and is obtainable only from `resolve_tool_step_dispatch()`.
STATELESS: no module variable that changes, no singleton, cache, registry, persistence, clock, randomness or background task.
"""
import math

from planning.tool_step_route import ROUTE_LEGACY_CAPABILITY, ROUTE_SECTION6_TOOL, resolve_execution_route

DISPATCH_STATUS_READY = "ready"
DISPATCH_STATUS_REJECTED = "rejected"

DISPATCH_KIND_LEGACY = "legacy_capability_dispatch"
DISPATCH_KIND_SECTION6_TOOL = "section6_tool_dispatch"

PAYLOAD_SOURCE_LEGACY_INPUT = "legacy_input"
PAYLOAD_SOURCE_TOOL_INPUT = "tool_input"

DISPATCH_CODE_LEGACY_INPUT_SELECTED = "LEGACY_INPUT_SELECTED"
DISPATCH_CODE_TOOL_INPUT_SELECTED = "TOOL_INPUT_SELECTED"
DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT = "REJECTED_PAYLOAD_ABSENT"
DISPATCH_CODE_REJECTED_PAYLOAD_INVALID = "REJECTED_PAYLOAD_INVALID"

DISPATCH_STATUSES = (DISPATCH_STATUS_READY, DISPATCH_STATUS_REJECTED)
DISPATCH_KINDS = (DISPATCH_KIND_LEGACY, DISPATCH_KIND_SECTION6_TOOL)
PAYLOAD_SOURCES = (PAYLOAD_SOURCE_LEGACY_INPUT, PAYLOAD_SOURCE_TOOL_INPUT)
DISPATCH_CODES = (DISPATCH_CODE_LEGACY_INPUT_SELECTED, DISPATCH_CODE_TOOL_INPUT_SELECTED,
                  DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)

MAX_PAYLOAD_DEPTH = 32
MAX_PAYLOAD_NODES = 100000

_DISPATCH_REASONS = (
    (DISPATCH_CODE_LEGACY_INPUT_SELECTED, "The caller-owned legacy input was selected for the legacy capability route."),
    (DISPATCH_CODE_TOOL_INPUT_SELECTED, "The caller-owned tool input was selected for the Section 6 tool route."),
    (DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, "The payload for the selected route was not provided; the route is unchanged."),
    (DISPATCH_CODE_REJECTED_PAYLOAD_INVALID, "The payload for the selected route is not JSON-safe structured data; the route is unchanged."),
)
_CREATE_TOKEN = object()
_NoneType = type(None)


class _InvalidPayload(Exception):
    pass


def _copy_payload(value, depth, path_ids, budget):
    """Validate `value` (exact JSON-safe types only) and return an independent deep copy. Raises _InvalidPayload otherwise.

    Only exact built-in types are ever touched; anything else is rejected from its type alone, without calling any of its methods.
    """
    budget[0] += 1
    if budget[0] > MAX_PAYLOAD_NODES or depth > MAX_PAYLOAD_DEPTH:
        raise _InvalidPayload()
    kind = type(value)
    if kind is _NoneType or kind is bool or kind is int or kind is str:
        return value
    if kind is float:
        if not math.isfinite(value):
            raise _InvalidPayload()
        return value
    if kind is list or kind is dict:
        ident = id(value)
        if ident in path_ids:                           # self-reference / cycle
            raise _InvalidPayload()
        path_ids.add(ident)
        try:
            if kind is list:
                return [_copy_payload(item, depth + 1, path_ids, budget) for item in value]
            out = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise _InvalidPayload()
                out[key] = _copy_payload(item, depth + 1, path_ids, budget)
            return out
        finally:
            path_ids.discard(ident)
    raise _InvalidPayload()


def _safe_copy(value):
    try:
        return _copy_payload(value, 0, set(), [0])
    except (_InvalidPayload, RecursionError):
        raise _InvalidPayload() from None


def _same(a, b):
    """Type-exact structural equality for already-validated payloads (True != 1, 1 != 1.0)."""
    if type(a) is not type(b):
        return False
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if type(a) is dict:
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    return a == b


class DispatchResolutionResult:
    """Immutable, data-only record of one `resolve_tool_step_dispatch()` call. Obtain it only from that function.

    route              ROUTE_LEGACY_CAPABILITY or ROUTE_SECTION6_TOOL, exactly as resolved by Prompt 716
    explicit           Prompt 716: True only for a valid explicit declaration
    fallback           Prompt 716: True only when the route is legacy because the declaration was absent / unknown / malformed
    declaration_valid  Prompt 716: True only when the declaration was exactly one of the two valid strings
    route_code         Prompt 716 resolver code (one of tool_step_route.ROUTE_CODES)
    route_reason       Prompt 716 fixed reason sentence for `route_code`
    route_result       the Prompt 716 RouteResolutionResult itself (immutable)
    dispatch_kind      DISPATCH_KIND_LEGACY or DISPATCH_KIND_SECTION6_TOOL (follows the route, even when rejected)
    dispatch_status    DISPATCH_STATUS_READY or DISPATCH_STATUS_REJECTED
    dispatch_code      one of DISPATCH_CODES
    dispatch_reason    fixed sentence for `dispatch_code`
    payload_source     PAYLOAD_SOURCE_* naming which caller-owned argument belongs to the route
    has_payload        True only when ready
    payload            fresh deep copy of the selected payload on each access; None when rejected
    is_section6_tool / is_legacy_capability / is_ready / is_rejected   convenience booleans
    """

    __slots__ = ("_route_result", "_kind", "_status", "_code", "_source", "_payload")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("DispatchResolutionResult cannot be subclassed.")

    def __init__(self, _token, route_result, kind, status, code, source, payload):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use resolve_tool_step_dispatch() to obtain a DispatchResolutionResult.")
        object.__setattr__(self, "_route_result", route_result)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_payload", payload)

    def __setattr__(self, key, value):
        raise AttributeError("DispatchResolutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("DispatchResolutionResult is immutable.")

    def __copy__(self):
        return self                                     # immutable: sharing is safe

    def __deepcopy__(self, memo):
        return self

    @property
    def route_result(self):
        return self._route_result

    @property
    def route(self):
        return self._route_result.route

    @property
    def explicit(self):
        return self._route_result.explicit

    @property
    def fallback(self):
        return self._route_result.fallback

    @property
    def declaration_valid(self):
        return self._route_result.declaration_valid

    @property
    def route_code(self):
        return self._route_result.code

    @property
    def route_reason(self):
        return self._route_result.reason

    @property
    def dispatch_kind(self):
        return self._kind

    @property
    def dispatch_status(self):
        return self._status

    @property
    def dispatch_code(self):
        return self._code

    @property
    def dispatch_reason(self):
        return dict(_DISPATCH_REASONS)[self._code]

    @property
    def payload_source(self):
        return self._source

    @property
    def has_payload(self):
        return self._status == DISPATCH_STATUS_READY

    @property
    def payload(self):
        if self._status != DISPATCH_STATUS_READY:
            return None
        return _safe_copy(self._payload)

    @property
    def is_section6_tool(self):
        return self._route_result.route == ROUTE_SECTION6_TOOL

    @property
    def is_legacy_capability(self):
        return self._route_result.route == ROUTE_LEGACY_CAPABILITY

    @property
    def is_ready(self):
        return self._status == DISPATCH_STATUS_READY

    @property
    def is_rejected(self):
        return self._status == DISPATCH_STATUS_REJECTED

    def as_dict(self):
        """A fresh plain dict (with a fresh payload copy) on every call; mutating it never affects this result."""
        return {"route": self.route, "explicit": self.explicit, "fallback": self.fallback,
                "declaration_valid": self.declaration_valid, "route_code": self.route_code, "route_reason": self.route_reason,
                "dispatch_kind": self._kind, "dispatch_status": self._status, "dispatch_code": self._code,
                "dispatch_reason": self.dispatch_reason, "payload_source": self._source, "has_payload": self.has_payload,
                "payload": self.payload, "is_section6_tool": self.is_section6_tool}

    def _key(self):
        return (self._route_result, self._kind, self._status, self._code, self._source)

    def __eq__(self, other):
        if type(other) is not DispatchResolutionResult:
            return NotImplemented
        return self._key() == other._key() and _same(self._payload, other._payload)

    def __hash__(self):
        return hash(self._key())                        # payload excluded: consistent with __eq__, and payloads are unhashable

    def __repr__(self):                                 # never includes the payload
        return ("DispatchResolutionResult(route=%r, explicit=%r, fallback=%r, declaration_valid=%r, route_code=%r, "
                "dispatch_kind=%r, dispatch_status=%r, dispatch_code=%r, payload_source=%r)"
                % (self.route, self.explicit, self.fallback, self.declaration_valid, self.route_code,
                   self._kind, self._status, self._code, self._source))


def _make(route_result, kind, status, code, source, payload):
    return DispatchResolutionResult(_CREATE_TOKEN, route_result, kind, status, code, source, payload)


def resolve_tool_step_dispatch(declaration=None, legacy_input=None, tool_input=None):
    """Turn the Prompt 716 route into a caller-facing dispatch decision. Pure, stateless, deterministic; executes nothing."""
    route_result = resolve_execution_route(declaration)           # exactly once; the only source of the route
    if route_result.route == ROUTE_SECTION6_TOOL:
        kind, source, selected, ready_code = DISPATCH_KIND_SECTION6_TOOL, PAYLOAD_SOURCE_TOOL_INPUT, tool_input, DISPATCH_CODE_TOOL_INPUT_SELECTED
    elif route_result.route == ROUTE_LEGACY_CAPABILITY:
        kind, source, selected, ready_code = DISPATCH_KIND_LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT, legacy_input, DISPATCH_CODE_LEGACY_INPUT_SELECTED
    else:
        raise ValueError("Unexpected route from the Prompt 716 resolver.")
    if selected is None:
        return _make(route_result, kind, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, source, None)
    try:
        payload = _safe_copy(selected)
    except _InvalidPayload:
        return _make(route_result, kind, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID, source, None)
    return _make(route_result, kind, DISPATCH_STATUS_READY, ready_code, source, payload)
