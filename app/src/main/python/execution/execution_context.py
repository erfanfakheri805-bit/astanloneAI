"""
Execution - Execution Context
=================================
`ExecutionContext` is a small, safe, structured record describing the
runtime context of one specific attempt to execute one PlanStep (or,
for a specific required capability within that step, one capability
call within that attempt):

    ExecutionEngine.execute_capability_step (execution_engine.py)
        -> builds one ExecutionContext per handler call
        -> handed to the registered handler, alongside the existing
           PlanStep argument, in a backward-compatible way (see below)

This is deliberately a *plain data record*, same "plain data in, plain
data out, nothing hidden" convention the rest of this project already
follows (see execution_result.py's module docstring): a context is
built once, at the start of one execution attempt, and only ever
*read* or *appended to* afterward (`add_previous_output`/
`set_metadata` - see requirement 3) - it never decides anything, never
calls a handler itself, never writes a PlanStep's status or data, and
never reaches into PlanManager/ExecutionEngine/ExecutionHistory at
all. Building an ExecutionContext has no side effects on any of those.

Nothing in this module:
  - uses eval(), exec(), subprocess, a shell command, or opens any
    network connection (requirement 6);
  - evaluates any string value held in `input_data`/`previous_outputs`/
    `metadata` as Python code, or turns any piece of context data into
    a callable/import/attribute lookup of any kind (requirements 4-5)
    - every value passed into a context is funneled through
      `planning.plan.ensure_structured_data` (the exact same
      structured-data safety check `PlanStep.set_input`/`set_output`
      already use), so a context can only ever hold plain, JSON-safe
      data - never an arbitrary Python object, and never something
      that could be executed;
  - calls an AI API, a capability, or a capability handler - a context
    is only ever *handed to* a handler by the existing execution
    system (see execute_capability_step's own docstring update); it
    never calls anything itself.

`execution_id`, `plan_id`, `step_id`, and `capability_name` are
protected identifiers (requirement 7): each is assigned exactly once,
at construction, exposed only as a read-only property, and can never
be silently overwritten afterward - not through `set_metadata` (which
explicitly rejects any of those four names as a key), not through
`add_previous_output` (which only ever writes into
`previous_outputs`, a separate dict entirely), and not through any
other method this class exposes. A caller that wants a *different*
identifier must build a new ExecutionContext, never mutate an existing
one's identity.

Optional values (`capability_name`, `input_data`, `previous_outputs`,
`metadata`) all default safely to `None`/an empty structure when
omitted (requirement 8) - a context never requires more than the
`plan_id`/`step_id` every execution attempt already has.

Deterministic and lightweight (requirement 9): constructing a context
does no I/O, no randomness beyond a fresh `execution_id` when one
isn't supplied (the same `uuid4`-based, collision-free generation
approach - never a global counter - already used for execution/plan/
goal ids elsewhere in this project), and holds nothing but small,
already-validated, JSON-shaped data - no references to PlanManager,
ExecutionEngine, ExecutionHistory, or any other heavyweight object.
"""

import inspect
import uuid
from datetime import datetime, timezone

from planning.plan import ensure_structured_data


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_execution_id():
    return f"ctx-{uuid.uuid4().hex}"


# The fixed set of identifier keys that name *this* execution and can
# never be overwritten through set_metadata/add_previous_output -
# requirement 7 ("protect internal identifiers"). Assigned once, at
# construction (see ExecutionContext.__init__), and read-only for the
# lifetime of the object afterward.
PROTECTED_IDENTIFIER_KEYS = frozenset({
    "execution_id", "plan_id", "step_id", "capability_name",
})


