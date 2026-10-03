"""
Game Creation Request (Prompt 739, Section 7 - Professional Game Creation)
=========================================================================
A small, immutable request model: the STRUCTURED INPUT a caller hands over when asking for a new game project. It only checks and holds the
six fields; it creates no project and no other state.

    create_game_creation_request(data) -> GameCreationRequestResult(ok, request, failures)
    GameCreationRequestResult.codes()   -> [code, ...]
    GameCreationRequestResult.to_dict() -> {"ok", "request", "failures"}
    GameCreationRequest.to_dict()       -> {"project_id", "name", "description", "genre", "target_platform", "version"}

`data` is an exact plain `dict` holding exactly the six fields below. Nothing else is accepted.

    project_id        str, not empty / not whitespace-only
    name              str, not empty / not whitespace-only
    description       str, may be empty
    genre             str, may be empty
    target_platform   str, may be empty
    version           str, not empty / not whitespace-only

RULES
- All six fields are required (no defaults are invented) and every value must be exactly a `str` (a `str` subclass or any other type is
  rejected). A required value is rejected when it is empty or only whitespace; the check never changes the value. Values are NEVER trimmed,
  normalized, coerced or rewritten: the request holds the very string objects that were supplied.
- Unexpected fields are rejected, never ignored. Missing fields are rejected. A non-dict `data`, including any dict subclass, is rejected.
- `create_game_creation_request()` never raises for bad data. It reports every problem at once in a fixed order (input; then unexpected fields
  sorted by name; then the six fields in the order above), using the stable codes below. The caller's dict is only read.

FAILURE CODES (prefix GAME_CREATION_REQUEST_)
INVALID_INPUT, UNEXPECTED_FIELD, MISSING_FIELD, INVALID_PROJECT_ID, INVALID_NAME, INVALID_DESCRIPTION, INVALID_GENRE, INVALID_TARGET_PLATFORM,
INVALID_VERSION. Every failure is {"code", "field", "message"} (`field` is None when no single field applies).

IMMUTABLE AND DETERMINISTIC
`GameCreationRequest` and `GameCreationRequestResult` use `__slots__`, refuse assignment and deletion, cannot be subclassed and cannot be
constructed directly (TypeError). Equal contents mean equal objects and equal hashes. `to_dict()`, `failures` and `codes()` return FRESH plain
data on every call. copy/deepcopy return the same object; pickling is refused.

INDEPENDENT
This module imports nothing. It does not create or depend on any project, definition, registry, validator, query, summary or count object, so it
can serve as a future input boundary. It has no module-level mutable state, no filesystem, network, database, AI model, clock or randomness,
and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
REQUIRED_NON_BLANK = ("project_id", "name", "version")

FAILURE_INVALID_INPUT = "GAME_CREATION_REQUEST_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_CREATION_REQUEST_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_CREATION_REQUEST_MISSING_FIELD"
FAILURE_INVALID_PROJECT_ID = "GAME_CREATION_REQUEST_INVALID_PROJECT_ID"
FAILURE_INVALID_NAME = "GAME_CREATION_REQUEST_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "GAME_CREATION_REQUEST_INVALID_DESCRIPTION"
FAILURE_INVALID_GENRE = "GAME_CREATION_REQUEST_INVALID_GENRE"
FAILURE_INVALID_TARGET_PLATFORM = "GAME_CREATION_REQUEST_INVALID_TARGET_PLATFORM"
FAILURE_INVALID_VERSION = "GAME_CREATION_REQUEST_INVALID_VERSION"

_INVALID_CODES = (FAILURE_INVALID_PROJECT_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION,          # aligned with FIELDS
                  FAILURE_INVALID_GENRE, FAILURE_INVALID_TARGET_PLATFORM, FAILURE_INVALID_VERSION)
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


class GameCreationRequest:
    """Immutable data record of a request to create a game project. Obtain it only from `create_game_creation_request()`."""

    __slots__ = ("_project_id", "_name", "_description", "_genre", "_target_platform", "_version")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameCreationRequest cannot be subclassed.")

    def __init__(self, _token, project_id, name, description, genre, target_platform, version):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_creation_request() to build a GameCreationRequest.")
        object.__setattr__(self, "_project_id", project_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_genre", genre)
        object.__setattr__(self, "_target_platform", target_platform)
        object.__setattr__(self, "_version", version)

    def __setattr__(self, key, value):
        raise AttributeError("GameCreationRequest is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameCreationRequest is immutable.")

    @property
    def project_id(self):
        return self._project_id

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def genre(self):
        return self._genre

    @property
    def target_platform(self):
        return self._target_platform

    @property
    def version(self):
        return self._version

    def to_dict(self):
        """A fresh plain dict (fixed field order). Mutating it never affects this request."""
        return {"project_id": self._project_id, "name": self._name, "description": self._description, "genre": self._genre,
                "target_platform": self._target_platform, "version": self._version}

    def _key(self):
        return (self._project_id, self._name, self._description, self._genre, self._target_platform, self._version)

    def __eq__(self, other):
        if type(other) is not GameCreationRequest:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameCreationRequest is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameCreationRequest(project_id=%r, name=%r, version=%r)" % (self._project_id, self._name, self._version)


class GameCreationRequestResult:
    """Immutable outcome of `create_game_creation_request()`: `request` is set only when `ok`. Obtain it only from that function."""

    __slots__ = ("_request", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameCreationRequestResult cannot be subclassed.")

    def __init__(self, _token, request, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_creation_request() to get a GameCreationRequestResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("GameCreationRequestResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameCreationRequestResult is immutable.")

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
        if type(other) is not GameCreationRequestResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameCreationRequestResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameCreationRequestResult(ok=%r, failures=%d)" % (self.ok, len(self._failures))


def create_game_creation_request(data):
    """Validate `data` (an exact plain dict with exactly the six request fields) and build an immutable `GameCreationRequest` holding the
    supplied strings unchanged. Deterministic, never raises for bad data, reads `data` without changing it, creates no project. Returns a
    `GameCreationRequestResult`."""
    if type(data) is not dict:
        return GameCreationRequestResult(_CREATE_TOKEN, None, [(FAILURE_INVALID_INPUT, None, "Game creation request data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append((FAILURE_UNEXPECTED_FIELD, None, "Game creation request data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append((FAILURE_UNEXPECTED_FIELD, key, "Unexpected game creation request field: %r." % key))
    for index, field in enumerate(FIELDS):
        if field not in data:
            failures.append((FAILURE_MISSING_FIELD, field, "Missing game creation request field: %s." % field))
            continue
        value = data[field]
        if type(value) is not str:
            failures.append((_INVALID_CODES[index], field, "%s must be a str." % field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append((_INVALID_CODES[index], field, "%s must not be empty or blank." % field))
    if failures:
        return GameCreationRequestResult(_CREATE_TOKEN, None, failures)
    return GameCreationRequestResult(_CREATE_TOKEN, GameCreationRequest(_CREATE_TOKEN, *(data[f] for f in FIELDS)), [])
