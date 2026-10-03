"""
Game Creation Request Bridge (Prompt 740, Section 7 - Professional Game Creation)
=================================================================================
A small, explicit, caller-driven bridge that turns one valid `GameCreationRequest` into one `GameProject` by calling the existing public
project factory. It adds no project rules of its own.

    create_game_project_from_request(request) -> GameCreationRequestBridgeResult(ok, project, failures)
    GameCreationRequestBridgeResult.codes()   -> [code, ...]
    GameCreationRequestBridgeResult.to_dict() -> {"ok", "project", "failures"}

DEPENDENCY DIRECTION
    GameCreationRequest -> bridge -> GameProject factory
This module imports `GameCreationRequest` (for the exact-type check) and `create_game_project` (the factory). Neither `game_creation_request.py`
nor `game_project.py` imports or knows about this module, and `GameProject` does not depend on `GameCreationRequest`.

BEHAVIOR
1. `request` must be exactly a `GameCreationRequest` (a subclass, look-alike, dict or `None` is rejected, nothing is coerced). Otherwise the result
   is `ok=False`, `project=None` and exactly one failure, `GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST`, and the factory is NOT called.
2. For a valid request the six fields (project_id, name, description, genre, target_platform, version) are read through the request's PUBLIC
   properties and handed unchanged, as the very same string objects, to `create_game_project(...)` in a fresh plain dict. Nothing is trimmed,
   normalized, coerced, rebuilt or checked again here.
3. If the factory succeeds, the `GameProject` it returned is stored and exposed as-is (same object, identity preserved; no copy, no rebuild).
4. If the factory unexpectedly reports failures, they are exposed unchanged (same codes, fields and messages, same order) with `ok=False` and
   `project=None`. The bridge invents no project-validation rule and no code for them, so such codes keep the factory's own prefix
   (`GAME_PROJECT_`); only the bridge's own failure carries the bridge prefix `GAME_CREATION_REQUEST_BRIDGE_`.
5. The request is only read, never changed. No private attribute of `GameCreationRequest` or `GameProject` is touched and no registry is used.

RESULT
`GameCreationRequestBridgeResult` follows the established Section 7 result conventions: `__slots__`, read-only attributes, not subclassable,
direct construction refused (TypeError), equal contents mean equal objects and equal hashes, `failures` and `to_dict()` return FRESH plain data on
every call, copy/deepcopy return the same object, pickling is refused, `codes()` returns the failure codes in order.

WHAT THIS MODULE DOES NOT DO
No runtime execution, no registry, no file/network/database/AI access, no clock or randomness, no module-level mutable state, and no wiring into
`process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it.
"""

from .game_creation_request import GameCreationRequest
from .game_project import create_game_project

FAILURE_PREFIX = "GAME_CREATION_REQUEST_BRIDGE_"
FAILURE_INVALID_REQUEST = "GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST"
FAILURE_CODES = (FAILURE_INVALID_REQUEST,)

_CREATE_TOKEN = object()


class GameCreationRequestBridgeResult:
    """Immutable outcome of `create_game_project_from_request()`: `project` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_project", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameCreationRequestBridgeResult cannot be subclassed.")

    def __init__(self, _token, project, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_project_from_request() to get a GameCreationRequestBridgeResult.")
        object.__setattr__(self, "_project", project)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameCreationRequestBridgeResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameCreationRequestBridgeResult is immutable.")

    @property
    def ok(self):
        return self._project is not None and not self._failures

    @property
    def project(self):
        return self._project

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "project": self._project.to_dict() if self._project is not None else None, "failures": self.failures}

    def _key(self):
        return (self._project, self._failures)

    def __eq__(self, other):
        if type(other) is not GameCreationRequestBridgeResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameCreationRequestBridgeResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameCreationRequestBridgeResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_project_from_request(request):
    """Convert one valid `GameCreationRequest` into a `GameProject` through the existing `create_game_project()` factory, passing the six request
    fields through unchanged. Deterministic, never raises for a bad `request`, reads `request` without changing it, runs nothing else. Returns a
    `GameCreationRequestBridgeResult`."""
    if type(request) is not GameCreationRequest:
        return GameCreationRequestBridgeResult(_CREATE_TOKEN, None, [(FAILURE_INVALID_REQUEST, "request", "request must be exactly a GameCreationRequest.")])
    produced = create_game_project({"project_id": request.project_id, "name": request.name, "description": request.description,
                                    "genre": request.genre, "target_platform": request.target_platform, "version": request.version})
    if produced.ok:
        return GameCreationRequestBridgeResult(_CREATE_TOKEN, produced.project, [])
    return GameCreationRequestBridgeResult(_CREATE_TOKEN, None, [(f["code"], f["field"], f["message"]) for f in produced.failures])
