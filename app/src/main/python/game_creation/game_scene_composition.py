"""
Game Scene Composition (Prompt 729, Section 7 - Professional Game Creation)
===========================================================================
A small, immutable, in-memory record of WHICH characters, assets and gameplay systems belong to one scene, stored as plain string identifiers only:

    create_game_scene_composition(data) -> GameSceneCompositionResult(ok, composition, failures)
    GameSceneComposition.to_dict()      -> {"scene_id", "character_ids", "asset_ids", "gameplay_system_ids"}

`data` is a plain `dict` holding exactly the four fields below. Nothing else is accepted.

    scene_id              str, not empty / not blank
    character_ids         list or tuple of identifiers
    asset_ids             list or tuple of identifiers
    gameplay_system_ids   list or tuple of identifiers

RULES
- All four fields must be present (no defaults are invented). `scene_id` must be exactly a `str`. Each of the three collections must be exactly a
  `list` or a `tuple` (a set, dict, generator, string or any subclass is rejected - nothing is coerced). An empty collection is valid.
- Every item must be exactly a `str` and not blank (`item.strip() != ""`). Identifiers are NEVER trimmed, lower-cased or otherwise changed, and
  order is preserved exactly. Duplicates are rejected within each collection by exact comparison; the same identifier may appear in two different
  collections (they are separate namespaces).
- Unexpected fields are rejected, never ignored. A non-dict `data` (including a dict subclass) is rejected.
- The identifiers are NOT resolved: nothing checks that a scene, character, asset or gameplay system with that id exists, and this module does
  not import any registry or the project validator. It only describes references.
- `create_game_scene_composition()` never raises for bad data: it reports every problem at once in a fixed order (input, unexpected fields sorted
  by name, missing fields in field order, `scene_id`, then `character_ids` and its items, `asset_ids` and its items, `gameplay_system_ids` and its
  items), using stable codes from `FAILURE_CODES`. A missing field is reported once and not checked further. The caller's dict and collections
  are only read, never changed.
- Direct `GameSceneComposition(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

IMMUTABLE AND DETERMINISTIC
Each collection is stored as a tuple (copied from the caller's collection, so later edits never reach the composition) and returned as that same
immutable tuple. `__slots__`, assignment/deletion raises, not subclassable. Equal data means equal objects and hashes (a different order is a
different composition); `to_dict()` returns FRESH plain data (lists) in a fixed field order on every call, and
`create_game_scene_composition(c.to_dict())` rebuilds an equal composition. copy/deepcopy return the same object; pickling is refused.

WHAT THIS MODULE DOES NOT DO
No scene loading, rendering, camera, physics, animation, audio, combat, AI, dialogue, inventory or engine; no filesystem, network, database, AI model
or external service; no clock or randomness, no module-level mutable state, no registry. Imports nothing at all and is not wired into
`process_input()`, Core, the Planner or the Agent Loop.
"""

FIELDS = ("scene_id", "character_ids", "asset_ids", "gameplay_system_ids")
COLLECTION_FIELDS = ("character_ids", "asset_ids", "gameplay_system_ids")

FAILURE_INVALID_INPUT = "GAME_SCENE_COMPOSITION_INVALID_INPUT"
FAILURE_UNEXPECTED_FIELD = "GAME_SCENE_COMPOSITION_UNEXPECTED_FIELD"
FAILURE_MISSING_FIELD = "GAME_SCENE_COMPOSITION_MISSING_FIELD"
FAILURE_INVALID_SCENE_ID = "GAME_SCENE_COMPOSITION_INVALID_SCENE_ID"
FAILURE_INVALID_CHARACTER_IDS = "GAME_SCENE_COMPOSITION_INVALID_CHARACTER_IDS"
FAILURE_INVALID_CHARACTER_ID = "GAME_SCENE_COMPOSITION_INVALID_CHARACTER_ID"
FAILURE_DUPLICATE_CHARACTER_ID = "GAME_SCENE_COMPOSITION_DUPLICATE_CHARACTER_ID"
FAILURE_INVALID_ASSET_IDS = "GAME_SCENE_COMPOSITION_INVALID_ASSET_IDS"
FAILURE_INVALID_ASSET_ID = "GAME_SCENE_COMPOSITION_INVALID_ASSET_ID"
FAILURE_DUPLICATE_ASSET_ID = "GAME_SCENE_COMPOSITION_DUPLICATE_ASSET_ID"
FAILURE_INVALID_GAMEPLAY_SYSTEM_IDS = "GAME_SCENE_COMPOSITION_INVALID_GAMEPLAY_SYSTEM_IDS"
FAILURE_INVALID_GAMEPLAY_SYSTEM_ID = "GAME_SCENE_COMPOSITION_INVALID_GAMEPLAY_SYSTEM_ID"
FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID = "GAME_SCENE_COMPOSITION_DUPLICATE_GAMEPLAY_SYSTEM_ID"

FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_UNEXPECTED_FIELD, FAILURE_MISSING_FIELD, FAILURE_INVALID_SCENE_ID,
                 FAILURE_INVALID_CHARACTER_IDS, FAILURE_INVALID_CHARACTER_ID, FAILURE_DUPLICATE_CHARACTER_ID,
                 FAILURE_INVALID_ASSET_IDS, FAILURE_INVALID_ASSET_ID, FAILURE_DUPLICATE_ASSET_ID,
                 FAILURE_INVALID_GAMEPLAY_SYSTEM_IDS, FAILURE_INVALID_GAMEPLAY_SYSTEM_ID, FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID)

