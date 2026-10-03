"""
Game Structure Registries From Request (Prompt 745, Section 7 - Professional Game Creation)
==========================================================================================
A small, explicit, caller-driven, read-only bridge from a `GameStructureRequest` to the four existing registry factories.

    create_game_structure_registries_from_request(request) -> GameStructureRegistriesFromRequestResult(ok, registries, failures)
    GameStructureRegistriesFromRequestResult.codes()   -> [code, ...]
    GameStructureRegistriesFromRequestResult.to_dict() -> {"ok", "registries", "failures"}

DEPENDENCY DIRECTION
    GameStructureRequest -> this bridge -> create_game_scene_registry / create_game_character_registry
                                           / create_gameplay_system_registry / create_game_asset_registry
This module imports `GameStructureRequest` (exact-type check only) and the four public registry factories. None of those modules knows this
one, and none of them was changed. It does not use `GameProjectStructure`, so the factories' optional `structure` argument is never passed.

BEHAVIOR
1. `request` must be exactly a `GameStructureRequest` (a subclass, look-alike, mock, dict, `None` or any other object is rejected, nothing is
   coerced). Otherwise: `ok=False`, `registries=None`, one failure `GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST` (field
   "request"), and NO factory is called.
2. For a valid request exactly four factories are called, each at most once, strictly in this order, each with one positional argument (the
   matching public request property: `scenes`, `characters`, `gameplay_systems`, `assets`):
       create_game_scene_registry -> create_game_character_registry -> create_gameplay_system_registry -> create_game_asset_registry
   Only those four public properties are read, each right before its own factory call. No private attribute is read.
3. CONTAINERS: the request stores each collection as a `tuple`, and all four factories accept an exact `list` OR an exact `tuple`. Nothing
   therefore needs adapting, so the request's own immutable tuples are passed straight through; no list is built and no item is copied.
4. This module does no validation of its own. Whatever a factory decides stands. Items are never normalized, trimmed, reordered,
   deduplicated, filtered or coerced.
5. SHORT-CIRCUIT: if a factory reports failures, the failures of that FIRST failing factory are exposed unchanged (same codes, fields, messages
   and order) with `ok=False` and `registries=None`, and no later factory is called. No failure is invented or re-coded, so they keep the
   factory's own prefix. Only the bridge's own failure carries the prefix `GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_`.
6. If all four factories succeed, the very registry objects they returned are exposed (identity preserved), under exactly the keys
   `scene_registry`, `character_registry`, `gameplay_system_registry`, `asset_registry`.
7. The request and the factories are never changed.

WHAT THE REQUEST CAN AND CANNOT BUILD (IMPORTANT)
A `GameStructureRequest` holds identifier STRINGS only. The gameplay-system registry is itself a registry of identifier strings, but the scene,
character and asset registries are registries of `GameScene`, `GameCharacter` and `GameAsset` record objects. This bridge deliberately turns no
string into a record (that would be inventing data), so a request with at least one scene, character or asset identifier makes the matching
factory report its own invalid-item failure, and that failure is returned unchanged. A request whose scenes, characters and assets are empty
(gameplay systems may be any valid identifiers) builds all four registries.

RESULT
The factories' own results are plain mutable holders, so they are not handed out. `GameStructureRegistriesFromRequestResult` follows the
established Section 7 immutable result conventions: `__slots__`, read-only attributes, not subclassable, direct construction refused
(TypeError), equal contents mean equal objects and equal hashes, `registries` / `failures` / `to_dict()` / `codes()` return FRESH plain
containers every call (the registry objects inside are themselves immutable and are the very objects the factories returned), copy/deepcopy
return the same object, pickling is refused.

WHAT THIS MODULE DOES NOT DO
No runtime execution, no composition or bundle, no filesystem, network, database or AI access, no clock or randomness, no module-level mutable
state, and no wiring into `process_input()`, Core, the Planner or the Agent Loop. It runs only when a caller calls it.
"""

from .game_asset_registry import create_game_asset_registry
from .game_character_registry import create_game_character_registry
from .game_scene_registry import create_game_scene_registry
from .game_structure_request import GameStructureRequest
from .gameplay_system_registry import create_gameplay_system_registry

FAILURE_PREFIX = "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_"
FAILURE_INVALID_REQUEST = "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST"
FAILURE_CODES = (FAILURE_INVALID_REQUEST,)

REGISTRY_KEYS = ("scene_registry", "character_registry", "gameplay_system_registry", "asset_registry")

_CREATE_TOKEN = object()


class GameStructureRegistriesFromRequestResult:
    """Immutable outcome of `create_game_structure_registries_from_request()`: `registries` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_registries", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameStructureRegistriesFromRequestResult cannot be subclassed.")

    def __init__(self, _token, registries, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_structure_registries_from_request() to get a GameStructureRegistriesFromRequestResult.")
        object.__setattr__(self, "_registries", None if registries is None else tuple(registries))
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameStructureRegistriesFromRequestResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameStructureRegistriesFromRequestResult is immutable.")

    @property
    def ok(self):
        return self._registries is not None and not self._failures

    @property
    def registries(self):
        """`None` unless `ok`; otherwise a FRESH dict with exactly the four registry keys, holding the registry objects the factories returned."""
        if self._registries is None:
            return None
        return dict(zip(REGISTRY_KEYS, self._registries))

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        registries = None
        if self._registries is not None:
            registries = {key: registry.to_dict() for key, registry in zip(REGISTRY_KEYS, self._registries)}
        return {"ok": self.ok, "registries": registries, "failures": self.failures}

    def _key(self):
        return (self._registries, self._failures)

    def __eq__(self, other):
        if type(other) is not GameStructureRegistriesFromRequestResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameStructureRegistriesFromRequestResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameStructureRegistriesFromRequestResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def _failed(produced):
    return GameStructureRegistriesFromRequestResult(_CREATE_TOKEN, None, [(f["code"], f["field"], f["message"]) for f in produced.failures])


def create_game_structure_registries_from_request(request):
    """Accept one exact `GameStructureRequest` and build the scene, character, gameplay-system and asset registries (in that order) through the
    four existing public factories, passing the request's four collections unchanged and adding no validation of its own. Stops at the first
    factory that fails and returns that factory's failures unchanged. Deterministic, never raises for a bad `request`, runs nothing else.
    Returns a `GameStructureRegistriesFromRequestResult`."""
    if type(request) is not GameStructureRequest:
        return GameStructureRegistriesFromRequestResult(
            _CREATE_TOKEN, None, [(FAILURE_INVALID_REQUEST, "request", "request must be exactly a GameStructureRequest.")])
    scene = create_game_scene_registry(request.scenes)
    if not scene.ok:
        return _failed(scene)
    character = create_game_character_registry(request.characters)
    if not character.ok:
        return _failed(character)
    gameplay_system = create_gameplay_system_registry(request.gameplay_systems)
    if not gameplay_system.ok:
        return _failed(gameplay_system)
    asset = create_game_asset_registry(request.assets)
    if not asset.ok:
        return _failed(asset)
    return GameStructureRegistriesFromRequestResult(
        _CREATE_TOKEN, (scene.registry, character.registry, gameplay_system.registry, asset.registry), [])
