"""
Game Scene Foundation (Prompt 722, Section 7 - Professional Game Creation)
==========================================================================
A small, immutable, in-memory record of the BASIC METADATA of one game scene:

    create_game_scene(data) -> GameSceneResult(ok, scene, failures)
    GameScene.to_dict()     -> {"scene_id", "name", "description", "scene_type"}

`data` is a plain `dict` holding exactly the four fields below. Nothing else is accepted.

    scene_id     str, not empty / not blank
    name         str, not empty / not blank
    description  str, may be empty
    scene_type   str, not empty / not blank (any text; no fixed scene-type list)

RULES
- All four fields must be present (no defaults are invented) and every value must be exactly a `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run). "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased or
  otherwise changed - what the caller supplied is what is stored.
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_game_scene()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the four fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read, never changed.
- Direct `GameScene(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call (the JSON-safe serialization). copy/deepcopy return the same object; pickling is
  refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
It describes no scene content: no objects/entities, transforms, maps, lighting, physics, AI, scripting, rendering or assets, and nothing
engine-specific. It is not linked to `GameProject` or `GameProjectStructure` and does not check that a scene id appears in a structure. No
filesystem, network, subprocess, database, AI model or external service, no clock or randomness, no module-level mutable state, no registry.
Imports nothing at all and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("scene_id", "name", "description", "scene_type")
REQUIRED_NON_BLANK = ("scene_id", "name", "scene_type")

FAILURE_INVALID_INPUT = "GAME_SCENE_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_SCENE_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_SCENE_MISSING_FIELD"
FAILURE_INVALID_SCENE_ID = "GAME_SCENE_INVALID_SCENE_ID"
FAILURE_INVALID_NAME = "GAME_SCENE_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "GAME_SCENE_INVALID_DESCRIPTION"
FAILURE_INVALID_SCENE_TYPE = "GAME_SCENE_INVALID_SCENE_TYPE"

_INVALID_CODES = (FAILURE_INVALID_SCENE_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION, FAILURE_INVALID_SCENE_TYPE)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameScene:
    """Immutable data record of one game scene's basic metadata. Obtain it only from `create_game_scene()`."""

    __slots__ = ("_scene_id", "_name", "_description", "_scene_type")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameScene cannot be subclassed.")

    def __init__(self, _token, scene_id, name, description, scene_type):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene() to build a GameScene.")
        object.__setattr__(self, "_scene_id", scene_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_scene_type", scene_type)

    def __setattr__(self, key, value):
        raise AttributeError("GameScene is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameScene is immutable.")

    @property
    def scene_id(self):
        return self._scene_id

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def scene_type(self):
        return self._scene_type

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this scene."""
        return {"scene_id": self._scene_id, "name": self._name, "description": self._description, "scene_type": self._scene_type}

    def _key(self):
        return (self._scene_id, self._name, self._description, self._scene_type)

    def __eq__(self, other):
        if type(other) is not GameScene:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameScene is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameScene(scene_id=%r, name=%r, scene_type=%r)" % (self._scene_id, self._name, self._scene_type)


class GameSceneResult:
    """Outcome of `create_game_scene()`: `scene` is set only when `ok`."""

    __slots__ = ("scene", "failures")

    def __init__(self, scene=None, failures=None):
        self.scene = scene
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.scene is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "scene": self.scene.to_dict() if self.scene is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_game_scene(data):
    """Validate `data` (a plain dict with exactly the four GameScene fields) and build an immutable `GameScene`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `GameSceneResult`."""
    if type(data) is not dict:
        return GameSceneResult(failures=[_failure(FAILURE_INVALID_INPUT, "Game scene data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Game scene data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected game scene field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing game scene field: %s." % field, field))
            continue
        value = data[field]
        if type(value) is not str:
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must be a str." % field, field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must not be empty or blank." % field, field))
    if failures:
        return GameSceneResult(failures=failures)
    return GameSceneResult(scene=GameScene(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
