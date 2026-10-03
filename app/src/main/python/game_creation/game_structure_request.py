"""
Game Structure Request (Prompt 743, Section 7 - Professional Game Creation)
==========================================================================
A small, immutable request model: the STRUCTURE DATA a caller hands over for a game (which scenes, characters, gameplay systems and assets it
should contain). It only checks and holds the four collections; it creates no project, structure or definition.

    create_game_structure_request(data) -> GameStructureRequestResult(ok, request, failures)
    GameStructureRequestResult.codes()   -> [code, ...]
    GameStructureRequestResult.to_dict() -> {"ok", "request", "failures"}
    GameStructureRequest.to_dict()       -> {"scenes", "characters", "gameplay_systems", "assets"}   (fresh lists)

`data` is an exact plain `dict` holding exactly the four fields below. Nothing else is accepted.

    scenes, characters, gameplay_systems, assets    each an exact `list` or exact `tuple` of identifier strings

RULES
- All four fields are required (nothing is defaulted). Each value must be exactly a `list` or exactly a `tuple` (any subclass, including a
  namedtuple, and every other type is rejected). Empty collections are valid.
- Every item must be exactly a `str` that is not empty and not whitespace-only. Items must be unique within their own collection; the same
  item may appear in different collections. Comparison is exact: "A" and "a", or "a" and " a", are different items.
- Values are NEVER trimmed, normalized, casefolded, coerced, rewritten or deduplicated. Input order is preserved; the request holds the very
  string objects that were supplied, in a fresh tuple per field.
- Unexpected fields are rejected, never ignored. Missing fields are rejected. A non-dict `data`, including any dict subclass, is rejected.
- `create_game_structure_request()` never raises for bad data. It reports every problem at once in a fixed order (input; then unexpected
  fields sorted by name; then the four fields in the order above, each: missing, or wrong collection type, or its items in position order)
  using the stable codes below. The caller's dict and collections are only read.

FAILURE CODES (prefix GAME_STRUCTURE_REQUEST_)
INVALID_INPUT, UNEXPECTED_FIELD, MISSING_FIELD, INVALID_COLLECTION, INVALID_ITEM, DUPLICATE_ITEM.
Every failure is {"code", "field", "message"} (`field` is None when no single field applies). For an item problem the message names the item
position. A duplicate is reported at every later occurrence of an item already seen in that collection (only valid items take part).

IMMUTABLE AND DETERMINISTIC
`GameStructureRequest` and `GameStructureRequestResult` use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be
constructed directly (TypeError). Equal contents mean equal objects and equal hashes. `to_dict()`, `failures` and `codes()` return FRESH plain
data on every call. copy/deepcopy return the same object; pickling is refused.

INDEPENDENT
This module imports nothing. It does not create or depend on any project, structure, definition, registry, validator, query, summary or count
object, and no existing module knows it. It has no module-level mutable state, no filesystem, network, database, AI model, clock or randomness,
and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("scenes", "characters", "gameplay_systems", "assets")

FAILURE_INVALID_INPUT = "GAME_STRUCTURE_REQUEST_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_STRUCTURE_REQUEST_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_STRUCTURE_REQUEST_MISSING_FIELD"
FAILURE_INVALID_COLLECTION = "GAME_STRUCTURE_REQUEST_INVALID_COLLECTION"
FAILURE_INVALID_ITEM = "GAME_STRUCTURE_REQUEST_INVALID_ITEM"
FAILURE_DUPLICATE_ITEM = "GAME_STRUCTURE_REQUEST_DUPLICATE_ITEM"

FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD, FAILURE_INVALID_COLLECTION,
                 FAILURE_INVALID_ITEM, FAILURE_DUPLICATE_ITEM)

_CREATE_TOKEN = object()


class GameStructureRequest:
    """Immutable data record of the structure collections requested for a game. Obtain it only from `create_game_structure_request()`."""

    __slots__ = ("_scenes", "_characters", "_gameplay_systems", "_assets")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameStructureRequest cannot be subclassed.")

    def __init__(self, _token, scenes, characters, gameplay_systems, assets):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_structure_request() to build a GameStructureRequest.")
        object.__setattr__(self, "_scenes", scenes)
        object.__setattr__(self, "_characters", characters)
        object.__setattr__(self, "_gameplay_systems", gameplay_systems)
        object.__setattr__(self, "_assets", assets)

    def __setattr__(self, key, value):
        raise AttributeError("GameStructureRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameStructureRequest is immutable.")

    @property
    def scenes(self):
        return self._scenes

    @property
    def characters(self):
        return self._characters

    @property
    def gameplay_systems(self):
        return self._gameplay_systems

    @property
    def assets(self):
        return self._assets

    def to_dict(self):
        """A fresh plain dict of fresh lists (fixed field order, JSON-safe). Mutating it never affects this request."""
        return {"scenes": list(self._scenes), "characters": list(self._characters),
                "gameplay_systems": list(self._gameplay_systems), "assets": list(self._assets)}

    def _key(self):
        return (self._scenes, self._characters, self._gameplay_systems, self._assets)

    def __eq__(self, other):
        if type(other) is not GameStructureRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameStructureRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameStructureRequest(scenes=%d, characters=%d, gameplay_systems=%d, assets=%d)" % (
            len(self._scenes), len(self._characters), len(self._gameplay_systems), len(self._assets))


class GameStructureRequestResult:
    """Immutable outcome of `create_game_structure_request()`: `request` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_request", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameStructureRequestResult cannot be subclassed.")

    def __init__(self, _token, request, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_structure_request() to get a GameStructureRequestResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameStructureRequestResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameStructureRequestResult is immutable.")

    @property
    def ok(self):
        return self._request is not None and not self._failures

    @property
    def request(self):
        return self._request

    @property
    def failures(self):
        """A fresh list of fresh `{"code", "field", "message"}` dicts. Mutating it never affects this result."""
        return [{"code": c, "field": f, "message": m} for c, f, m in self._failures]

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        return {"ok": self.ok, "request": self._request.to_dict() if self._request is not None else None, "failures": self.failures}

    def _key(self):
        return (self._request, self._failures)

    def __eq__(self, other):
        if type(other) is not GameStructureRequestResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameStructureRequestResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameStructureRequestResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def _check_collection(field, items, failures):
    """Append every problem found in one present collection to `failures`. Only reads `items`."""
    if type(items) is not list and type(items) is not tuple:
        failures.append((FAILURE_INVALID_COLLECTION, field, "%s must be a list or a tuple." % field))
        return
    seen = set()
    for index, item in enumerate(items):
        if type(item) is not str:
            failures.append((FAILURE_INVALID_ITEM, field, "%s item %d must be a str." % (field, index)))
        elif item.strip() == "":
            failures.append((FAILURE_INVALID_ITEM, field, "%s item %d must not be empty or blank." % (field, index)))
        elif item in seen:
            failures.append((FAILURE_DUPLICATE_ITEM, field, "%s item %d duplicates an earlier item: %r." % (field, index, item)))
        else:
            seen.add(item)


def create_game_structure_request(data):
    """Validate `data` (an exact plain dict with exactly the four structure fields, each an exact list or tuple of unique non-blank exact
    strings) and build an immutable `GameStructureRequest` holding the supplied strings unchanged, in order, as tuples. Deterministic, never
    raises for bad data, reads `data` without changing it, creates no project or structure. Returns a `GameStructureRequestResult`."""
    if type(data) is not dict:
        return GameStructureRequestResult(_CREATE_TOKEN, None, [(FAILURE_INVALID_INPUT, None, "Game structure request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append((FAILURE_UNEXPECTED_FIELD, None, "Game structure request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append((FAILURE_UNEXPECTED_FIELD, key, "Unexpected game structure request field: %r." % key))
    for field in FIELDS:
        if field not in data:
            failures.append((FAILURE_MISSING_FIELD, field, "Missing game structure request field: %s." % field))
        else:
            _check_collection(field, data[field], failures)
    if failures:
        return GameStructureRequestResult(_CREATE_TOKEN, None, failures)
    return GameStructureRequestResult(_CREATE_TOKEN, GameStructureRequest(_CREATE_TOKEN, *(tuple(data[f]) for f in FIELDS)), [])
