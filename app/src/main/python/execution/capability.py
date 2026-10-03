"""
Execution - Standard Capability Interface
=============================================
`Capability` is a small, explicit, self-contained wrapper around one
executable capability:

    NAME + SCHEMA + AN EXPLICIT HANDLER -> Capability
        -> validate_input(data) -> execute(data) -> CapabilityExecutionResult

It is a *third*, separate concept from the other two capability-shaped
things already in this project:
  - `capabilities.capability_system.CapabilitySystem` tracks whether a
    capability is registered/enabled at all (a yes/no, persisted in
    `memory`'s `capabilities` table);
  - `execution.capability_handlers.CapabilityHandlerRegistry` maps a
    capability *name* to whatever plain callable should run for it.
Neither of those describes the shape of a capability itself - what
input it expects, what it returns, what version it is. `Capability`
fills exactly that gap: one small, uniform, introspectable object a
caller can construct once and then validate/execute/describe through
the same four methods, no matter what the underlying handler actually
does.

This module never executes anything on its own initiative. A
`Capability` only ever calls the one callable it was explicitly built
with (`handler` - required, no default, never auto-discovered, same
"no execution without an explicit handler" rule already enforced by
execution_engine.py and execution/capability_handlers.py); it never
scans modules, entry points, decorators, or naming conventions to find
a handler, and it never creates, enables, or registers a capability
anywhere else. It also never uses eval(), exec(), subprocess, a shell
command, or network/filesystem access - a "handler" is always just an
ordinary Python callable the caller already wrote and already owns.

`validate_input`/`execute` are deterministic: the same `data` against
the same `input_schema` always produces the same validation outcome,
and `execute` never does anything except (1) validate, (2) call the
one registered handler, and (3) report what happened - it never
retries, never falls back to a different handler, and never mutates
`data` before handing it to the handler.

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows (see execution_result.py's module
docstring): `validate_input` returns a `CapabilityValidationResult` and
`execute` returns a `CapabilityExecutionResult`, both plain,
JSON-shaped records with a `to_dict()` method, rather than a bare bool
or a formatted message.
"""


# ----------------------------------------------------------------------
# Schema vocabulary
# ----------------------------------------------------------------------
# `input_schema`/`output_schema` are a small, fixed, JSON-Schema-like
# subset - deliberately not the full JSON Schema spec (no $ref, no
# oneOf/anyOf, no regex patterns) so validation stays deterministic and
# easy to reason about:
#
#   {
#       "type": "object",                 # optional, defaults to "object"
#       "properties": {
#           "field_name": {"type": "string", "required": True},
#           "other_field": {"type": "integer"},   # required defaults to False
#       },
#       "additionalProperties": False,    # optional, defaults to True
#   }
#
# A `None` or `{}` schema imposes no constraints at all - `validate_input`
# always succeeds in that case, regardless of `data`. An unrecognized
# `type` name is treated as "any" (always matches) rather than raising -
# same "never surprise a caller with a validation failure that has
# nothing to do with their actual data" reasoning already used
# elsewhere in this project for optional/omitted inputs.
_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
    "null": lambda value: value is None,
}


def _matches_type(value, type_name):
    check = _TYPE_CHECKS.get(type_name)
    if check is None:
        # Unknown/"any" type name - deterministic no-op match, never a
        # crash and never a silently-invented stricter rule.
        return True
    return check(value)


class CapabilityValidationResult:
    """The outcome of one `Capability.validate_input` call. Purely a
    data record - never decides *to* execute anything and never calls
    the handler. Same convention as PreflightResult
    (execution/preflight.py): `errors` is always a plain list of
    `{"field": <name-or-None>, "reason": <str>}` dicts (never None),
    and `valid` can never disagree with it - adding an error always
    means invalid, no matter what `valid` a caller separately passed
    in."""

    __slots__ = ("valid", "errors")

    def __init__(self, valid=True, errors=None):
        self.errors = list(errors) if errors else []
        self.valid = bool(valid) and not self.errors

    def __repr__(self):
        return f"CapabilityValidationResult(valid={self.valid!r}, errors={len(self.errors)})"

    def to_dict(self):
        """Structured (JSON-shaped) representation - same convention
        as ExecutionResult.to_dict/PreflightResult.to_dict."""
        return {"valid": self.valid, "errors": [dict(entry) for entry in self.errors]}


