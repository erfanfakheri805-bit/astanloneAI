"""
Controlled Plan Step Execution Orchestration (Prompt 691)
===========================================================
The smallest additive layer that explicitly runs ONE already-ready plan step through a CALLER-OWNED executor:

    execute_plan_step(plan, step_id, executor) -> PlanStepExecutionResult

This is NOT the Tools section. The executor is an injected callback and nothing else: no tool discovery,
selection or invocation, no network/filesystem/app access, no threads, subprocesses, scheduling or background
work, and no wiring into `process_input()`. `PlanStep`, `PlanManager` and Prompts 684-690 are reused, not changed.

FLOW (each numbered gate rejects BEFORE any mutation and BEFORE the executor is ever called)
  1. `plan` is a Plan, `step_id` a non-empty string, `executor` callable.
  2. `validate_plan(plan)` (Prompt 680) is valid. Validation/readiness never execute anything.
  3. `start_plan_step(plan, step_id)` (Prompt 689) applies. It stays authoritative for unknown step, inconsistent
     plan state, readiness (Prompt 686) and `execution_authorized is True`; its failure codes are passed through.
  4. The executor is called EXACTLY ONCE with a plain dict holding only that step's own data (step_id,
     description, input_data, expected_output, required_capabilities) - deep copies, never the Plan or PlanStep.
  5. Its returned value is the explicit step output -> `complete_plan_step(plan, step_id, output)`.
     If the executor raises an `Exception`, it is caught here (never re-raised) -> `fail_plan_step(...)` with a
     deterministic structured reason. If it returns something `complete_plan_step` refuses (None, blank string,
     not JSON-safe), the step is failed the same way with EXECUTOR_OUTPUT_INVALID. There is NO automatic retry.

Once step 3 has applied, a `failed` final state is intentional and stays consistent with
`validate_plan_step_states` / `validate_plan`. Authorization is permission only; it never runs anything itself.
"""

from planning.plan import Plan, ensure_structured_data
from planning.plan_builder import _failure
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.plan_validation import validate_plan

STATUS_EXECUTION_COMPLETED = "completed"
STATUS_EXECUTION_FAILED = "failed"        # the step ran (was started) and ended failed
STATUS_EXECUTION_REJECTED = "rejected"    # a precondition failed; plan untouched, executor never called

ORCH_INVALID_PLAN_OBJECT = "INVALID_PLAN_OBJECT"
ORCH_INVALID_PLAN = "INVALID_PLAN"
ORCH_INVALID_STEP_ID = "INVALID_STEP_ID"
ORCH_INVALID_EXECUTOR = "INVALID_EXECUTOR"
ORCH_EXECUTOR_EXCEPTION = "EXECUTOR_EXCEPTION"
ORCH_EXECUTOR_OUTPUT_INVALID = "EXECUTOR_OUTPUT_INVALID"
ORCH_TRANSITION_FAILED = "STEP_TRANSITION_FAILED"

_MAX_MESSAGE = 500


class PlanStepExecutionResult:
    __slots__ = ("status", "step_id", "previous_state", "final_state", "output", "reason", "failures",
                 "executor_called")

    def __init__(self, step_id=None):
        self.status = STATUS_EXECUTION_REJECTED
        self.step_id = step_id
        self.previous_state = None
        self.final_state = None     # equals previous_state when rejected (nothing changed)
        self.output = None          # the stored step output; only set on success
        self.reason = None          # first failure code, or None on success
        self.failures = []
        self.executor_called = False

    @property
    def ok(self):
        return self.status == STATUS_EXECUTION_COMPLETED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {
            "ok": self.ok,
            "status": self.status,
            "step_id": self.step_id,
            "previous_state": self.previous_state,
            "final_state": self.final_state,
            "output": self.output,
            "reason": self.reason,
            "failures": [dict(f) for f in self.failures],
            "executor_called": self.executor_called,
        }


