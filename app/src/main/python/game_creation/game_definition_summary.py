"""
Game Definition Summary (Prompt 737, Section 7 - Professional Game Creation)
===========================================================================
A small read-only summary of one `GameDefinition` (Prompt 734): its project plus how many entries each registry holds.

    build_game_definition_summary(game_definition) -> GameDefinitionSummaryResult(ok, summary, failures)
    GameDefinitionSummaryResult.to_dict()          -> {"ok", "summary", "failures"}

`summary` (a FRESH dict on every access, only when `ok`) has exactly these keys:
    "project"                - the `GameDefinition.project` object itself (identity preserved)
    "scene_count"            - len(game_definition.scene_registry.scenes)
    "character_count"        - len(game_definition.character_registry.characters)
    "gameplay_system_count"  - len(game_definition.gameplay_system_registry.gameplay_system_ids)
    "asset_count"            - len(game_definition.asset_registry.assets)
    "composition_count"      - len(game_definition.composition_registry.compositions)
    "bundle_count"           - len(game_definition.bundle_registry.bundles)
Counts come only from the public tuple properties the registries already expose; nothing is scanned, sorted, re-validated or copied, and no
private attribute is read. In `to_dict()` the project appears as `project.to_dict()` (fresh plain data); every value is plain data.

FAILURES
`game_definition` must be exactly a `GameDefinition`. Anything else gives ok=False, summary=None and one failure
{"code": "GAME_DEFINITION_SUMMARY_INVALID_GAME_DEFINITION", "field": "game_definition", "message": ...}. The function never raises for an
invalid argument and mutates nothing.

IMMUTABLE AND DETERMINISTIC
The result uses `__slots__`, refuses assignment and deletion, cannot be subclassed or constructed directly (TypeError). Equal contents mean equal
results and equal hashes. `summary`, `failures` and `to_dict()` return FRESH containers each call, so no returned mutable structure aliases
internal state (the project object itself is the one intentional shared reference, and it is immutable). copy/deepcopy return the same object;
pickling is refused. The module is stateless, deterministic, not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_definition import GameDefinition

FAILURE_INVALID_GAME_DEFINITION = "GAME_DEFINITION_SUMMARY_INVALID_GAME_DEFINITION"

_CREATE_TOKEN = object()


class GameDefinitionSummaryResult:
    """Immutable outcome of `build_game_definition_summary()`: `summary` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_data", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameDefinitionSummaryResult cannot be subclassed.")

    def __init__(self, _token, data, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use build_game_definition_summary() to get a GameDefinitionSummaryResult.")
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameDefinitionSummaryResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameDefinitionSummaryResult is immutable.")

    @property
    def ok(self):
        return self._data is not None and not self._failures

    @property
    def summary(self):
        """A fresh dict with exactly the seven summary keys, or None when not `ok`. Mutating it never affects this result."""
        if self._data is None:
            return None
        project, scenes, characters, systems, assets, compositions, bundles = self._data
        return {"project": project, "scene_count": scenes, "character_count": characters, "gameplay_system_count": systems,
                "asset_count": assets, "composition_count": compositions, "bundle_count": bundles}

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def to_dict(self):
        """Fresh plain data only (the project is serialized with its own `to_dict()`)."""
        summary = self.summary
        if summary is not None:
            summary["project"] = summary["project"].to_dict()
        return {"ok": self.ok, "summary": summary, "failures": self.failures}

    def _key(self):
        return (self._data, self._failures)

    def __eq__(self, other):
        if type(other) is not GameDefinitionSummaryResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameDefinitionSummaryResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameDefinitionSummaryResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def build_game_definition_summary(game_definition):
    """Summarize a `GameDefinition`: its project (by identity) and the number of entries in each of its six registries, read through their
    public tuple properties. Deterministic, never raises for an invalid argument, changes nothing it is given. Returns a
    `GameDefinitionSummaryResult`."""
    if type(game_definition) is not GameDefinition:
        return GameDefinitionSummaryResult(_CREATE_TOKEN, None, [
            (FAILURE_INVALID_GAME_DEFINITION, "game_definition", "game_definition must be exactly a GameDefinition.")])
    return GameDefinitionSummaryResult(_CREATE_TOKEN, (
        game_definition.project,
        len(game_definition.scene_registry.scenes),
        len(game_definition.character_registry.characters),
        len(game_definition.gameplay_system_registry.gameplay_system_ids),
        len(game_definition.asset_registry.assets),
        len(game_definition.composition_registry.compositions),
        len(game_definition.bundle_registry.bundles)), [])
