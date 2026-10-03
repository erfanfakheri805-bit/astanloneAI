"""
Execution - Capability Output
=================================
`CapabilityOutput` is a small, standardized, safe record describing
the outcome of one capability execution - a stricter, opt-in sibling
of the existing, looser records already in this package:

    Capability.execute (capability.py)
        -> CapabilityExecutionResult (success/output/error/validation)
    ExecutionEngine.execute_capability_step (execution_engine.py)
        -> handler(step[, context]) -> raw return value
        -> ExecutionResult.output[capability_name] = raw return value

Neither of those is replaced or duplicated here (requirement: "do not
duplicate systems that already exist"). `CapabilityOutput` is a single,
uniform *shape* a handler (new or existing) can optionally produce -
or a caller can build from an existing `CapabilityExecutionResult` via
`CapabilityOutput.from_capability_execution_result` - so downstream
code (ExecutionResult, ExecutionContext) has one deterministic,
JSON-shaped record to reason about instead of an arbitrary handler
return value. An existing handler that still just returns a plain
dict/list/string/etc. (or nothing at all) keeps working completely
unchanged everywhere in this project - `CapabilityOutput` is never
required, only recognized when present (see execution_engine.py's
`execute_capability_step` and `_safe_previous_outputs`, and
execution_result.py's `attach_capability_output`).

Same "plain data in, plain data out, nothing hidden" convention as
ExecutionResult/ExecutionContext/CapabilityExecutionResult: a
CapabilityOutput is built once and only ever read afterward. Nothing
here calls a handler, decides *to* execute anything, or reaches into
PlanManager/ExecutionEngine/ExecutionHistory.

Safety (requirements 6/7/12/13):
  - `output`/`metadata` are always funneled through the same
    recursive, JSON-shaped safety walk `ensure_structured_data`
    (planning/plan.py) already performs for PlanStep input/output and
    ExecutionContext - see `_normalize_structured_value` below - so a
    CapabilityOutput can only ever hold `None`, `bool`, `int`, `float`,
    `str`, `list`, or `dict` (with string keys), nested arbitrarily.
  - Unlike `ensure_structured_data` (which raises TypeError the first
    time it finds anything else), normalization here never raises and
    never crashes the caller: an unsupported value anywhere in
    `output`/`metadata` is safely replaced with `None` in place, and a
    structured warning naming its type and location is recorded
    instead (requirement 13: "a failed normalization ... must produce
    a structured failure instead of crashing the entire execution
    system"). `validate()`/`is_successful()` then reflect that this
    happened - see below - so the failure is visible and structured,
    never silent and never a crash.
  - Nothing here ever calls eval(), exec(), subprocess, a shell
    command, opens a network connection, or calls an external AI API;
    no string held anywhere in a CapabilityOutput is ever interpreted
    as code, and no unsupported object is ever executed or evaluated -
    it is only ever inspected (via `isinstance`) and, if unsupported,
    discarded in favor of `None`.
"""

import copy
import itertools
from datetime import datetime, timezone

from .capability import CapabilityValidationResult


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Deterministic, process-wide fallback id source - same convention
# execution_result.py's `_generate_execution_id` already uses - so a
# CapabilityOutput built without an explicit `execution_id` (e.g. in a
# quick test or a standalone handler) still always gets a real,
# unique one rather than leaving the field empty.
_id_counter = itertools.count(1)


def _generate_execution_id():
    return f"capability-execution-{next(_id_counter)}"


# The fixed vocabulary `output_type` is drawn from - exactly the
# allowed leaf/container shapes `_normalize_structured_value` can ever
# produce (requirement 6), so `output_type` can never name something
# `output` itself could not actually be.
OUTPUT_TYPE_NONE = "none"
OUTPUT_TYPE_BOOL = "bool"
OUTPUT_TYPE_INT = "int"
OUTPUT_TYPE_FLOAT = "float"
OUTPUT_TYPE_STR = "str"
OUTPUT_TYPE_LIST = "list"
OUTPUT_TYPE_DICT = "dict"

ALL_OUTPUT_TYPES = frozenset({
    OUTPUT_TYPE_NONE, OUTPUT_TYPE_BOOL, OUTPUT_TYPE_INT, OUTPUT_TYPE_FLOAT,
    OUTPUT_TYPE_STR, OUTPUT_TYPE_LIST, OUTPUT_TYPE_DICT,
})


