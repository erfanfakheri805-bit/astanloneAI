"""
Game Definition From Request (Prompt 742, Section 7 - Professional Game Creation)
=================================================================================
A small, explicit, caller-driven, read-only bridge from a `GameCreationRequest` to the existing `GameDefinition` layer.

    create_game_definition_from_request(request) -> GameDefinitionFromRequestResult(ok, definition, failures)
    GameDefinitionFromRequestResult.codes()   -> [code, ...]
    GameDefinitionFromRequestResult.to_dict() -> {"ok", "definition", "failures"}

DEPENDENCY DIRECTION
    GameCreationRequest -> this bridge -> the existing public factories -> GameDefinition
This module imports `GameCreationRequest` (exact-type check only) and the public factories listed below. None of those modules knows this one, and
none of them was changed. The Prompt 740 / 741 bridges are NOT imported; the same public factories they use are called directly.

WHAT THE REQUEST CONTRIBUTES (IMPORTANT)
A `GameCreationRequest` holds six project fields and NO structure, scene, character, gameplay-system, asset, composition or bundle data. This bridge
invents none. A valid request yields exactly this minimum, deterministic, EMPTY definition graph, built only through existing public factories:

    project                   create_game_project({the six request fields, unchanged})
    structure                 create_game_project_structure({"scenes": [], "characters": [], "gameplay_systems": [], "assets": []})
    scene_registry            create_game_scene_registry([])
    character_registry        create_game_character_registry([])
    gameplay_system_registry  create_gameplay_system_registry([])
    asset_registry            create_game_asset_registry([])
    composition_registry      create_game_scene_composition_registry([])
    bundle_registry           create_game_scene_bundle_registry([])
    definition                create_game_definition(project, structure, <the six registries above, in that order>)

Only the six project fields are read from the request, through its PUBLIC properties, and they are handed on unchanged (the very same str
objects). Nothing else is read, nothing is derived from any value.

BEHAVIOR
1. `request` must be exactly a `GameCreationRequest` (a subclass, look-alike, dict, `None` or any other object is rejected, nothing is coerced).
   Otherwise: `ok=False`, `definition=None`, one failure `GAME_DEFINITION_FROM_REQUEST_INVALID_REQUEST` (field "request"); no factory is called.
2. For a valid request the nine factories are called in the order above, each exactly once, through their public names. This module does no
   validation of its own and does not trim, normalize, coerce or rebuild anything.
3. Each factory's result is used only through its public `ok`, `failures` and product attribute. The FIRST stage that reports failures stops the
   chain; its failures are exposed unchanged (same codes, fields, messages and order, `source` kept when the factory gave one) with `ok=False` and
   `definition=None`. No failure is invented or re-coded, so they keep the producing factory's own prefix (GAME_PROJECT_, GAME_PROJECT_STRUCTURE_,
   GAME_*_REGISTRY_, GAME_DEFINITION_). Only this bridge's own failure carries the prefix `GAME_DEFINITION_FROM_REQUEST_`. With valid input and the
   current factories no such delegated failure can occur; the pass-through exists so a changed factory can never be hidden.
4. If every stage succeeds, the `GameDefinition` returned by `create_game_definition()` is exposed as-is (same object). The objects inside it are
   the very objects the factories returned (identity preserved; no copy, no rebuild).
5. The request is never changed. No private attribute of any object is accessed.

RESULT
`GameDefinitionFromRequestResult` follows the established Section 7 immutable result conventions: `__slots__`, read-only attributes, not
subclassable, direct construction refused (TypeError), equal contents mean equal objects and equal hashes, `failures` / `to_dict()` / `codes()` return
FRESH plain data every call, copy/deepcopy return the same object, pickling is refused. Every failure is {"code", "field", "message", "source"};
`source` is None except where `create_game_definition()` supplied one (then a fresh {"code", "field", "message"} dict).

WHAT THIS MODULE DOES NOT DO
No runtime execution, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable state, and no wiring into
`process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it.
"""

