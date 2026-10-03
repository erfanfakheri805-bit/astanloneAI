"""
Game Structure Request Bridge (Prompt 744, Section 7 - Professional Game Creation)
=================================================================================
A small, explicit, caller-driven, read-only bridge from a `GameStructureRequest` to the existing `GameProjectStructure` factory.

    create_game_project_structure_from_request(request) -> GameStructureRequestBridgeResult(ok, structure, failures)
    GameStructureRequestBridgeResult.codes()   -> [code, ...]
    GameStructureRequestBridgeResult.to_dict() -> {"ok", "structure", "failures"}

DEPENDENCY DIRECTION
    GameStructureRequest -> this bridge -> create_game_project_structure()
This module imports `GameStructureRequest` (exact-type check only) and the public factory `create_game_project_structure`. Neither of those
modules knows this one, and none of them was changed. (The older Prompt 741 bridge is a different, unrelated bridge that starts from another
request type; this module neither imports nor changes it.)

BEHAVIOR
1. `request` must be exactly a `GameStructureRequest` (a subclass, look-alike, dict, `None`, a request of another type or any other object is
   rejected, nothing is coerced). Otherwise: `ok=False`, `structure=None`, one failure `GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST`
   (field "request"), and the factory is NOT called.
2. For a valid request only the four public properties `scenes`, `characters`, `gameplay_systems`, `assets` are read, in that order, and the
   factory is called exactly once through its public name with a plain dict of those four values. No private attribute is read.
3. CONTAINER ADAPTATION (the one thing this bridge does besides passing values on): the factory accepts only an exact `list` for a collection,
   while the request stores each collection as a `tuple`. The bridge therefore hands the factory a FRESH `list` of each tuple's items. The items
   are the very same string objects, in the same order; nothing is trimmed, normalized, reordered, deduplicated, filtered or rewritten. This is a
   container change only, not a validation or a value change.
4. This module does no validation of its own. Whatever the factory decides stands.
5. If the factory succeeds, the `GameProjectStructure` it returned is exposed as-is (same object; identity preserved).
6. If the factory reports failures, they are exposed unchanged (same codes, fields, messages and order) with `ok=False` and `structure=None`. No
   failure is invented or re-coded, so they keep the factory's `GAME_PROJECT_STRUCTURE_` prefix. Only the bridge's own failure carries the bridge
   prefix `GAME_STRUCTURE_REQUEST_BRIDGE_`.
7. The request is never changed; no registry is used.

RESULT
The factory's own `GameProjectStructureResult` is a plain mutable holder, so it is not handed out. `GameStructureRequestBridgeResult` follows the
established Section 7 immutable result conventions: `__slots__`, read-only attributes, not subclassable, direct construction refused (TypeError),
equal contents mean equal objects and equal hashes, `failures` / `to_dict()` / `codes()` return FRESH plain data every call, copy/deepcopy return
the same object, pickling is refused.

WHAT THIS MODULE DOES NOT DO
No runtime execution, no registry, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state, and no
wiring into `process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it.
"""

from .game_project_structure import create_game_project_structure
from .game_structure_request import GameStructureRequest

FAILURE_PREFIX = "GAME_STRUCTURE_REQUEST_BRIDGE_"
FAILURE_INVALID_REQUEST = "GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST"
FAILURE_CODES = (FAILURE_INVALID_REQUEST,)

_CREATE_TOKEN = object()


class GameStructureRequestBridgeResult:
    """Immutable outcome of `create_game_project_structure_from_request()`: `structure` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_structure", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameStructureRequestBridgeResult cannot be subclassed.")

    def __init__(self, _token, structure, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_project_structure_from_request() to get a GameStructureRequestBridgeResult.")
        object.__setattr__(self, "_structure", structure)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameStructureRequestBridgeResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameStructureRequestBridgeResult is immutable.")

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
        if type(other) is not GameStructureRequestBridgeResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameStructureRequestBridgeResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameStructureRequestBridgeResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_project_structure_from_request(request):
    """Accept one exact `GameStructureRequest` and obtain a `GameProjectStructure` through the existing public
    `create_game_project_structure()` factory, passing the request's four collections (as fresh lists of the same items, same order) and
    adding no validation of its own. Deterministic, never raises for a bad `request`, runs nothing else. Returns a
    `GameStructureRequestBridgeResult`."""
    if type(request) is not GameStructureRequest:
        return GameStructureRequestBridgeResult(_CREATE_TOKEN, None, [(FAILURE_INVALID_REQUEST, "request", "request must be exactly a GameStructureRequest.")])
    produced = create_game_project_structure({"scenes": list(request.scenes), "characters": list(request.characters),
                                              "gameplay_systems": list(request.gameplay_systems), "assets": list(request.assets)})
    if produced.ok:
        return GameStructureRequestBridgeResult(_CREATE_TOKEN, produced.structure, [])
    return GameStructureRequestBridgeResult(_CREATE_TOKEN, None, [(f["code"], f["field"], f["message"]) for f in produced.failures])
