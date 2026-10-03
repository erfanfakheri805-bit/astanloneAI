"""
Game Project Structure (Prompt 721, Section 7 - Professional Game Creation)
===========================================================================
A small, immutable, in-memory record of the MAIN STRUCTURAL COMPONENTS of one game project, stored as plain string identifiers only:

    create_game_project_structure(data) -> GameProjectStructureResult(ok, structure, failures)
    GameProjectStructure.to_dict()      -> {"scenes": [...], "characters": [...], "gameplay_systems": [...], "assets": [...]}

`data` is a plain `dict` holding exactly the four fields below. Nothing else is accepted.

    scenes              list of identifiers
    characters          list of identifiers
    gameplay_systems    list of identifiers
    assets              list of identifiers

RULES
- All four fields must be present (no defaults are invented) and each must be exactly a `list` (a tuple, set, generator, `list` subclass or
  any other type is rejected - nothing is coerced). An empty list is valid.
- Every item must be exactly a `str` (a `str` subclass or any other type is rejected, so no caller-supplied method is ever run). An item is
  rejected when it is blank (`item.strip() == ""`). Identifiers are NEVER trimmed, lower-cased or otherwise changed; two identifiers are
  duplicates only when they are exactly equal, and duplicates are rejected within each collection (the same identifier may appear in two
  different collections - they are separate namespaces).
- Input order is preserved exactly.
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_game_project_structure()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields
  sorted by name, then the four fields in the order above, items by position), using stable codes from `FAILURE_CODES`. The caller's dict and
  lists are only read, never changed.
- Direct `GameProjectStructure(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- Each collection is stored as a tuple (copied from the caller's list, so later edits to the input never reach the structure) and returned as
  that same immutable tuple by its accessor. `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal
  objects and equal hashes; `to_dict()` returns FRESH plain dict/lists in a fixed field order on every call (the JSON-safe serialization) and
  `create_game_project_structure(s.to_dict())` rebuilds an equal structure. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
It defines no scene, character, gameplay-system or asset object - only identifiers. It does not link to `GameProject`, check that identifiers
refer to anything, generate code or assets, or touch an engine. No filesystem, network, database, AI model or external service, no clock or
randomness, no module-level mutable state, no registry. Imports nothing at all and is not wired into `process_input()`, Core, the Planner or
the Agent Loop.
"""

FIELDS = ("scenes", "characters", "gameplay_systems", "assets")

FAILURE_INVALID_INPUT = "GAME_PROJECT_STRUCTURE_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_PROJECT_STRUCTURE_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_PROJECT_STRUCTURE_MISSING_FIELD"
FAILURE_INVALID_COLLECTION = "GAME_PROJECT_STRUCTURE_INVALID_COLLECTION"
FAILURE_INVALID_IDENTIFIER_TYPE = "GAME_PROJECT_STRUCTURE_INVALID_IDENTIFIER_TYPE"
FAILURE_BLANK_IDENTIFIER = "GAME_PROJECT_STRUCTURE_BLANK_IDENTIFIER"
FAILURE_DUPLICATE_IDENTIFIER = "GAME_PROJECT_STRUCTURE_DUPLICATE_IDENTIFIER"

FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD, FAILURE_INVALID_COLLECTION,
                 FAILURE_INVALID_IDENTIFIER_TYPE, FAILURE_BLANK_IDENTIFIER, FAILURE_DUPLICATE_IDENTIFIER)

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameProjectStructure:
    """Immutable record of a game project's scene, character, gameplay-system and asset identifiers. Obtain it only from
    `create_game_project_structure()`."""

    __slots__ = ("_scenes", "_characters", "_gameplay_systems", "_assets")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameProjectStructure cannot be subclassed.")

    def __init__(self, _token, scenes, characters, gameplay_systems, assets):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_project_structure() to build a GameProjectStructure.")
        object.__setattr__(self, "_scenes", tuple(scenes))
        object.__setattr__(self, "_characters", tuple(characters))
        object.__setattr__(self, "_gameplay_systems", tuple(gameplay_systems))
        object.__setattr__(self, "_assets", tuple(assets))

    def __setattr__(self, key, value):
        raise AttributeError("GameProjectStructure is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameProjectStructure is immutable.")

    @property
    def scenes(self):
        """Tuple of scene identifiers, in input order."""
        return self._scenes

    @property
    def characters(self):
        """Tuple of character identifiers, in input order."""
        return self._characters

    @property
    def gameplay_systems(self):
        """Tuple of gameplay-system identifiers, in input order."""
        return self._gameplay_systems

    @property
    def assets(self):
        """Tuple of asset identifiers, in input order."""
        return self._assets

    def to_dict(self):
        """A fresh plain dict of fresh lists (fixed field order, JSON-safe). Mutating it never affects this structure."""
        return {"scenes": list(self._scenes), "characters": list(self._characters),
                "gameplay_systems": list(self._gameplay_systems), "assets": list(self._assets)}

    def _key(self):
        return (self._scenes, self._characters, self._gameplay_systems, self._assets)

    def __eq__(self, other):
        if type(other) is not GameProjectStructure:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameProjectStructure is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameProjectStructure(scenes=%d, characters=%d, gameplay_systems=%d, assets=%d)" % (
            len(self._scenes), len(self._characters), len(self._gameplay_systems), len(self._assets))


class GameProjectStructureResult:
    """Outcome of `create_game_project_structure()`: `structure` is set only when `ok`."""

    __slots__ = ("structure", "failures")

    def __init__(self, structure=None, failures=None):
        self.structure = structure
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.structure is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "structure": self.structure.to_dict() if self.structure is not None else None,
                "failures": [dict(f) for f in self.failures]}


def _check_collection(field, items, failures):
    """Append every problem found in one collection to `failures`."""
    if type(items) is not list:
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "%s must be a list." % field, field))
        return
    seen = set()
    for index, item in enumerate(items):
        if type(item) is not str:
            failures.append(_failure(FAILURE_INVALID_IDENTIFIER_TYPE, "%s[%d] must be a str." % (field, index), field))
        elif item.strip() == "":
            failures.append(_failure(FAILURE_BLANK_IDENTIFIER, "%s[%d] must not be empty or blank." % (field, index), field))
        elif item in seen:
            failures.append(_failure(FAILURE_DUPLICATE_IDENTIFIER, "%s[%d] duplicates an earlier identifier: %r." % (field, index, item), field))
        else:
            seen.add(item)


def create_game_project_structure(data):
    """Validate `data` (a plain dict with exactly the four structure fields, each a list of unique non-blank str identifiers) and build an
    immutable `GameProjectStructure`. Deterministic, never raises for bad data, reads `data` without changing it. Returns a
    `GameProjectStructureResult`."""
    if type(data) is not dict:
        return GameProjectStructureResult(failures=[_failure(FAILURE_INVALID_INPUT, "Game project structure data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Game project structure data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected game project structure field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing game project structure field: %s." % field, field))
            continue
        _check_collection(field, data[field], failures)
    if failures:
        return GameProjectStructureResult(failures=failures)
    return GameProjectStructureResult(structure=GameProjectStructure(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
