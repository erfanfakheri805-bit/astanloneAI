"""
Game Definition Counts (Prompt 738, Section 7 - Professional Game Creation)
==========================================================================
A small read-only count query over one `GameDefinition` (Prompt 734): how many entries each of its six registries holds.

    get_game_definition_counts(game_definition) -> GameDefinitionCountsResult(ok, counts, failures)
    GameDefinitionCountsResult.to_dict()        -> {"ok", "counts", "failures"}

`counts` (a FRESH dict on every access, only when `ok`) has exactly these keys, in this order:
    "scene_count"            - len(game_definition.scene_registry.scenes)
    "character_count"        - len(game_definition.character_registry.characters)
    "gameplay_system_count"  - len(game_definition.gameplay_system_registry.gameplay_system_ids)
    "asset_count"            - len(game_definition.asset_registry.assets)
    "composition_count"      - len(game_definition.composition_registry.compositions)
    "bundle_count"           - len(game_definition.bundle_registry.bundles)
Counts come only from the public tuple properties the registries already expose. Nothing is scanned, sorted, normalized, validated, copied or
mutated, and no private attribute is read. This layer is independent: it uses no other Section 7 query or summary API.

FAILURE
Only the argument type is checked: `game_definition` must be exactly a `GameDefinition`. Anything else gives ok=False, counts=None and one
failure {"code": "GAME_DEFINITION_COUNTS_INVALID_GAME_DEFINITION", "field": "game_definition", "message": ...}. It never raises for an invalid
argument.

IMMUTABLE AND DETERMINISTIC
The result uses `__slots__`, refuses assignment and deletion, cannot be subclassed or constructed directly (TypeError). Equal contents mean equal
results and equal hashes. `counts`, `failures` and `to_dict()` return FRESH containers on every call. copy/deepcopy return the same object;
pickling is refused. The module is stateless and deterministic, and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_definition import GameDefinition

FAILURE_INVALID_GAME_DEFINITION = "GAME_DEFINITION_COUNTS_INVALID_GAME_DEFINITION"

_CREATE_TOKEN = object()


class GameDefinitionCountsResult:
    """Immutable outcome of `get_game_definition_counts()`: `counts` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_data", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameDefinitionCountsResult cannot be subclassed.")

    def __init__(self, _token, data, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use get_game_definition_counts() to get a GameDefinitionCountsResult.")
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameDefinitionCountsResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameDefinitionCountsResult is immutable.")

    @property
    def ok(self):
        return self._data is not None and not self._failures

    @property
    def counts(self):
        """A fresh dict with exactly the six count keys, or None when not `ok`. Mutating it never affects this result."""
        if self._data is None:
            return None
        scenes, characters, systems, assets, compositions, bundles = self._data
        return {"scene_count": scenes, "character_count": characters, "gameplay_system_count": systems, "asset_count": assets,
                "composition_count": compositions, "bundle_count": bundles}

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def to_dict(self):
        """Fresh plain data. Mutating it never affects this result."""
        return {"ok": self.ok, "counts": self.counts, "failures": self.failures}

    def _key(self):
        return (self._data, self._failures)

    def __eq__(self, other):
        if type(other) is not GameDefinitionCountsResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameDefinitionCountsResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameDefinitionCountsResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def get_game_definition_counts(game_definition):
    """Count the entries in each of the six registries of a `GameDefinition`, read through their public tuple properties. Deterministic, never
    raises for an invalid argument, changes nothing it is given. Returns a `GameDefinitionCountsResult`."""
    if type(game_definition) is not GameDefinition:
        return GameDefinitionCountsResult(_CREATE_TOKEN, None, [
            (FAILURE_INVALID_GAME_DEFINITION, "game_definition", "game_definition must be exactly a GameDefinition.")])
    return GameDefinitionCountsResult(_CREATE_TOKEN, (
        len(game_definition.scene_registry.scenes),
        len(game_definition.character_registry.characters),
        len(game_definition.gameplay_system_registry.gameplay_system_ids),
        len(game_definition.asset_registry.assets),
        len(game_definition.composition_registry.compositions),
        len(game_definition.bundle_registry.bundles)), [])
