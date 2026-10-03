"""
Execution - Capability Handler Registry
==========================================
`CapabilityHandlerRegistry` is a small, explicit map from a capability
name (the same strings that show up in `PlanStep.required_capabilities`
- see planning/plan.py) to the one Python callable that actually knows
how to carry that capability out:

    APPROVED CAPABILITY NAME -> CapabilityHandlerRegistry -> HANDLER (callable)
        -> ExecutionEngine.execute_capability_step (execution_engine.py)

This is deliberately a *second*, separate concept from
`capabilities.capability_system.CapabilitySystem`: that module tracks
whether a capability is registered/enabled at all (a yes/no, persisted
in `memory`'s `capabilities` table); this module tracks, for a
capability that's already been decided to exist, exactly which
callable is allowed to run when a step asks for it. Neither module
reads or writes the other - `execute_capability_step`
(execution_engine.py) is what brings the two together at call time by
checking `capability_system` for availability (via the existing
PreflightValidator - execution/preflight.py) and this registry for a
handler, refusing to run anything if either is missing.

Nothing here executes anything. `register`/`unregister`/`replace` only
ever store or remove a reference to a callable the caller already
wrote and already owns; they never call it, and never inspect its
behavior. Only `ExecutionEngine.execute_capability_step` ever actually
calls a handler that's been looked up here - same "no execution
without an explicit handler" rule `execute_step` already enforces for
its own handler argument (see execution_engine.py's module docstring).

No handler is ever auto-discovered: there is no scanning of modules,
entry points, decorators, or naming conventions anywhere in this file.
A capability name only ever has a handler because some caller called
`register` (or `replace`) with that exact name and that exact
callable. This module also never uses eval(), exec(), subprocess, a
shell command, or network/filesystem access - a "handler" is always
just an ordinary Python object the caller already constructed; this
registry never turns a string, a path, or any other data into code.

`register`/`replace`/`get`/`has` never changed shape or behavior for
this: a plain function/lambda/callable object registered the way it
always was still works exactly as before (requirement: "existing
simple callable handlers must continue to work"). What's new is purely
additive - `Capability` (execution/capability.py) defines `__call__`,
so `callable(capability_instance)` is already True and a `Capability`
can be handed to `register`/`replace` today with no code change here
at all. `register_capability`/`replace_capability`/`get_capability`
below are thin, optional convenience wrappers for that case (deriving
the registration name from `capability.name` instead of making the
caller repeat it, and letting a caller ask for the original
`Capability` object back instead of just its callable form) - they
never introduce a second storage location or a different validation
path; a `Capability` registered through `register_capability` lives in
the exact same `self._handlers` dict, found by `get`/`has`/
`list_registered` exactly like any other handler.

`check_execution_readiness` (added this stage) is a read-only,
pre-execution report: for every name in a PlanStep's own
`required_capabilities`, it checks - without ever calling a handler,
and without ever creating/enabling/modifying/registering a capability
or a handler - whether that capability actually exists in the
capability registry, whether it's currently enabled there, and
whether this registry has a handler for it, and returns a
`CapabilityReadinessResult` describing all three per capability.
`ExecutionEngine.execute_capability_step` (execution_engine.py) is the
only thing that acts on that result - refusing to run anything at all
when it isn't `ready` - this module itself never decides *to*
execute.
"""


