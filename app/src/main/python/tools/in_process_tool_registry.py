"""
In-Process Tool Registry and Tool Metadata Contract (Prompt 697, Section 5 foundation)
=========================================================================================
The smallest deterministic registry of caller-provided, in-process tool handlers:

    ToolSpec(name, description, handler, input_schema, output_description, enabled)
        -> InProcessToolRegistry.register(spec) -> ToolRegistrationResult
        -> InProcessToolRegistry.invoke(name, tool_input) -> ToolInvocationResult   (explicit caller action)

This sits NEXT TO the existing definition-only `ToolDefinition`/`ToolRegistry` (Prompts before 697), which are
unchanged: those describe a tool's shape and have no handler; this contract adds the callable handler and the
"is it invokable" gate. Nothing here is wired into `process_input()`, the Agent Loop, Section 4 or any execution flow.

CONTRACT
- Names are stable, exact and case-sensitive: `^[a-z][a-z0-9_]{0,63}$`. No normalization, aliasing or fuzzy match.
- `ToolSpec` construction never raises; `validate_tool_spec()` reports problems with stable codes in field order.
  Required: valid name, non-blank description, callable handler, JSON-safe dict `input_schema` (descriptive metadata
  only - it is stored, never enforced or interpreted), non-blank `output_description`, real-bool `enabled`.
- `register()` validates first and rejects (never raises, never repairs) invalid specs and duplicate names
  (`DUPLICATE_TOOL_NAME`; the first registration is left untouched). The registry keeps its own copy of the metadata
  and the single authoritative `enabled` flag; later edits to the caller's spec object change nothing.
- Lookup (`has`, `describe`, `is_invokable`) is exact. Unknown names give False/None, never a guess.
- `enable(name)` / `disable(name)` are explicit caller actions. A disabled or unknown tool is NEVER invokable:
  `invoke()` rejects it (`UNKNOWN_TOOL` / `TOOL_DISABLED`) without calling the handler.
- `invoke()` is caller-driven: it calls the handler exactly once, in-process, with a deep copy of the caller's
  JSON-safe dict input. A handler `Exception` is caught and reported (`TOOL_HANDLER_EXCEPTION`, status `failed`); a
  non-JSON-safe return value is reported `TOOL_OUTPUT_INVALID`. No retries, no fallback tool, no scheduling, no threads.
- Listings are sorted by name, so the same registrations always give the same results. `describe()` never exposes the
  handler. There is no module-level registry: state lives only in an instance the caller creates.

INVOCATION AUDIT TRAIL (Prompt 698): every `invoke()` call that returns appends ONE `ToolInvocationRecord` to an
instance-local, in-memory history (invocation order; `sequence` is 1-based). A record is built only from the
`ToolInvocationResult` the call already produced - nothing is re-decided - and holds: `sequence`, `tool_name` (the name
when it is a string, else None), `status`, `ok`, `outcome_code` (`TOOL_COMPLETED`, or the first failure code),
`handler_called`, `input_json_safe`/`input_type`/`input` (a deep copy when the input is JSON-safe, else None; never a
repr, so records stay deterministic), `output_available`/`output` (deep copy, only for a completed call) and `failures`.
The handler is never stored. `get_invocation_history()` is the explicit read-only inspection method and returns fresh
deep-copied dicts, so callers cannot mutate the history and reading never changes it. The history is unbounded, lives
only in the instance, and nothing is written anywhere. A `BaseException` from a handler still propagates unrecorded.

EXPLICIT PERMISSION / CONFIRMATION GATE (Prompt 699): `ToolSpec.permissions` lists what a tool needs, using the EXISTING
closed vocabulary `tools.tool_definition.SUPPORTED_PERMISSIONS` (network / filesystem / external_application /
user_account / user_confirmation); `permissions` defaults to empty and is validated (`INVALID_TOOL_PERMISSIONS`). The
caller authorizes ONE call with `invoke(name, tool_input, granted_permissions=None, confirmed=False)`:
- a tool needing permissions is DENIED by default; each needed permission (other than `user_confirmation`) must be named in
  `granted_permissions` -> else `TOOL_PERMISSION_DENIED` (decision `denied`, missing names listed);
- a tool that lists `user_confirmation` also needs `confirmed=True` (a real bool; naming `user_confirmation` in
  `granted_permissions` is NOT a confirmation) -> else `TOOL_CONFIRMATION_REQUIRED` (decision `confirmation_required`);
  permission denial is reported before a missing confirmation;
- malformed authorization arguments (not a list/tuple/set/frozenset of supported permission names, or `confirmed` not a
  bool) -> `INVALID_TOOL_AUTHORIZATION`;
- otherwise the decision is `accepted` (or `not_required` for a tool that lists no permissions - unchanged old behavior).
The gate runs after the unknown/disabled checks and before input validation; a rejection never calls the handler. The
decision is derived only from the arguments of this call: nothing is inferred, auto-granted, remembered or shared between
calls, and the registry holds no authorization state. Every record carries `authorization_decision` (`not_evaluated` when the
call was rejected before the gate: unknown/disabled tool), `authorization_code` (the rejection code or None),
`required_permissions`, `granted_permissions` (sorted, deduplicated, as supplied) and `confirmed`.

CONTROLLED EXECUTION CONTRACT (Prompt 700): `execute(name, tool_input, granted_permissions=None, confirmed=False)` is the
caller-facing wrapper around `invoke()`. It runs `invoke()` once (same gate, same single audit record, same at-most-once handler
call) and returns a `ToolExecutionResult` built from the audit record that call just appended, so result and record cannot
disagree. `execution_status` is one of: `succeeded` (TOOL_COMPLETED), `handler_failed` (TOOL_HANDLER_EXCEPTION /
TOOL_OUTPUT_INVALID; handler was called), `authorization_rejected` (TOOL_PERMISSION_DENIED / TOOL_CONFIRMATION_REQUIRED /
INVALID_TOOL_AUTHORIZATION), `input_rejected` (INVALID_TOOL_INPUT, after authorization was accepted) and `tool_rejected`
(UNKNOWN_TOOL / TOOL_DISABLED, before the gate). Fields: `tool_name`, `execution_status`, `outcome_code`,
`authorization_accepted` (True only for decision accepted / not_required), `authorization_decision`, `handler_called`,
`output_available`, `output` (deep copy; None unless succeeded), `failures`, `sequence` (the audit record's number). The
permission/confirmation gate stays the only authorization boundary; the result never holds or exposes the handler; nothing
is retried, scheduled or auto-run. `invoke()` and its return value are unchanged.

CAPABILITY REQUIREMENTS & PREFLIGHT (Prompt 701): `ToolSpec.capabilities` (optional, default empty) lists the capabilities a tool
requires. It reuses the existing `ToolDefinition.capabilities` convention (a list of capability-name strings, free-form, no
fixed vocabulary, nothing is discovered or interpreted) and the registry's own name format `^[a-z][a-z0-9_]{0,63}$` (the
same snake_case style as the planned application capabilities); no competing capability system is created. Validation
rejects a non-list/tuple or malformed name (`INVALID_TOOL_CAPABILITIES`) and duplicate names (`DUPLICATE_TOOL_CAPABILITY`).
The registry stores a sorted private copy (`get_required_capabilities(name)`); `describe()` is unchanged.
The caller authorizes capabilities per call with `granted_capabilities=` (list/tuple/set/frozenset of valid names, default
none) on `invoke()`, `execute()` and `preflight()`. Nothing is inferred from names, descriptions, permissions, the request or
earlier calls, and nothing is stored or cached.
`_evaluate()` is the ONE authoritative, read-only check, in this order: tool exists (`UNKNOWN_TOOL`) -> enabled
(`TOOL_DISABLED`) -> authorization arguments well-formed (`INVALID_TOOL_AUTHORIZATION`) -> permissions (`TOOL_PERMISSION_DENIED`)
-> confirmation (`TOOL_CONFIRMATION_REQUIRED`) -> capabilities (`TOOL_CAPABILITY_MISSING`, decision `capability_missing`,
`missing_capabilities` listed) -> input validity (`INVALID_TOOL_INPUT`). It stops at the first failure. `invoke()` (and so
`execute()`) runs it before the handler, so neither can bypass it; `preflight(name, tool_input, granted_permissions=None,
confirmed=False, granted_capabilities=None)` runs the same check and returns a `ToolPreflightResult` WITHOUT calling the
handler, WITHOUT appending an audit record and without changing any state. Result fields: `tool_name`, `tool_exists`,
`tool_enabled`, `authorization_decision`, `authorization_accepted`, `required/granted_permissions`, `confirmed`,
`required/granted/missing_capabilities`, `input_valid` (True/False, or None when input was not reached), `preflight_status`
(`passed` / `rejected`), `outcome_code` (`TOOL_PREFLIGHT_PASSED` or the first failure code), `failure_codes`, `failures`. A
capability rejection is an `authorization_rejected` execution status. Records gain `required_capabilities` and
`granted_capabilities`.

OUTPUT VALIDATION & NORMALIZATION (Prompt 702): every handler return value is passed through `normalize_tool_output()`, a pure
function that rebuilds it as plain JSON data (exact `dict`/`list`/`str`/`int`/`float`/`bool`/`None`) using only the base types'
unbound methods, so no handler-supplied code (overridden `__iter__`, `__str__`, `__deepcopy__`, ...) is ever run, and the caller
never receives the handler's own object. Nothing is coerced: tuples, sets, bytes, NaN/inf, non-str keys, other types and
nesting deeper than `MAX_OUTPUT_DEPTH` (which also stops cyclic structures; previously a cycle raised RecursionError out of
`invoke()`) are rejected as `TOOL_OUTPUT_INVALID` (handler ran, execution status `handler_failed`, unchanged). Subclass instances
of the JSON types are rebuilt as their plain base type (same value). Key order is preserved.
Existing output metadata is only `output_description`, a free-text string: it stays descriptive-only and is never parsed or
enforced. The single enforceable, optional addition is `ToolSpec.output_type` (default None = no validation, unchanged
behavior), one JSON type name from `OUTPUT_TYPES` (object, array, string, number, integer, boolean, null; `number` accepts int or
float, `integer` only int, neither accepts bool; no coercion), validated at registration (`INVALID_TOOL_OUTPUT_TYPE`). When
declared, a JSON-safe output of another type is rejected as `TOOL_OUTPUT_VALIDATION_FAILED` (status `failed`; failure carries
`expected_type` and `actual_type` as JSON type names; the output is not exposed); the execution status is `output_invalid`
(the handler ran and returned, but its output was rejected). The four outcomes stay distinct: `succeeded`; `output_invalid`
(and `handler_failed` for exception / non-JSON-safe output); rejections before the handler (`tool_rejected`,
`authorization_rejected`, `input_rejected`). Audit records agree with the final outcome (outcome_code, handler_called, no
output for a rejected output). The handler is never retried. `describe()` is unchanged; `get_output_type(name)` reads it.

TOOLREQUEST ENTRY POINT & CONTRACT AUDIT (Prompt 704): `execute_request(request)` accepts a `tools.tool_request.ToolRequest` (data only;
it grants nothing) and runs `self.execute(**request.to_registry_arguments())`: the same single `_evaluate()` check, handler gate,
output validation and exactly one audit record as a direct `execute()`; there is no second execution path and no duplicated rule.
Anything that is not a usable `ToolRequest` (wrong type, or an instance forged without `create_tool_request()`) gives the new code
`INVALID_TOOL_REQUEST` (execution status `tool_rejected`, handler never called, tool_name None), audited like any other rejected call.
Audit fixes at this boundary (all one root cause: two competing "JSON-safe" authorities): `_json_safe` now delegates to
`normalize_tool_output`, so schema/input checks never recurse without bound (a cyclic or very deep input/schema used to raise
`RecursionError` out of `preflight()`/`invoke()`/`register()`, before any audit record) and never run caller-supplied hooks;
`_evaluate()` now normalizes the input once and the handler receives THAT plain private copy (before, a dict subclass with its own
`__deepcopy__` could hand the handler the caller's own object), the audit record and stored `input_schema` are plain copies too. Input
nested deeper than `MAX_OUTPUT_DEPTH` is now `INVALID_TOOL_INPUT` (it was previously accepted or crashed, depending on the stack).
`_NAME_RE` now uses a true end-of-string anchor (the code comment on it explains): a dollar-sign anchor also matched before a trailing
newline, so a name or capability with a trailing newline was registrable, contradicting the exact-name contract above.

Imports only `copy`, `math`, `re`, the existing permission vocabulary from `tools.tool_definition` (which imports nothing) and, lazily
inside `execute_request()`, `tools.tool_request` (which imports this module): no network, filesystem, subprocess or engine access.
"""

