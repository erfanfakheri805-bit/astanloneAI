"""
Controlled Retry Policy for Tool Steps (Prompt 711, Section 6)
================================================================
A narrow, additive, STATELESS and caller-controlled retry layer over the existing pre-start boundary:

    execute_plan_tool_step_with_retry(plan, step_id, request, registry, max_attempts,
                                      required_capabilities=None, capability_mapping=None,
                                      attempt_log=None) -> ToolStepRetryResult

  max_attempts           explicit int > 0 supplied by the caller (a real int, not bool). Never inferred, stored or defaulted.
  required_capabilities  } both None -> every attempt is the Prompt 709 preflighted call; both given -> every attempt is the
  capability_mapping     } Prompt 710 mapped call. Exactly one given is an invalid argument (no attempt is made).
  attempt_log            optional caller-owned list; one fresh plain-dict record per attempt is appended to THAT list. The module
                         keeps no log, counter, cache or module variable of its own.

EVERY attempt is exactly one call of the existing pre-start path (the preflighted or mapped function). This module never calls a handler,
the registry's execution entry point, the bridge, a step transition or the registry itself; Section 4 and Section 5 stay the only authorities.

WHAT MAY BE RETRIED (only failures that happened BEFORE the step started, and only these):
  1. Section 4 step state that can change outside this call: `STEP_NOT_READY` and `EXECUTION_NOT_AUTHORIZED`, and only while the step is
     still `pending` (a step that is completed/failed/in_progress is never retried).
  2. Capability-mapping rejection where the mapping itself is well-formed but does not satisfy the requirements (`CAPABILITY_MAPPING_REJECTED`
     with mapping status `unmapped`).
  3. A mapped Section 5 grant the request did not supply (`MAPPED_GRANT_NOT_SUPPLIED`).
  4. A Section 5 registry preflight rejection (`registry_preflight_rejection`: unknown/disabled tool, permission, confirmation, capability,
     input), except a defective `preflight()` (`PRESTART_PREFLIGHT_EXCEPTION`).
WHAT IS NEVER RETRIED (stops immediately):
  - a completed step, or any step that started (`execution_called`): success is terminal, a real tool/execution failure (including a
    TOCTOU failure after a passed preflight) is terminal and the step stays failed;
  - malformed arguments (`INVALID_BRIDGE_*`, `UNKNOWN_BRIDGE_STEP`, `INVALID_PRESTART_REQUEST`, `INVALID_REJECTION_LOG`), invalid plans
    (`INVALID_PLAN`, `INVALID_PLAN_OBJECT`, `PLAN_READINESS_UNDETERMINED`), unknown steps, a malformed mapping or required list
    (mapping status `invalid_mapping`/`invalid_input`), a defective registry preflight, and anything not on the list above (allow-list).
  - invalid retry arguments (`max_attempts`, `attempt_log`, the mapping pair) -> rejected with ZERO attempts.
  - programming errors: exceptions are not caught here and propagate.

INVARIANTS
  - Nothing is changed between attempts: the request, its grants/permissions/confirmation, the mapping and the required list are passed
    unchanged each time. A retryable condition that stays the same is re-asked only because the caller allowed several attempts; if the
    outside world (plan state, registry) changed in between, the next attempt simply sees it.
  - No delay, backoff, thread, scheduling, clock or randomness. Attempts run synchronously, in order.
  - Pre-start rejections are NOT invocations: no sequence number is created (`sequence` is None in their records); only a started execution
    carries the registry's own audit `sequence`, copied unchanged. The registry history is never written by a rejection.
  - Stops at: `completed`, `execution_failed` (started then failed), `non_retryable_rejection`, `attempt_limit_reached`, `invalid_arguments`.
"""

from planning.tool_step_executor import (OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_REGISTRY_PREFLIGHT_REJECTION,
                                         PRESTART_CAPABILITY_MAPPING_REJECTED, PRESTART_MAPPED_GRANT_NOT_SUPPLIED,
                                         PRESTART_PREFLIGHT_EXCEPTION, STATUS_TOOL_STEP_COMPLETED,
                                         STATUS_TOOL_STEP_FAILED, execute_plan_tool_step_mapped,
                                         execute_plan_tool_step_preflighted)

STATUS_RETRY_COMPLETED = "completed"
STATUS_RETRY_FAILED = "failed"          # the step started and failed (terminal)
STATUS_RETRY_REJECTED = "rejected"      # never started: non-retryable, limit reached, or invalid retry arguments

STOP_COMPLETED = "completed"
STOP_EXECUTION_FAILED = "execution_failed"
STOP_NON_RETRYABLE = "non_retryable_rejection"
STOP_LIMIT_REACHED = "attempt_limit_reached"
STOP_INVALID_ARGUMENTS = "invalid_arguments"

RETRY_INVALID_LIMIT = "INVALID_RETRY_ATTEMPT_LIMIT"
RETRY_INVALID_LOG = "INVALID_RETRY_ATTEMPT_LOG"
RETRY_INVALID_MAPPING_PAIR = "INVALID_RETRY_MAPPING_ARGUMENTS"

_RETRYABLE_STEP_STATE_CODES = frozenset({"STEP_NOT_READY", "EXECUTION_NOT_AUTHORIZED"})     # Section 4 codes, pending step only
_MAPPING_UNMAPPED_STATUS = "unmapped"


def _copy_json(value):
    if isinstance(value, dict):
        return {k: _copy_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_json(v) for v in value]
    return value