def _state_of(plan, step_id):
    """Read-only lookup of a step's current state, or None when it cannot be determined."""
    if isinstance(plan, Plan) and isinstance(plan.steps, list):
        for step in plan.steps:
            if getattr(step, "step_id", None) == step_id:
                return getattr(step, "status", None)
    return None


def _reject(result, plan, failures):
    result.status = STATUS_EXECUTION_REJECTED
    result.previous_state = result.final_state = _state_of(plan, result.step_id)
    result.failures = failures
    result.reason = failures[0]["code"]
    return result


def _executor_input(step):
    """Only what is needed to perform this step; plain, defensively-copied data."""
    return {
        "step_id": step.step_id,
        "description": step.description,
        "input_data": ensure_structured_data(step.input_data),
        "expected_output": step.expected_output,
        "required_capabilities": list(step.required_capabilities),
    }


def _fail_started_step(result, plan, code, message, reason_payload):
    """The step is in_progress and the executor did not deliver an explicit output: record failure."""
    failed = fail_plan_step(plan, result.step_id, reason_payload)
    result.status = STATUS_EXECUTION_FAILED
    result.final_state = _state_of(plan, result.step_id)
    result.failures = [_failure(code, message, **{k: v for k, v in reason_payload.items()
                                                    if k not in ("code", "message")})]
    if not failed.ok:       # defensive: the failure could not be recorded; report it, never raise
        result.failures.append(_failure(ORCH_TRANSITION_FAILED, "The failure could not be recorded.",
                                        issues=[dict(f) for f in failed.failures]))
    result.reason = code
    return result


def execute_plan_step(plan, step_id, executor):
    """Run one ready step of an authorized, valid plan through the caller-provided `executor(step_input)`.
    Returns a `PlanStepExecutionResult`. Never raises for executor failures; never retries."""
    result = PlanStepExecutionResult(step_id if isinstance(step_id, str) else None)

    if not isinstance(plan, Plan):
        return _reject(result, plan, [_failure(ORCH_INVALID_PLAN_OBJECT, "Not a Plan; nothing to execute.")])
    if not isinstance(step_id, str) or not step_id.strip():
        return _reject(result, plan, [_failure(ORCH_INVALID_STEP_ID, "The step id must be a non-empty string.")])
    if not callable(executor):
        return _reject(result, plan, [_failure(ORCH_INVALID_EXECUTOR, "An explicit callable executor is required.")])

    validation = validate_plan(plan)
    if not validation.valid:
        return _reject(result, plan, [_failure(ORCH_INVALID_PLAN, "The plan is not valid; nothing executed.",
                                               issues=[dict(i) for i in validation.issues])])

    started = start_plan_step(plan, step_id)      # authoritative: known step, consistent state, ready, authorized
    result.previous_state = started.previous_state
    if not started.ok:
        result.final_state = started.new_state
        result.failures = [dict(f) for f in started.failures]
        result.reason = result.failures[0]["code"]
        return result

    # From here the step is in_progress; the executor is called exactly once.
    result.executor_called = True
    try:
        output = executor(_executor_input(started.step))
    except Exception as exc:        # caught at the boundary; deliberately not re-raised
        try:
            message = str(exc)[:_MAX_MESSAGE]
        except Exception:
            message = ""
        payload = {"code": ORCH_EXECUTOR_EXCEPTION, "exception_type": type(exc).__name__, "message": message}
        return _fail_started_step(result, plan, ORCH_EXECUTOR_EXCEPTION,
                                  f"The executor raised {type(exc).__name__}.", payload)

    completed = complete_plan_step(plan, step_id, output)
    if not completed.ok:            # e.g. None / blank / non-JSON-safe output: explicit output is required
        payload = {"code": ORCH_EXECUTOR_OUTPUT_INVALID, "rejected_by": completed.codes()[0]}
        return _fail_started_step(result, plan, ORCH_EXECUTOR_OUTPUT_INVALID,
                                  "The executor returned no explicit, JSON-safe output.", payload)

    result.status = STATUS_EXECUTION_COMPLETED
    result.final_state = completed.new_state
    result.output = completed.step.output_data
    return result
