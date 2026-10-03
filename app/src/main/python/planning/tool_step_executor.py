"""
Tool-Step Execution Adapter (Prompt 708, Section 6)
=====================================================
The smallest caller-driven composition of three EXISTING contracts, so that one tool call can drive one plan step through
its whole lifecycle:

    execute_plan_tool_step(plan, step_id, request, registry) -> ToolStepExecutionResult

    plan      a caller-provided `planning.plan.Plan` (validated and transitioned ONLY by the existing Section 4 authorities)
    step_id   the id of a step of that plan
    request   a caller-built Section 5 `ToolRequest` (the ONLY carrier of tool name, input, grants, confirmation)
    registry  a caller-provided an `InProcessToolRegistry` (Section 5)

FLOW (composition only; every rule below is owned elsewhere and is NOT re-implemented here)
  1. `validate_plan(plan)` (Prompt 680) must be valid. Rejected -> `rejected`, plan untouched, registry untouched.
  2. `start_plan_step(plan, step_id)` (Prompt 689) must apply. It stays the sole authority for unknown step, inconsistent plan
     state, readiness, and `execution_authorized is True`. Rejected -> `rejected` with its failure entries passed through,
     plan untouched, registry untouched. NOTHING is read from the request or the registry before this point.
  3. `execute_tool_step(plan, step_id, request, registry)` (Prompt 707) is called EXACTLY ONCE. It alone reaches the registry
     (its single request entry point), so Section 5 (`_evaluate()`) stays the only authorization/input/output authority and the
     handler is never called from here.
  4. Bridge `succeeded` -> `complete_plan_step(plan, step_id, {"tool_result": bridge_result.to_dict()})`  (step `completed`).
     Bridge `failed` (Section 5 rejected/failed the call) or `rejected` (the bridge's own arguments were unusable)
     -> `fail_plan_step(plan, step_id, {"code", "message", "tool_result": bridge_result.to_dict()})`  (step `failed`).
     The complete `ToolStepBridgeResult.to_dict()` (status, failure_source, tool name, execution status, outcome code,
     authorization decision, handler_called, output, failures, audit `sequence`) is stored unchanged in the step's output data, so
     reporting can reconstruct what happened and join the step to the registry's audit record by `sequence`.

INTEGRITY
- Once step 2 has applied the step is NEVER left `in_progress`: an unexpected `Exception` raised by a defective registry is caught
  and recorded as a failed step (`TOOL_STEP_BRIDGE_EXCEPTION`); a `BaseException` is recorded the same way and then re-raised.
  If a transition that should record the outcome is itself refused (defensive; not reachable with a valid plan) the result
  reports it (`STEP_TRANSITION_FAILED`) instead of raising.
- There is no retry, no fallback tool, no second bridge call and no tool selection (the tool is whatever `request.name` says; a
  step's description/input_data/expected_output/required_capabilities are never read here). No grants, permissions, capabilities
  or confirmation are created, defaulted, remembered or accepted as arguments: they exist only inside the caller's `ToolRequest`.
- The adapter is a plain function with no state (no module variable, no object, no cache). Same plan state + same request +
  equivalent registry -> same result. No persistence, threads, network, scheduling or clock reads.
- `execute_plan_tool_step()` itself is unchanged since Prompt 708: a `ToolRequest`/registry that is unusable is judged by the bridge,
  i.e. AFTER the step started, so that step ends `failed`. Prompt 709 adds the caller's opt-in alternative below.

PRE-START PREFLIGHT (Prompt 709; resolves Prompt 706 hazards H3 and H4)

    execute_plan_tool_step_preflighted(plan, step_id, request, registry, rejection_log=None) -> PreflightedToolStepResult

  Nothing is started, executed or mutated unless the request is first known to be usable. Order (each stage stops at its first
  rejection; a rejection never starts the step, never reaches the registry's execution entry point, never calls a handler, never mutates the plan
  and never appends a `ToolInvocationRecord`):
    1. `rejection_log` must be None or a list (the caller-supplied H3 record, see below).
    2. the bridge's own arguments (`validate_bridge_arguments()`, the bridge stays their only owner) and the request's
       `to_registry_arguments()` must be usable.
    3. the plan context: `validate_plan()` plus `start_plan_step()` run on a DEEP COPY of the plan, so the Section 4 authorities stay
       the only judges of unknown step, plan state, readiness and authorization while the real plan is not touched.
    4. `registry.preflight(**request.to_registry_arguments())` (Section 5, the sole authority for tool existence, enabled state,
       permissions, confirmation, capabilities and input). The complete `ToolPreflightResult.to_dict()` is preserved unchanged.
    5. only after a passed preflight: exactly ONE call of the unchanged `execute_plan_tool_step()` (so `start_plan_step`, then
       the registry's normal execution path and all its checks run for real). If the registry changed between preflight and
       execution (TOCTOU) and execution is rejected or fails, the ACTUAL execution result is recorded and the started step is failed
       normally; nothing is bypassed and nothing is retried.
  `PreflightedToolStepResult.outcome_kind` separates the three kinds of not-ok outcome (plus success):
    `pre_registry_rejection`        rejected before the Registry could be asked (steps 1-3); `preflight_called` is False.
    `registry_preflight_rejection`  the Registry's preflight said no (step 4); `preflight` holds its complete report.
    `tool_execution_failure`        the step was started and the execution path failed it (step 5); `execution` holds the outcome.
    `completed`                     preflight passed and the tool step completed.
  H3: every pre-start rejection is described by a plain-dict rejection record (`record_type == "prestart_rejection"`, `rejection_kind`,
  step id, tool name, failure codes/failures, the preflight report if any, `invocation_recorded` False, `sequence` None). It is returned
  on the result and, when the caller supplies a list as `rejection_log`, appended to THAT list; the module keeps no log of its own.
  A record never pretends to be a `ToolInvocationRecord`: no sequence is fabricated and the registry history is never written.

EXPLICIT CAPABILITY MAPPING (Prompt 710; decision F2, see planning/tool_capability_mapping.py)

    execute_plan_tool_step_mapped(plan, step_id, request, registry, required_capabilities, capability_mapping,
                                  rejection_log=None) -> PreflightedToolStepResult

  A caller-driven gate IN FRONT OF `execute_plan_tool_step_preflighted()` (which is unchanged, signature included). The caller
  supplies the Section 4 names, the mapping and the request; nothing is read from the plan or the registry. Order: rejection_log,
  the bridge's own arguments and `request.to_registry_arguments()` (same owners as Prompt 709), then the mapping: the pure
  `map_required_capabilities()` must be `satisfied` and EVERY resulting Section 5 grant name must already be in the caller's
  request grants. Any failure here is a pre-start rejection (`pre_registry_rejection`, H3 record, step stays `pending`, registry
  and handler untouched, plan untouched) with the mapping report inside the failure entries. Only then the unchanged preflighted
  function runs, so Section 5 stays the final authority (a mapped grant is translation, never authorization; the request and its
  grants are never modified, extra grants stay, nothing is granted here). No retry.

EXPLICITLY NOT DECIDED HERE: H3/H4 are resolved for callers that use `execute_plan_tool_step_preflighted()` (Prompt 709). Not wired
into `process_input()`, the Agent Loop or `execute_plan_step()`. Retry and F3 remain open.
"""