# (collection field, invalid-collection code, invalid-item code, duplicate-item code) - aligned with COLLECTION_FIELDS
_COLLECTION_CODES = ((FAILURE_INVALID_CHARACTER_IDS, FAILURE_INVALID_CHARACTER_ID, FAILURE_DUPLICATE_CHARACTER_ID),
                     (FAILURE_INVALID_ASSET_IDS, FAILURE_INVALID_ASSET_ID, FAILURE_DUPLICATE_ASSET_ID),
                     (FAILURE_INVALID_GAMEPLAY_SYSTEM_IDS, FAILURE_INVALID_GAMEPLAY_SYSTEM_ID, FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID))

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameSceneComposition:
    """Immutable record of the character, asset and gameplay-system identifiers of one scene. Obtain it only from
    `create_game_scene_composition()`."""

    __slots__ = ("_scene_id", "_character_ids", "_asset_ids", "_gameplay_system_ids")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameSceneComposition cannot be subclassed.")

    def __init__(self, _token, scene_id, character_ids, asset_ids, gameplay_system_ids):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_scene_composition() to build a GameSceneComposition.")
        object.__setattr__(self, "_scene_id", scene_id)
        object.__setattr__(self, "_character_ids", tuple(character_ids))
        object.__setattr__(self, "_asset_ids", tuple(asset_ids))
        object.__setattr__(self, "_gameplay_system_ids", tuple(gameplay_system_ids))

    def __setattr__(self, key, value):
        raise AttributeError("GameSceneComposition is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameSceneComposition is immutable.")

    @property
    def scene_id(self):
        return self._scene_id

    @property
    def character_ids(self):
        """Tuple of character identifiers, in input order."""
        return self._character_ids

    @property
    def asset_ids(self):
        """Tuple of asset identifiers, in input order."""
        return self._asset_ids

    @property
    def gameplay_system_ids(self):
        """Tuple of gameplay-system identifiers, in input order."""
        return self._gameplay_system_ids

    def to_dict(self):
        """A fresh plain dict of fresh lists (fixed field order, JSON-safe). Mutating it never affects this composition."""
        return {"scene_id": self._scene_id, "character_ids": list(self._character_ids), "asset_ids": list(self._asset_ids),
                "gameplay_system_ids": list(self._gameplay_system_ids)}

    def _key(self):
        return (self._scene_id, self._character_ids, self._asset_ids, self._gameplay_system_ids)

    def __eq__(self, other):
        if type(other) is not GameSceneComposition:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameSceneComposition is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameSceneComposition(scene_id=%r, characters=%d, assets=%d, gameplay_systems=%d)" % (
            self._scene_id, len(self._character_ids), len(self._asset_ids), len(self._gameplay_system_ids))


class GameSceneCompositionResult:
    """Outcome of `create_game_scene_composition()`: `composition` is set only when `ok`."""

    __slots__ = ("composition", "failures")

    def __init__(self, composition=None, failures=None):
        self.composition = composition
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.composition is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "composition": self.composition.to_dict() if self.composition is not None else None,
                "failures": [dict(f) for f in self.failures]}


def _check_collection(field, items, codes, failures):
    """Append every problem found in one identifier collection to `failures`."""
    invalid_collection, invalid_item, duplicate_item = codes
    if type(items) not in (list, tuple):
        failures.append(_failure(invalid_collection, "%s must be a list or a tuple of str identifiers." % field, field))
        return
    seen = set()
    for index, item in enumerate(items):
        if type(item) is not str:
            failures.append(_failure(invalid_item, "%s[%d] must be a str." % (field, index), field))
        elif item.strip() == "":
            failures.append(_failure(invalid_item, "%s[%d] must not be empty or blank." % (field, index), field))
        elif item in seen:
            failures.append(_failure(duplicate_item, "%s[%d] duplicates an earlier identifier: %r." % (field, index, item), field))
        else:
            seen.add(item)


def create_game_scene_composition(data):
    """Validate `data` (a plain dict with exactly the four composition fields) and build an immutable `GameSceneComposition`. Identifiers are not
    resolved against any registry. Deterministic, never raises for bad data, reads `data` without changing it. Returns a
    `GameSceneCompositionResult`."""
    if type(data) is not dict:
        return GameSceneCompositionResult(failures=[_failure(FAILURE_INVALID_INPUT, "Game scene composition data must be a plain dict.")])
    failures = []
    names = [k for k in data if type(k) is str]
    if len(names) != len(data):
        failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Game scene composition data has a field name that is not a str."))
    for key in sorted(names):
        if key not in FIELDS:
            failures.append(_failure(FAILURE_UNEXPECTED_FIELD, "Unexpected game scene composition field: %r." % key, key))
    for field in FIELDS:
        if field not in data:
            failures.append(_failure(FAILURE_MISSING_FIELD, "Missing game scene composition field: %s." % field, field))
    if "scene_id" in data:
        scene_id = data["scene_id"]
        if type(scene_id) is not str:
            failures.append(_failure(FAILURE_INVALID_SCENE_ID, "scene_id must be a str.", "scene_id"))
        elif scene_id.strip() == "":
            failures.append(_failure(FAILURE_INVALID_SCENE_ID, "scene_id must not be empty or blank.", "scene_id"))
    for field, codes in zip(COLLECTION_FIELDS, _COLLECTION_CODES):
        if field in data:
            _check_collection(field, data[field], codes, failures)
    if failures:
        return GameSceneCompositionResult(failures=failures)
    return GameSceneCompositionResult(composition=GameSceneComposition(_CREATE_TOKEN, *(data[f] for f in FIELDS)))
