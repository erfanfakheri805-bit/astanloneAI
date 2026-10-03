"""
Game Character Foundation (Prompt 723, Section 7 - Professional Game Creation)
===========================================================================
A small, immutable, in-memory record of the BASIC METADATA of one game character:

    create_game_character(data) -> GameCharacterResult(ok, character, failures)
    GameCharacter.to_dict()     -> {"character_id", "name", "description", "role"}

`data` is a plain `dict` holding exactly the four fields below. Nothing else is accepted.

    character_id  str, not empty / not blank
    name          str, not empty / not blank
    description   str, may be empty
    role          str, not empty / not blank (any text; no fixed role list)

RULES
- All four fields must be present (no defaults are invented) and every value must be exactly a `str` (a `str` subclass or any other type is
  rejected, so no caller-supplied method is ever run). "Not blank" means `value.strip() != ""`; values are NEVER trimmed, lower-cased or
  otherwise changed - what the caller supplied is what is stored.
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- `create_game_character()` never raises for bad data: it reports every problem at once, in a fixed order (input, unexpected fields sorted by
  name, then the four fields in the order above), using stable codes from `FAILURE_CODES`. The caller's dict is only read, never changed.
- Direct `GameCharacter(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
- `__slots__`, attribute assignment/deletion raises, not subclassable. Equal data means equal objects and equal hashes; `to_dict()` returns a
  FRESH plain dict in a fixed field order on every call (the JSON-safe serialization). copy/deepcopy return the same object; pickling is
  refused (`to_dict()` is the only serialization).

WHAT THIS MODULE DOES NOT DO
It describes no character capabilities: no health, stats, abilities, inventory, weapons, AI behavior, dialogue, animation, skeletal data,
2D/3D models, textures, audio or rendering, and nothing engine-specific. It is not linked to `GameProject`, `GameProjectStructure` or
`GameScene` and does not check that a character id appears in a structure. No
filesystem, network, subprocess, database, AI model or external service, no clock or randomness, no module-level mutable state, no registry.
Imports nothing at all and is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("character_id", "name", "description", "role")
REQUIRED_NON_BLANK = ("character_id", "name", "role")

FAILURE_INVALID_INPUT = "GAME_CHARACTER_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_CHARACTER_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_CHARACTER_MISSING_FIELD"
FAILURE_INVALID_CHARACTER_ID = "GAME_CHARACTER_INVALID_CHARACTER_ID"
FAILURE_INVALID_NAME = "GAME_CHARACTER_INVALID_NAME"
FAILURE_INVALID_DESCRIPTION = "GAME_CHARACTER_INVALID_DESCRIPTION"
FAILURE_INVALID_ROLE = "GAME_CHARACTER_INVALID_ROLE"

_INVALID_CODES = (FAILURE_INVALID_CHARACTER_ID, FAILURE_INVALID_NAME, FAILURE_INVALID_DESCRIPTION, FAILURE_INVALID_ROLE)   # aligned with FIELDS
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD) + _INVALID_CODES

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameCharacter:
    """Immutable data record of one game character's basic metadata. Obtain it only from `create_game_character()`."""

    __slots__ = ("_character_id", "_name", "_description", "_role")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameCharacter cannot be subclassed.")

    def __init__(self, _token, character_id, name, description, role):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_character() to build a GameCharacter.")
        object.__setattr__(self, "_character_id", character_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_description", description)
        object.__setattr__(self, "_role", role)

    def __setattr__(self, key, value):
        raise AttributeError("GameCharacter is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameCharacter is immutable.")

    @property
    def character_id(self):
        return self._character_id

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def role(self):
        return self._role

    def to_dict(self):
        """A fresh plain dict (fixed field order, JSON-safe). Mutating it never affects this character."""
        return {"character_id": self._character_id, "name": self._name, "description": self._description, "role": self._role}

    def _key(self):
        return (self._character_id, self._name, self._description, self._role)

    def __eq__(self, other):
        if type(other) is not GameCharacter:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameCharacter is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameCharacter(character_id=%r, name=%r, role=%r)" % (self._character_id, self._name, self._role)


class GameCharacterResult:
    """Outcome of `create_game_character()`: `character` is set only when `ok`."""

    __slots__ = ("character", "failures")

    def __init__(self, character=None, failures=None):
        self.character = character
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.character is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "character": self.character.to_dict() if self.character is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_game_character(data):
    """Validate `data` (a plain dict with exactly the four GameCharacter fields) and build an immutable `GameCharacter`.
    Deterministic, never raises for bad data, reads `data` without changing it. Returns a `GameCharacterResult`."""
    if type(data) is not dict:
        return GameCharacterResult(failures=[_failure(FAILURE_INVALID_INPUT, "Game character data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Game character data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected game character field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing game character field: %s." % field, field))
            continue
        value = data[field]
        if type(value) is not str:
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must be a str." % field, field))
        elif field in REQUIRED_NON_BLANK and value.strip() == "":
            failures.append(_failure(_INVALID_CODES[FIELDS.index(field)], "%s must not be empty or blank." % field, field))
    if failures:
        return GameCharacterResult(failures=failures)
    return GameCharacterResult(character=GameCharacter(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