import copy
import math
import re

from tools.tool_definition import SUPPORTED_PERMISSIONS

STATUS_REGISTERED = "registered"
STATUS_REGISTRATION_REJECTED = "rejected"
STATUS_INVOCATION_COMPLETED = "completed"
STATUS_INVOCATION_FAILED = "failed"          # the handler was called and did not deliver a valid result
STATUS_INVOCATION_REJECTED = "rejected"      # a precondition failed; the handler was never called

TOOL_INVALID_SPEC = "INVALID_TOOL_SPEC"
TOOL_INVALID_NAME = "INVALID_TOOL_NAME"
TOOL_INVALID_DESCRIPTION = "INVALID_TOOL_DESCRIPTION"
TOOL_INVALID_HANDLER = "INVALID_TOOL_HANDLER"
TOOL_INVALID_INPUT_SCHEMA = "INVALID_TOOL_INPUT_SCHEMA"
TOOL_INVALID_OUTPUT_DESCRIPTION = "INVALID_TOOL_OUTPUT_DESCRIPTION"
TOOL_INVALID_ENABLED = "INVALID_TOOL_ENABLED"
TOOL_DUPLICATE_NAME = "DUPLICATE_TOOL_NAME"
TOOL_COMPLETED = "TOOL_COMPLETED"           # outcome_code of a successful invocation record
TOOL_UNKNOWN = "UNKNOWN_TOOL"
TOOL_DISABLED = "TOOL_DISABLED"
TOOL_INVALID_INPUT = "INVALID_TOOL_INPUT"
TOOL_HANDLER_EXCEPTION = "TOOL_HANDLER_EXCEPTION"
TOOL_OUTPUT_INVALID = "TOOL_OUTPUT_INVALID"
TOOL_INVALID_PERMISSIONS = "INVALID_TOOL_PERMISSIONS"
TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
TOOL_CONFIRMATION_REQUIRED = "TOOL_CONFIRMATION_REQUIRED"
TOOL_INVALID_AUTHORIZATION = "INVALID_TOOL_AUTHORIZATION"
TOOL_INVALID_CAPABILITIES = "INVALID_TOOL_CAPABILITIES"
TOOL_DUPLICATE_CAPABILITY = "DUPLICATE_TOOL_CAPABILITY"
TOOL_CAPABILITY_MISSING = "TOOL_CAPABILITY_MISSING"
TOOL_PREFLIGHT_PASSED = "TOOL_PREFLIGHT_PASSED"
TOOL_INVALID_OUTPUT_TYPE = "INVALID_TOOL_OUTPUT_TYPE"
TOOL_OUTPUT_VALIDATION_FAILED = "TOOL_OUTPUT_VALIDATION_FAILED"
TOOL_INVALID_REQUEST = "INVALID_TOOL_REQUEST"           # execute_request() was not given a usable ToolRequest
PREFLIGHT_PASSED = "passed"
PREFLIGHT_REJECTED = "rejected"
AUTH_CAPABILITY_MISSING = "capability_missing"