def is_retryable_prestart_result(result):
    """True only for a pre-start rejection on the retryable list (see the module docstring). Pure; reads `result` only."""
    if result.execution_called or result.status == STATUS_TOOL_STEP_COMPLETED or result.status == STATUS_TOOL_STEP_FAILED:
        return False
    reason = result.reason
    if result.outcome_kind == OUTCOME_REGISTRY_PREFLIGHT_REJECTION:
        return reason != PRESTART_PREFLIGHT_EXCEPTION
    if result.outcome_kind != OUTCOME_PRE_REGISTRY_REJECTION:
        return False
    if reason == PRESTART_MAPPED_GRANT_NOT_SUPPLIED:
        return True
    if reason == PRESTART_CAPABILITY_MAPPING_REJECTED:
        mapping = result.failures[0].get("capability_mapping") if result.failures else None
        return isinstance(mapping, dict) and mapping.get("status") == _MAPPING_UNMAPPED_STATUS
    if reason in _RETRYABLE_STEP_STATE_CODES:
        return result.previous_state == "pending"
    return False


class ToolStepRetryResult:
    """Outcome of one `execute_plan_tool_step_with_retry()` call. Plain data; holds no plan, request, registry or handler."""

    __slots__ = ("status", "stop_reason", "step_id", "max_attempts", "attempts_made", "attempts", "final", "reason", "failures")

    def __init__(self, step_id=None, max_attempts=None):
        self.status = STATUS_RETRY_REJECTED
        self.stop_reason = STOP_INVALID_ARGUMENTS
        self.step_id = step_id
        self.max_attempts = max_attempts
        self.attempts_made = 0
        self.attempts = []          # one plain dict per attempt, in order (independent copies of what the caller's log received)
        self.final = None           # PreflightedToolStepResult.to_dict() of the last attempt, or None when no attempt was made
        self.reason = None
        self.failures = []

    @property
    def ok(self):
        return self.status == STATUS_RETRY_COMPLETED

    def codes(self):
        return [f["code"] for f in self.failures]

    def to_dict(self):
        return {"ok": self.ok, "status": self.status, "stop_reason": self.stop_reason, "step_id": self.step_id,
                "max_attempts": self.max_attempts, "attempts_made": self.attempts_made, "attempts": _copy_json(self.attempts),
                "final": None if self.final is None else _copy_json(self.final), "reason": self.reason,
                "failures": _copy_json(self.failures)}


def _invalid(result, code, message):
    result.failures = [{"code": code, "message": message}]
    result.reason = code
    return result


def _record(number, res, retryable):
    return {"record_type": "tool_step_attempt", "attempt": number, "outcome_kind": res.outcome_kind, "status": res.status,
            "execution_started": bool(res.execution_called), "retryable": retryable, "step_id": res.step_id,
            "tool_name": res.tool_name, "previous_state": res.previous_state, "final_state": res.final_state,
            "reason": res.reason, "codes": res.codes(), "failures": _copy_json(res.failures),
            "invocation_recorded": bool(res.execution_called) and res.sequence is not None, "sequence": res.sequence}


def execute_plan_tool_step_with_retry(plan, step_id, request, registry, max_attempts, required_capabilities=None,
                                      capability_mapping=None, attempt_log=None):
    """Run the pre-start tool-step path up to `max_attempts` times, retrying ONLY retryable pre-start rejections (see the module
    docstring). Returns a `ToolStepRetryResult`; never raises for rejections or tool failures, never mutates its arguments, keeps no
    state, never delays."""
    result = ToolStepRetryResult(step_id if isinstance(step_id, str) else None,
                                 max_attempts if isinstance(max_attempts, int) and not isinstance(max_attempts, bool) else None)
    if not (isinstance(max_attempts, int) and not isinstance(max_attempts, bool) and max_attempts > 0):
        return _invalid(result, RETRY_INVALID_LIMIT, "max_attempts must be an int greater than 0 supplied by the caller.")
    if attempt_log is not None and not isinstance(attempt_log, list):
        return _invalid(result, RETRY_INVALID_LOG, "attempt_log must be None or a list.")
    if (required_capabilities is None) != (capability_mapping is None):
        return _invalid(result, RETRY_INVALID_MAPPING_PAIR,
                        "required_capabilities and capability_mapping must be supplied together or not at all.")
    mapped = capability_mapping is not None

    for number in range(1, max_attempts + 1):
        if mapped:
            res = execute_plan_tool_step_mapped(plan, step_id, request, registry, required_capabilities, capability_mapping)
        else:
            res = execute_plan_tool_step_preflighted(plan, step_id, request, registry)
        retryable = is_retryable_prestart_result(res)
        record = _record(number, res, retryable)
        result.attempts.append(record)
        if attempt_log is not None:
            list.append(attempt_log, _copy_json(record))        # the caller's own log; this module keeps none
        result.attempts_made = number
        result.final = res.to_dict()
        result.reason = res.reason
        result.failures = _copy_json(res.failures)
        if res.status == STATUS_TOOL_STEP_COMPLETED:
            result.status, result.stop_reason = STATUS_RETRY_COMPLETED, STOP_COMPLETED
            return result
        if res.execution_called:                                # started and did not complete: terminal, never retried
            result.status, result.stop_reason = STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED
            return result
        result.status = STATUS_RETRY_REJECTED
        if not retryable:
            result.stop_reason = STOP_NON_RETRYABLE
            return result
    result.stop_reason = STOP_LIMIT_REACHED
    return result
