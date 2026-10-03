"""
Game Character Registry (Prompt 724, Section 7 - Professional Game Creation)
============================================================================
A small, immutable, in-memory collection of `GameCharacter` definitions with lookup by exact `character_id`, optionally checked against the
character identifiers listed by a `GameProjectStructure`:

    create_game_character_registry(characters, structure=None) -> GameCharacterRegistryResult(ok, registry, failures)
    GameCharacterRegistry.lookup(character_id)                 -> GameCharacterLookupResult(found, character, code)
    GameCharacterRegistry.to_dict()                            -> {"characters": [GameCharacter.to_dict(), ...]}

INPUT RULES
- `characters` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is coerced, and
  an unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly a `GameCharacter` (Prompt 723). `character_id` values must be unique (exact comparison). Input order is preserved.
- `structure` is `None` (no structure check) or exactly a `GameProjectStructure` (Prompt 721). When given, EVERY identifier in
  `structure.characters` must have a registered character; a registered character that the structure does not list is allowed (unused
  definitions are fine). Neither the structure nor the characters are changed.
- `create_game_character_registry()` never raises for bad input: it reports every problem at once in a fixed order (collection problems by
  position, then the structure, then missing references in `structure.characters` order), using stable codes from `FAILURE_CODES`. The reference
  check runs only when `structure` is valid, against the valid characters found.
- Direct `GameCharacterRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(character_id)` never raises: it returns a `GameCharacterLookupResult` with `found=True` and the `GameCharacter`, or `found=False`,
`character=None` and code `FAILURE_CHARACTER_NOT_FOUND` (also for a `character_id` that is not exactly a `str`). No trimming or case folding.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the (already immutable) characters; `characters` and `character_ids` return tuples. `__slots__`, assignment /
deletion raises, not subclassable. Equal characters in the same order mean equal registries and hashes (a different order is a different
registry); `to_dict()` returns FRESH plain data in registration order on every call. copy/deepcopy return the same object; pickling is refused.
The structure is used only for validation and is not stored.

WHAT THIS MODULE DOES NOT DO
No scene or asset relationships, no character content (health, inventory, AI, dialogue, animation, ...), no filesystem, network, database, AI
model or external service, no clock or randomness, no module-level mutable state, no global registry. Its only imports are the two Section 7
record modules. It is not wired into `process_input()`, Core, the Planner or the Agent Loop.
"""

from .game_character import GameCharacter
from .game_project_structure import GameProjectStructure

FAILURE_INVALID_COLLECTION = "GAME_CHARACTER_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_CHARACTER = "GAME_CHARACTER_REGISTRY_INVALID_CHARACTER"
FAILURE_DUPLICATE_CHARACTER_ID = "GAME_CHARACTER_REGISTRY_DUPLICATE_CHARACTER_ID"
FAILURE_INVALID_STRUCTURE = "GAME_CHARACTER_REGISTRY_INVALID_STRUCTURE"
FAILURE_MISSING_CHARACTER_REFERENCE = "GAME_CHARACTER_REGISTRY_MISSING_CHARACTER_REFERENCE"
FAILURE_CHARACTER_NOT_FOUND = "GAME_CHARACTER_REGISTRY_CHARACTER_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_CHARACTER, FAILURE_DUPLICATE_CHARACTER_ID, FAILURE_INVALID_STRUCTURE,
                 FAILURE_MISSING_CHARACTER_REFERENCE, FAILURE_CHARACTER_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameCharacterLookupResult:
    """Outcome of `GameCharacterRegistry.lookup()`: `character` is set only when `found`; otherwise `code` is FAILURE_CHARACTER_NOT_FOUND."""

    __slots__ = ("found", "character", "code")

    def __init__(self, found, character=None, code=None):
        self.found = found
        self.character = character
        self.code = code

    def to_dict(self):
        return {"found": self.found, "character": self.character.to_dict() if self.character is not None else None, "code": self.code}


class GameCharacterRegistry:
    """Immutable, ordered collection of `GameCharacter` objects with unique ids. Obtain it only from `create_game_character_registry()`."""

    __slots__ = ("_characters",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameCharacterRegistry cannot be subclassed.")

    def __init__(self, _token, characters):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_game_character_registry() to build a GameCharacterRegistry.")
        object.__setattr__(self, "_characters", tuple(characters))

    def __setattr__(self, key, value):
        raise AttributeError("GameCharacterRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameCharacterRegistry is immutable.")

    @property
    def characters(self):
        """Tuple of the registered `GameCharacter` objects, in registration order."""
        return self._characters

    @property
    def character_ids(self):
        """Tuple of the registered character ids, in registration order."""
        return tuple(c.character_id for c in self._characters)

    def lookup(self, character_id):
        """Find a character by exact `character_id`. Never raises; returns a `GameCharacterLookupResult`."""
        if type(character_id) is str:
            for character in self._characters:
                if character.character_id == character_id:
                    return GameCharacterLookupResult(True, character)
        return GameCharacterLookupResult(False, None, FAILURE_CHARACTER_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"characters": [c.to_dict() for c in self._characters]}

    def __eq__(self, other):
        if type(other) is not GameCharacterRegistry:
            return NotImplemented
        return self._characters == other._characters

    def __hash__(self):
        return hash(self._characters)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameCharacterRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameCharacterRegistry(character_ids=%r)" % (self.character_ids,)


class GameCharacterRegistryResult:
    """Outcome of `create_game_character_registry()`: `registry` is set only when `ok`."""

    __slots__ = ("registry", "failures")

    def __init__(self, registry=None, failures=None):
        self.registry = registry
        self.failures = [] if failures is None else failures

    @property
    def ok(self):
        return self.registry is not None and not self.failures

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "registry": self.registry.to_dict() if self.registry is not None else None,
                "failures": [dict(f) for f in self.failures]}


def create_game_character_registry(characters, structure=None):
    """Validate `characters` (a list or tuple of `GameCharacter`, unique ids) and, when given, `structure` (a `GameProjectStructure` whose
    character ids must all be registered), then build an immutable `GameCharacterRegistry`. Deterministic, never raises for bad input, changes
    nothing it is given. Returns a `GameCharacterRegistryResult`."""
    failures = []
    valid = []
    if type(characters) not in (list, tuple):
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "characters must be a list or a tuple of GameCharacter objects.", "characters"))
    else:
        seen = set()
        for index, item in enumerate(characters):
            if type(item) is not GameCharacter:
                failures.append(_failure(FAILURE_INVALID_CHARACTER, "characters[%d] must be a GameCharacter." % index, "characters"))
            elif item.character_id in seen:
                failures.append(_failure(FAILURE_DUPLICATE_CHARACTER_ID,
                                         "characters[%d] duplicates an earlier character_id: %r." % (index, item.character_id), "characters"))
            else:
                seen.add(item.character_id)
                valid.append(item)
    if structure is not None:
        if type(structure) is not GameProjectStructure:
            failures.append(_failure(FAILURE_INVALID_STRUCTURE, "structure must be None or a GameProjectStructure.", "structure"))
        else:
            known = set(c.character_id for c in valid)
            for character_id in structure.characters:
                if character_id not in known:
                    failures.append(_failure(FAILURE_MISSING_CHARACTER_REFERENCE,
                                             "structure.characters lists %r but no such character is registered." % character_id, "structure"))
    if failures:
        return GameCharacterRegistryResult(failures=failures)
    return GameCharacterRegistryResult(registry=GameCharacterRegistry(_CREATE_TOKEN, valid))