import copy

from planning.plan import Plan
from planning.plan_builder import _failure
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.plan_validation import validate_plan
from planning.tool_capability_mapping import find_ungranted_capabilities, map_required_capabilities
from planning.tool_step_bridge import BRIDGE_SUCCEEDED, execute_tool_step, validate_bridge_arguments

STATUS_TOOL_STEP_COMPLETED = "completed"    # the tool ran successfully and the step is completed with its output
STATUS_TOOL_STEP_FAILED = "failed"          # the step was started and ended failed (tool failure/bridge rejection/defect)
STATUS_TOOL_STEP_REJECTED = "rejected"      # a precondition failed before the step started; plan and registry untouched

TOOL_STEP_INVALID_PLAN_OBJECT = "INVALID_PLAN_OBJECT"
TOOL_STEP_INVALID_PLAN = "INVALID_PLAN"
TOOL_STEP_TOOL_FAILED = "TOOL_STEP_TOOL_FAILED"
TOOL_STEP_BRIDGE_REJECTED = "TOOL_STEP_BRIDGE_REJECTED"
TOOL_STEP_BRIDGE_EXCEPTION = "TOOL_STEP_BRIDGE_EXCEPTION"
TOOL_STEP_OUTPUT_NOT_RECORDED = "TOOL_STEP_OUTPUT_NOT_RECORDED"
TOOL_STEP_TRANSITION_FAILED = "STEP_TRANSITION_FAILED"