AUTH_NOT_EVALUATED = "not_evaluated"          # rejected before the gate (unknown / disabled tool)
AUTH_NOT_REQUIRED = "not_required"            # the tool lists no permissions
AUTH_ACCEPTED = "accepted"
AUTH_DENIED = "denied"
AUTH_CONFIRMATION_REQUIRED = "confirmation_required"
AUTH_INVALID = "invalid"                      # malformed authorization arguments
CONFIRMATION_PERMISSION = "user_confirmation"  # existing vocabulary entry; satisfied ONLY by confirmed=True

OUTPUT_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")
MAX_OUTPUT_DEPTH = 100

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")   # \Z, not $: "$" also matches before a trailing newline
_MAX_MESSAGE = 500


def _failure(code, message, **details):
    failure = {"code": code, "message": message}
    failure.update(details)
    return failure


def _json_safe(value):
    """True only for plain JSON data (see `normalize_tool_output`): the ONE JSON-safety authority. Never raises, never runs
    code supplied by the value, and rejects cycles/over-deep nesting instead of recursing without bound."""
    return normalize_tool_output(value)[0]


def _json_type(value):
    """JSON type name of an already-normalized value: object/array/string/integer/number/boolean/null."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _normalize(value, depth):
    if depth > MAX_OUTPUT_DEPTH:
        raise ValueError("too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, int):
        return int.__int__(value)
    if isinstance(value, float):
        exact = float.__float__(value)
        if not math.isfinite(exact):
            raise ValueError("non-finite float")
        return exact
    if isinstance(value, list):
        return [_normalize(item, depth + 1) for item in list.__iter__(value)]
    if isinstance(value, dict):
        out = {}
        for key, item in dict.items(value):
            if not isinstance(key, str):
                raise ValueError("non-str key")
            out[str.__str__(key)] = _normalize(item, depth + 1)
        return out
    raise ValueError("not JSON data")


def normalize_tool_output(value):
    """Pure, deterministic. Returns `(True, fresh_plain_json_copy)` or `(False, None)`. Never coerces between types, never
    runs code supplied by the value, never mutates it."""
    try:
        return True, _normalize(value, 0)
    except (ValueError, RecursionError):
        return False, None


def output_matches_type(value, output_type):
    """True if a normalized value satisfies one JSON type name from OUTPUT_TYPES (no coercion; bool is not a number)."""
    actual = _json_type(value)
    return actual == output_type or (output_type == "number" and actual == "integer")


def _authorization(decision, code, required, granted, confirmed, required_caps=(), granted_caps=(), missing_caps=()):
    return {"decision": decision, "code": code, "required_permissions": list(required),
            "granted_permissions": list(granted), "confirmed": confirmed, "required_capabilities": list(required_caps),
            "granted_capabilities": list(granted_caps), "missing_capabilities": list(missing_caps)}


def _non_blank(value):
    return isinstance(value, str) and bool(value.strip())


class ToolSpec:
    """Plain, mutable metadata record for one tool. Construction never raises; use `validate_tool_spec`."""

    def __init__(self, name=None, description=None, handler=None, input_schema=None, output_description=None,
                 enabled=True, permissions=None, capabilities=None, output_type=None):
        self.name = name
        self.description = description
        self.handler = handler
        self.input_schema = {} if input_schema is None else input_schema
        self.output_description = output_description
        self.enabled = enabled
        self.permissions = [] if permissions is None else permissions
        self.capabilities = [] if capabilities is None else capabilities
        self.output_type = output_type

    def __repr__(self):
        return f"ToolSpec(name={self.name!r}, enabled={self.enabled!r})"


def validate_tool_spec(spec):
    """Deterministic, read-only check. Returns a list of failure dicts (empty when valid), in field order."""
    if not isinstance(spec, ToolSpec):
        return [_failure(TOOL_INVALID_SPEC, "Not a ToolSpec.")]
    failures = []
    if not (isinstance(spec.name, str) and _NAME_RE.match(spec.name)):
        failures.append(_failure(TOOL_INVALID_NAME, "Tool name must match ^[a-z][a-z0-9_]{0,63}$ exactly."))
    if not _non_blank(spec.description):
        failures.append(_failure(TOOL_INVALID_DESCRIPTION, "Description must be a non-blank string."))
    if not callable(spec.handler):
        failures.append(_failure(TOOL_INVALID_HANDLER, "Handler must be a caller-provided callable."))
    if not (isinstance(spec.input_schema, dict) and _json_safe(spec.input_schema)):
        failures.append(_failure(TOOL_INVALID_INPUT_SCHEMA, "Input schema must be a JSON-safe dict."))
    if not _non_blank(spec.output_description):
        failures.append(_failure(TOOL_INVALID_OUTPUT_DESCRIPTION, "Output description must be a non-blank string."))
    if not isinstance(spec.enabled, bool):
        failures.append(_failure(TOOL_INVALID_ENABLED, "Enabled must be a real bool."))
    perms = spec.permissions
    if not (isinstance(perms, (list, tuple)) and all(isinstance(p, str) and p in SUPPORTED_PERMISSIONS for p in perms)):
        failures.append(_failure(TOOL_INVALID_PERMISSIONS,
                                 "Permissions must be a list/tuple of names from SUPPORTED_PERMISSIONS."))
    caps = spec.capabilities
    if not (isinstance(caps, (list, tuple)) and all(isinstance(c, str) and _NAME_RE.match(c) for c in caps)):
        failures.append(_failure(TOOL_INVALID_CAPABILITIES,
                                 "Capabilities must be a list/tuple of names matching ^[a-z][a-z0-9_]{0,63}$."))
    elif len(set(caps)) != len(caps):
        failures.append(_failure(TOOL_DUPLICATE_CAPABILITY, "Capability names must not be repeated."))
    if not (spec.output_type is None or (isinstance(spec.output_type, str) and spec.output_type in OUTPUT_TYPES)):
        failures.append(_failure(TOOL_INVALID_OUTPUT_TYPE, "Output type must be None or one of OUTPUT_TYPES."))
    return failures


class ToolRegistrationResult:
    __slots__ = ("status", "name", "failures")

    def __init__(self, name=None):
        self.status = STATUS_REGISTRATION_REJECTED
        self.name = name
        self.failures = []

    @property
    def ok(self):
        return self.status == STATUS_REGISTERED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "status": self.status, "name": self.name,
                "failures": [dict(f) for f in self.failures]}


class ToolInvocationResult:
    __slots__ = ("status", "tool_name", "handler_called", "output", "failures", "authorization")

    def __init__(self, tool_name=None):
        self.status = STATUS_INVOCATION_REJECTED
        self.tool_name = tool_name
        self.authorization = _authorization(AUTH_NOT_EVALUATED, None, [], [], False)
        self.handler_called = False
        self.output = None
        self.failures = []

    @property
    def ok(self):
        return self.status == STATUS_INVOCATION_COMPLETED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "status": self.status, "tool_name": self.tool_name,
                "handler_called": self.handler_called, "output": copy.deepcopy(self.output),
                "failures": [dict(f) for f in self.failures]}


class ToolInvocationRecord:
    """One immutable-by-convention audit entry. Never holds the handler; `to_dict()` returns fresh deep copies."""
    __slots__ = ("sequence", "tool_name", "status", "ok", "outcome_code", "handler_called", "input_json_safe",
                 "input_type", "input", "output_available", "output", "failures", "authorization_decision",
                 "authorization_code", "required_permissions", "granted_permissions", "confirmed",
                 "required_capabilities", "granted_capabilities")

    def __init__(self, sequence, result, tool_input):
        self.sequence = sequence
        self.tool_name = result.tool_name
        self.status = result.status
        self.ok = result.ok
        self.outcome_code = TOOL_COMPLETED if result.ok else result.failures[0]["code"]
        self.handler_called = result.handler_called
        valid, plain = normalize_tool_output(tool_input)
        self.input_json_safe = valid and isinstance(plain, dict)
        self.input_type = type(tool_input).__name__
        self.input = plain if self.input_json_safe else None
        self.output_available = result.ok
        self.output = copy.deepcopy(result.output) if result.ok else None
        self.failures = copy.deepcopy(result.failures)
        auth = result.authorization
        self.authorization_decision = auth["decision"]
        self.authorization_code = auth["code"]
        self.required_permissions = list(auth["required_permissions"])
        self.granted_permissions = list(auth["granted_permissions"])
        self.confirmed = auth["confirmed"]
        self.required_capabilities = list(auth["required_capabilities"])
        self.granted_capabilities = list(auth["granted_capabilities"])

    def to_dict(self):
        return {"sequence": self.sequence, "tool_name": self.tool_name, "status": self.status, "ok": self.ok,
                "outcome_code": self.outcome_code, "handler_called": self.handler_called,
                "input_json_safe": self.input_json_safe, "input_type": self.input_type,
                "input": copy.deepcopy(self.input), "output_available": self.output_available,
                "output": copy.deepcopy(self.output), "failures": copy.deepcopy(self.failures),
                "authorization_decision": self.authorization_decision, "authorization_code": self.authorization_code,
                "required_permissions": list(self.required_permissions),
                "granted_permissions": list(self.granted_permissions), "confirmed": self.confirmed,
                "required_capabilities": list(self.required_capabilities),
                "granted_capabilities": list(self.granted_capabilities)}


EXEC_SUCCEEDED = "succeeded"
EXEC_HANDLER_FAILED = "handler_failed"
EXEC_AUTHORIZATION_REJECTED = "authorization_rejected"
EXEC_OUTPUT_INVALID = "output_invalid"       # the handler returned, but its output was rejected
EXEC_INPUT_REJECTED = "input_rejected"
EXEC_TOOL_REJECTED = "tool_rejected"

_EXEC_STATUS_BY_CODE = {
    TOOL_COMPLETED: EXEC_SUCCEEDED,
    TOOL_HANDLER_EXCEPTION: EXEC_HANDLER_FAILED,
    TOOL_OUTPUT_INVALID: EXEC_HANDLER_FAILED,
    TOOL_OUTPUT_VALIDATION_FAILED: EXEC_OUTPUT_INVALID,
    TOOL_PERMISSION_DENIED: EXEC_AUTHORIZATION_REJECTED,
    TOOL_CONFIRMATION_REQUIRED: EXEC_AUTHORIZATION_REJECTED,
    TOOL_INVALID_AUTHORIZATION: EXEC_AUTHORIZATION_REJECTED,
    TOOL_CAPABILITY_MISSING: EXEC_AUTHORIZATION_REJECTED,
    TOOL_INVALID_INPUT: EXEC_INPUT_REJECTED,
    TOOL_UNKNOWN: EXEC_TOOL_REJECTED,
    TOOL_INVALID_REQUEST: EXEC_TOOL_REJECTED,
    TOOL_DISABLED: EXEC_TOOL_REJECTED,
}


class ToolExecutionResult:
    """Plain result of `InProcessToolRegistry.execute()`, derived from the call's audit record. Never holds the handler."""
    __slots__ = ("tool_name", "execution_status", "outcome_code", "authorization_accepted", "authorization_decision",
                 "handler_called", "output_available", "output", "failures", "sequence")

    def __init__(self, record):
        self.tool_name = record.tool_name
        self.execution_status = _EXEC_STATUS_BY_CODE[record.outcome_code]
        self.outcome_code = record.outcome_code
        self.authorization_decision = record.authorization_decision
        self.authorization_accepted = record.authorization_decision in (AUTH_ACCEPTED, AUTH_NOT_REQUIRED)
        self.handler_called = record.handler_called
        self.output_available = record.output_available
        self.output = copy.deepcopy(record.output)
        self.failures = copy.deepcopy(record.failures)
        self.sequence = record.sequence

    @property
    def ok(self):
        return self.execution_status == EXEC_SUCCEEDED

    def to_dict(self):
        return {"tool_name": self.tool_name, "execution_status": self.execution_status,
                "outcome_code": self.outcome_code, "authorization_accepted": self.authorization_accepted,
                "authorization_decision": self.authorization_decision, "handler_called": self.handler_called,
                "output_available": self.output_available, "output": copy.deepcopy(self.output),
                "failures": copy.deepcopy(self.failures), "sequence": self.sequence, "ok": self.ok}


