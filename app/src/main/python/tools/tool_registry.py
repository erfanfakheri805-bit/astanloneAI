"""
Tools - Tool Registry
========================
`ToolRegistry` is a small, in-memory registry that tracks
`ToolDefinition` objects (tool_definition.py) by their own `name`:

    ToolDefinition -> ToolRegistry.register(tool)
        -> ToolRegistry.is_available(name) -> [only if True] a future
           stage could route work to this tool

This is the tool-side analogue of
`execution.executable_registry.ExecutableCapabilityRegistry`, but one
layer earlier: that registry tracks already-executable `Capability`
objects (each with a real, callable handler); this one only ever
tracks `ToolDefinition`s (no handler at all - see that module's
docstring). Nothing here ever calls a handler, because a
`ToolDefinition` doesn't have one yet.

Unlike `ExecutableCapabilityRegistry` (which keeps its own separate
`{"capability": ..., "enabled": ...}` entry because `Capability` has
no `enabled` field of its own), `ToolDefinition` already carries its
own `enabled` flag, so this registry stores the `ToolDefinition`
object itself as the single source of truth for that state - `enable`/
`disable` simply flip that same flag on the stored object, rather than
maintaining a second, parallel boolean that could drift out of sync.

Nothing here executes anything, discovers or installs a tool on its
own initiative, accesses the network, or accesses any external
application. A name only ever has an entry because some caller
explicitly called `register` with that exact `ToolDefinition` object
- no scanning, no naming-convention-based discovery, no automatic
registration of the tool categories described in tool_definition.py's
module docstring (web browsing, web search, file operations, and so
on). This module also never touches a `Plan`, `Goal`, `Capability`, or
the learning system.
"""

from .tool_definition import ToolDefinition


class ToolRegistry:
    """A plain, in-memory `{name: ToolDefinition}` map. Not
    thread-safe (matches the rest of this project - see
    `ExecutableCapabilityRegistry`/`CapabilityHandlerRegistry`'s own
    notes). Safe to use one instance per Core / per conversation
    session, or to share one instance across several callers that
    should see the same set of registered tools."""

    def __init__(self):
        self._tools = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, tool):
        """Register `tool` under its own `tool.name` (stripped of
        surrounding whitespace, so lookups via `get`/`has`/`is_available`
        - which normalize their own `name` argument the same way -
        always agree on the same key).

        Raises TypeError - and stores nothing - if `tool` isn't a
        `ToolDefinition` instance at all. Raises ValueError - and
        stores nothing - if `tool.is_valid()` is False (an empty/
        non-string name, a non-dict schema or metadata, a non-bool
        `enabled`, ...) - only an already-well-formed `ToolDefinition`
        may ever be registered.

        Raises ValueError - and leaves the existing registration
        untouched - if a tool is already registered under that same
        (stripped) name; this registry has no `replace()` escape
        hatch by design, same as `ExecutableCapabilityRegistry.register`
        - `unregister` the old entry first if a deliberate replacement
        is what's wanted, so a silent overwrite of an existing tool is
        never possible here.

        Registration is deterministic: the same `tool` registered
        under the same never-before-used name always succeeds the
        same way, and a name, once taken, stays taken until explicitly
        unregistered - nothing here is randomized or time-dependent.
        Never calls any handler (a `ToolDefinition` has none). Returns
        `tool` unchanged."""
        if not isinstance(tool, ToolDefinition):
            raise TypeError("tool must be a ToolDefinition instance.")
        if not tool.is_valid():
            raise ValueError("tool is not valid and cannot be registered.")

        name = tool.name.strip()
        if name in self._tools:
            raise ValueError(
                f"A tool is already registered under the name {name!r}; "
                "unregister it first if you intend to replace it."
            )

        self._tools[name] = tool
        return tool

    def unregister(self, name):
        """Remove any entry registered under `name`. Returns True if
        an entry was actually removed, False if `name` had no entry
        (never raises for an unknown, empty, or non-string name - same
        "read-only-safe on a miss" convention as
        `ExecutableCapabilityRegistry.unregister`)."""
        key = _normalize_name(name)
        if key is not None and key in self._tools:
            del self._tools[key]
            return True
        return False

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, name):
        """The `ToolDefinition` object registered under `name`, or
        `None` if nothing is registered there (never raises for an
        unknown, empty, or non-string name). Does not check enabled
        state - use `is_available` for that. Returns the actual stored
        object (not a copy), same convention as
        `ExecutableCapabilityRegistry.get` - a caller that wants a
        safe, independent snapshot should use `list_all()` or
        `tool.to_dict()` instead."""
        key = _normalize_name(name)
        return self._tools.get(key) if key is not None else None

    def has(self, name):
        """True if a `ToolDefinition` is currently registered under
        `name`, regardless of its enabled state (False for an unknown,
        empty, or non-string name - never raises)."""
        key = _normalize_name(name)
        return key is not None and key in self._tools

    def list_all(self):
        """A plain list (never None) of fresh `to_dict()` snapshots -
        one per registered tool, in the order each was first
        registered. Each snapshot is independent of this registry's
        internal state (see `ToolDefinition.to_dict`'s own defensive
        copies), so mutating an entry in the returned list can never
        affect a registered tool."""
        return [tool.to_dict() for tool in self._tools.values()]

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------
    def enable(self, name):
        """Mark the tool registered under `name` as enabled (sets its
        own `tool.enabled = True`). Returns True if an entry was
        actually found and updated, False if `name` has no entry
        (never raises for an unknown name)."""
        tool = self.get(name)
        if tool is None:
            return False
        tool.enabled = True
        return True

    def disable(self, name):
        """Mark the tool registered under `name` as disabled (sets its
        own `tool.enabled = False`) - after this, `is_available(name)`
        is always False, even though the tool stays registered and
        `has(name)`/`get(name)` still find it. Returns True if an
        entry was actually found and updated, False if `name` has no
        entry (never raises for an unknown name)."""
        tool = self.get(name)
        if tool is None:
            return False
        tool.enabled = False
        return True

    # ------------------------------------------------------------------
    # Availability (read-only)
    # ------------------------------------------------------------------
    def is_available(self, name):
        """True only when both of the following hold: (1) a tool is
        actually registered under `name`; (2) that tool's own
        `enabled` flag is currently `True`. Returns False (never
        raises) for an unknown, empty, or non-string `name`, and for a
        registered-but-disabled tool. Never calls anything - a
        `ToolDefinition` has no handler to call."""
        tool = self.get(name)
        if tool is None:
            return False
        return bool(tool.enabled)

    def __len__(self):
        return len(self._tools)

    def __repr__(self):
        return f"ToolRegistry({list(self._tools.keys())!r})"


def _normalize_name(name):
    if not name or not isinstance(name, str) or not name.strip():
        return None
    return name.strip()
