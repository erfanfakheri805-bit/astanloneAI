"""
Structured Tool-Step Bridge (Prompt 707, Section 6)
=====================================================
The smallest pure, caller-driven contract for the Section 4 <-> Section 5 tool-step boundary found in Prompt 706:

    execute_tool_step(plan, step_id, request, registry) -> ToolStepBridgeResult

    plan      a caller-provided `planning.plan.Plan` (read-only context; never started, completed, failed or mutated here)
    step_id   the id of a step of that plan (identifies which step this tool call belongs to; nothing else)
    request   a caller-provided `tools.tool_request.ToolRequest` (it alone carries the tool name, input, grants, confirmation)
    registry  a caller-provided `tools.in_process_tool_registry.InProcessToolRegistry`

CONTRACT
- The bridge is a plain function. It has NO state: no object, class attribute, module variable or argument holds
  "confirmed for this executor", grants or a default tool. Confirmation and grants exist only inside the specific `ToolRequest`
  the caller built with `create_tool_request()`, so they cannot authorize any other request (Prompt 706 hazard H2 is closed at
  the contract level: there is nowhere to keep a generic confirmation, and the function accepts no such argument).
- It never selects a tool. The tool is whatever `request.name` says; the step's description, `input_data`, `expected_output` and
  `required_capabilities` are never read, so nothing in plan data can name a tool or grant anything.
- It never invents permissions, capabilities, confirmation or grants and validates nothing the Section 5 contracts already validate:
  request validation stays in `create_tool_request()`, authorization/input/output rules stay in the registry's single `_evaluate()`
  path. The bridge only checks its OWN arguments (are these a Plan, a step id of that plan, a ToolRequest, a registry?).
- Execution goes through `registry.execute_request(request)` only: exactly one call, no retry, no fallback tool, no second attempt,
  no `preflight()`, no direct handler access. A forged `ToolRequest` (built without the factory) is not judged here; the registry
  rejects it (`INVALID_TOOL_REQUEST`) and that failure is reported like any other tool failure.
- The outcome is DATA, never an exception for tool failures. `ToolStepBridgeResult.status` is one of:
    `succeeded`  the tool completed (`execution_status == "succeeded"`); `output` holds the tool's normalized output.
    `failed`     Section 5 rejected or failed the call (unknown/disabled tool, permission, confirmation, capability, input,
                 handler exception, invalid output, ...). Tool name, execution status, outcome code, authorization decision,
                 `handler_called`, `output_available`, failures and the audit `sequence` are copied unchanged from the
                 registry's `ToolExecutionResult`, so no Section 5 failure information is lost or re-labelled.
    `rejected`   the bridge's own arguments were unusable; the registry was never called, so the handler cannot have run, no audit
                 record exists (`sequence is None`) and `outcome_code` is one of the `INVALID_BRIDGE_*` / `UNKNOWN_BRIDGE_STEP`
                 codes. All problems are reported at once, in argument order.
  `failure_source` is `None` (succeeded), `"tool"` (failed) or `"bridge"` (rejected).
- `ToolStepBridgeResult` is immutable data (no `__dict__`, assignment refused, `output`/`failures` return fresh deep copies,
  `to_dict()` returns fresh plain JSON with a fixed key set). It holds no registry, request, plan, step or handler. `to_dict()` is
  safe structured data, so a future executor can hand it to `fail_plan_step(plan, step_id, result.to_dict())` /
  `complete_plan_step(plan, step_id, result.to_dict())` and keep the complete Section 5 outcome on the plan step.
- The `ToolRequest` is never modified (it is immutable); the plan is never modified; the registry changes only by the one audit record
  a call that reaches `execute_request()` always appends. No persistence, no background work, no networking, no scheduling.
- A `BaseException` (and any unexpected `Exception` from a defective registry subclass) propagates: the bridge does not mask defects.

EXPLICITLY NOT DECIDED HERE (Prompt 706 findings, see docs/section6_tool_step_bridge_prompt707.md)
- F1: legacy `ExecutionEngine`/`PlanExecutionController` (used by the Agent Loop) vs the Prompt 689-694 step layer. The bridge
  is not wired into `process_input()`, the Agent Loop, the Planner or `execute_plan_step()`; it neither starts nor finishes steps and
  does not check step state (that is the step layer's gate).
- F2: Section 4 `required_capabilities` (free-form) vs Section 5 grant names (`^[a-z][a-z0-9_]{0,63}$`). The bridge neither maps
  nor compares them; a step's `required_capabilities` are never read.

This is the ONLY `planning/` module that imports `tools`. It imports `copy`, `planning.plan` and the two Section 5 modules named above.
"""