OUTCOME_COMPLETED = "completed"
OUTCOME_PRE_REGISTRY_REJECTION = "pre_registry_rejection"
OUTCOME_REGISTRY_PREFLIGHT_REJECTION = "registry_preflight_rejection"
OUTCOME_TOOL_EXECUTION_FAILURE = "tool_execution_failure"

PRESTART_INVALID_REQUEST = "INVALID_PRESTART_REQUEST"
PRESTART_INVALID_REJECTION_LOG = "INVALID_REJECTION_LOG"
PRESTART_PREFLIGHT_EXCEPTION = "PRESTART_PREFLIGHT_EXCEPTION"
PRESTART_CAPABILITY_MAPPING_REJECTED = "CAPABILITY_MAPPING_REJECTED"
PRESTART_MAPPED_GRANT_NOT_SUPPLIED = "MAPPED_GRANT_NOT_SUPPLIED"
REJECTION_RECORD_TYPE = "prestart_rejection"

_MAX_MESSAGE = 500


class ToolStepExecutionResult:
    """Outcome of one `execute_plan_tool_step()` call. `tool_result` is the bridge's `to_dict()` (fresh plain JSON) or None when
    the bridge was never reached; `recorded_output` is what was stored on the step (None when nothing was recorded)."""

    __slots__ = ("status", "step_id", "previous_state", "final_state", "bridge_called", "tool_result", "recorded_output",
                 "reason", "failures")

    def __init__(self, step_id=None):
        self.status = STATUS_TOOL_STEP_REJECTED
        self.step_id = step_id
        self.previous_state = None
        self.final_state = None         # equals previous_state when rejected (nothing changed)
        self.bridge_called = False
        self.tool_result = None
        self.recorded_output = None
        self.reason = None              # first failure code, or None on success
        self.failures = []

    @property
    def ok(self):
        return self.status == STATUS_TOOL_STEP_COMPLETED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "status": self.status, "step_id": self.step_id, "previous_state": self.previous_state,
                "final_state": self.final_state, "bridge_called": self.bridge_called,
                "tool_result": None if self.tool_result is None else _copy_json(self.tool_result),
                "recorded_output": None if self.recorded_output is None else _copy_json(self.recorded_output),
                "reason": self.reason, "failures": [dict(f) for f in self.failures]}


def _copy_json(value):
    if isinstance(value, dict):
        return {k: _copy_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_json(v) for v in value]
    return value


def _state_of(plan, step_id):
    """Read-only lookup of a step's current state, or None when it cannot be determined."""
    if isinstance(plan, Plan) and isinstance(plan.steps, list):
        for step in plan.steps:
            if getattr(step, "step_id", None) == step_id:
                return getattr(step, "status", None)
    return None


def _reject(result, failures):
    result.status = STATUS_TOOL_STEP_REJECTED
    result.final_state = result.previous_state
    result.failures = failures
    result.reason = failures[0]["code"]
    return result


def _record_failed(result, plan, step_id, code, message, tool_result, **details):
    """The step is in_progress and did not complete: record a terminal failed state carrying everything known."""
    payload = {"code": code, "message": message, "tool_result": tool_result}
    payload.update(details)
    failed = fail_plan_step(plan, step_id, payload)
    result.status = STATUS_TOOL_STEP_FAILED
    result.final_state = _state_of(plan, step_id)
    result.tool_result = tool_result
    result.recorded_output = payload if failed.ok else None
    result.failures = [_failure(code, message, **details)]
    if not failed.ok:       # defensive: the failure could not be recorded; report it, never raise
        result.failures.append(_failure(TOOL_STEP_TRANSITION_FAILED, "The failure could not be recorded.",
                                        issues=[dict(f) for f in failed.failures]))
    result.reason = code
    return result


