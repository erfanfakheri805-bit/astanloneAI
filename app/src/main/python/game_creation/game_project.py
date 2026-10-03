"""
Game Project Foundation (Prompt 720, Section 7 - Professional Game Creation)
=============================================================================
A small, immutable, in-memory record of the BASIC IDENTITY AND CONFIGURATION of one game project:

    create_game_project(data) -> GameProjectResult(ok, project, failures)
    GameProject.to_dict()     -> {"project_id", "name", "description", "genre", "target_platform", "version"}

`data` is a plain `dict` holding exactly the six fields below. Nothing else is accepted.

    project_id        str, not empty / not blank
    name              str, not empty / not blank
    description       str, may be empty
    genre             str (may be empty; any text, no fixed genre list)
    target_platform   str (may be empty; any text, no fixed platform list)
    version           str, not empty / not blank (any text; no version scheme is imposed)

RULES
- All six fields must be present (no defaults are invented) and every value must be exactly a `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run). "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased or
  otherwise changed - what the caller supplied is what is stored.
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_game_project()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the six fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read, never changed.
- Direct `GameProject(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call (the JSON-safe serialization). copy/deepcopy return the same object; pickling is
  refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
No engine, no code/asset generation, no rendering/audio/video, no filesystem, network, database, AI model or external service, no clock or
randomness, no module-level mutable state, no registry of projects, no code execution, no self-modification. Imports nothing at all and is not
wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
REQUIRED_NON_BLANK = ("project_id", "name", "version")

FAILURE_INVALID_INPUT = "GAME_PROJECT_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_PROJECT_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_PROJECT_MISSING_FIELD"
FAILURE_INVALID_PROJECT_ID = "GAME_PROJECT_INVALID_PROJECT_ID"
FAILURE_INVALID_NAME = "GAME_PROJECT_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "GAME_PROJECT_INVALID_DESCRIPTION"
FAILURE_INVALID_GENRE = "GAME_PROJECT_INVALID_GENRE"
FAILURE_INVALID_TARGET_PLATFORM = "GAME_PROJECT_INVALID_TARGET_PLATFORM"
FAILURE_INVALID_VERSION = "GAME_PROJECT_INVALID_VERSION"

_INVALID_CODES = (FAILURE_INVALID_PROJECT_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION,          # aligned with FIELDS
                  FAILURE_INVALID_GENRE, FAILURE_INVALID_TARGET_PLATFORM, FAILURE_INVALID_VERSION)
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameProject:
    """Immutable data record of one game project's identity and configuration. Obtain it only from `create_game_project()`."""

    __slots__ = ("_project_id", "_name", "_description", "_genre", "_target_platform", "_version")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameProject cannot be subclassed.")

    def __init__(self, _token, project_id, name, description, genre, target_platform, version):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_project() to build a GameProject.")
        object.__setattr__(self, "_project_id", project_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_genre", genre)
        object.__setattr__(self, "_target_platform", target_platform)
        object.__setattr__(self, "_version", version)

    def __setattr__(self, key, value):
        raise AttributeError("GameProject is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameProject is immutable.")

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
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this project."""
        return {"project_id": self._project_id, "name": self._name, "description": self._description, "genre": self._genre,
                "target_platform": self._target_platform, "version": self._version}

    def _key(self):
        return (self._project_id, self._name, self._description, self._genre, self._target_platform, self._version)

    def __eq__(self, other):
        if type(other) is not GameProject:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameProject is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameProject(project_id=%r, name=%r, version=%r)" % (self._project_id, self._name, self._version)


class GameProjectResult:
    """Outcome of `create_game_project()`: `project` is set only when `ok`."""

    __slots__ = ("project", "failures")

    def __init__(self, project=None, failures=None):
        self.project = project
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.project is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "project": self.project.to_dict() if self.project is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_game_project(data):
    """Validate `data` (a plain dict with exactly the six GameProject fields) and build an immutable `GameProject`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `GameProjectResult`."""
    if type(data) is not dict:
        return GameProjectResult(failures=[_failure(FAILURE_INVALID_INPUT, "Game project data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Game project data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected game project field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing game project field: %s." % field, field))
            continue
        value = data[field]
        if type(value) is not str:
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must be a str." % field, field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must not be empty or blank." % field, field))
    if failures:
        return GameProjectResult(failures=failures)
    return GameProjectResult(project=GameProject(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
