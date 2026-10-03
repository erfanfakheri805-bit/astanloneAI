"""
Voice Enrollment Executor (Prompt 793, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
==============================================================================================================
The next small layer after `VoiceEnrollmentPlan` (Prompt 792). It is a deliberate PLACEHOLDER: it accepts a plan and reports, deterministically, that
voice enrollment is NOT IMPLEMENTED. It never enrolls anything. It follows the earlier Section 9 executor convention (Prompt 778) but returns the existing
`VoiceEnrollmentResult` contract (Prompt 790), which is not changed.

    execute_voice_enrollment_plan(plan) -> VoiceEnrollmentResult

BEHAVIOR
1. `plan` must be exactly a `VoiceEnrollmentPlan` (None, a dict, a look-alike, a spoofed `__class__`, ... is not). Anything else gives a REJECTED
   result: status "REJECTED", code `VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN`, metadata None. Nothing is read from the input.
2. A valid plan gives a NOT_IMPLEMENTED result: status "NOT_IMPLEMENTED", code `VOICE_ENROLLMENT_EXECUTOR_NOT_IMPLEMENTED`. Nothing is enrolled.
3. The plan's three values are copied into the result's metadata exactly (the very same `str` objects), holding ONLY the keys request_id, profile_id,
   enrollment_mode in that order, and request_id / profile_id of the result are the plan's own. The plan object itself is NOT retained.
4. A plan whose values cannot be read, or are not exact non-empty strings (possible only for a malformed object), is treated as an invalid plan.
   `request_id` / `profile_id` are checked by the result contract itself; `enrollment_mode` (which only appears in metadata, whose contents the
   contract never inspects) is checked here with the same exact-type, non-empty rule.

THE REJECTED RESULT NEEDS PLACEHOLDER IDS
`VoiceEnrollmentResult` requires a non-empty `request_id` and `profile_id`, and a rejected input has none. The rejected result therefore carries the fixed
text `UNKNOWN` (`UNKNOWN_ID`) for both. It is a marker, not a looked-up or invented identity; the status and code are what identify the outcome.

RESULT
The returned object is the immutable `VoiceEnrollmentResult` built through its own public factory; this module defines no new result type, adds no failure
codes to the contract and changes no existing voice contract or validator. Execution is deterministic: equal plans give equal results.

WHAT THIS MODULE DOES NOT DO
No audio capture, recording, voice recognition, matching, enrollment or biometric processing, no networking, filesystem access, subprocess, persistence,
database, AI model or external service. No clock or randomness, no module-level mutable state, no automatic execution. Its only imports are the Prompt 792
plan type and the Prompt 790 result factory. Not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or runtime voice processing.
"""

from .voice_enrollment_plan import VoiceEnrollmentPlan
from .voice_enrollment_result import create_voice_enrollment_result

STATUS_REJECTED = "REJECTED"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
STATUSES = (STATUS_REJECTED, STATUS_NOT_IMPLEMENTED)

CODE_INVALID_PLAN = "VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN"
CODE_NOT_IMPLEMENTED = "VOICE_ENROLLMENT_EXECUTOR_NOT_IMPLEMENTED"
CODES = (CODE_INVALID_PLAN, CODE_NOT_IMPLEMENTED)

UNKNOWN_ID = "UNKNOWN"


def _build(request_id, profile_id, status, code, metadata):
    return create_voice_enrollment_result({"request_id": request_id, "profile_id": profile_id, "status": status, "code": code,
                                           "metadata": metadata}).result


def _rejected():
    return _build(UNKNOWN_ID, UNKNOWN_ID, STATUS_REJECTED, CODE_INVALID_PLAN, None)


def execute_voice_enrollment_plan(plan):
    """Report that executing `plan` (an exact `VoiceEnrollmentPlan`) is not implemented. Performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceEnrollmentResult`."""
    if type(plan) is not VoiceEnrollmentPlan:
        return _rejected()
    try:
        request_id, profile_id, enrollment_mode = plan.request_id, plan.profile_id, plan.enrollment_mode
    except Exception:
        return _rejected()
    if type(enrollment_mode) is not str or enrollment_mode == "":      # the result contract does not inspect metadata, so this one value is checked here
        return _rejected()
    result = _build(request_id, profile_id, STATUS_NOT_IMPLEMENTED, CODE_NOT_IMPLEMENTED,
                    {"request_id": request_id, "profile_id": profile_id, "enrollment_mode": enrollment_mode})
    return result if result is not None else _rejected()