def execute_plan_tool_step(plan, step_id, request, registry):
    """Start `step_id`, run the caller's `request` through the Prompt 707 bridge once, and record the outcome on the step.
    Returns a `ToolStepExecutionResult`. Never raises for tool failures; never retries; keeps no state."""
    result = ToolStepExecutionResult(step_id if isinstance(step_id, str) else None)
    result.previous_state = _state_of(plan, step_id)

    if not isinstance(plan, Plan):
        return _reject(result, [_failure(TOOL_STEP_INVALID_PLAN_OBJECT, "Not a Plan; nothing to execute.")])
    validation = validate_plan(plan)
    if not validation.valid:
        return _reject(result, [_failure(TOOL_STEP_INVALID_PLAN, "The plan is not valid; nothing executed.",
                                         issues=[dict(i) for i in validation.issues])])

    started = start_plan_step(plan, step_id)        # authoritative: known step, consistent state, ready, authorized
    result.previous_state = started.previous_state
    if not started.ok:
        result.final_state = started.new_state
        result.failures = [dict(f) for f in started.failures]
        result.reason = result.failures[0]["code"]
        return result

    # From here the step is in_progress and must end terminal. The bridge is called exactly once.
    result.bridge_called = True
    try:
        bridge_result = execute_tool_step(plan, step_id, request, registry)
    except Exception as exc:        # a defective registry: recorded on the step, not re-raised, not retried
        try:
            text = str(exc)[:_MAX_MESSAGE]
        except Exception:
            text = ""
        return _record_failed(result, plan, step_id, TOOL_STEP_BRIDGE_EXCEPTION,
                              f"The tool bridge raised {type(exc).__name__}.", None,
                              exception_type=type(exc).__name__, exception_message=text)
    except BaseException as exc:    # never leave the step in_progress, but do not swallow the interrupt
        _record_failed(result, plan, step_id, TOOL_STEP_BRIDGE_EXCEPTION,
                       f"The tool bridge was interrupted by {type(exc).__name__}.", None,
                       exception_type=type(exc).__name__)
        raise

    tool_result = bridge_result.to_dict()
    if bridge_result.status == BRIDGE_SUCCEEDED:
        completed = complete_plan_step(plan, step_id, {"tool_result": tool_result})
        if completed.ok:
            result.status = STATUS_TOOL_STEP_COMPLETED
            result.final_state = completed.new_state
            result.tool_result = tool_result
            result.recorded_output = completed.step.output_data
            return result
        return _record_failed(result, plan, step_id, TOOL_STEP_OUTPUT_NOT_RECORDED,
                              "The tool succeeded but its result could not be recorded as step output.", tool_result,
                              rejected_by=completed.codes()[0])
    if bridge_result.failure_source == "bridge":
        return _record_failed(result, plan, step_id, TOOL_STEP_BRIDGE_REJECTED,
                              "The bridge rejected its arguments; the tool was never called.", tool_result,
                              outcome_code=bridge_result.outcome_code)
    return _record_failed(result, plan, step_id, TOOL_STEP_TOOL_FAILED, "The tool call failed.", tool_result,
                          outcome_code=bridge_result.outcome_code, execution_status=bridge_result.execution_status,
                          sequence=bridge_result.sequence)


# ----------------------------------------------------------------------------------------------------------------------
# Prompt 709: pre-start tool preflight and rejection recording (H3, H4)
# ----------------------------------------------------------------------------------------------------------------------

