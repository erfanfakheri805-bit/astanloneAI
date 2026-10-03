"""
Explicit Tool-Step Execution Route Resolver (Prompt 716, Section 6)
=====================================================================
The isolated implementation of the execution-route contract decided in Prompt 715
(docs/section6_agent_loop_routing_decision_prompt715.md, DECISION-1). It is ROUTING METADATA ONLY. It is NOT wired anywhere: not into
`process_input()`, not into `AgentLoop`, not into `execution/`, not into `PlanManager`, not into the Section 6 adapter.

    resolve_execution_route(declaration=None) -> RouteResolutionResult

  declaration   caller-provided routing metadata and nothing else. Exactly two values are valid:
                    "legacy_capability"   ->  ROUTE_LEGACY_CAPABILITY  (explicit, valid)
                    "section6_tool"       ->  ROUTE_SECTION6_TOOL      (explicit, valid)
                Anything else falls back to the legacy route (the pre-existing behaviour), and NEVER to the tool route:
                    absent (omitted or None)          -> legacy, code FALLBACK_ABSENT_DECLARATION
                    a `str` that is not exactly valid -> legacy, code FALLBACK_UNKNOWN_DECLARATION   ("", "Section6_Tool", "section6_tool ", ...)
                    any non-`str` value, or a `str`
                    subclass instance                 -> legacy, code FALLBACK_MALFORMED_DECLARATION

MATCHING IS EXACT. No trimming, no case folding, no normalisation, no fuzzy matching, no intent inference, no defaults from context.
Only an object whose type is exactly `str` is ever compared, so a `str` subclass (which could override `__eq__`, `__hash__` or any other
method) is treated as malformed and none of its methods is ever called. Containers and arbitrary objects are never iterated, indexed,
stringified, hashed or compared; only their type is looked at.

WHAT THIS MODULE DOES NOT DO: it does not read a Plan, PlanStep, registry, tool name, handler, capability, permission, execution state or
Agent Loop state; it validates no plan or step; it constructs no ToolRequest; it resolves no capability; it executes nothing; it keeps no
module-level routing registry. The Section 6 Agent Loop adapter stays responsible for every plan/step/request check.
This module imports nothing from the project (only the standard library is used).

INVARIANT: `route == ROUTE_SECTION6_TOOL` if and only if the declaration was exactly the str "section6_tool".

RESULT: `RouteResolutionResult` is immutable, data-only, cannot be subclassed and is obtainable only from `resolve_execution_route()`. It
holds five plain values (str / bool), so there is no shared mutable state; `as_dict()` returns a fresh dict on every call.

STATELESS: no module variable that changes, no singleton, cache, registry, persistence, clock, randomness or background task.
"""

ROUTE_LEGACY_CAPABILITY = "legacy_capability"
ROUTE_SECTION6_TOOL = "section6_tool"

ROUTE_CODE_EXPLICIT_LEGACY = "EXPLICIT_LEGACY_CAPABILITY"
ROUTE_CODE_EXPLICIT_SECTION6 = "EXPLICIT_SECTION6_TOOL"
ROUTE_CODE_FALLBACK_ABSENT = "FALLBACK_ABSENT_DECLARATION"
ROUTE_CODE_FALLBACK_UNKNOWN = "FALLBACK_UNKNOWN_DECLARATION"
ROUTE_CODE_FALLBACK_MALFORMED = "FALLBACK_MALFORMED_DECLARATION"

VALID_ROUTES = (ROUTE_LEGACY_CAPABILITY, ROUTE_SECTION6_TOOL)
ROUTE_CODES = (ROUTE_CODE_EXPLICIT_LEGACY, ROUTE_CODE_EXPLICIT_SECTION6, ROUTE_CODE_FALLBACK_ABSENT,
               ROUTE_CODE_FALLBACK_UNKNOWN, ROUTE_CODE_FALLBACK_MALFORMED)