from .game_asset_registry import create_game_asset_registry
from .game_character_registry import create_game_character_registry
from .game_creation_request import GameCreationRequest
from .game_definition import create_game_definition
from .game_project import create_game_project
from .game_project_structure import create_game_project_structure
from .game_scene_bundle_registry import create_game_scene_bundle_registry
from .game_scene_composition_registry import create_game_scene_composition_registry
from .game_scene_registry import create_game_scene_registry
from .gameplay_system_registry import create_gameplay_system_registry

FAILURE_PREFIX = "GAME_DEFINITION_FROM_REQUEST_"
FAILURE_INVALID_REQUEST = "GAME_DEFINITION_FROM_REQUEST_INVALID_REQUEST"
FAILURE_CODES = (FAILURE_INVALID_REQUEST,)

_CREATE_TOKEN = object()


def _row(failure):
    source = failure.get("source")
    return (failure["code"], failure["field"], failure["message"],
            None if source is None else (source["code"], source["field"], source["message"]))


class GameDefinitionFromRequestResult:
    """Immutable outcome of `create_game_definition_from_request()`: `definition` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_definition", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameDefinitionFromRequestResult cannot be subclassed.")

    def __init__(self, _token, definition, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_definition_from_request() to get a GameDefinitionFromRequestResult.")
        object.__setattr__(self, "_definition", definition)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameDefinitionFromRequestResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameDefinitionFromRequestResult is immutable.")

    @property
    def ok(self):
        return self._definition is not None and not self._failures

    @property
    def definition(self):
        return self._definition

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message", "source"}` dicts (`source` is None or a fresh dict). Mutating it never affects this
        result."""
        return [{"code": c, "field": f, "message": m,
                 "source": None if s is None else {"code": s[0], "field": s[1], "message": s[2]}} for c, f, m, s in self._failures]

    def codes(self):
        return [c for c, _f, _m, _s in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "definition": self._definition.to_dict() if self._definition is not None else None, "failures": self.failures}

    def _key(self):
        return (self._definition, self._failures)

    def __eq__(self, other):
        if type(other) is not GameDefinitionFromRequestResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameDefinitionFromRequestResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameDefinitionFromRequestResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def _failed(failures):
    return GameDefinitionFromRequestResult(_CREATE_TOKEN, None, [_row(f) for f in failures])


def create_game_definition_from_request(request):
    """Accept one exact `GameCreationRequest` and obtain a new, EMPTY `GameDefinition` through the existing public factories. Only the six project
    fields are read from the request; no structure, registry or definition data is invented. Deterministic, never raises for a bad `request`, runs
    nothing else. Returns a `GameDefinitionFromRequestResult`."""
    if type(request) is not GameCreationRequest:
        return _failed([{"code": FAILURE_INVALID_REQUEST, "field": "request", "message": "request must be exactly a GameCreationRequest."}])
    project = create_game_project({"project_id": request.project_id, "name": request.name, "description": request.description,
                                   "genre": request.genre, "target_platform": request.target_platform, "version": request.version})
    if not project.ok:
        return _failed(project.failures)
    structure = create_game_project_structure({"scenes": [], "characters": [], "gameplay_systems": [], "assets": []})
    if not structure.ok:
        return _failed(structure.failures)
    scenes = create_game_scene_registry([])
    if not scenes.ok:
        return _failed(scenes.failures)
    characters = create_game_character_registry([])
    if not characters.ok:
        return _failed(characters.failures)
    gameplay_systems = create_gameplay_system_registry([])
    if not gameplay_systems.ok:
        return _failed(gameplay_systems.failures)
    assets = create_game_asset_registry([])
    if not assets.ok:
        return _failed(assets.failures)
    compositions = create_game_scene_composition_registry([])
    if not compositions.ok:
        return _failed(compositions.failures)
    bundles = create_game_scene_bundle_registry([])
    if not bundles.ok:
        return _failed(bundles.failures)
    produced = create_game_definition(project.project, structure.structure, scenes.registry, characters.registry, gameplay_systems.registry,
                                      assets.registry, compositions.registry, bundles.registry)
    if not produced.ok:
        return _failed(produced.failures)
    return GameDefinitionFromRequestResult(_CREATE_TOKEN, produced.definition, [])