class CapabilityReadinessResult:
    """The outcome of one `CapabilityHandlerRegistry.check_execution_readiness`
    call. Purely a data record, same "plain data in, plain data out"
    convention as `execution.preflight.PreflightResult` - nothing here
    decides *to* execute anything, calls a handler, or changes a
    capability/handler registration; see that module's docstring for
    the same convention applied to plan-level preflight checks.

    `capabilities`, `missing_capabilities`, `unavailable_capabilities`,
    `missing_handlers`, and `warnings` are always plain lists (never
    None) - same "callers can iterate immediately, no None check"
    convention as PreflightResult.failed_checks/warnings. `ready` is
    always derived from whether any of the three problem lists is
    non-empty - it can never disagree with them, the same way
    PreflightResult.valid can never disagree with failed_checks."""

    __slots__ = (
        "ready", "capabilities", "missing_capabilities",
        "unavailable_capabilities", "missing_handlers", "warnings",
    )

    def __init__(self, capabilities=None, missing_capabilities=None,
                 unavailable_capabilities=None, missing_handlers=None, warnings=None):
        self.capabilities = list(capabilities) if capabilities else []
        self.missing_capabilities = list(missing_capabilities) if missing_capabilities else []
        self.unavailable_capabilities = (
            list(unavailable_capabilities) if unavailable_capabilities else []
        )
        self.missing_handlers = list(missing_handlers) if missing_handlers else []
        self.warnings = list(warnings) if warnings else []
        # Always derived, never trusted from a caller - a readiness
        # result with any recorded problem is never ready, no matter
        # what else was passed in (same rule PreflightResult.valid
        # already applies to failed_checks).
        self.ready = not (
            self.missing_capabilities or self.unavailable_capabilities
            or self.missing_handlers
        )

    def __repr__(self):
        return (
            f"CapabilityReadinessResult(ready={self.ready!r}, "
            f"capabilities={len(self.capabilities)}, "
            f"missing_capabilities={len(self.missing_capabilities)}, "
            f"unavailable_capabilities={len(self.unavailable_capabilities)}, "
            f"missing_handlers={len(self.missing_handlers)})"
        )

    def to_dict(self):
        """Structured (JSON-shaped) representation - same convention
        as PreflightResult.to_dict/ExecutionResult.to_dict."""
        return {
            "ready": self.ready,
            "capabilities": [dict(entry) for entry in self.capabilities],
            "missing_capabilities": list(self.missing_capabilities),
            "unavailable_capabilities": list(self.unavailable_capabilities),
            "missing_handlers": list(self.missing_handlers),
            "warnings": list(self.warnings),
        }