class CapabilityExecutionResult:
    """The outcome of one `Capability.execute` call. Purely a data
    record, same convention as ExecutionResult
    (execution/execution_result.py) - it does not itself run anything;
    it only reports what already happened. `validation` is always the
    `CapabilityValidationResult` `execute` produced along the way (even
    on success), so a caller never has to call `validate_input` a
    second time just to see it.

    `success` and `error` can never both be meaningful at once in a way
    that disagrees with each other: a successful result always has
    `error is None`, and a failed result always has `output is None` -
    enforced in the constructor, not left to the caller to keep in
    sync (same "derived, never independently trusted" rule
    CapabilityReadinessResult.ready already follows - see
    execution/capability_handlers.py)."""

    __slots__ = ("success", "output", "error", "validation")

    def __init__(self, success, output=None, error=None, validation=None):
        self.success = bool(success)
        self.output = output if self.success else None
        self.error = None if self.success else error
        self.validation = validation

    def __repr__(self):
        return f"CapabilityExecutionResult(success={self.success!r})"

    def to_dict(self):
        """Structured (JSON-shaped) representation - same convention
        as ExecutionResult.to_dict."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "validation": self.validation.to_dict() if self.validation is not None else None,
        }


class Capability:
    """One executable capability: a name, a human description, a
    version, an input/output schema pair, an explicit handler, and a
    free-form metadata dict. Always either a fully-formed, valid
    object or a raised exception - never a half-built one (same "safe
    construction" convention as ExecutionResult/CapabilityHandlerRegistry
    entries).

    `handler` is required and must be an explicit callable - never
    `None`, never a string that gets turned into code, never
    auto-discovered. Nothing in this class ever inspects `handler`'s
    internals, imports it dynamically, or calls it anywhere except
    inside `execute()` (and, for backward-compatible direct calls via
    `__call__` - see below).
    """

    __slots__ = (
        "name", "description", "version", "input_schema", "output_schema",
        "handler", "metadata",
    )

    def __init__(
        self, name, handler, description="", version="1.0.0",
        input_schema=None, output_schema=None, metadata=None,
    ):
        """Raises ValueError - and constructs nothing - if `name` is
        empty, whitespace-only, or not a string. Raises TypeError -
        and constructs nothing - if `handler` is `None` or anything
        that isn't callable. Raises TypeError - and constructs nothing
        - if `description`/`version` are given but aren't strings, or
        if `input_schema`/`output_schema`/`metadata` are given but
        aren't dicts. Never calls `handler` during construction."""
        self.name = _validate_name(name)
        _validate_handler(handler)
        self.handler = handler

        if description is not None and not isinstance(description, str):
            raise TypeError("Capability description must be a string.")
        self.description = description or ""

        if not isinstance(version, str) or not version.strip():
            raise TypeError("Capability version must be a non-empty string.")
        self.version = version

        if input_schema is not None and not isinstance(input_schema, dict):
            raise TypeError("Capability input_schema must be a dict or None.")
        self.input_schema = dict(input_schema) if input_schema else {}

        if output_schema is not None and not isinstance(output_schema, dict):
            raise TypeError("Capability output_schema must be a dict or None.")
        self.output_schema = dict(output_schema) if output_schema else {}

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("Capability metadata must be a dict or None.")
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return f"Capability(name={self.name!r}, version={self.version!r})"

    # ------------------------------------------------------------------
    # Backward-compatible direct call
    # ------------------------------------------------------------------
    def __call__(self, *args, **kwargs):
        """Delegates directly to the registered handler, unchanged
        call signature and no validation/result-wrapping - this is
        what lets a `Capability` be dropped anywhere a plain callable
        handler was already accepted (e.g.
        `execution.capability_handlers.CapabilityHandlerRegistry`,
        which only ever requires `callable(handler)`), without forcing
        that caller to know about schemas, `execute()`, or
        `CapabilityExecutionResult` at all. For schema-validated,
        structured execution, call `execute()` instead."""
        return self.handler(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_input(self, data):
        """Deterministic validation of `data` against `self.input_schema`
        - never calls `self.handler`, never mutates `data`, and never
        raises for invalid `data` (invalid input is reported in the
        returned `CapabilityValidationResult`, not an exception - the
        same "plain data in, plain data out" contract this module's
        docstring describes). Returns a `CapabilityValidationResult`.

        An empty/omitted `input_schema` imposes no constraints and
        always validates successfully, regardless of `data`. Otherwise:
          - if the schema's top-level `type` (default `"object"`) is
            `"object"`, `data` must be a dict; each declared property
            is checked for presence (when `required: True`) and, if
            present, for a matching `type`; if the schema sets
            `additionalProperties: False`, any field in `data` that
            isn't declared in `properties` is also an error;
          - for any other top-level `type`, `data` itself is checked
            against that type directly (no `properties` lookup).
        """
        schema = self.input_schema
        if not schema:
            return CapabilityValidationResult(valid=True, errors=[])

        errors = []
        expected_type = schema.get("type", "object")

        if expected_type == "object":
            if not isinstance(data, dict):
                errors.append({
                    "field": None,
                    "reason": "Input data must be an object (dict).",
                })
                return CapabilityValidationResult(valid=False, errors=errors)

            properties = schema.get("properties") or {}
            for field_name, field_spec in properties.items():
                field_spec = field_spec or {}
                required = bool(field_spec.get("required", False))
                if field_name not in data:
                    if required:
                        errors.append({
                            "field": field_name,
                            "reason": "Required field is missing.",
                        })
                    continue

                type_name = field_spec.get("type")
                if type_name and not _matches_type(data[field_name], type_name):
                    errors.append({
                        "field": field_name,
                        "reason": (
                            f"Expected type {type_name!r}, got "
                            f"{type(data[field_name]).__name__!r}."
                        ),
                    })

            if schema.get("additionalProperties", True) is False:
                for field_name in data:
                    if field_name not in properties:
                        errors.append({
                            "field": field_name,
                            "reason": "Field is not allowed by input_schema.",
                        })
        else:
            if not _matches_type(data, expected_type):
                errors.append({
                    "field": None,
                    "reason": (
                        f"Expected type {expected_type!r}, got "
                        f"{type(data).__name__!r}."
                    ),
                })

        return CapabilityValidationResult(valid=not errors, errors=errors)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(self, data):
        """Validate `data`, then - only if valid - call the explicitly
        registered `self.handler(data)` and report the outcome.
        Returns a `CapabilityExecutionResult`; never raises for a
        validation failure or a handler error (both are reported in
        the result, not propagated as an exception).

        Order is fixed and always the same: (1) `validate_input(data)`
        - if invalid, `self.handler` is never called at all, and the
        returned result is a failure carrying that validation; (2)
        call `self.handler(data)` - the *only* callable this method
        ever invokes, never a different handler and never a second,
        differently-named lookup; (3) on a normal return, wrap the
        return value as a successful result; on any exception, catch
        it and wrap a safe description (the exception's type name and
        message, never a raw traceback) as a failed result - same
        "a handler that raises never crashes the caller" rule already
        used by ExecutionEngine.execute_step (execution_engine.py)."""
        validation = self.validate_input(data)
        if not validation.valid:
            return CapabilityExecutionResult(
                success=False,
                error="Input validation failed.",
                validation=validation,
            )

        try:
            output = self.handler(data)
        except Exception as exc:
            return CapabilityExecutionResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                validation=validation,
            )

        return CapabilityExecutionResult(success=True, output=output, validation=validation)

    # ------------------------------------------------------------------
    # Introspection / serialization
    # ------------------------------------------------------------------
    def describe(self):
        """A structured, human/introspection-oriented description of
        this capability - what a UI, a planner, or a future
        Capability directory would show *about* it, without needing to
        call it. Never calls `self.handler`. Currently identical in
        content to `to_dict()` (see that method) - kept as a distinct
        method because "describe what I am" and "serialize me" are
        different callers' intents even when today they produce the
        same shape, and a future stage may grow one independently of
        the other without disturbing the other's contract."""
        return self.to_dict()

    def to_dict(self):
        """Structured (JSON-shaped) representation - the general-
        purpose serialization for a UI, a test, or a future Capability
        directory. Same convention as ExecutionResult.to_dict/
        CapabilityHandlerRegistry's result types (see module
        docstring). `handler` itself (a live Python callable) is never
        JSON-shaped data, so it's represented here only by its name
        (or, for a handler with no `__name__`, e.g. a lambda assigned
        to a variable or a callable object, its `repr`) - enough to
        identify which handler is registered without pretending a
        function object is serializable data."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "metadata": dict(self.metadata),
            "handler": getattr(self.handler, "__name__", repr(self.handler)),
        }


def _validate_name(name):
    if not name or not isinstance(name, str) or not name.strip():
        raise ValueError("Capability name must be a non-empty string.")
    return name.strip()


def _validate_handler(handler):
    if handler is None or not callable(handler):
        raise TypeError("Capability handler must be an explicit callable.")
