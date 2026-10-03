"""
Tools - Tool Definition
==========================
`ToolDefinition` is a small, plain data record describing the shape of
one future Agent tool - a name, a human description, a version, an
input/output schema pair, an enabled flag, and a free-form metadata
dict:

    ToolDefinition(name=..., description=..., ...) -> ToolRegistry.register(tool)

This is deliberately *shape only*, one step earlier than
`execution.capability.Capability`: `Capability` wraps an explicit,
already-callable `handler` and can `validate_input`/`execute` against
it; `ToolDefinition` has no handler at all yet - it only describes
what a tool called `name` *would* look like (its schemas, its
version, whether it's currently enabled, what it would need in order
to operate) so a `ToolRegistry` (tools/tool_registry.py) has
something concrete to hold before any tool is actually wired up to
real behavior. Same "plain, JSON-shaped record with a to_dict()"
convention already used by `LearningRecord`
(learning/learning_record.py), `LearningResult`, `LearningDecision`,
and `LearningInput`.

`requirements` is a small, free-form dict describing what a
not-yet-executable tool *would* need in order to run - e.g.
`{"network": False, "filesystem": False, "external_application":
False, "user_permission": False}`. It is purely descriptive
metadata, same status as `metadata` itself: declaring
`requirements={"network": True}` does not open a network
connection, request any permission, or enable anything - it is only
a structured note for some future stage to read before it ever
decides whether/how to actually grant a tool something. Nothing in
this class inspects, enforces, or acts on the *content* of
`requirements` - it is only ever validated for shape (must be a
dict) and returned as a safe copy.

`permissions` is a small, closed-vocabulary list naming which kinds
of permission a not-yet-executable tool *would* need - each entry
must be one of `SUPPORTED_PERMISSIONS`
(`"network"`/`"filesystem"`/`"external_application"`/
`"user_account"`/`"user_confirmation"`). Like `requirements`, this is
purely descriptive: listing `permissions=["network"]` does not open a
network connection, does not request or grant anything, and does not
enable the tool - it is only a structured note for some future stage
to read. Nothing in this class grants, requests, or acts on any
permission - `permissions` is only ever validated for shape (a list
of supported, non-empty strings) and returned, deduplicated, as a
safe copy via `get_permissions()`, or queried one name at a time via
`requires_permission(name)`.

`capabilities` is a small, free-form (not closed-vocabulary, unlike
`permissions`) list naming what a not-yet-executable tool *could*
potentially do - e.g. `"web_search"`, `"file_access"`,
`"image_processing"`, `"device_control"`. Purely descriptive, same
status as `permissions`: listing `capabilities=["web_search"]` does
not perform a web search, access a file, or implement anything - it
is only a structured note for some future stage to read. Nothing in
this class implements, executes, or acts on any capability -
`capabilities` is only ever validated for shape (a list of non-empty
strings; any name is accepted, since there is no fixed vocabulary
for this stage) and returned, deduplicated, as a safe copy via
`get_capabilities()`, or queried one name at a time via
`has_capability(name)`.

`access_level` is a single closed-vocabulary string naming how far a
not-yet-executable tool's *reach* would extend, from
`SUPPORTED_ACCESS_LEVELS`: `"local"` (only inside the Agent itself,
the default), `"device"` (device capabilities), `"network"`
(network-based resources), or `"external"` (external applications,
services, or accounts). Like `permissions`, this is purely
descriptive - setting `access_level="external"` does not open a
connection, control a device, or grant any actual access; it only
names, for some future stage to read, how far a real implementation
of this tool *would* need to reach. Nothing in this class grants any
access or acts on the value - `access_level` is only ever validated
for shape (must be one of `SUPPORTED_ACCESS_LEVELS`) and returned as
plain data via `get_access_level()`.

Same "construction never raises, is_valid() reports fitness for use"
convention as `LearningRecord.is_valid()` (rather than `Capability`'s
"raise immediately on a bad name/handler" convention) - a caller can
freely build a `ToolDefinition` from untrusted/partial data and then
decide, via `is_valid()`, whether it's fit to register, rather than
having to wrap construction in a try/except. `ToolRegistry.register`
is the one place `is_valid()` is actually enforced (see that module).

Nothing here executes anything, discovers anything, or talks to the
network/filesystem/any external application - this is purely the
static description of a tool a future stage might someday back with
real behavior (web browsing, web search, file operations, image
generation/editing, video processing, code generation/execution, 3D
asset creation, project creation, application interaction, social
media automation, app/game publishing, ...). None of those tools are
implemented by this class or anywhere else in this stage.
"""


