"""
Caller-side Tool Step Runner (Prompt 719-B, Section 6)
=======================================================
A small, STATELESS adapter between a successful Prompt 719-A `ToolStepIntentResult` and the existing Prompt 711 retry authority:

    run_tool_step_intent(intent_result, plan, registry, attempt_log=None) -> ToolStepRunResult

The runner reads plan_id, step_id, request, max_attempts, required_capabilities and capability_mapping from the intent result and makes
EXACTLY ONE call:

    execute_plan_tool_step_with_retry(plan, step_id, request, registry, max_attempts, required_capabilities, capability_mapping, attempt_log)

`plan` is the caller's Plan object: the retry API needs it and the intent result deliberately carries none. The runner only compares
`plan.plan_id` with the intent's `plan_id` (so a step is never run against a different plan) and passes the plan on untouched.
`capability_system` is NOT a parameter: no existing Section 6 execution API takes one, so there is nothing to pass it to.

REJECTED BEFORE EXECUTION (registry, executor and plan untouched; no attempt record is appended to the caller's log)
    RUNNER_INVALID_INTENT_RESULT   not an exact `ToolStepIntentResult`
    RUNNER_INTENT_NOT_OK           the intent result has ok == False
    RUNNER_INVALID_MAPPING_PAIR    exactly one of required_capabilities / capability_mapping is present (Prompt 711 rule; never invented)
    RUNNER_PLAN_ID_MISMATCH        `plan.plan_id` is not the intent's plan_id

MAPPING ARGUMENTS (Prompt 711 rules)  neither -> no mapping; both -> both passed unchanged; one only -> rejected.
ATTEMPT LOG  caller-owned; passed to the retry layer as-is. The runner keeps no log and appends no record of its own.

RESULT  `ToolStepRunResult` is immutable and data-only (read-only slots, not subclassable, obtainable only from the runner, copy/deepcopy
return the same object, pickling refused, unhashable). ok, plan_id, step_id, outcome_kind, stop_reason, attempts, final_step_state,
failures, execution_result. Every read of a mutable value returns a FRESH copy. No handler, registry or capability-system object is held.

WHAT THIS MODULE DOES NOT DO  retry, start/complete PlanSteps, authorize, map capabilities, create ToolRequests, resolve routes, select
tools, inspect natural language, revalidate the intent, touch AgentLoop/`process_input`/Core, or keep module-level state.
"""

from agent.tool_step_intent import ToolStepIntentResult
from planning.tool_step_retry import execute_plan_tool_step_with_retry

RUNNER_INVALID_INTENT_RESULT = "RUNNER_INVALID_INTENT_RESULT"
RUNNER_INTENT_NOT_OK = "RUNNER_INTENT_NOT_OK"
RUNNER_INVALID_MAPPING_PAIR = "RUNNER_INVALID_MAPPING_PAIR"
RUNNER_PLAN_ID_MISMATCH = "RUNNER_PLAN_ID_MISMATCH"
RUNNER_REJECTION_CODES = (RUNNER_INVALID_INTENT_RESULT, RUNNER_INTENT_NOT_OK, RUNNER_INVALID_MAPPING_PAIR, RUNNER_PLAN_ID_MISMATCH)

OUTCOME_RUNNER_REJECTION = "runner_rejection"
STOP_RUNNER_REJECTED = "runner_rejected"

_CREATE_TOKEN = object()