class ToolPreflightResult:
    """Plain, read-only report of `InProcessToolRegistry.preflight()`. Never holds the handler; not an execution record."""
    __slots__ = ("tool_name", "tool_exists", "tool_enabled", "authorization_decision", "authorization_accepted",
                 "required_permissions", "granted_permissions", "confirmed", "required_capabilities",
                 "granted_capabilities", "missing_capabilities", "input_valid", "preflight_status", "outcome_code",
                 "failure_codes", "failures")

    def __init__(self, ev):
        auth = ev["authorization"]
        self.tool_name = ev["tool_name"]
        self.tool_exists = ev["exists"]
        self.tool_enabled = ev["enabled"]
        self.authorization_decision = auth["decision"]
        self.authorization_accepted = auth["decision"] in (AUTH_ACCEPTED, AUTH_NOT_REQUIRED)
        self.required_permissions = list(auth["required_permissions"])
        self.granted_permissions = list(auth["granted_permissions"])
        self.confirmed = auth["confirmed"]
        self.required_capabilities = list(auth["required_capabilities"])
        self.granted_capabilities = list(auth["granted_capabilities"])
        self.missing_capabilities = list(auth["missing_capabilities"])
        self.input_valid = ev["input_valid"]
        self.failures = copy.deepcopy(ev["failures"])
        self.failure_codes = [f["code"] for f in self.failures]
        self.preflight_status = PREFLIGHT_REJECTED if self.failures else PREFLIGHT_PASSED
        self.outcome_code = self.failure_codes[0] if self.failures else TOOL_PREFLIGHT_PASSED

    @property
    def ok(self):
        return self.preflight_status == PREFLIGHT_PASSED

    def to_dict(self):
        return {"tool_name": self.tool_name, "tool_exists": self.tool_exists, "tool_enabled": self.tool_enabled,
                "authorization_decision": self.authorization_decision,
                "authorization_accepted": self.authorization_accepted,
                "required_permissions": list(self.required_permissions),
                "granted_permissions": list(self.granted_permissions), "confirmed": self.confirmed,
                "required_capabilities": list(self.required_capabilities),
                "granted_capabilities": list(self.granted_capabilities),
                "missing_capabilities": list(self.missing_capabilities), "input_valid": self.input_valid,
                "preflight_status": self.preflight_status, "outcome_code": self.outcome_code,
                "failure_codes": list(self.failure_codes), "failures": copy.deepcopy(self.failures), "ok": self.ok}