import copy

from planning.plan import Plan
from tools.in_process_tool_registry import InProcessToolRegistry
from tools.tool_request import ToolRequest

BRIDGE_SUCCEEDED = "succeeded"
BRIDGE_FAILED = "failed"          # Section 5 rejected/failed the call; the original information is preserved
BRIDGE_REJECTED = "rejected"      # the bridge's own arguments were unusable; the registry was never called

FAILURE_SOURCE_TOOL = "tool"
FAILURE_SOURCE_BRIDGE = "bridge"

BRIDGE_INVALID_PLAN = "INVALID_BRIDGE_PLAN"
BRIDGE_INVALID_STEP_ID = "INVALID_BRIDGE_STEP_ID"
BRIDGE_UNKNOWN_STEP = "UNKNOWN_BRIDGE_STEP"
BRIDGE_INVALID_REQUEST = "INVALID_BRIDGE_REQUEST"
BRIDGE_INVALID_REGISTRY = "INVALID_BRIDGE_REGISTRY"

_CREATE_TOKEN = object()


def _failure(code, message):
    return {"code": code, "message": message}


class ToolStepBridgeResult:
    """Immutable record of one `execute_tool_step()` call. Obtain it only from that function."""

    __slots__ = ("_status", "_step_id", "_tool_name", "_execution_status", "_outcome_code", "_authorization_decision",
                 "_authorization_accepted", "_handler_called", "_output_available", "_output", "_failures", "_sequence")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ToolStepBridgeResult cannot be subclassed.")

    def __init__(self, _token, status, step_id, tool_name, execution_status, outcome_code, authorization_decision,
                 authorization_accepted, handler_called, output_available, output, failures, sequence):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_tool_step() to obtain a ToolStepBridgeResult.")
        for key, value in (("status", status), ("step_id", step_id), ("tool_name", tool_name),
                           ("execution_status", execution_status), ("outcome_code", outcome_code),
                           ("authorization_decision", authorization_decision),
                           ("authorization_accepted", authorization_accepted), ("handler_called", handler_called),
                           ("output_available", output_available), ("output", output), ("failures", failures),
                           ("sequence", sequence)):
            object.__setattr__(self, "_" + key, value)

    def __setattr__(self, key, value):
        raise AttributeError("ToolStepBridgeResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ToolStepBridgeResult is immutable.")

    @property
    def status(self):
        return self._status

    @property
    def ok(self):
        return self._status == BRIDGE_SUCCEEDED

    @property
    def failure_source(self):
        return {BRIDGE_FAILED: FAILURE_SOURCE_TOOL, BRIDGE_REJECTED: FAILURE_SOURCE_BRIDGE}.get(self._status)

    @property
    def step_id(self):
        return self._step_id

    @property
    def tool_name(self):
        return self._tool_name

    @property
    def execution_status(self):
        return self._execution_status

    @property
    def outcome_code(self):
        return self._outcome_code

    @property
    def authorization_decision(self):
        return self._authorization_decision

    @property
    def authorization_accepted(self):
        return self._authorization_accepted

    @property
    def handler_called(self):
        return self._handler_called

    @property
    def output_available(self):
        return self._output_available

    @property
    def output(self):
        """A fresh deep copy on every read."""
        return copy.deepcopy(self._output)

    @property
    def failures(self):
        """A fresh deep copy on every read."""
        return copy.deepcopy(self._failures)

    @property
    def sequence(self):
        """The registry's audit/invocation sequence number, or None when the registry was never called."""
        return self._sequence

    def codes(self):
        return [f["code"] for f in self._failures]

    def to_dict(self):
        """Fresh plain-JSON view with a fixed key set (never contains a handler, registry, request or callable)."""
        return {"ok": self.ok, "status": self._status, "failure_source": self.failure_source, "step_id": self._step_id,
                "tool_name": self._tool_name, "execution_status": self._execution_status,
                "outcome_code": self._outcome_code, "authorization_decision": self._authorization_decision,
                "authorization_accepted": self._authorization_accepted, "handler_called": self._handler_called,
                "output_available": self._output_available, "output": copy.deepcopy(self._output),
                "failures": copy.deepcopy(self._failures), "sequence": self._sequence}

    def __eq__(self, other):
        if not isinstance(other, ToolStepBridgeResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ToolStepBridgeResult is never persisted or pickled.")

    def __repr__(self):
        return (f"ToolStepBridgeResult(status={self._status!r}, step_id={self._step_id!r}, "
                f"tool_name={self._tool_name!r}, outcome_code={self._outcome_code!r})")


def _rejected(step_id, tool_name, failures):
    return ToolStepBridgeResult(_CREATE_TOKEN, BRIDGE_REJECTED, step_id, tool_name, None, failures[0]["code"], None, False,
                                False, False, None, failures, None)


def _has_step(plan, step_id):
    return any(getattr(step, "step_id", None) == step_id for step in plan.steps)


def validate_bridge_arguments(plan, step_id, request, registry):
    """Read-only check of the bridge's OWN four arguments (Prompt 709: the single owner of these checks, shared by
    `execute_tool_step()` and the pre-start preflight so the rules are never duplicated). Returns the list of failures, all
    problems at once in argument order; `[]` means usable. Touches neither the plan, the request nor the registry state."""
    failures = []
    plan_ok = isinstance(plan, Plan)
    if not plan_ok:
        failures.append(_failure(BRIDGE_INVALID_PLAN, "The plan context must be a Plan."))
    step_ok = isinstance(step_id, str) and bool(step_id.strip())
    if not step_ok:
        failures.append(_failure(BRIDGE_INVALID_STEP_ID, "The step id must be a non-empty string."))
    elif plan_ok and not _has_step(plan, step_id):
        failures.append(_failure(BRIDGE_UNKNOWN_STEP, f"The plan has no step with id {step_id!r}."))
    if not isinstance(request, ToolRequest):
        failures.append(_failure(BRIDGE_INVALID_REQUEST, "The request must be a ToolRequest from create_tool_request()."))
    if not isinstance(registry, InProcessToolRegistry):
        failures.append(_failure(BRIDGE_INVALID_REGISTRY, "The registry must be an InProcessToolRegistry."))
    return failures


def execute_tool_step(plan, step_id, request, registry):
    """Run ONE caller-built `ToolRequest` for ONE step of a caller-provided plan through `registry.execute_request(request)`.

    Returns a `ToolStepBridgeResult` (see the module docstring). Never raises for bad arguments or tool failures; never selects a
    tool, grants anything, retries, mutates the plan/request, or keeps any state."""
    step_text = step_id if isinstance(step_id, str) else None
    tool_text = None
    if isinstance(request, ToolRequest):
        try:
            tool_text = request.name if isinstance(request.name, str) else None
        except AttributeError:                      # a ToolRequest forged without create_tool_request() has no name
            tool_text = None
    failures = validate_bridge_arguments(plan, step_id, request, registry)
    if failures:
        return _rejected(step_text, tool_text, failures)
    result = registry.execute_request(request)          # the ONLY execution call: one audit record, at most one handler call
    status = BRIDGE_SUCCEEDED if result.ok else BRIDGE_FAILED
    return ToolStepBridgeResult(_CREATE_TOKEN, status, step_id, result.tool_name, result.execution_status,
                                result.outcome_code, result.authorization_decision, result.authorization_accepted,
                                result.handler_called, result.output_available, copy.deepcopy(result.output),
                                copy.deepcopy(result.failures), result.sequence)
