"""
Agent-Loop Tool-Step Adapter (Prompt 714, Section 6)
======================================================
The isolated, caller-side entry boundary that a FUTURE Agent Loop must use to run ONE Section 6 tool step (decisions of the
Prompt 713 hand-over record, docs/section6_agent_loop_handover_decision_prompt713.md). It is NOT wired anywhere: not into
`process_input()`, not into `AgentLoop.run()`, not into the legacy `execution/` stack, not into `PlanManager.refresh_*`.

    execute_agent_tool_step(plan, step_id, request, registry, max_attempts, required_capabilities=None,
                            capability_mapping=None, attempt_log=None) -> AgentToolStepResult

  plan                  a caller-owned `planning.plan.Plan` (Section 4 owns plan truth; nothing here repairs or refreshes it)
  step_id               id of the step to run
  request               a caller-built Section 5 `ToolRequest`. The adapter never constructs, modifies or defaults it: the caller
                        owns tool name, input, permissions, capability grants and confirmation.
  registry              the caller's Section 5 registry. The adapter never imports it and never calls it (only the unchanged retry
                        layer reaches it, through the existing pre-start path).
  max_attempts          caller-supplied int, 1..MAX_ADAPTER_ATTEMPTS (the adapter's own finite bound, see below). No default.
  required_capabilities } the caller's explicit Section 4 -> Section 5 mapping pair: both None (no mapping) or both given.
  capability_mapping    } Nothing is inferred, discovered or defaulted; a mapping is translation, never authorization.
  attempt_log           optional caller-owned list; the retry layer appends one fresh record per attempt to THAT list (the single
                        documented write this call performs on caller-owned data).

VALIDATION ORDER (every stage runs BEFORE any step starts; the first failing stage rejects; a rejection is `status == "rejected"`,
`failure_source == "adapter"`, zero attempts, and touches nothing: no plan change, no registry call, no handler call, no
invocation record, no registry sequence number):
  a. plan validity              `plan` is a `Plan` (ADAPTER_INVALID_PLAN_OBJECT) and `validate_plan(plan)` is valid (ADAPTER_INVALID_PLAN)
  b. step-state consistency     `validate_plan_step_states(plan)` is valid. Legacy `ready` / `blocked` step states are rejected
                                explicitly (ADAPTER_LEGACY_STEP_STATE) - never converted, repaired or refreshed; any other
                                inconsistency is ADAPTER_INCONSISTENT_STEP_STATE. `validate_plan()` alone ACCEPTS `ready`/`blocked`
                                (Prompt 713 conflict C2), so BOTH validations are required and the adapter fails closed.
  c. step existence             `step_id` is a non-empty str (ADAPTER_INVALID_STEP_ID) naming a step of the plan (ADAPTER_UNKNOWN_STEP)
  d. execution authorization    `plan.metadata["execution_authorized"] is True` (ADAPTER_EXECUTION_NOT_AUTHORIZED). A plan-level gate
                                owned by the plan's owner; never inferred from capabilities, permissions, mapping or tool state.
  e. retry arguments            `max_attempts` is an int (not bool) with 1 <= n <= MAX_ADAPTER_ATTEMPTS (ADAPTER_INVALID_MAX_ATTEMPTS);
                                `attempt_log` is None or a list (ADAPTER_INVALID_ATTEMPT_LOG)
  f. mapping consistency        the pair is supplied together or not at all (ADAPTER_INVALID_MAPPING_ARGUMENTS); a supplied pair must be
                                well-formed - pure `map_required_capabilities()` status is not `invalid_input`/`invalid_mapping`
                                (ADAPTER_MALFORMED_CAPABILITY_MAPPING). A well-formed mapping that is merely `unmapped`, and a mapped
                                grant the request did not supply, are judged by the retry layer (pre-start, retryable per Prompt 711).

EXECUTION: the ONLY execution entry point is `planning.tool_step_retry.execute_plan_tool_step_with_retry()`, called at most once.
This module never calls `execute_plan_tool_step`, `execute_tool_step`, `execute_plan_tool_step_preflighted/_mapped`, a registry
method or a handler. The request/registry validity (`INVALID_BRIDGE_REQUEST`, `INVALID_BRIDGE_REGISTRY`) is judged by the retry layer's
first attempt, still before the step starts. Prompt 711 semantics are preserved unchanged: only pre-start rejections on the Prompt 711
allow-list may be retried (never more than the caller's `max_attempts`); a started step is terminal; a completed step is terminal; a
failed execution is terminal; malformed input is not retried. There is no automatic retry policy, delay or backoff.

CAPABILITY SEMANTICS (Prompt 710/713): required Section 4 names and the mapping are caller-supplied; no inference, no automatic
mapping; the mapping never grants anything; Section 5 (`registry.preflight()` / `_evaluate()`) remains the final authority.

RESULT: `AgentToolStepResult` is immutable, data-only, holds no plan, request, registry, handler or mutable reference; every
structured value is returned as a fresh deep copy. Invocation `sequence` is copied from the registry's own audit record and only
when a real invocation happened; nothing is ever fabricated for a rejection.

STATELESS: no module variable that changes, no singleton, cache, registry, persistence or background task.
"""