#: The closed vocabulary of permission names `permissions` entries may
#: use for this stage. Deliberately small and fixed - naming a
#: permission here does not implement or grant it; it only makes that
#: name available for a `ToolDefinition` to *describe itself* with.
SUPPORTED_PERMISSIONS = (
    "network",
    "filesystem",
    "external_application",
    "user_account",
    "user_confirmation",
)

#: The closed vocabulary of access-level names `access_level` may take
#: for this stage, ordered from narrowest to widest reach. Naming a
#: level here does not implement or grant it; it only makes that name
#: available for a `ToolDefinition` to *describe itself* with.
SUPPORTED_ACCESS_LEVELS = (
    "local",
    "device",
    "network",
    "external",
)

#: The default `access_level` for a `ToolDefinition` that doesn't
#: specify one - the narrowest possible reach (inside the Agent
#: itself only).
DEFAULT_ACCESS_LEVEL = "local"


class ToolDefinition:
    """One described (not-yet-executable) tool. Purely a data record:
    construction never raises, matching `LearningRecord`'s convention
    - use `is_valid()` to decide whether a given instance is fit to
    register.

    `input_schema`/`output_schema`/`metadata`/`requirements` are
    always plain dicts (never `None`), same convention as
    `Goal.metadata`/`Plan.metadata`/`Capability.metadata` - an
    omitted value becomes `{}`, not `None`, so callers never have to
    guard against a missing dict. `permissions`/`capabilities` are
    always plain lists (never `None`) for the same reason - an
    omitted value becomes `[]`. `access_level` is always a plain
    string - an omitted value becomes `DEFAULT_ACCESS_LEVEL`
    (`"local"`), the narrowest supported reach."""

    __slots__ = (
        "name", "description", "version", "input_schema", "output_schema",
        "enabled", "metadata", "requirements", "permissions", "access_level",
        "capabilities",
    )

    def __init__(
        self, name, description="", version="1.0.0",
        input_schema=None, output_schema=None, enabled=True, metadata=None,
        requirements=None, permissions=None, access_level=None,
        capabilities=None,
    ):
        self.name = name
        self.description = description
        self.version = version
        self.input_schema = input_schema if input_schema is not None else {}
        self.output_schema = output_schema if output_schema is not None else {}
        self.enabled = enabled
        self.metadata = metadata if metadata is not None else {}
        self.requirements = requirements if requirements is not None else {}
        self.permissions = permissions if permissions is not None else []
        self.access_level = (
            access_level if access_level is not None else DEFAULT_ACCESS_LEVEL
        )
        self.capabilities = capabilities if capabilities is not None else []

    def __repr__(self):
        return f"ToolDefinition(name={self.name!r}, version={self.version!r})"

    def is_valid(self):
        """Plain boolean check - never raises. A `ToolDefinition` is
        valid when all of the following hold:
          - `name` is a non-empty (non-whitespace-only) string
          - `description` is a string
          - `version` is a non-empty (non-whitespace-only) string
          - `input_schema` is a dict
          - `output_schema` is a dict
          - `enabled` is a plain bool
          - `metadata` is a dict
          - `requirements` is a dict
          - `permissions` is a list, where every entry is a non-empty
            string that is also one of `SUPPORTED_PERMISSIONS`
          - `access_level` is one of `SUPPORTED_ACCESS_LEVELS`
          - `capabilities` is a list, where every entry is a
            non-empty string

        `requirements` is only checked for shape (must be a dict),
        same as `metadata` - its contents are never inspected, and no
        particular key is required. `permissions`, by contrast, is
        checked entry-by-entry against the fixed `SUPPORTED_PERMISSIONS`
        vocabulary - an unsupported name (a typo, or a name from some
        future stage) makes the whole `ToolDefinition` invalid, same
        as an empty `name`. Duplicate entries are not, by themselves,
        invalid - `get_permissions()` is where duplicates are removed.
        `access_level` is checked the same way as a `permissions`
        entry - it must be a member of `SUPPORTED_ACCESS_LEVELS`, not
        merely any string. `capabilities` is checked for shape only,
        same as `requirements` - unlike `permissions`, there is no
        fixed vocabulary for this stage, so any non-empty string name
        is accepted; duplicate entries are not, by themselves, invalid
        - `get_capabilities()` is where duplicates are removed. Does
        not mutate this instance and never raises for bad field
        values - a caller can build a `ToolDefinition` with any
        values at all and then use this to decide whether it is fit
        to hand to `ToolRegistry.register`."""
        if not isinstance(self.name, str) or not self.name.strip():
            return False
        if not isinstance(self.description, str):
            return False
        if not isinstance(self.version, str) or not self.version.strip():
            return False
        if not isinstance(self.input_schema, dict):
            return False
        if not isinstance(self.output_schema, dict):
            return False
        if not isinstance(self.enabled, bool):
            return False
        if not isinstance(self.metadata, dict):
            return False
        if not isinstance(self.requirements, dict):
            return False
        if not isinstance(self.permissions, list):
            return False
        for permission in self.permissions:
            if not isinstance(permission, str) or not permission.strip():
                return False
            if permission not in SUPPORTED_PERMISSIONS:
                return False
        if (
            not isinstance(self.access_level, str)
            or self.access_level not in SUPPORTED_ACCESS_LEVELS
        ):
            return False
        if not isinstance(self.capabilities, list):
            return False
        for capability in self.capabilities:
            if not isinstance(capability, str) or not capability.strip():
                return False
        return True

    def to_dict(self):
        """Structured (JSON-shaped) representation - same convention
        as `Capability.to_dict`/`LearningRecord.to_dict`. `input_schema`,
        `output_schema`, `metadata`, and `requirements` are returned as
        fresh, shallow copies (never the live dict this instance
        holds), `permissions`/`capabilities` are each returned as a
        fresh list (never the live list this instance holds), and
        `access_level` is returned as-is (plain, immutable data), so a
        caller mutating the returned dict can never affect this
        `ToolDefinition`. Never raises, even for a field that fails
        `is_valid()` - a field that isn't actually a dict/list is
        passed through unchanged rather than crashing on
        `dict(...)`/`list(...)`."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": (
                dict(self.input_schema) if isinstance(self.input_schema, dict)
                else self.input_schema
            ),
            "output_schema": (
                dict(self.output_schema) if isinstance(self.output_schema, dict)
                else self.output_schema
            ),
            "enabled": self.enabled,
            "metadata": (
                dict(self.metadata) if isinstance(self.metadata, dict)
                else self.metadata
            ),
            "requirements": (
                dict(self.requirements) if isinstance(self.requirements, dict)
                else self.requirements
            ),
            "permissions": (
                list(self.permissions) if isinstance(self.permissions, list)
                else self.permissions
            ),
            "access_level": self.access_level,
            "capabilities": (
                list(self.capabilities) if isinstance(self.capabilities, list)
                else self.capabilities
            ),
        }

    def get_requirements(self):
        """A safe, independent copy of this tool's `requirements`
        dict - e.g. `{"network": False, "filesystem": False,
        "external_application": False, "user_permission": False}`.
        Mutating the returned dict can never affect this
        `ToolDefinition`, same "fresh copy" convention as
        `to_dict()`'s dict fields.

        Returns an empty dict (`{}`) - the same default construction
        already falls back to - when no `requirements` were provided,
        never `None`. If `requirements` was set to something other
        than a dict (a caller bypassing `is_valid()`), that value is
        returned unchanged rather than crashing on `dict(...)`, same
        defensive convention as `to_dict()`.

        Purely descriptive: this only reads and copies already-stored
        data. It never executes anything, never requests a
        permission, and never touches the network, filesystem, or any
        external application - and it never enables a tool or changes
        any field on this instance."""
        return (
            dict(self.requirements) if isinstance(self.requirements, dict)
            else self.requirements
        )

    def get_permissions(self):
        """A safe, independent copy of this tool's `permissions` list,
        e.g. `["network", "user_confirmation"]`, with duplicate names
        removed and deterministic ordering preserved (each name kept
        at the position of its *first* occurrence, same "stable
        dedupe" convention as an ordered-set). Mutating the returned
        list can never affect this `ToolDefinition`, same "fresh copy"
        convention as `get_requirements()`.

        Returns an empty list (`[]`) - the same default construction
        already falls back to - when no `permissions` were provided,
        never `None`. If `permissions` was set to something other
        than a list (a caller bypassing `is_valid()`), that value is
        returned unchanged rather than crashing on iteration, same
        defensive convention as `get_requirements()`.

        Purely descriptive: this only reads and copies already-stored
        names. It never grants, requests, or checks any permission,
        never executes anything, and never touches the network,
        filesystem, or any external application - and it never
        enables a tool or changes any field on this instance."""
        if not isinstance(self.permissions, list):
            return self.permissions
        deduped = []
        seen = set()
        for permission in self.permissions:
            if permission in seen:
                continue
            seen.add(permission)
            deduped.append(permission)
        return deduped

    def get_access_level(self):
        """This tool's configured `access_level` (one of
        `SUPPORTED_ACCESS_LEVELS`), or `DEFAULT_ACCESS_LEVEL`
        (`"local"`) when none was ever provided - matching the same
        default `__init__` already falls back to, so this never
        returns `None`. If `access_level` was set to something other
        than a supported value (a caller bypassing `is_valid()`),
        that value is returned unchanged rather than silently
        substituted, same defensive "pass invalid data through rather
        than crash or hide it" convention as `get_requirements()`/
        `get_permissions()`.

        `access_level` is plain, immutable string data, so - unlike
        `get_requirements()`/`get_permissions()` - there is no
        mutable container to copy defensively here.

        Purely descriptive: this only reads and returns an
        already-stored value. It never grants any actual access,
        never executes anything, never requests a permission, and
        never touches a device capability, the network, or any
        external application - and it never enables a tool or changes
        any field on this instance."""
        return self.access_level

    def requires_permission(self, permission_name):
        """`True` if `permission_name` is one of the names this tool
        declares in its own `permissions` list, `False` otherwise.
        Built on `get_permissions()` (so duplicates in `permissions`
        never affect the answer - the same name checked once or many
        times behaves identically) rather than on the raw `permissions`
        list directly.

        `False` (never raises) whenever `permission_name` isn't a
        non-empty string - e.g. `""`, `"   "`, `None`, or a non-string
        value - same "invalid input is simply not a match, not an
        error" convention as `ToolRegistry`'s own lookups. `False`
        (never raises) when `self.permissions` isn't a list at all (a
        caller bypassing `is_valid()`), since there is then nothing
        valid to match against.

        Purely a metadata query for some future Android/external tool
        layer to consult before deciding whether/how to grant
        anything: this method never grants, requests, or checks a
        *real* permission, never accesses any Android API, never
        executes this or any other tool, and never modifies this
        `ToolDefinition`, a `ToolRegistry`, a `Capability`, or a
        `Plan`."""
        if not isinstance(permission_name, str) or not permission_name.strip():
            return False
        permissions = self.get_permissions()
        if not isinstance(permissions, list):
            return False
        return permission_name in permissions

    def get_capabilities(self):
        """A safe, independent copy of this tool's `capabilities`
        list, e.g. `["web_search", "file_access"]`, with duplicate
        names removed and deterministic ordering preserved (each name
        kept at the position of its *first* occurrence, same "stable
        dedupe" convention as `get_permissions()`). Mutating the
        returned list can never affect this `ToolDefinition`, same
        "fresh copy" convention as `get_permissions()`/
        `get_requirements()`.

        Returns an empty list (`[]`) - the same default construction
        already falls back to - when no `capabilities` were provided,
        never `None`. If `capabilities` was set to something other
        than a list (a caller bypassing `is_valid()`), that value is
        returned unchanged rather than crashing on iteration, same
        defensive convention as `get_permissions()`.

        Purely descriptive: this only reads and copies already-stored
        names. It never implements, executes, or performs any
        capability, never grants a permission, and never touches the
        network, filesystem, or any external system - and it never
        enables a tool or changes any field on this instance."""
        if not isinstance(self.capabilities, list):
            return self.capabilities
        deduped = []
        seen = set()
        for capability in self.capabilities:
            if capability in seen:
                continue
            seen.add(capability)
            deduped.append(capability)
        return deduped

    def has_capability(self, capability_name):
        """`True` if `capability_name` is one of the names this tool
        declares in its own `capabilities` list, `False` otherwise.
        Built on `get_capabilities()` (so duplicates in `capabilities`
        never affect the answer), same convention as
        `requires_permission()`/`get_permissions()`.

        `False` (never raises) whenever `capability_name` isn't a
        non-empty string - e.g. `""`, `"   "`, `None`, or a non-string
        value - same "invalid input is simply not a match, not an
        error" convention as `requires_permission()`. `False` (never
        raises) when `self.capabilities` isn't a list at all (a
        caller bypassing `is_valid()`), since there is then nothing
        valid to match against.

        Purely a metadata query for some future tool layer to consult
        before deciding whether/how to route work to this tool: this
        method never implements, executes, or performs the named
        capability, never grants or requests any permission, never
        accesses any external system, and never modifies this
        `ToolDefinition`, a `ToolRegistry`, a `Capability`, or a
        `Plan`."""
        if not isinstance(capability_name, str) or not capability_name.strip():
            return False
        capabilities = self.get_capabilities()
        if not isinstance(capabilities, list):
            return False
        return capability_name in capabilities