_REASONS = (
    (ROUTE_CODE_EXPLICIT_LEGACY, "The caller explicitly declared the legacy capability route."),
    (ROUTE_CODE_EXPLICIT_SECTION6, "The caller explicitly declared the Section 6 tool route."),
    (ROUTE_CODE_FALLBACK_ABSENT, "No declaration was supplied; falling back to the legacy capability route."),
    (ROUTE_CODE_FALLBACK_UNKNOWN, "The declaration is a string that is not an exact valid route; falling back to the legacy capability route."),
    (ROUTE_CODE_FALLBACK_MALFORMED, "The declaration is not an exact str; falling back to the legacy capability route."),
)
_CREATE_TOKEN = object()


class RouteResolutionResult:
    """Immutable, data-only record of one `resolve_execution_route()` call. Obtain it only from that function.

    route              ROUTE_LEGACY_CAPABILITY or ROUTE_SECTION6_TOOL
    explicit           True only when the caller made a valid explicit declaration (legacy or Section 6)
    fallback           True only when the route is legacy because the declaration was absent, unknown or malformed
    declaration_valid  True only when the declaration was exactly one of the two valid strings
    code               one of ROUTE_CODES
    reason             a fixed human-readable sentence for `code`
    """

    __slots__ = ("_route", "_explicit", "_fallback", "_declaration_valid", "_code")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("RouteResolutionResult cannot be subclassed.")

    def __init__(self, _token, route, explicit, fallback, declaration_valid, code):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use resolve_execution_route() to obtain a RouteResolutionResult.")
        object.__setattr__(self, "_route", route)
        object.__setattr__(self, "_explicit", explicit)
        object.__setattr__(self, "_fallback", fallback)
        object.__setattr__(self, "_declaration_valid", declaration_valid)
        object.__setattr__(self, "_code", code)

    def __setattr__(self, key, value):
        raise AttributeError("RouteResolutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("RouteResolutionResult is immutable.")

    def __copy__(self):
        return self                                     # immutable: sharing is safe

    def __deepcopy__(self, memo):
        return self

    @property
    def route(self):
        return self._route

    @property
    def explicit(self):
        return self._explicit

    @property
    def fallback(self):
        return self._fallback

    @property
    def declaration_valid(self):
        return self._declaration_valid

    @property
    def code(self):
        return self._code

    @property
    def reason(self):
        return dict(_REASONS)[self._code]

    @property
    def is_section6_tool(self):
        return self._route == ROUTE_SECTION6_TOOL

    @property
    def is_legacy_capability(self):
        return self._route == ROUTE_LEGACY_CAPABILITY

    def as_dict(self):
        """A fresh plain dict on every call; mutating it never affects this result."""
        return {"route": self._route, "explicit": self._explicit, "fallback": self._fallback,
                "declaration_valid": self._declaration_valid, "code": self._code, "reason": self.reason}

    def _key(self):
        return (self._route, self._explicit, self._fallback, self._declaration_valid, self._code)

    def __eq__(self, other):
        if type(other) is not RouteResolutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        return "RouteResolutionResult(route=%r, explicit=%r, fallback=%r, declaration_valid=%r, code=%r)" % self._key()


def _make(route, explicit, fallback, declaration_valid, code):
    return RouteResolutionResult(_CREATE_TOKEN, route, explicit, fallback, declaration_valid, code)


def resolve_execution_route(declaration=None):
    """Resolve caller-provided routing metadata to an execution route. Pure, stateless, deterministic; reads nothing else."""
    if declaration is None:
        return _make(ROUTE_LEGACY_CAPABILITY, False, True, False, ROUTE_CODE_FALLBACK_ABSENT)
    if type(declaration) is not str:                    # exact type only: subclasses / non-strings are never inspected
        return _make(ROUTE_LEGACY_CAPABILITY, False, True, False, ROUTE_CODE_FALLBACK_MALFORMED)
    if declaration == "section6_tool":
        return _make(ROUTE_SECTION6_TOOL, True, False, True, ROUTE_CODE_EXPLICIT_SECTION6)
    if declaration == "legacy_capability":
        return _make(ROUTE_LEGACY_CAPABILITY, True, False, True, ROUTE_CODE_EXPLICIT_LEGACY)
    return _make(ROUTE_LEGACY_CAPABILITY, False, True, False, ROUTE_CODE_FALLBACK_UNKNOWN)