def _describe_output_type(value):
    """The `output_type` name for an already-normalized `value` (only
    ever called on data that already passed through
    `_normalize_structured_value`, so this always finds an exact
    match - `"unknown"` only exists as a last-resort, never-executed
    guard, not a real branch)."""
    if value is None:
        return OUTPUT_TYPE_NONE
    if isinstance(value, bool):
        return OUTPUT_TYPE_BOOL
    if isinstance(value, int):
        return OUTPUT_TYPE_INT
    if isinstance(value, float):
        return OUTPUT_TYPE_FLOAT
    if isinstance(value, str):
        return OUTPUT_TYPE_STR
    if isinstance(value, list):
        return OUTPUT_TYPE_LIST
    if isinstance(value, dict):
        return OUTPUT_TYPE_DICT
    return "unknown"  # pragma: no cover - unreachable for normalized data


def _normalize_structured_value(value, warnings, path):
    """Recursively walk `value` and return a safe, JSON-shaped
    version of it (requirement 12: "preserve valid primitive values;
    recursively validate lists and dictionaries; reject or safely
    represent unsupported objects"). Same allowed shape as
    `planning.plan.ensure_structured_data` - `None`, `bool`, `int`,
    `float`, `str`, `list`/`tuple` (returned as a fresh `list`), and
    `dict` with string keys - but this never raises: anything else
    (an arbitrary object, a non-string dict key, a function, an
    exception instance, bytes, a set, ...) is replaced with `None` in
    place and recorded in `warnings` as a short, structured string
    naming its type and location, so the caller gets a deterministic,
    safe result instead of a crash (requirement 13) or a silently
    dropped value.

    Never executes, evaluates, or calls anything held in `value` -
    every branch below only ever inspects `value`'s type via
    `isinstance`."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [
            _normalize_structured_value(item, warnings, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                warnings.append(
                    f"Non-string key at {path} ({key!r}) was dropped; "
                    "only string keys are allowed."
                )
                continue
            result[key] = _normalize_structured_value(item, warnings, f"{path}[{key!r}]")
        return result
    warnings.append(
        f"Unsupported value of type {type(value).__name__} at {path} "
        "was replaced with None."
    )
    return None


class CapabilityOutput:
    """A standardized, validated record of one capability execution's
    outcome. Purely a data record, same convention as ExecutionResult/
    ExecutionContext/CapabilityExecutionResult - it never decides *to*
    execute anything, never calls a handler, and never mutates
    anything outside itself.

    `output`/`metadata` are always normalized at construction time via
    `_normalize_structured_value` (requirements 6/12) - safe, never
    raises, never executes anything. If normalization had to replace
    anything unsupported, that fact is recorded both as entries in
    `warnings` and internally, so `validate()`/`is_successful()` can
    correctly report the resulting failure as structured data
    (requirement 13) rather than silently pretending the output was
    always safe.

    `__slots__` - no arbitrary attribute assignment - same convention
    ExecutionResult/ExecutionContext/CapabilityExecutionResult already
    follow."""

    __slots__ = (
        "success", "capability_name", "execution_id", "output", "output_type",
        "error", "warnings", "metadata", "created_at", "_had_unsafe_content",
    )

    def __init__(
        self,
        success,
        capability_name,
        execution_id=None,
        output=None,
        output_type=None,
        error=None,
        warnings=None,
        metadata=None,
        created_at=None,
    ):
        """Safe construction: always ends with a fully-formed, valid
        record or raises ValueError/TypeError (and creates nothing) -
        never a half-built object, same convention as ExecutionResult/
        ExecutionContext/Capability. `success` must be an actual
        `bool` (requirement: "success is a boolean" - never a truthy/
        falsy stand-in silently coerced, so a caller can never
        accidentally pass e.g. a status string and have it misread).
        `capability_name` is required and must be a non-empty string
        (requirement: "capability_name is valid"). `execution_id` is
        optional - if omitted, one is generated (see
        `_generate_execution_id`) so every CapabilityOutput always has
        one, same "never a dangling reference" rule ExecutionResult
        already applies to its own `execution_id`; if given, it must
        be a non-empty string (requirement: "execution_id is valid").

        `output`/`metadata` are never rejected outright for containing
        unsupported data - see `_normalize_structured_value` above -
        so construction itself never raises over *what a handler
        returned*; the safety outcome is instead visible afterward via
        `warnings`, `validate()`, and `is_successful()`."""
        if not isinstance(success, bool):
            raise TypeError("CapabilityOutput success must be a bool.")
        self.success = success

        if not capability_name or not isinstance(capability_name, str) or not capability_name.strip():
            raise ValueError("CapabilityOutput requires a non-empty capability_name string.")
        self.capability_name = capability_name.strip()

        if execution_id is not None and (
            not isinstance(execution_id, str) or not execution_id.strip()
        ):
            raise ValueError("CapabilityOutput execution_id must be a non-empty string when given.")
        self.execution_id = execution_id.strip() if execution_id else _generate_execution_id()

        normalization_warnings = []
        self.output = _normalize_structured_value(output, normalization_warnings, "output")
        had_unsafe_output = bool(normalization_warnings)

        if output_type is not None and (not isinstance(output_type, str) or not output_type.strip()):
            raise TypeError("CapabilityOutput output_type must be a non-empty string when given.")
        self.output_type = output_type.strip() if output_type else _describe_output_type(self.output)

        if error is not None and not isinstance(error, str):
            raise TypeError("CapabilityOutput error must be a string or None.")
        self.error = error

        self.warnings = []
        if warnings:
            if not isinstance(warnings, (list, tuple)):
                raise TypeError("CapabilityOutput warnings must be a list of strings or None.")
            for entry in warnings:
                if not isinstance(entry, str):
                    raise TypeError("CapabilityOutput warnings entries must all be strings.")
                self.warnings.append(entry)
        self.warnings.extend(normalization_warnings)

        metadata_warnings = []
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("CapabilityOutput metadata must be a dict or None.")
        self.metadata = (
            _normalize_structured_value(metadata, metadata_warnings, "metadata")
            if metadata
            else {}
        )
        had_unsafe_metadata = bool(metadata_warnings)
        self.warnings.extend(metadata_warnings)

        # Recorded once, at construction, purely so validate()/
        # is_successful() can deterministically report a normalization
        # failure later (requirement 13) without re-walking `output`/
        # `metadata` a second time.
        self._had_unsafe_content = had_unsafe_output or had_unsafe_metadata

        self.created_at = created_at if created_at is not None else _now_iso()

    def __repr__(self):
        return (
            f"CapabilityOutput(capability_name={self.capability_name!r}, "
            f"execution_id={self.execution_id!r}, success={self.success!r})"
        )

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------
    @classmethod
    def succeeded(
        cls, capability_name, execution_id=None, output=None, output_type=None,
        warnings=None, metadata=None, created_at=None,
    ):
        """Build a successful CapabilityOutput. Convenience wrapper
        around `__init__` with `success=True, error=None` - never
        anything a caller couldn't already do by calling `__init__`
        directly."""
        return cls(
            success=True,
            capability_name=capability_name,
            execution_id=execution_id,
            output=output,
            output_type=output_type,
            error=None,
            warnings=warnings,
            metadata=metadata,
            created_at=created_at,
        )

    @classmethod
    def failed(
        cls, capability_name, error, execution_id=None, output=None, output_type=None,
        warnings=None, metadata=None, created_at=None,
    ):
        """Build a failed CapabilityOutput. `error` is required and
        must be a non-empty string (requirement: "support ... failed
        capability executions" - a failure always names what went
        wrong, same "never a dangling/empty error" rule
        ExecutionResult.mark_failed's docstring already documents)."""
        if not error or not isinstance(error, str) or not error.strip():
            raise ValueError("CapabilityOutput.failed requires a non-empty error string.")
        return cls(
            success=False,
            capability_name=capability_name,
            execution_id=execution_id,
            output=output,
            output_type=output_type,
            error=error.strip(),
            warnings=warnings,
            metadata=metadata,
            created_at=created_at,
        )

    @classmethod
    def from_capability_execution_result(cls, capability_name, execution_id, result):
        """Build a CapabilityOutput from an existing
        `CapabilityExecutionResult` (capability.py) - reuses that
        record's own `success`/`output`/`error`/`validation` rather
        than a second, parallel execution path (requirement 8/15: "do
        not duplicate systems that already exist"; "integrate ...
        while remaining backward compatible"). The source
        `CapabilityExecutionResult`'s `validation`
        (`CapabilityValidationResult.to_dict()`), if present, is
        preserved under `metadata["validation"]` so nothing it already
        reported is lost."""
        from .capability import CapabilityExecutionResult  # local import - avoids a hard cycle
        if not isinstance(result, CapabilityExecutionResult):
            raise TypeError(
                "from_capability_execution_result requires a CapabilityExecutionResult instance."
            )
        metadata = None
        if result.validation is not None:
            metadata = {"validation": result.validation.to_dict()}
        if result.success:
            return cls.succeeded(
                capability_name=capability_name,
                execution_id=execution_id,
                output=result.output,
                metadata=metadata,
            )
        return cls.failed(
            capability_name=capability_name,
            execution_id=execution_id,
            error=result.error or "Capability execution failed.",
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self):
        """Verify this CapabilityOutput's own fields and return a
        `CapabilityValidationResult` (capability.py) - the exact same
        `{valid, errors}` shape `Capability.validate_input` already
        produces, reused rather than duplicated (requirement 15).
        Never raises; always returns a result, even when invalid.

        Checks (requirement 2): `capability_name` is a non-empty
        string; `execution_id` is a non-empty string; `success` is an
        actual `bool`; `output_type` is one of the fixed, safe
        vocabulary in `ALL_OUTPUT_TYPES`; `error` is a string or
        `None`; `warnings` is a list of strings; `metadata` is a dict.
        It also reports - as a structured error, not a crash
        (requirement 13) - if construction had to replace any
        unsupported value found in `output`/`metadata` with `None`."""
        errors = []

        if not self.capability_name or not isinstance(self.capability_name, str):
            errors.append({"field": "capability_name", "reason": "must be a non-empty string."})
        if not self.execution_id or not isinstance(self.execution_id, str):
            errors.append({"field": "execution_id", "reason": "must be a non-empty string."})
        if not isinstance(self.success, bool):
            errors.append({"field": "success", "reason": "must be a boolean."})
        if self.output_type not in ALL_OUTPUT_TYPES:
            errors.append({
                "field": "output_type",
                "reason": f"must be one of {sorted(ALL_OUTPUT_TYPES)}; got {self.output_type!r}.",
            })
        if self.error is not None and not isinstance(self.error, str):
            errors.append({"field": "error", "reason": "must be a string or None."})
        if not isinstance(self.warnings, list) or any(
            not isinstance(entry, str) for entry in self.warnings
        ):
            errors.append({"field": "warnings", "reason": "must be a list of strings."})
        if not isinstance(self.metadata, dict):
            errors.append({"field": "metadata", "reason": "must be a dict."})
        if self._had_unsafe_content:
            errors.append({
                "field": "output",
                "reason": (
                    "output or metadata contained unsupported data that was "
                    "replaced with None; see warnings for details."
                ),
            })

        return CapabilityValidationResult(valid=not errors, errors=errors)

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------
    def is_successful(self):
        """True only when `success` is `True`, this record's own
        `validate()` passes, and no `error` is present (requirement
        4) - all three, never just one. A CapabilityOutput can report
        `success=True` yet still be unsuccessful overall if, say, its
        output had to be safely sanitized (validation fails) or an
        `error` was nonetheless attached."""
        return bool(self.success) and self.validate().valid and self.error is None

    def get_output(self):
        """The normalized `output` (requirement 5) - always safe,
        JSON-shaped structured data (requirement 6), suitable for use
        as-is as a previous output in a later ExecutionContext
        (execution_context.py's `add_previous_output`/
        `previous_outputs` - requirement 9). Returns a defensive deep
        copy - same "callers get a copy, not a handle" convention
        `ExecutionContext.get_previous_outputs`/`get_metadata` already
        follow - so mutating the returned value can never reach back
        into this record's own state."""
        return copy.deepcopy(self.output)

    # ------------------------------------------------------------------
    # Structured representation
    # ------------------------------------------------------------------
    def to_dict(self):
        """Deterministic, JSON-shaped dictionary representation
        containing every field (requirement 3) - same convention as
        ExecutionResult.to_dict/ExecutionContext.to_dict/
        CapabilityExecutionResult.to_dict throughout this project."""
        return {
            "success": self.success,
            "capability_name": self.capability_name,
            "execution_id": self.execution_id,
            "output": copy.deepcopy(self.output),
            "output_type": self.output_type,
            "error": self.error,
            "warnings": list(self.warnings),
            "metadata": copy.deepcopy(self.metadata),
            "created_at": self.created_at,
        }


# ----------------------------------------------------------------------
# ExecutionContext data-flow integration (requirement 9)
# ----------------------------------------------------------------------
def unwrap_for_previous_output(value):
    """If `value` is a `CapabilityOutput`, return its already-
    normalized `get_output()` value so it can be handed directly to
    `ExecutionContext.add_previous_output`/used as a `previous_outputs`
    entry (requirement 9: "the normalized output should be suitable
    for use as a previous output in later ExecutionContext data
    flow"). For anything else - an existing handler's plain return
    value - `value` is returned completely unchanged, so existing,
    non-CapabilityOutput handler outputs flow through exactly as they
    always have (requirement 11: "existing handlers ... must continue
    working").

    Never executes, evaluates, or calls anything - only ever inspects
    `value`'s type."""
    if isinstance(value, CapabilityOutput):
        return value.get_output()
    return value