import copy

from planning.plan import Plan
from planning.plan_builder import validate_plan_step_states
from planning.plan_validation import validate_plan
from planning.tool_capability_mapping import STATUS_INVALID_INPUT, STATUS_INVALID_MAPPING, map_required_capabilities
from planning.tool_step_retry import execute_plan_tool_step_with_retry

STATUS_ADAPTER_COMPLETED = "completed"      # the tool ran and the step is completed
STATUS_ADAPTER_FAILED = "failed"            # the step started and ended failed (terminal)
STATUS_ADAPTER_REJECTED = "rejected"        # the step never started

SOURCE_ADAPTER = "adapter"                  # the adapter's own validation (stages a-f) rejected the call
SOURCE_PRE_START = "pre_start"              # rejected before the step started by the existing pre-start path (request, registry preflight, mapping, plan state)
SOURCE_TOOL_EXECUTION = "tool_execution"    # the step started and the execution failed

MAX_ADAPTER_ATTEMPTS = 10                   # the adapter's own finite upper bound for caller-supplied max_attempts

ADAPTER_INVALID_PLAN_OBJECT = "ADAPTER_INVALID_PLAN_OBJECT"
ADAPTER_INVALID_PLAN = "ADAPTER_INVALID_PLAN"
ADAPTER_INCONSISTENT_STEP_STATE = "ADAPTER_INCONSISTENT_STEP_STATE"
ADAPTER_LEGACY_STEP_STATE = "ADAPTER_LEGACY_STEP_STATE"
ADAPTER_INVALID_STEP_ID = "ADAPTER_INVALID_STEP_ID"
ADAPTER_UNKNOWN_STEP = "ADAPTER_UNKNOWN_STEP"
ADAPTER_EXECUTION_NOT_AUTHORIZED = "ADAPTER_EXECUTION_NOT_AUTHORIZED"
ADAPTER_INVALID_MAX_ATTEMPTS = "ADAPTER_INVALID_MAX_ATTEMPTS"
ADAPTER_INVALID_ATTEMPT_LOG = "ADAPTER_INVALID_ATTEMPT_LOG"
ADAPTER_INVALID_MAPPING_ARGUMENTS = "ADAPTER_INVALID_MAPPING_ARGUMENTS"
ADAPTER_MALFORMED_CAPABILITY_MAPPING = "ADAPTER_MALFORMED_CAPABILITY_MAPPING"

LEGACY_STEP_STATES = ("ready", "blocked")   # labels written by PlanManager.refresh_*; never Section 4 states

_CREATE_TOKEN = object()
_MAPPING_FAILURE_STATUSES = (STATUS_INVALID_INPUT, STATUS_INVALID_MAPPING)


def _failure(code, message, **details):
    entry = {"code": code, "message": message}
    entry.update(details)
    return entry


