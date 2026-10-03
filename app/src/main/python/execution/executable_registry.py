"""
Execution - Executable Capability Registry
==============================================
`ExecutableCapabilityRegistry` is a small, in-memory registry that
tracks `Capability` objects (execution/capability.py) specifically -
each entry keyed by the capability's own `name`, each carrying its own
enabled/disabled state:

    Capability (execution/capability.py) -> ExecutableCapabilityRegistry
        -> is_available(name) -> [only if True] execute the capability

This is deliberately a *fourth*, separate concept from the three
capability-shaped things already in this project:
  - `capabilities.capability_system.CapabilitySystem` tracks whether a
    capability is registered/enabled at all, persisted in `memory`'s
    `capabilities` table - a yes/no the *application* has decided
    about a capability in general.
  - `execution.capability_handlers.CapabilityHandlerRegistry` maps a
    capability *name* to whatever plain callable (or, optionally, a
    `Capability`) should run for it - a loose, general-purpose name-to-
    handler map with no opinion about enabled/disabled state.
  - `Capability` (execution/capability.py) itself is just the shape of
    one capability - it doesn't know whether it's "the" registered
    instance for its name, or whether anything has decided to allow it
    to run.
`ExecutableCapabilityRegistry` is narrower than all three: it only
ever stores real `Capability` objects (never a bare callable - use
`CapabilityHandlerRegistry` for that), it is the one place an
enabled/disabled flag lives *per Capability instance*, and it never
reads or writes `CapabilitySystem`'s database-backed table or
`CapabilityHandlerRegistry`'s handler map. Keeping it separate (rather
than folding this into either of those) means neither of those two
existing registries has to change shape or behavior at all
(requirement 11/15 - their existing semantics are untouched).

Nothing here executes anything, ever. `register`/`unregister`/`enable`/
`disable` only ever store, remove, or flip a boolean next to a
`Capability` object the caller already constructed and already owns -
none of them call `capability.execute()`, `capability.handler`, or
`capability()`. `is_available` is a pure read-only check (existence +
enabled + a currently-callable handler) - it never calls the handler
either, only `callable(...)`-tests it. Nothing in this module ever
discovers, creates, or installs a `Capability` on its own initiative -
a name only ever has an entry because some caller explicitly called
`register` with that exact `Capability` object. No eval(), exec(),
subprocess, shell command, or network/filesystem access happens
anywhere in this file.

`execution.capability_handlers.CapabilityHandlerRegistry.check_execution_readiness`
now optionally accepts an `executable_registry=` argument
(execution/capability_handlers.py) - when supplied, a required
capability that this registry reports `is_available` for is treated as
having a registered handler, even if `CapabilityHandlerRegistry` itself
has nothing under that name. This is purely additive: omitting
`executable_registry` (the default) leaves `check_execution_readiness`
behaving exactly as it already did (requirement 15 - backward
compatibility with the existing `CapabilityHandlerRegistry`).
"""