class CapabilityHandlerRegistry:
    """A plain, in-memory `{capability_name: handler}` map. Not
    thread-safe (matches the rest of this project - see
    ExecutionEngine/PlanManager's own notes). Safe to use one instance
    per Core / per conversation session, or to share one across
    several ExecutionEngine instances that should see the same set of
    approved handlers (same "can be shared explicitly" convention
    ExecutionHistory already follows - see execution_history.py).
    """

    def __init__(self):
        self._handlers = {}

    # ------------------------------------------------------------------
    # Optional Capability convenience wrappers (see module docstring)
    # ------------------------------------------------------------------
    def register_capability(self, capability):
        """Convenience wrapper around `register(capability.name,
        capability)` for a `Capability` object (execution/capability.py)
        - saves the caller repeating the name and lets `capability`
        itself be looked up later via `get_capability`. Raises
        TypeError - and stores nothing - if `capability` isn't a
        `Capability` instance; otherwise follows exactly the same
        rules `register` already does (rejects a duplicate name unless
        `replace_capability`/`replace` is used, never calls the
        capability). Returns `capability` unchanged."""
        _validate_capability_object(capability)
        self.register(capability.name, capability)
        return capability

    def replace_capability(self, capability):
        """Convenience wrapper around `replace(capability.name,
        capability)` for a `Capability` object - same explicit-
        overwrite contract `replace` already has, never calls the
        capability. Raises TypeError - and stores nothing - if
        `capability` isn't a `Capability` instance. Returns
        `capability` unchanged."""
        _validate_capability_object(capability)
        self.replace(capability.name, capability)
        return capability

    def get_capability(self, capability_name):
        """The `Capability` object registered for `capability_name`,
        or `None` if nothing is registered under that name *or* what's
        registered there is a plain callable rather than a
        `Capability` (use plain `get` for that case instead). Never
        raises for an unknown name - same convention as `get`."""
        from .capability import Capability
        handler = self.get(capability_name)
        return handler if isinstance(handler, Capability) else None

    def is_capability(self, capability_name):
        """True only if `capability_name` currently resolves to a
        `Capability` object (as opposed to a plain callable, or
        nothing at all). Never raises for an unknown name."""
        return self.get_capability(capability_name) is not None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, capability_name, handler):
        """Register `handler` as the callable for `capability_name`.

        Raises ValueError - and stores nothing - if `capability_name`
        is empty, whitespace-only, or not a string. Raises TypeError -
        and stores nothing - if `handler` is `None` or anything that
        isn't callable (requirement 5: "reject non-callable
        handlers"). Raises ValueError - and leaves the existing
        registration untouched - if `capability_name` already has a
        handler registered; re-registering the same name is never a
        silent overwrite (requirement 5: "reject duplicate
        registration unless explicitly replaced through a separate
        safe operation") - use `replace` for that explicit case
        instead.

        Never calls `handler` (requirement 7: "do not execute
        handlers during registration") and never discovers a handler
        on its own (requirement 6) - `handler` is always exactly the
        callable the caller passed in.

        Returns `handler` unchanged, for convenience (e.g.
        `foo = registry.register("foo", foo)`)."""
        name = _validate_capability_name(capability_name)
        _validate_handler(handler)

        if name in self._handlers:
            raise ValueError(
                f"A handler is already registered for capability {name!r}; "
                "use replace() to explicitly replace it."
            )

        self._handlers[name] = handler
        return handler

    def replace(self, capability_name, handler):
        """Explicitly replace whatever handler (if any) is currently
        registered for `capability_name` with `handler` - the one
        "separate safe operation" `register` points to for
        overwriting an existing registration (requirement 5). Same
        validation as `register` (non-empty `capability_name`,
        callable `handler`), but never raises for a name that's
        already registered - that's the whole point of this being a
        separate method. Registering a brand-new name through
        `replace` is also fine (it behaves like `register` in that
        case). Never calls `handler`. Returns `handler` unchanged."""
        name = _validate_capability_name(capability_name)
        _validate_handler(handler)

        self._handlers[name] = handler
        return handler

    def unregister(self, capability_name):
        """Remove any handler registered for `capability_name`.
        Returns True if a handler was actually removed, False if
        `capability_name` had no handler registered (never raises for
        an unknown name - same "read-only-safe on a miss" convention
        as ExecutionHistory.get/PlanManager.get_plan)."""
        if not capability_name or not isinstance(capability_name, str):
            return False
        name = capability_name.strip()
        if name in self._handlers:
            del self._handlers[name]
            return True
        return False

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, capability_name):
        """The callable registered for `capability_name`, or `None`
        if none is registered (never raises for an unknown name - same
        convention as `unregister`). Does not call the handler."""
        if not capability_name or not isinstance(capability_name, str):
            return None
        return self._handlers.get(capability_name.strip())

    def has(self, capability_name):
        """True if a handler is currently registered for
        `capability_name`, False otherwise (including for an empty or
        non-string name - never raises)."""
        if not capability_name or not isinstance(capability_name, str):
            return False
        return capability_name.strip() in self._handlers

    def list_registered(self):
        """Every currently-registered capability name, in the order
        each was first registered (re-registering via `replace` does
        not move a name later in this order). A plain list (never
        None) - same "callers can iterate immediately" convention used
        throughout this project."""
        return list(self._handlers.keys())

    # ------------------------------------------------------------------
    # Readiness (read-only - see module docstring)
    # ------------------------------------------------------------------
    def check_execution_readiness(self, step, capability_system=None, executable_registry=None):
        """Read-only pre-execution report for `step` (a PlanStep -
        planning/plan.py): for every name in `step.required_capabilities`,
        checks whether that capability exists in `capability_system`,
        whether it's currently enabled there, and whether a handler is
        available for it - and returns a fully-populated
        `CapabilityReadinessResult` describing all three, per
        capability. Never calls a handler (requirement 5: "do not
        execute any handler during this check") and never creates,
        enables, modifies, or registers a capability or a handler
        (requirements 6-7) - purely reads `capability_system.all()`,
        `self._handlers`, and (when supplied) `executable_registry`.

        `executable_registry` is optional (defaults to `None`) - an
        `ExecutableCapabilityRegistry` (execution/executable_registry.py).
        When supplied, a required capability counts as having a
        handler if *either* `self.has(capability_name)` is True (the
        existing check, untouched) *or*
        `executable_registry.is_available(capability_name)` is True -
        i.e. a properly registered, enabled `Capability` with a
        currently-callable handler satisfies readiness exactly like an
        entry already registered in this `CapabilityHandlerRegistry`
        would. Omitting `executable_registry` (the default) leaves
        this method behaving exactly as it already did - this is a
        purely additive, opt-in source of handlers, never a second,
        conflicting source of truth about `self._handlers` itself
        (requirement 15: backward compatibility with the existing
        `CapabilityHandlerRegistry`). `executable_registry.is_available`
        is itself read-only (never calls a handler - see that
        registry's own docstring), so this check remains just as
        read-only as it already was.

        `capability_system` is optional (defaults to None), matching
        the exact contract `PreflightValidator.validate_step` and
        `PlanManager._unavailable_capabilities` already use (see
        preflight.py/plan_manager.py): omitting it skips the
        existence/availability checks entirely for every required
        capability (a warning is added instead, naming which
        capabilities weren't checked) rather than treating every one
        of them as missing or unavailable - only handler registration
        is still verified in that case. This is requirement 10 ("reuse
        existing capability and preflight logic wherever possible")
        applied here: the same registry lookup shape
        PlanManager._capability_registry_lookup already builds
        (`{row["name"]: row for row in capability_system.all()}`) is
        rebuilt here rather than invented differently, and the same
        "no registry supplied means skip, not fail" rule
        _unavailable_capabilities already follows is applied to this
        check too.

        Each entry in `result.capabilities` (in
        `required_capabilities` order) is a plain dict:
          - `capability_name`: the required capability's name;
          - `available`: True if the capability exists in
            `capability_system` and is enabled there (or if
            `capability_system` was omitted - see above); False if it
            doesn't exist or is disabled;
          - `handler_registered`: `self.has(capability_name)`, or, if
            that's False and `executable_registry` was supplied,
            `executable_registry.is_available(capability_name)`
            instead - never affected by `capability_system` at all;
          - `status`: one of `"missing_capability"` (doesn't exist in
            `capability_system`), `"unavailable"` (exists but
            disabled), `"missing_handler"` (available but no handler
            registered), or `"ready"` (available and a handler is
            registered) - evaluated in that order, so a capability
            that's both unregistered *and* missing a handler is
            reported as `"missing_capability"` (the more fundamental
            problem), not `"missing_handler"`.

        `result.missing_capabilities`, `result.unavailable_capabilities`,
        and `result.missing_handlers` are independent checks, not
        mirrors of `status` above: a required capability that doesn't
        exist in `capability_system` *and* has no registered handler
        appears in both `missing_capabilities` and `missing_handlers`
        (each list answers its own question - "does this capability
        exist?", "is it enabled?", "is a handler registered?" -
        regardless of what the other two answer), so a caller checking
        one specific list gets a complete answer to that one question
        without also having to cross-reference `status`.

        `result.ready` is True only when all three of those lists are
        empty (see CapabilityReadinessResult.__init__) - i.e. only
        when every required capability is `"ready"`. A step with no
        required capabilities is trivially ready (empty lists, empty
        `capabilities`, no warnings)."""
        required = list(getattr(step, "required_capabilities", None) or [])

        capabilities = []
        missing_capabilities = []
        unavailable_capabilities = []
        missing_handlers = []
        warnings = []

        if capability_system is None:
            registered_lookup = {}
            if required:
                warnings.append(
                    "No capability_system was supplied, so capability "
                    f"existence/availability were not checked for {required!r}; "
                    "only handler registration was verified."
                )
        else:
            # Same registry-lookup shape
            # PlanManager._capability_registry_lookup already builds -
            # never a second, differently-shaped copy of it
            # (requirement 10).
            registered_lookup = {row["name"]: row for row in capability_system.all()}

        for capability_name in required:
            handler_registered = self.has(capability_name)
            if not handler_registered and executable_registry is not None:
                # Purely additive fallback source of handlers - never
                # consulted unless the caller explicitly opted in by
                # supplying executable_registry (requirement 15).
                handler_registered = executable_registry.is_available(capability_name)
            if not handler_registered:
                missing_handlers.append(capability_name)

            if capability_system is None:
                # Existence/availability intentionally left unchecked
                # (see warning above) - same "omitting capability_system
                # skips this check rather than failing it" contract
                # PreflightValidator/PlanManager already use.
                exists = True
                available = True
            else:
                row = registered_lookup.get(capability_name)
                exists = row is not None
                available = exists and bool(row["enabled"])
                if not exists:
                    missing_capabilities.append(capability_name)
                elif not available:
                    unavailable_capabilities.append(capability_name)

            if not exists:
                status = "missing_capability"
            elif not available:
                status = "unavailable"
            elif not handler_registered:
                status = "missing_handler"
            else:
                status = "ready"

            capabilities.append({
                "capability_name": capability_name,
                "available": bool(available),
                "handler_registered": handler_registered,
                "status": status,
            })

        return CapabilityReadinessResult(
            capabilities=capabilities,
            missing_capabilities=missing_capabilities,
            unavailable_capabilities=unavailable_capabilities,
            missing_handlers=missing_handlers,
            warnings=warnings,
        )

    def __len__(self):
        return len(self._handlers)

    def __repr__(self):
        return f"CapabilityHandlerRegistry({list(self._handlers.keys())!r})"


def _validate_capability_name(capability_name):
    if not capability_name or not isinstance(capability_name, str) or not capability_name.strip():
        raise ValueError("capability_name must be a non-empty string.")
    return capability_name.strip()


def _validate_handler(handler):
    if handler is None or not callable(handler):
        raise TypeError("handler must be an explicit callable.")


def _validate_capability_object(capability):
    from .capability import Capability
    if not isinstance(capability, Capability):
        raise TypeError("capability must be a Capability instance.")