class PreflightedToolStepResult:
    """Outcome of one `execute_plan_tool_step_preflighted()` call. Plain data; holds no plan, request, registry or handler."""

    __slots__ = ("status", "outcome_kind", "step_id", "tool_name", "previous_state", "final_state", "preflight_called",
                 "preflight", "execution_called", "execution", "reason", "failures", "rejection_record", "sequence")

    def __init__(self, step_id=None, tool_name=None):
        self.status = STATUS_TOOL_STEP_REJECTED
        self.outcome_kind = OUTCOME_PRE_REGISTRY_REJECTION
        self.step_id = step_id
        self.tool_name = tool_name
        self.previous_state = None
        self.final_state = None             # equals previous_state for every pre-start rejection (nothing changed)
        self.preflight_called = False
        self.preflight = None               # the registry's complete ToolPreflightResult.to_dict(), or None
        self.execution_called = False       # True only when the unchanged execute_plan_tool_step() was reached
        self.execution = None               # ToolStepExecutionResult.to_dict() of that call, or None
        self.reason = None
        self.failures = []
        self.rejection_record = None        # plain dict for every pre-start rejection, else None
        self.sequence = None                # the registry audit sequence of the ACTUAL execution only, else None

    @property
    def ok(self):
        return self.status == STATUS_TOOL_STEP_COMPLETED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "status": self.status, "outcome_kind": self.outcome_kind, "step_id": self.step_id,
                "tool_name": self.tool_name, "previous_state": self.previous_state, "final_state": self.final_state,
                "preflight_called": self.preflight_called,
                "preflight": None if self.preflight is None else _copy_json(self.preflight),
                "execution_called": self.execution_called,
                "execution": None if self.execution is None else _copy_json(self.execution),
                "reason": self.reason, "failures": _copy_json(self.failures),
                "rejection_record": None if self.rejection_record is None else _copy_json(self.rejection_record),
                "sequence": self.sequence}


def _prestart_reject(result, kind, failures, log, preflight=None):
    """Finish `result` as a pre-start rejection: nothing started, nothing executed. Builds the H3 record (never an audit record)."""
    result.status = STATUS_TOOL_STEP_REJECTED
    result.outcome_kind = kind
    result.final_state = result.previous_state
    result.failures = _copy_json(failures)
    result.reason = failures[0]["code"]
    result.preflight = None if preflight is None else _copy_json(preflight)
    record = {"record_type": REJECTION_RECORD_TYPE, "rejection_kind": kind, "step_id": result.step_id,
              "tool_name": result.tool_name, "codes": [f["code"] for f in failures], "failures": _copy_json(failures),
              "preflight": None if preflight is None else _copy_json(preflight),
              "invocation_recorded": False, "sequence": None}
    result.rejection_record = record
    if isinstance(log, list):
        list.append(log, _copy_json(record))       # the caller's own record; this module keeps none
    return result


def execute_plan_tool_step_preflighted(plan, step_id, request, registry, rejection_log=None):
    """Like `execute_plan_tool_step()`, but the step is only started after `registry.preflight(**request.to_registry_arguments())`
    passed (see the module docstring). Returns a `PreflightedToolStepResult`; never raises for rejections or tool failures, never
    retries, keeps no state. `rejection_log` is an optional caller-owned list that receives one record per pre-start rejection."""
    tool_name = getattr(request, "name", None)          # a forged request has no name -> None
    result = PreflightedToolStepResult(step_id if isinstance(step_id, str) else None,
                                       tool_name if isinstance(tool_name, str) else None)
    result.previous_state = _state_of(plan, step_id)
    log = rejection_log if isinstance(rejection_log, list) else None

    if rejection_log is not None and log is None:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION,
                                [_failure(PRESTART_INVALID_REJECTION_LOG, "rejection_log must be None or a list.")], None)

    failures = validate_bridge_arguments(plan, step_id, request, registry)     # the bridge remains their only owner
    if failures:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION, failures, log)
    try:
        arguments = request.to_registry_arguments()
    except Exception:                                   # e.g. a request object forged without its factory
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION,
                                [_failure(PRESTART_INVALID_REQUEST, "The request cannot be converted to registry arguments.")], log)

    # Plan context: the Section 4 authorities judge it, on a copy, so the real plan is never touched before the registry agrees.
    validation = validate_plan(plan)
    if not validation.valid:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION,
                                [_failure(TOOL_STEP_INVALID_PLAN, "The plan is not valid; nothing executed.",
                                          issues=[dict(i) for i in validation.issues])], log)
    dry_run = start_plan_step(copy.deepcopy(plan), step_id)
    result.previous_state = dry_run.previous_state
    if not dry_run.ok:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION, [dict(f) for f in dry_run.failures], log)

    # Section 5 is the sole authority for everything about the tool call; this module only asks and records the answer.
    result.preflight_called = True
    try:
        report = registry.preflight(**arguments).to_dict()
    except Exception as exc:                            # a defective registry: no verdict exists, so the step is not started
        return _prestart_reject(result, OUTCOME_REGISTRY_PREFLIGHT_REJECTION,
                                [_failure(PRESTART_PREFLIGHT_EXCEPTION, f"The registry preflight raised {type(exc).__name__}.",
                                          exception_type=type(exc).__name__)], log)
    if report["ok"] is not True:
        return _prestart_reject(result, OUTCOME_REGISTRY_PREFLIGHT_REJECTION, report["failures"], log, preflight=report)
    result.preflight = report

    # Preflight passed: exactly one normal execution through the unchanged path (start -> bridge -> registry execution -> record).
    result.execution_called = True
    execution = execute_plan_tool_step(plan, step_id, request, registry)
    result.execution = execution.to_dict()
    result.previous_state = execution.previous_state
    result.final_state = execution.final_state
    result.failures = _copy_json(execution.failures)
    result.reason = execution.reason
    if execution.tool_result is not None:
        result.sequence = execution.tool_result["sequence"]
    if execution.status == STATUS_TOOL_STEP_COMPLETED:
        result.status, result.outcome_kind = STATUS_TOOL_STEP_COMPLETED, OUTCOME_COMPLETED
    elif execution.status == STATUS_TOOL_STEP_FAILED:
        result.status, result.outcome_kind = STATUS_TOOL_STEP_FAILED, OUTCOME_TOOL_EXECUTION_FAILURE
    else:       # defensive: the step never started, so this is still a pre-start rejection (no registry call was made)
        result.execution_called = False
        result.execution = None
        _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION, [dict(f) for f in execution.failures], log,
                         preflight=report)
    return result


