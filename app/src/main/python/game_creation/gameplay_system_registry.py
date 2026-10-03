"""
Gameplay System Registry (Prompt 726, Section 7 - Professional Game Creation)
=============================================================================
A small, immutable, in-memory collection of gameplay-system IDENTIFIERS (plain strings) with lookup by exact id, optionally checked against
the gameplay-system identifiers listed by a `GameProjectStructure`:

    create_gameplay_system_registry(gameplay_systems, structure=None) -> GameplaySystemRegistryResult(ok, registry, failures)
    GameplaySystemRegistry.lookup(system_id)           -> GameplaySystemLookupResult(found, system_id, code)
    GameplaySystemRegistry.to_dict()                   -> {"gameplay_systems": [id, ...]}

INPUT RULES
- `gameplay_systems` must be exactly a `list` or a `tuple` (sets, dicts, generators, strings and subclasses are rejected - nothing is
  coerced, and an unordered collection could not give a deterministic order). An empty collection is valid.
- Every item must be exactly a `str` that is not blank (`item.strip() != ""`); a `str` subclass or any other type is rejected. Ids are NEVER
  trimmed, lower-cased or otherwise changed: "Combat" and "combat" are different ids. Ids must be unique (exact comparison). Order is kept.
- `structure` is `None` (no structure check) or exactly a `GameProjectStructure` (Prompt 721). When given, EVERY identifier in
  `structure.gameplay_systems` must be registered; a registered id the structure does not list is allowed (unused ids are fine). Neither the
  structure nor the caller's collection is changed, and the structure is not stored.
- `create_gameplay_system_registry()` never raises for bad input: it reports every problem at once in a fixed order (collection problems by
  position, then the structure, then missing references in `structure.gameplay_systems` order), using stable codes from `FAILURE_CODES`. The
  reference check runs only when `structure` is valid, against the valid ids found.
- Direct `GameplaySystemRegistry(...)` construction is refused (TypeError); the only way to get one is a successful factory call.

LOOKUP
`lookup(system_id)` never raises: it returns `found=True` with the id, or `found=False`, `system_id=None` and code
`FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND` (also for an id that is not exactly a `str`). No trimming or case folding.

IMMUTABLE AND DETERMINISTIC
The registry stores a tuple of the ids (copied from the caller's collection); `gameplay_system_ids` returns that tuple. `__slots__`, assignment /
deletion raises, not subclassable. The same ids in the same order mean equal registries and hashes (a different order is a different
registry); `to_dict()` returns a FRESH plain dict/list in registration order on every call. copy/deepcopy return the same object; pickling is
refused.

WHAT THIS MODULE DOES NOT DO
It implements no gameplay system (no combat, health, inventory, weapons, quests, progression, physics, AI, input, rendering, animation, audio)
and holds no system content, only names. No filesystem, network, database, AI model or external service, no clock or randomness, no
module-level mutable state, no global registry. Its only import is the Section 7 structure record. It is not wired into `process_input()`,
Core, the Planner or the Agent Loop.
"""

from .game_project_structure import GameProjectStructure

FAILURE_INVALID_COLLECTION = "GAMEPLAY_SYSTEM_REGISTRY_INVALID_COLLECTION"
FAILURE_INVALID_GAMEPLAY_SYSTEM = "GAMEPLAY_SYSTEM_REGISTRY_INVALID_GAMEPLAY_SYSTEM"
FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID = "GAMEPLAY_SYSTEM_REGISTRY_DUPLICATE_GAMEPLAY_SYSTEM_ID"
FAILURE_INVALID_STRUCTURE = "GAMEPLAY_SYSTEM_REGISTRY_INVALID_STRUCTURE"
FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE = "GAMEPLAY_SYSTEM_REGISTRY_MISSING_GAMEPLAY_SYSTEM_REFERENCE"
FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND = "GAMEPLAY_SYSTEM_REGISTRY_GAMEPLAY_SYSTEM_NOT_FOUND"      # lookup only; never produced by the factory

FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_GAMEPLAY_SYSTEM, FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID, FAILURE_INVALID_STRUCTURE,
                 FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE, FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND)

_CREATE_TOKEN = object()


def _failure(code, message, field=None):
    return {"code": code, "field": field, "message": message}