class AgentToolStepResult:
    """Immutable, data-only record of one `execute_agent_tool_step()` call. Obtain it only from that function."""

    __slots__ = ("_status", "_failure_source", "_failure_code", "_step_id", "_execution_started", "_final_step_state",
                 "_retry_stop_reason", "_attempt_count", "_attempts", "_tool_result", "_failures", "_invocation_sequence",
                 "_outcome_kind", "_mapping", "_preflight")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AgentToolStepResult cannot be subclassed.")

    def __init__(self, _token, **fields):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_agent_tool_step() to obtain an AgentToolStepResult.")
        for name in self.__slots__:
            object.__setattr__(self, name, copy.deepcopy(fields[name[1:]]))     # a private copy: nothing shared with the caller

    def __setattr__(self, key, value):
        raise AttributeError("AgentToolStepResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AgentToolStepResult is immutable.")

    @property
    def status(self):
        return self._status

    @property
    def ok(self):
        return self._status == STATUS_ADAPTER_COMPLETED

    @property
    def failure_source(self):
        return self._failure_source

    @property
    def failure_code(self):
        return self._failure_code

    @property
    def step_id(self):
        return self._step_id

    @property
    def execution_started(self):
        return self._execution_started

    @property
    def final_step_state(self):
        return self._final_step_state

    @property
    def retry_stop_reason(self):
        return self._retry_stop_reason

    @property
    def attempt_count(self):
        return self._attempt_count

    @property
    def outcome_kind(self):
        return self._outcome_kind

    @property
    def invocation_sequence(self):
        """The registry's own audit sequence of the ACTUAL invocation, or None (never fabricated for a rejection)."""
        return self._invocation_sequence

    @property
    def attempts(self):
        """Fresh deep copy on every read."""
        return copy.deepcopy(self._attempts)

    @property
    def tool_result(self):
        """Fresh deep copy on every read (the bridge's tool execution report), or None when no tool execution happened."""
        return copy.deepcopy(self._tool_result)

    @property
    def failures(self):
        """Fresh deep copy on every read."""
        return copy.deepcopy(self._failures)

    @property
    def mapping(self):
        """Fresh deep copy of the pure mapping report when a mapping pair was supplied and reached stage f, else None."""
        return copy.deepcopy(self._mapping)

    @property
    def preflight(self):
        """Fresh deep copy of the registry's preflight report (last attempt) when one was made, else None."""
        return copy.deepcopy(self._preflight)

    def codes(self):
        return [f["code"] for f in self._failures]

    def to_dict(self):
        """Fresh plain-JSON view with a fixed key set (never contains a handler, registry, request, plan or callable)."""
        return {"ok": self.ok, "status": self._status, "failure_source": self._failure_source,
                "failure_code": self._failure_code, "step_id": self._step_id, "execution_started": self._execution_started,
                "final_step_state": self._final_step_state, "retry_stop_reason": self._retry_stop_reason,
                "attempt_count": self._attempt_count, "attempts": copy.deepcopy(self._attempts),
                "outcome_kind": self._outcome_kind, "tool_result": copy.deepcopy(self._tool_result),
                "failures": copy.deepcopy(self._failures), "invocation_sequence": self._invocation_sequence,
                "mapping": copy.deepcopy(self._mapping), "preflight": copy.deepcopy(self._preflight)}

    def __eq__(self, other):
        if not isinstance(other, AgentToolStepResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AgentToolStepResult is never persisted or pickled.")

    def __repr__(self):
        return (f"AgentToolStepResult(status={self._status!r}, step_id={self._step_id!r}, "
                f"failure_code={self._failure_code!r}, attempt_count={self._attempt_count!r})")


def _step_state(plan, step_id):
    """Read-only lookup of a step's current state, or None when it cannot be determined."""
    if isinstance(plan, Plan) and isinstance(plan.steps, list):
        for step in plan.steps:
            if getattr(step, "step_id", None) == step_id:
                state = getattr(step, "status", None)
                return state if isinstance(state, str) else None
    return None


def _rejected(step_id, state, failures, mapping=None):
    return AgentToolStepResult(
        _CREATE_TOKEN, status=STATUS_ADAPTER_REJECTED, failure_source=SOURCE_ADAPTER, failure_code=failures[0]["code"],
        step_id=step_id if isinstance(step_id, str) else None, execution_started=False, final_step_state=state,
        retry_stop_reason=None, attempt_count=0, attempts=[], tool_result=None, failures=failures,
        invocation_sequence=None, outcome_kind=None, mapping=mapping, preflight=None)


def _legacy_step_ids(check, plan):
    """Ids of steps (plan order) whose state is a legacy label, plus True when the plan-level status is one."""
    ids = [sid for sid, state in check.states.items() if state in LEGACY_STEP_STATES]
    plan_level = isinstance(plan.status, str) and plan.status in LEGACY_STEP_STATES
    return ids, plan_level


def _validate(plan, step_id, max_attempts, required_capabilities, capability_mapping, attempt_log):
    """Stages a-f in their fixed order. Returns (failures, mapping_report); failures is empty when every stage passed."""
    # a. plan validity
    if not isinstance(plan, Plan):
        return [_failure(ADAPTER_INVALID_PLAN_OBJECT, "Not a Plan; nothing to execute.")], None
    validity = validate_plan(plan)
    if not validity.valid:
        return [_failure(ADAPTER_INVALID_PLAN, "The plan is not valid; nothing executed.",
                         issues=[dict(i) for i in validity.issues])], None

    # b. step-state consistency (validate_plan() alone accepts legacy ready/blocked, so this second validation is mandatory)
    states = validate_plan_step_states(plan)
    if not states.valid:
        legacy_ids, legacy_plan = _legacy_step_ids(states, plan)
        issues = [dict(i) for i in states.issues]
        if legacy_ids or legacy_plan:
            return [_failure(ADAPTER_LEGACY_STEP_STATE,
                             "Legacy 'ready'/'blocked' states are not Section 4 states; the plan is not eligible for tool-step "
                             "execution and is neither converted nor repaired.", step_ids=legacy_ids,
                             plan_level=legacy_plan, issues=issues)], None
        return [_failure(ADAPTER_INCONSISTENT_STEP_STATE,
                         "The plan's step states are inconsistent with the Section 4 state contract; nothing executed.",
                         issues=issues)], None

    # c. step existence
    if not isinstance(step_id, str) or not step_id.strip():
        return [_failure(ADAPTER_INVALID_STEP_ID, "step_id must be a non-empty string.")], None
    if not any(getattr(step, "step_id", None) == step_id for step in plan.steps):
        return [_failure(ADAPTER_UNKNOWN_STEP, f"The plan has no step {step_id!r}.", step_id=step_id)], None

    # d. explicit execution authorization (plan-level gate; never inferred)
    if plan.metadata.get("execution_authorized") is not True:
        return [_failure(ADAPTER_EXECUTION_NOT_AUTHORIZED, "Execution is not authorized for this plan.")], None

    # e. retry arguments
    if not (isinstance(max_attempts, int) and not isinstance(max_attempts, bool) and 1 <= max_attempts <= MAX_ADAPTER_ATTEMPTS):
        return [_failure(ADAPTER_INVALID_MAX_ATTEMPTS,
                         f"max_attempts must be an int from 1 to {MAX_ADAPTER_ATTEMPTS} supplied by the caller.")], None
    if attempt_log is not None and not isinstance(attempt_log, list):
        return [_failure(ADAPTER_INVALID_ATTEMPT_LOG, "attempt_log must be None or a list.")], None

    # f. optional mapping consistency (the pair is explicit and caller-supplied; nothing is inferred)
    if (required_capabilities is None) != (capability_mapping is None):
        return [_failure(ADAPTER_INVALID_MAPPING_ARGUMENTS,
                         "required_capabilities and capability_mapping must be supplied together or not at all.")], None
    if capability_mapping is None:
        return [], None
    report = map_required_capabilities(required_capabilities, capability_mapping)      # pure; mutates nothing
    if report.status in _MAPPING_FAILURE_STATUSES:
        return [_failure(ADAPTER_MALFORMED_CAPABILITY_MAPPING,
                         "The supplied capability mapping or required list is malformed; nothing started.",
                         mapping_status=report.status)], report.to_dict()
    return [], report.to_dict()


def execute_agent_tool_step(plan, step_id, request, registry, max_attempts, required_capabilities=None,
                            capability_mapping=None, attempt_log=None):
    """Validate (stages a-f, see the module docstring) and then run ONE tool step through
    `execute_plan_tool_step_with_retry()`, the adapter's only execution entry point. Returns an immutable `AgentToolStepResult`;
    never raises for rejections or tool failures, never builds or changes the request, mapping or grants, keeps no state."""
    failures, mapping_report = _validate(plan, step_id, max_attempts, required_capabilities, capability_mapping, attempt_log)
    if failures:
        state = _step_state(plan, step_id) if isinstance(step_id, str) else None
        return _rejected(step_id, state, failures, mapping_report)

    outcome = execute_plan_tool_step_with_retry(plan, step_id, request, registry, max_attempts, required_capabilities,
                                                capability_mapping, attempt_log)
    final = outcome.final if isinstance(outcome.final, dict) else {}
    started = bool(final.get("execution_called"))
    execution = final.get("execution") if isinstance(final.get("execution"), dict) else {}
    if outcome.ok:
        source = None
    elif started:
        source = SOURCE_TOOL_EXECUTION
    else:
        source = SOURCE_PRE_START
    sequence = final.get("sequence") if started else None
    return AgentToolStepResult(
        _CREATE_TOKEN, status=outcome.status, failure_source=source, failure_code=None if outcome.ok else outcome.reason,
        step_id=outcome.step_id, execution_started=started, final_step_state=final.get("final_state"),
        retry_stop_reason=outcome.stop_reason, attempt_count=outcome.attempts_made, attempts=outcome.attempts,
        tool_result=execution.get("tool_result"), failures=outcome.failures, invocation_sequence=sequence,
        outcome_kind=final.get("outcome_kind"), mapping=mapping_report, preflight=final.get("preflight"))