# ----------------------------------------------------------------------------------------------------------------------
# Prompt 710: explicit Section 4 -> Section 5 capability mapping gate (F2)
# ----------------------------------------------------------------------------------------------------------------------

def execute_plan_tool_step_mapped(plan, step_id, request, registry, required_capabilities, capability_mapping,
                                  rejection_log=None):
    """`execute_plan_tool_step_preflighted()` behind an explicit capability-mapping check (see the module docstring).

    `required_capabilities` (the Section 4 names) and `capability_mapping` are supplied by the caller; the request's own grants
    must already contain every mapped Section 5 name. A mapping failure rejects before `start_plan_step()` (H3 record, step stays
    pending). Returns a `PreflightedToolStepResult`; never raises for rejections, never retries, never grants, keeps no state."""
    tool_name = getattr(request, "name", None)
    result = PreflightedToolStepResult(step_id if isinstance(step_id, str) else None,
                                       tool_name if isinstance(tool_name, str) else None)
    result.previous_state = _state_of(plan, step_id)
    log = rejection_log if isinstance(rejection_log, list) else None

    # Same first stages and owners as Prompt 709, so a bad log/argument/request is judged identically before any mapping work.
    if rejection_log is not None and log is None:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION,
                                [_failure(PRESTART_INVALID_REJECTION_LOG, "rejection_log must be None or a list.")], None)
    failures = validate_bridge_arguments(plan, step_id, request, registry)
    if failures:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION, failures, log)
    try:
        arguments = request.to_registry_arguments()
    except Exception:
        return _prestart_reject(result, OUTCOME_PRE_REGISTRY_REJECTION,
                                [_failure(PRESTART_INVALID_REQUEST, "The request cannot be converted to registry arguments.")], log)

    mapping = map_required_capabilities(required_capabilities, capability_mapping)
    if not mapping.ok:
        return _prestart_reject(
            result, OUTCOME_PRE_REGISTRY_REJECTION,
            [_failure(PRESTART_CAPABILITY_MAPPING_REJECTED, "The supplied mapping does not satisfy the required capabilities; "
                      "nothing started.", capability_mapping=mapping.to_dict())] + mapping.failures, log)
    ungranted = find_ungranted_capabilities(mapping, arguments["granted_capabilities"])
    if ungranted:
        return _prestart_reject(
            result, OUTCOME_PRE_REGISTRY_REJECTION,
            [_failure(PRESTART_MAPPED_GRANT_NOT_SUPPLIED, "The request does not grant every mapped Section 5 capability; "
                      "nothing was granted here and nothing started.", missing_grants=list(ungranted),
                      capability_mapping=mapping.to_dict())], log)

    return execute_plan_tool_step_preflighted(plan, step_id, request, registry, rejection_log)