class ExecutionContext:
    """One execution attempt's safe, structured runtime context. Not
    thread-safe (matches the rest of this project - see PlanManager/
    ExecutionEngine's own notes); a single ExecutionContext is meant
    to be built for, and used within, one handler call, never shared
    across concurrent executions.

    `__slots__` (no arbitrary attribute assignment - matches PlanStep/
    ExecutionResult/PreflightResult's own convention) so nothing else
    can be silently bolted onto a context after construction, on top
    of the identifier protection `set_metadata`/`add_previous_output`
    already enforce."""

    __slots__ = (
        "_execution_id", "_plan_id", "_step_id", "_capability_name",
        "_input_data", "_previous_outputs", "_metadata", "_created_at",
    )

    def __init__(
        self, plan_id, step_id, capability_name=None, input_data=None,
        previous_outputs=None, metadata=None, execution_id=None, created_at=None,
    ):
        """Raises ValueError - and constructs nothing - if `plan_id`/
        `step_id` are empty, whitespace-only, or not strings; every
        ExecutionContext always names a real plan/step it belongs to
        (requirement 7 - these are identifiers, never optional).
        `capability_name` is optional (a context can describe a plain
        `execute_step` attempt with no specific capability involved)
        but, if given, must be a string. Raises TypeError - and
        constructs nothing - if `input_data`/`previous_outputs`/
        `metadata` contain anything that isn't safe, JSON-shaped
        structured data (see `ensure_structured_data`; requirements
        1/4/5 - a context can never hold something that could be
        mistaken for executable code).

        `execution_id`/`created_at` are normally left to be generated
        here (a fresh `uuid4`-based id, and the current UTC time,
        respectively) - both can also be supplied explicitly (e.g. so
        a context shares the same `execution_id` as the
        `ExecutionResult` it accompanies), but only at construction
        time; neither is ever settable afterward (requirement 7)."""
        if not plan_id or not isinstance(plan_id, str):
            raise ValueError("ExecutionContext requires a non-empty plan_id string.")
        if not step_id or not isinstance(step_id, str):
            raise ValueError("ExecutionContext requires a non-empty step_id string.")
        if capability_name is not None and not isinstance(capability_name, str):
            raise TypeError("ExecutionContext capability_name must be a string or None.")
        if execution_id is not None and (
            not isinstance(execution_id, str) or not execution_id.strip()
        ):
            raise ValueError("ExecutionContext execution_id must be a non-empty string when given.")

        self._plan_id = plan_id
        self._step_id = step_id
        self._capability_name = capability_name
        self._execution_id = execution_id if execution_id else _new_execution_id()
        self._created_at = created_at if created_at is not None else _now_iso()

        self._input_data = (
            ensure_structured_data(input_data) if input_data is not None else None
        )

        self._previous_outputs = {}
        if previous_outputs:
            if not isinstance(previous_outputs, dict):
                raise TypeError(
                    "ExecutionContext previous_outputs must be a dict or None."
                )
            for key, value in previous_outputs.items():
                if not isinstance(key, str):
                    raise TypeError(
                        "ExecutionContext previous_outputs keys must be strings."
                    )
                self._previous_outputs[key] = ensure_structured_data(value)

        self._metadata = {}
        if metadata:
            if not isinstance(metadata, dict):
                raise TypeError("ExecutionContext metadata must be a dict or None.")
            for key, value in metadata.items():
                self._set_metadata_entry(key, value)

    def __repr__(self):
        return (
            f"ExecutionContext(execution_id={self._execution_id!r}, "
            f"plan_id={self._plan_id!r}, step_id={self._step_id!r}, "
            f"capability_name={self._capability_name!r})"
        )

    # ------------------------------------------------------------------
    # Protected identifiers - read-only properties (requirement 7)
    # ------------------------------------------------------------------
    @property
    def execution_id(self):
        return self._execution_id

    @property
    def plan_id(self):
        return self._plan_id

    @property
    def step_id(self):
        return self._step_id

    @property
    def capability_name(self):
        return self._capability_name

    @property
    def created_at(self):
        return self._created_at

    # ------------------------------------------------------------------
    # Accessors (requirement 2)
    # ------------------------------------------------------------------
    def get_input(self):
        """This context's `input_data`, or `None` if none was
        supplied. Never copies-on-read beyond what `ensure_structured_data`
        already defensively copied at construction (lists/dicts are
        already fresh containers - see that helper's own docstring in
        planning/plan.py) - same read-only-view convention
        `PlanStep.get_input` already follows."""
        return self._input_data

    def get_previous_outputs(self):
        """A defensive copy of this context's `previous_outputs` dict
        - mutating the returned dict never affects this context's own
        state (same "callers get a copy, not a handle" convention
        `to_dict()` already follows throughout this project)."""
        return dict(self._previous_outputs)

    def get_metadata(self):
        """A defensive copy of this context's `metadata` dict - same
        "callers get a copy, not a handle" convention as
        `get_previous_outputs`."""
        return dict(self._metadata)

    def get(self, key, default=None):
        """A single, uniform lookup across everything this context
        holds - metadata first, then the protected identifiers/
        `created_at`/`input_data`/`previous_outputs` themselves (so a
        caller doesn't need to remember which specific accessor a
        given key lives behind) - and `default` (defaults to `None`)
        for anything not found in any of those (requirement: "support
        missing optional values safely"). Never raises for an unknown
        `key`. A metadata entry always wins over a same-named built-in
        field (there isn't one - `_PROTECTED_KEYS` are exactly the
        names metadata itself refuses to accept - but this ordering is
        still the deterministic, documented rule)."""
        if key in self._metadata:
            return self._metadata[key]
        if key == "execution_id":
            return self._execution_id
        if key == "plan_id":
            return self._plan_id
        if key == "step_id":
            return self._step_id
        if key == "capability_name":
            return self._capability_name
        if key == "created_at":
            return self._created_at
        if key == "input_data":
            return self._input_data
        if key == "previous_outputs":
            return dict(self._previous_outputs)
        return default

    # ------------------------------------------------------------------
    # Controlled mutation (requirement 3)
    # ------------------------------------------------------------------
    def add_previous_output(self, step_id, output):
        """Record `output` (any safe, structured data - see
        `ensure_structured_data`; `None` is allowed) as the previously-
        produced output for `step_id`, so a later capability/handler
        within the same execution attempt can look it up via
        `get_previous_outputs()`/`get(step_id)`. Raises ValueError -
        and stores nothing - if `step_id` is empty, whitespace-only,
        or not a string. Raises TypeError - and stores nothing - if
        `output` isn't safe, JSON-shaped structured data. Overwrites
        any existing entry for the same `step_id` (an explicit,
        caller-driven update - never a merge). Returns `self`, for
        convenience (`context.add_previous_output(...).add_previous_output(...)`)."""
        if not step_id or not isinstance(step_id, str):
            raise ValueError("add_previous_output requires a non-empty step_id string.")
        self._previous_outputs[step_id] = (
            ensure_structured_data(output) if output is not None else None
        )
        return self

    def set_metadata(self, key, value):
        """Record `value` (any safe, structured data; `None` is
        allowed) under `key` in this context's metadata. Raises
        ValueError - and stores nothing - if `key` is empty,
        whitespace-only, or not a string, *or* if `key` is one of the
        protected identifier names (`execution_id`/`plan_id`/
        `step_id`/`capability_name` - requirement 7: these can never
        be silently replaced by arbitrary metadata). Raises TypeError
        - and stores nothing - if `value` isn't safe, JSON-shaped
        structured data. Overwrites any existing metadata entry for
        the same `key`. Returns `self`, for convenience."""
        self._set_metadata_entry(key, value)
        return self

    def _set_metadata_entry(self, key, value):
        """The one place `metadata` is ever actually written to -
        shared by `__init__`'s bulk `metadata=` argument and
        `set_metadata` above, so the exact same key/protection/value
        validation always applies no matter which path added an
        entry."""
        if not key or not isinstance(key, str):
            raise ValueError("Metadata key must be a non-empty string.")
        if key in PROTECTED_IDENTIFIER_KEYS:
            raise ValueError(
                f"{key!r} is a protected identifier and cannot be set via metadata."
            )
        self._metadata[key] = ensure_structured_data(value) if value is not None else None

    # ------------------------------------------------------------------
    # Structured representation
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation - same convention
        as ExecutionResult.to_dict/PreflightResult.to_dict throughout
        this project. Always includes every field this context holds,
        even when a value is `None`/empty, so a caller can rely on the
        shape without a `KeyError`."""
        return {
            "execution_id": self._execution_id,
            "plan_id": self._plan_id,
            "step_id": self._step_id,
            "capability_name": self._capability_name,
            "input_data": self._input_data,
            "previous_outputs": dict(self._previous_outputs),
            "metadata": dict(self._metadata),
            "created_at": self._created_at,
        }


# ----------------------------------------------------------------------
# Backward-compatible handler invocation (requirement 11)
# ----------------------------------------------------------------------
def call_handler_with_context(handler, step, context):
    """Call `handler` with `(step, context)` if `handler`'s own
    declared signature actually accepts two positional arguments,
    otherwise fall back to the original, pre-ExecutionContext
    `handler(step)` call - so an existing handler that was only ever
    written to expect a single PlanStep argument keeps working exactly
    as it always did (requirement 11: "existing handlers that only
    expect their previous input format must continue working"), while
    a new handler written to also accept an ExecutionContext receives
    one automatically, with no registration-time flag or opt-in
    required from the caller.

    This is decided purely by inspecting `handler`'s own signature via
    `inspect.signature`/`Signature.bind` - never by calling `handler`
    speculatively, never by catching a `TypeError` raised *from
    inside* a call and guessing whether it meant "wrong arity" or
    "the handler's own logic legitimately raised TypeError" (which
    would risk silently swallowing a genuine handler bug). If
    `handler` has no introspectable signature at all (e.g. some
    builtins/C-implemented callables), this falls back to the
    original single-argument call - the same safe default as any
    handler whose signature doesn't accept two positional arguments.

    Never uses eval(), exec(), or any other form of dynamic code
    execution - this only reads `handler`'s already-declared parameter
    list, exactly the same static information `help(handler)` would
    show."""
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler(step)
    try:
        signature.bind(step, context)
    except TypeError:
        return handler(step)
    return handler(step, context)