class ExecutableCapabilityRegistry:
    """A plain, in-memory `{capability_name: {"capability": Capability,
    "enabled": bool}}` map. Not thread-safe (matches the rest of this
    project - see CapabilityHandlerRegistry/ExecutionEngine's own
    notes). Safe to use one instance per Core / per conversation
    session, or to share one instance across several callers that
    should see the same set of executable capabilities (same
    "can be shared explicitly" convention CapabilityHandlerRegistry/
    ExecutionHistory already follow).
    """

    def __init__(self):
        self._entries = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, capability, enabled=True):
        """Register `capability` under its own `capability.name`.

        Raises TypeError - and stores nothing - if `capability` isn't
        a `Capability` instance (execution/capability.py); a
        `Capability`'s own constructor already guarantees a valid
        name and a valid callable handler at the time it was built, so
        this registry never re-validates those - it only refuses to
        store something that isn't a `Capability` at all (requirement
        4: "only valid Capability objects may be registered").

        Raises ValueError - and leaves the existing registration
        untouched - if `capability.name` already has an entry
        (requirement 5: "capability names must be unique"); this
        registry has no `replace()` escape hatch by design (unlike
        `CapabilityHandlerRegistry.replace`) - `unregister` the old
        entry first if a deliberate replacement is what's wanted, so a
        silent overwrite is never possible here.

        `enabled` defaults to `True` (requirement 7: "newly registered
        capabilities should be enabled by default unless explicitly
        specified otherwise"); pass `enabled=False` to register a
        capability that starts out disabled. Never calls
        `capability.handler` or `capability.execute()`. Returns
        `capability` unchanged."""
        _validate_capability_object(capability)
        name = capability.name

        if name in self._entries:
            raise ValueError(
                f"A capability is already registered under the name {name!r}; "
                "unregister it first if you intend to replace it."
            )

        self._entries[name] = {"capability": capability, "enabled": bool(enabled)}
        return capability

    def unregister(self, name):
        """Remove any entry registered under `name`. Returns True if
        an entry was actually removed, False if `name` had no entry
        (never raises for an unknown name - same "read-only-safe on a
        miss" convention as CapabilityHandlerRegistry.unregister)."""
        key = _normalize_name(name)
        if key is not None and key in self._entries:
            del self._entries[key]
            return True
        return False

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, name):
        """The `Capability` object registered under `name`, or `None`
        if nothing is registered there (never raises for an unknown
        name - same convention as CapabilityHandlerRegistry.get). Does
        not check enabled state and does not call the handler - use
        `is_available` to also account for enabled state and handler
        validity."""
        key = _normalize_name(name)
        entry = self._entries.get(key) if key is not None else None
        return entry["capability"] if entry is not None else None

    def has(self, name):
        """True if a `Capability` is currently registered under
        `name`, regardless of its enabled state (False for an unknown,
        empty, or non-string name - never raises)."""
        key = _normalize_name(name)
        return key is not None and key in self._entries

    def list_all(self):
        """A plain list (never None) of lightweight summaries - one
        `{"name": ..., "enabled": ..., "available": ...}` dict per
        registered capability, in the order each was first registered
        - so a caller (a UI, a directory listing) can see every
        registered capability's current state at a glance without
        pulling each one's full `describe()` output. For the full
        structured description of one specific capability, use
        `describe(name)` instead."""
        return [
            {
                "name": name,
                "enabled": entry["enabled"],
                "available": self.is_available(name),
            }
            for name, entry in self._entries.items()
        ]

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------
    def enable(self, name):
        """Mark the capability registered under `name` as enabled.
        Returns True if an entry was actually found and updated, False
        if `name` has no entry (never raises for an unknown name).
        Never calls the handler."""
        key = _normalize_name(name)
        entry = self._entries.get(key) if key is not None else None
        if entry is None:
            return False
        entry["enabled"] = True
        return True

    def disable(self, name):
        """Mark the capability registered under `name` as disabled -
        after this, `is_available(name)` is always False (requirement
        8: "disabled capabilities must never be executable"), even if
        the capability's handler is otherwise perfectly valid. Returns
        True if an entry was actually found and updated, False if
        `name` has no entry (never raises for an unknown name). Never
        calls the handler."""
        key = _normalize_name(name)
        entry = self._entries.get(key) if key is not None else None
        if entry is None:
            return False
        entry["enabled"] = False
        return True

    # ------------------------------------------------------------------
    # Availability (read-only - see module docstring)
    # ------------------------------------------------------------------
    def is_available(self, name):
        """True only when all three of the following hold
        (requirement 9), evaluated in this order:
          1. a capability actually exists under `name`;
          2. its registered entry is currently enabled;
          3. its `.handler` is still a real callable right now (a
             `Capability`'s constructor already guaranteed this at
             registration time, but `handler` is a plain, mutable
             attribute - not frozen - so this is checked fresh here
             rather than trusted from construction time, the same
             "never trust a stale guarantee" reasoning
             `CapabilityReadinessResult.ready` already applies to its
             own three problem lists).
        Never calls the handler itself - only `callable(...)`-tests
        it. Returns False (never raises) for an unknown, empty, or
        non-string `name`."""
        capability = self.get(name)
        if capability is None:
            return False
        key = _normalize_name(name)
        if not self._entries[key]["enabled"]:
            return False
        return callable(capability.handler)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def describe(self, name):
        """A structured (JSON-shaped) inspection of the capability
        registered under `name`: its own `Capability.describe()`
        output, plus this registry's own state for it (`enabled`,
        `available`). Returns `None` - never raises - if `name` has no
        entry (same "never raise for an unknown name" convention every
        other lookup in this module follows). Never calls the
        handler."""
        capability = self.get(name)
        if capability is None:
            return None
        description = capability.describe()
        description["enabled"] = self._entries[_normalize_name(name)]["enabled"]
        description["available"] = self.is_available(name)
        return description

    def __len__(self):
        return len(self._entries)

    def __repr__(self):
        return f"ExecutableCapabilityRegistry({list(self._entries.keys())!r})"


def _normalize_name(name):
    if not name or not isinstance(name, str) or not name.strip():
        return None
    return name.strip()


def _validate_capability_object(capability):
    from .capability import Capability
    if not isinstance(capability, Capability):
        raise TypeError("capability must be a Capability instance.")
