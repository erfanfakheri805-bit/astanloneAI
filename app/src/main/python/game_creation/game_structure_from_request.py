"""
Game Structure From Request (Prompt 741, Section 7 - Professional Game Creation)
===============================================================================
A small, explicit, caller-driven, read-only bridge from a `GameCreationRequest` to the existing `GameProjectStructure` factory layer.

    create_game_project_structure_from_request(request) -> GameStructureFromRequestResult(ok, structure, failures)
    GameStructureFromRequestResult.codes()   -> [code, ...]
    GameStructureFromRequestResult.to_dict() -> {"ok", "structure", "failures"}

DEPENDENCY DIRECTION
    GameCreationRequest -> this bridge -> create_game_project_structure()
This module imports `GameCreationRequest` (exact-type check only) and the public factory `create_game_project_structure`. Neither of those modules
knows this one, and none of them was changed.

WHAT THE REQUEST CONTRIBUTES (IMPORTANT)
A `GameCreationRequest` holds exactly six project fields (project_id, name, description, genre, target_platform, version). A
`GameProjectStructure` holds four collections of identifiers (scenes, characters, gameplay_systems, assets). The request carries NO structural
information, and this bridge deliberately invents none: it never reads any request field. A valid request is the caller's go-ahead for a new, EMPTY
project structure, so the factory is called with exactly four empty lists:

    create_game_project_structure({"scenes": [], "characters": [], "gameplay_systems": [], "assets": []})

(An empty list is valid for the factory, so this is the factory's own documented shape, not a new rule.) Nothing is derived from the request's
name, genre, description or any other value. Each call builds fresh lists; no list is shared between calls.

BEHAVIOR
1. `request` must be exactly a `GameCreationRequest` (a subclass, look-alike, dict, `None` or any other object is rejected, nothing is coerced).
   Otherwise: `ok=False`, `structure=None`, one failure `GAME_STRUCTURE_FROM_REQUEST_INVALID_REQUEST` (field "request"), and the factory is NOT called.
2. For a valid request the factory is called exactly once through its public name. This module does no validation of its own and does not trim,
   normalize, coerce or rebuild anything.
3. If the factory succeeds, the `GameProjectStructure` it returned is exposed as-is (same object; identity preserved).
4. If the factory reports failures, they are exposed unchanged (same codes, fields, messages and order) with `ok=False` and `structure=None`. No
   failure is invented or re-coded, so they keep the factory's `GAME_PROJECT_STRUCTURE_` prefix. Only the bridge's own failure carries the bridge
   prefix `GAME_STRUCTURE_FROM_REQUEST_`.
5. The request is never changed and never read beyond its type; no private attribute of any object is accessed; no registry is used.

RESULT
The factory's own `GameProjectStructureResult` is a plain mutable holder, so it is not handed out. `GameStructureFromRequestResult` follows the
established Section 7 immutable result conventions: `__slots__`, read-only attributes, not subclassable, direct construction refused (TypeError),
equal contents mean equal objects and equal hashes, `failures` / `to_dict()` / `codes()` return FRESH plain data every call, copy/deepcopy return the
same object, pickling is refused.

WHAT THIS MODULE DOES NOT DO
No runtime execution, no registry, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state, and no
wiring into `process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it.
"""

from .game_creation_request import GameCreationRequest
from .game_project_structure import create_game_project_structure

FAILURE_PREFIX = "GAME_STRUCTURE_FROM_REQUEST_"
FAILURE_INVALID_REQUEST = "GAME_STRUCTURE_FROM_REQUEST_INVALID_REQUEST"
FAILURE_CODES = (FAILURE_INVALID_REQUEST,)

_CREATE_TOKEN = object()


class GameStructureFromRequestResult:
    """Immutable outcome of `create_game_project_structure_from_request()`: `structure` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_structure", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameStructureFromRequestResult cannot be subclassed.")

    def __init__(self, _token, structure, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_project_structure_from_request() to get a GameStructureFromRequestResult.")
        object.__setattr__(self, "_structure", structure)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameStructureFromRequestResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameStructureFromRequestResult is immutable.")

    @property
    def ok(self):
        return self._structure is not None and not self._failures

    @property
    def structure(self):
        return self._structure

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "structure": self._structure.to_dict() if self._structure is not None else None, "failures": self.failures}

    def _key(self):
        return (self._structure, self._failures)

    def __eq__(self, other):
        if type(other) is not GameStructureFromRequestResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameStructureFromRequestResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameStructureFromRequestResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_project_structure_from_request(request):
    """Accept one exact `GameCreationRequest` and obtain a new, empty `GameProjectStructure` through the existing public
    `create_game_project_structure()` factory. The request supplies no structure data and is never read beyond its type. Deterministic, never raises
    for a bad `request`, runs nothing else. Returns a `GameStructureFromRequestResult`."""
    if type(request) is not GameCreationRequest:
        return GameStructureFromRequestResult(_CREATE_TOKEN, None, [(FAILURE_INVALID_REQUEST, "request", "request must be exactly a GameCreationRequest.")])
    produced = create_game_project_structure({"scenes": [], "characters": [], "gameplay_systems": [], "assets": []})
    if produced.ok:
        return GameStructureFromRequestResult(_CREATE_TOKEN, produced.structure, [])
    return GameStructureFromRequestResult(_CREATE_TOKEN, None, [(f["code"], f["field"], f["message"]) for f in produced.failures])