class GameplaySystemLookupResult:
    """Outcome of `GameplaySystemRegistry.lookup()`: `system_id` is set only when `found`; otherwise `code` is FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND."""

    __slots__ = ("found", "system_id", "code")

    def __init__(self, found, system_id=None, code=None):
        self.found = found
        self.system_id = system_id
        self.code = code

    def to_dict(self):
        return {"found": self.found, "system_id": self.system_id, "code": self.code}


class GameplaySystemRegistry:
    """Immutable, ordered collection of unique gameplay-system ids. Obtain it only from `create_gameplay_system_registry()`."""

    __slots__ = ("_ids",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("GameplaySystemRegistry cannot be subclassed.")

    def __init__(self, _token, gameplay_system_ids):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_gameplay_system_registry() to build a GameplaySystemRegistry.")
        object.__setattr__(self, "_ids", tuple(gameplay_system_ids))

    def __setattr__(self, key, value):
        raise AttributeError("GameplaySystemRegistry is immutable.")

    def __delattr__(self, key):
        raise AttributeError("GameplaySystemRegistry is immutable.")

    @property
    def gameplay_system_ids(self):
        """Tuple of the registered gameplay-system ids, in registration order."""
        return self._ids

    def lookup(self, system_id):
        """Find a gameplay-system id by exact match. Never raises; returns a `GameplaySystemLookupResult`."""
        if type(system_id) is str:
            for registered in self._ids:
                if registered == system_id:
                    return GameplaySystemLookupResult(True, registered)
        return GameplaySystemLookupResult(False, None, FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND)

    def to_dict(self):
        """Fresh plain data in registration order. Mutating it never affects this registry."""
        return {"gameplay_systems": list(self._ids)}

    def __eq__(self, other):
        if type(other) is not GameplaySystemRegistry:
            return NotImplemented
        return self._ids == other._ids

    def __hash__(self):
        return hash(self._ids)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("GameplaySystemRegistry is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "GameplaySystemRegistry(gameplay_system_ids=%r)" % (self._ids,)


class GameplaySystemRegistryResult:
    """Outcome of `create_gameplay_system_registry()`: `registry` is set only when `ok`."""

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


def create_gameplay_system_registry(gameplay_systems, structure=None):
    """Validate `gameplay_systems` (a list or tuple of unique, non-blank `str` ids) and, when given, `structure` (a `GameProjectStructure` whose
    gameplay-system ids must all be registered), then build an immutable `GameplaySystemRegistry`. Deterministic, never raises for bad input,
    changes nothing it is given. Returns a `GameplaySystemRegistryResult`."""
    failures = []
    valid = []
    if type(gameplay_systems) not in (list, tuple):
        failures.append(_failure(FAILURE_INVALID_COLLECTION, "gameplay_systems must be a list or a tuple of str ids.", "gameplay_systems"))
    else:
        seen = set()
        for index, item in enumerate(gameplay_systems):
            if type(item) is not str:
                failures.append(_failure(FAILURE_INVALID_GAMEPLAY_SYSTEM, "gameplay_systems[%d] must be a str." % index, "gameplay_systems"))
            elif item.strip() == "":
                failures.append(_failure(FAILURE_INVALID_GAMEPLAY_SYSTEM, "gameplay_systems[%d] must not be empty or blank." % index,
                                         "gameplay_systems"))
            elif item in seen:
                failures.append(_failure(FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID,
                                         "gameplay_systems[%d] duplicates an earlier id: %r." % (index, item), "gameplay_systems"))
            else:
                seen.add(item)
                valid.append(item)
    if structure is not None:
        if type(structure) is not GameProjectStructure:
            failures.append(_failure(FAILURE_INVALID_STRUCTURE, "structure must be None or a GameProjectStructure.", "structure"))
        else:
            known = set(valid)
            for system_id in structure.gameplay_systems:
                if system_id not in known:
                    failures.append(_failure(FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE,
                                             "structure.gameplay_systems lists %r but no such gameplay system is registered." % system_id,
                                             "structure"))
    if failures:
        return GameplaySystemRegistryResult(failures=failures)
    return GameplaySystemRegistryResult(registry=GameplaySystemRegistry(_CREATE_TOKEN, valid))
