"""
Voice Verification Executor (Prompt 802, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
================================================================================================================
The next small layer after `VoiceVerificationPlan` (Prompt 800) and `VoiceVerificationResult` (Prompt 801). It is a deliberate PLACEHOLDER: it accepts a
plan and reports, deterministically, that voice verification is NOT IMPLEMENTED. It never verifies anything. It follows the `VoiceEnrollmentExecutor`
convention (Prompt 793) as a separate, unrelated type and returns the existing `VoiceVerificationResult` contract (Prompt 801), which is not changed.

    execute_voice_verification_plan(plan) -> VoiceVerificationResult

BEHAVIOR
1. `plan` must be exactly a `VoiceVerificationPlan` (None, a dict, a look-alike, a spoofed `__class__`, ... is not). Anything else gives a REJECTED
   result: status "REJECTED", code `VOICE_VERIFICATION_EXECUTOR_INVALID_PLAN`, metadata None. Nothing is read from the input.
2. A valid plan gives a NOT_IMPLEMENTED result: status "NOT_IMPLEMENTED", code `VOICE_VERIFICATION_EXECUTOR_NOT_IMPLEMENTED`. Nothing is verified.
3. The plan's three values are copied into the result's metadata exactly (the very same `str` objects), holding ONLY the keys request_id, profile_id,
   verification_mode in that order, and request_id / profile_id of the result are the plan's own. The plan object itself is NOT retained.
4. A plan whose values cannot be read, or are not exact non-empty strings (possible only for a malformed object), is treated as an invalid plan.
   `request_id` / `profile_id` are checked by the result contract itself; `verification_mode` (which only appears in metadata, whose contents the
   contract never inspects) is checked here with the same exact-type, non-empty rule.

THE REJECTED RESULT NEEDS PLACEHOLDER IDS
`VoiceVerificationResult` requires a non-empty `request_id` and `profile_id`, and a rejected input has none. The rejected result therefore carries the
fixed text `UNKNOWN` (`UNKNOWN_ID`) for both. It is a marker, not a looked-up or invented identity; the status and code are what identify the outcome.

RESULT
The returned object is the immutable `VoiceVerificationResult` built through its own public factory; this module defines no new result type, adds no
failure codes to the contract and changes no existing voice contract or validator. Execution is deterministic: equal plans give equal results.

WHAT THIS MODULE DOES NOT DO
No audio capture, recording, voice recognition, speaker verification, matching or biometric processing, no embeddings, no networking, filesystem access,
subprocess, persistence, database, AI model or external service. No clock or randomness, no module-level mutable state, no automatic execution. Its only
imports are the Prompt 800 plan type and the Prompt 801 result factory. Not wired into `process_input()`, Core, the Planner, the Agent Loop, Android or
runtime voice processing.
"""

from .voice_verification_plan import VoiceVerificationPlan
from .voice_verification_result import create_voice_verification_result

STATUS_REJECTED = "REJECTED"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
STATUSES = (STATUS_REJECTED, STATUS_NOT_IMPLEMENTED)

CODE_INVALID_PLAN = "VOICE_VERIFICATION_EXECUTOR_INVALID_PLAN"
CODE_NOT_IMPLEMENTED = "VOICE_VERIFICATION_EXECUTOR_NOT_IMPLEMENTED"
CODES = (CODE_INVALID_PLAN, CODE_NOT_IMPLEMENTED)

UNKNOWN_ID = "UNKNOWN"


def _build(request_id, profile_id, status, code, metadata):
    return create_voice_verification_result({"request_id": request_id, "profile_id": profile_id, "status": status, "code": code,
                                             "metadata": metadata}).result


def _rejected():
    return _build(UNKNOWN_ID, UNKNOWN_ID, STATUS_REJECTED, CODE_INVALID_PLAN, None)


def execute_voice_verification_plan(plan):
    """Report that executing `plan` (an exact `VoiceVerificationPlan`) is not implemented. Performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceVerificationResult`."""
    if type(plan) is not VoiceVerificationPlan:
        return _rejected()
    try:
        request_id, profile_id, verification_mode = plan.request_id, plan.profile_id, plan.verification_mode
    except Exception:
        return _rejected()
    if type(verification_mode) is not str or verification_mode == "":      # the result contract does not inspect metadata, so this one value is checked here
        return _rejected()
    result = _build(request_id, profile_id, STATUS_NOT_IMPLEMENTED, CODE_NOT_IMPLEMENTED,
                    {"request_id": request_id, "profile_id": profile_id, "verification_mode": verification_mode})
    return result if result is not None else _rejected()