def _copy_json(value):
    if isinstance(value, dict):
        return {k: _copy_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_json(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_copy_json(v) for v in value)
    return value


class ToolStepRunResult:
    """Immutable data-only outcome of `run_tool_step_intent()`. Obtain it only from that function."""

    __slots__ = ("_ok", "_plan_id", "_step_id", "_outcome_kind", "_stop_reason", "_attempts", "_final_step_state", "_failures",
                 "_execution_result")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ToolStepRunResult cannot be subclassed.")

    def __init__(self, _token, ok, plan_id, step_id, outcome_kind, stop_reason, attempts, final_step_state, failures,
                 execution_result):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use run_tool_step_intent() to obtain a ToolStepRunResult.")
        for slot, value in (("_ok", ok), ("_plan_id", plan_id), ("_step_id", step_id), ("_outcome_kind", outcome_kind),
                            ("_stop_reason", stop_reason), ("_attempts", _copy_json(attempts)),
                            ("_final_step_state", final_step_state), ("_failures", _copy_json(failures)),
                            ("_execution_result", _copy_json(execution_result))):
            object.__setattr__(self, slot, value)

    def __setattr__(self, key, value):
        raise AttributeError("ToolStepRunResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ToolStepRunResult is immutable.")

    @property
    def ok(self):
        return self._ok

    @property
    def plan_id(self):
        return self._plan_id

    @property
    def step_id(self):
        return self._step_id

    @property
    def outcome_kind(self):
        return self._outcome_kind

    @property
    def stop_reason(self):
        return self._stop_reason

    @property
    def attempts(self):
        """A fresh list of fresh attempt records on every read."""
        return _copy_json(self._attempts)

    @property
    def final_step_state(self):
        return self._final_step_state

    @property
    def failures(self):
        """A fresh list of fresh dicts on every read."""
        return _copy_json(self._failures)

    @property
    def execution_result(self):
        """A fresh copy of the last attempt's plain-data result (None when nothing was attempted)."""
        return _copy_json(self._execution_result)

    def codes(self):
        return [f["code"] for f in self._failures]

    def to_dict(self):
        return {"ok": self._ok, "plan_id": self._plan_id, "step_id": self._step_id, "outcome_kind": self._outcome_kind,
                "stop_reason": self._stop_reason, "attempts": self.attempts, "final_step_state": self._final_step_state,
                "failures": self.failures, "execution_result": self.execution_result}

    def __eq__(self, other):
        if not isinstance(other, ToolStepRunResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ToolStepRunResult is never persisted or pickled.")

    def __repr__(self):
        return f"ToolStepRunResult(ok={self._ok!r}, outcome_kind={self._outcome_kind!r}, stop_reason={self._stop_reason!r})"


def _rejected(code, message, plan_id=None, step_id=None):
    return ToolStepRunResult(_CREATE_TOKEN, False, plan_id, step_id, OUTCOME_RUNNER_REJECTION, STOP_RUNNER_REJECTED, [], None,
                             [{"code": code, "message": message}], None)


def run_tool_step_intent(intent_result, plan, registry, attempt_log=None):
    """Run one successful `ToolStepIntentResult` through `execute_plan_tool_step_with_retry` and return a `ToolStepRunResult`.
    Pure adapter: rejects before execution on the codes in the module docstring, otherwise delegates once and reports the outcome."""
    if type(intent_result) is not ToolStepIntentResult:
        return _rejected(RUNNER_INVALID_INTENT_RESULT, "intent_result must be a ToolStepIntentResult.")
    if intent_result.ok is not True:
        return _rejected(RUNNER_INTENT_NOT_OK, "Only a successful ToolStepIntentResult can be run.")

    plan_id = intent_result.plan_id
    step_id = intent_result.step_id
    required = intent_result.required_capabilities
    mapping = intent_result.capability_mapping
    if (required is None) != (mapping is None):
        return _rejected(RUNNER_INVALID_MAPPING_PAIR,
                         "required_capabilities and capability_mapping must both be present or both be absent.", plan_id, step_id)
    if getattr(plan, "plan_id", None) != plan_id:
        return _rejected(RUNNER_PLAN_ID_MISMATCH, "The plan's plan_id does not match the intent's plan_id.", plan_id, step_id)

    retry = execute_plan_tool_step_with_retry(plan, step_id, intent_result.request, registry, intent_result.max_attempts,
                                              required, mapping, attempt_log)
    data = retry.to_dict()
    final = data["final"]
    return ToolStepRunResult(_CREATE_TOKEN, data["ok"], plan_id, step_id,
                             None if final is None else final.get("outcome_kind"), data["stop_reason"], data["attempts"],
                             None if final is None else final.get("final_state"), data["failures"], final)