class InProcessToolRegistry:
    """Instance-local registry of `ToolSpec`s. Every operation is an explicit caller action."""

    def __init__(self):
        self._entries = {}      # name -> {"description", "handler", "input_schema", "output_description", "enabled"}
        self._history = []      # ToolInvocationRecord, in invocation order (Prompt 698)

    def __len__(self):
        return len(self._entries)

    def register(self, spec):
        """Validate and store a private copy of `spec`. Rejects invalid specs and duplicate names. Never raises."""
        result = ToolRegistrationResult(spec.name if isinstance(spec, ToolSpec) and isinstance(spec.name, str)
                                        else None)
        result.failures = validate_tool_spec(spec)
        if result.failures:
            return result
        if spec.name in self._entries:
            result.failures = [_failure(TOOL_DUPLICATE_NAME, f"A tool named {spec.name!r} is already registered.",
                                        name=spec.name)]
            return result
        self._entries[spec.name] = {"description": spec.description, "handler": spec.handler,
                                    "input_schema": normalize_tool_output(spec.input_schema)[1],
                                    "output_description": spec.output_description, "enabled": spec.enabled,
                                    "permissions": sorted(set(spec.permissions)),
                                    "capabilities": sorted(spec.capabilities), "output_type": spec.output_type}
        result.status = STATUS_REGISTERED
        return result

    def has(self, name):
        return isinstance(name, str) and name in self._entries

    def is_enabled(self, name):
        return self.has(name) and self._entries[name]["enabled"] is True

    def is_invokable(self, name):
        """True only for a registered AND enabled tool."""
        return self.is_enabled(name)

    def enable(self, name):
        """Explicit action. True if the tool exists (now enabled), False for an unknown name."""
        if not self.has(name):
            return False
        self._entries[name]["enabled"] = True
        return True

    def disable(self, name):
        """Explicit action. True if the tool exists (now disabled), False for an unknown name."""
        if not self.has(name):
            return False
        self._entries[name]["enabled"] = False
        return True

    def describe(self, name):
        """Fresh metadata dict (never the handler), or None for an unknown name."""
        if not self.has(name):
            return None
        e = self._entries[name]
        return {"name": name, "description": e["description"], "input_schema": copy.deepcopy(e["input_schema"]),
                "output_description": e["output_description"], "enabled": e["enabled"]}

    def list_names(self):
        return sorted(self._entries)

    def list_descriptions(self):
        return [self.describe(n) for n in self.list_names()]

    def get_required_permissions(self, name):
        """Sorted list of the permissions a tool declares, or None for an unknown name. Read-only."""
        return list(self._entries[name]["permissions"]) if self.has(name) else None

    def get_output_type(self, name):
        """Declared output type name (or None = not validated) for a tool; None also for an unknown name. Read-only."""
        return self._entries[name]["output_type"] if self.has(name) else None

    def get_required_capabilities(self, name):
        """Sorted list of the capabilities a tool declares, or None for an unknown name. Read-only."""
        return list(self._entries[name]["capabilities"]) if self.has(name) else None

    def preflight(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None):
        """Read-only check of a proposed invocation using the same authoritative rules as `invoke()`/`execute()`. Never
        calls the handler, never appends an audit record, never stores the supplied authorization."""
        return ToolPreflightResult(self._evaluate(name, tool_input, granted_permissions, confirmed, granted_capabilities))

    def invoke(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None):
        """Run `_invoke` and append exactly one audit record for the outcome. `granted_permissions` and `confirmed` are
        explicit per-call authorization: they are never stored, inferred or reused by another call."""
        result = self._invoke(name, tool_input, granted_permissions, confirmed, granted_capabilities)
        self._history.append(ToolInvocationRecord(len(self._history) + 1, result, tool_input))
        return result

    def execute(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None):
        """Controlled execution: one `invoke()` (gate, single audit record, at most one handler call) and a
        `ToolExecutionResult` built from the record it appended. Never raises for handler failures, never retries."""
        self.invoke(name, tool_input, granted_permissions, confirmed, granted_capabilities)
        return ToolExecutionResult(self._history[-1])

    def execute_request(self, request):
        """Explicit caller action: run a `ToolRequest` through the existing `execute()` (so through `_evaluate()`, the single
        handler gate, output validation and exactly one audit record). The request only supplies the caller's own arguments via
        `to_registry_arguments()`; nothing is validated, granted, repaired or executed here. Anything that is not a usable
        `ToolRequest` is rejected (`INVALID_TOOL_REQUEST`, execution status `tool_rejected`, handler never called) and audited
        like any other rejected call. Returns a `ToolExecutionResult`."""
        from tools.tool_request import ToolRequest      # lazy: tool_request imports this module
        args = None
        if isinstance(request, ToolRequest):
            try:
                args = request.to_registry_arguments()
            except Exception:                            # e.g. an instance forged without going through create_tool_request()
                args = None
        if args is None:
            result = ToolInvocationResult(None)
            result.failures = [_failure(TOOL_INVALID_REQUEST, "execute_request() needs a ToolRequest from create_tool_request().")]
            self._history.append(ToolInvocationRecord(len(self._history) + 1, result, None))
            return ToolExecutionResult(self._history[-1])
        return self.execute(**args)

    def get_invocation_history(self):
        """Read-only: a new list of fresh deep-copied record dicts, oldest first. Never mutates the history."""
        return [r.to_dict() for r in self._history]

    def invocation_count(self):
        return len(self._history)

    def _evaluate(self, name, tool_input, granted_permissions, confirmed, granted_capabilities):
        """The single authoritative, read-only pre-handler check (see module docstring for the fixed order). Stops at the
        first failure. Returns a dict; never calls the handler and never touches registry state."""
        ev = {"tool_name": name if isinstance(name, str) else None, "exists": False, "enabled": False,
              "authorization": _authorization(AUTH_NOT_EVALUATED, None, [], [], False), "input_valid": None,
              "failures": [], "input_copy": None}
        if not self.has(name):
            ev["failures"] = [_failure(TOOL_UNKNOWN, "No tool is registered under that exact name.")]
            return ev
        ev["exists"] = True
        if self._entries[name]["enabled"] is not True:
            ev["failures"] = [_failure(TOOL_DISABLED, f"Tool {name!r} is disabled.", name=name)]
            return ev
        ev["enabled"] = True
        required = list(self._entries[name]["permissions"])
        required_caps = list(self._entries[name]["capabilities"])
        if granted_permissions is None:
            granted_permissions = ()
        if granted_capabilities is None:
            granted_capabilities = ()
        if not (isinstance(granted_permissions, (list, tuple, set, frozenset))
                and all(isinstance(p, str) and p in SUPPORTED_PERMISSIONS for p in granted_permissions)
                and isinstance(granted_capabilities, (list, tuple, set, frozenset))
                and all(isinstance(c, str) and _NAME_RE.match(c) for c in granted_capabilities)
                and isinstance(confirmed, bool)):
            ev["authorization"] = _authorization(AUTH_INVALID, TOOL_INVALID_AUTHORIZATION, required, [], False,
                                                 required_caps)
            ev["failures"] = [_failure(TOOL_INVALID_AUTHORIZATION,
                                       "granted_permissions must be a list/tuple/set of supported permission names, "
                                       "granted_capabilities a list/tuple/set of valid capability names and confirmed "
                                       "a bool.", name=name)]
            return ev
        granted = sorted(set(granted_permissions))
        granted_caps = sorted(set(granted_capabilities))
        missing = [p for p in required if p != CONFIRMATION_PERMISSION and p not in granted]
        if missing:
            ev["authorization"] = _authorization(AUTH_DENIED, TOOL_PERMISSION_DENIED, required, granted, confirmed,
                                                 required_caps, granted_caps)
            ev["failures"] = [_failure(TOOL_PERMISSION_DENIED, f"Tool {name!r} needs permissions that were not granted.",
                                       name=name, missing_permissions=missing)]
            return ev
        if CONFIRMATION_PERMISSION in required and confirmed is not True:
            ev["authorization"] = _authorization(AUTH_CONFIRMATION_REQUIRED, TOOL_CONFIRMATION_REQUIRED, required,
                                                 granted, confirmed, required_caps, granted_caps)
            ev["failures"] = [_failure(TOOL_CONFIRMATION_REQUIRED, f"Tool {name!r} requires explicit confirmation.",
                                       name=name)]
            return ev
        missing_caps = [c for c in required_caps if c not in granted_caps]
        if missing_caps:
            ev["authorization"] = _authorization(AUTH_CAPABILITY_MISSING, TOOL_CAPABILITY_MISSING, required, granted,
                                                 confirmed, required_caps, granted_caps, missing_caps)
            ev["failures"] = [_failure(TOOL_CAPABILITY_MISSING, f"Tool {name!r} needs capabilities that were not granted.",
                                       name=name, missing_capabilities=missing_caps)]
            return ev
        ev["authorization"] = _authorization(AUTH_ACCEPTED if (required or required_caps) else AUTH_NOT_REQUIRED, None,
                                             required, granted, confirmed, required_caps, granted_caps)
        valid, plain = normalize_tool_output(tool_input)
        ev["input_valid"] = valid and isinstance(plain, dict)
        if ev["input_valid"]:
            ev["input_copy"] = plain
        else:
            ev["failures"] = [_failure(TOOL_INVALID_INPUT, "Tool input must be a JSON-safe dict.", name=name)]
        return ev

    def _invoke(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None):
        """Explicit, caller-driven, single in-process call of an enabled tool's handler, only after `_evaluate` passes.
        Never raises for handler failures, never retries."""
        ev = self._evaluate(name, tool_input, granted_permissions, confirmed, granted_capabilities)
        result = ToolInvocationResult(ev["tool_name"])
        result.authorization = ev["authorization"]
        result.failures = ev["failures"]
        if result.failures:
            return result
        handler = self._entries[name]["handler"]
        result.handler_called = True
        try:
            output = handler(ev["input_copy"])
        except Exception as exc:      # caught at the boundary; deliberately not re-raised, never retried
            try:
                message = str(exc)[:_MAX_MESSAGE]
            except Exception:
                message = ""
            result.status = STATUS_INVOCATION_FAILED
            result.failures = [_failure(TOOL_HANDLER_EXCEPTION, f"The handler raised {type(exc).__name__}.",
                                        exception_type=type(exc).__name__, exception_message=message)]
            return result
        valid, normalized = normalize_tool_output(output)
        if not valid:
            result.status = STATUS_INVOCATION_FAILED
            result.failures = [_failure(TOOL_OUTPUT_INVALID, "The handler returned data that is not JSON-safe.")]
            return result
        expected = self._entries[name]["output_type"]
        if expected is not None and not output_matches_type(normalized, expected):
            result.status = STATUS_INVOCATION_FAILED
            result.failures = [_failure(TOOL_OUTPUT_VALIDATION_FAILED,
                                        f"The handler's output does not match the declared output type {expected!r}.",
                                        expected_type=expected, actual_type=_json_type(normalized))]
            return result
        result.status = STATUS_INVOCATION_COMPLETED
        result.output = normalized
        return result
