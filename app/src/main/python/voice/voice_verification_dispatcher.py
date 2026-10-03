"""
Voice Verification Dispatcher (Prompt 803, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
===================================================================================================================
A thin, deterministic dispatch layer in front of the Prompt 802 executor. It adds a strict exact-type gate and otherwise delegates; it holds no
verification logic of its own. It follows the `VoiceEnrollmentDispatcher` convention (Prompt 794) as a separate, unrelated type.

    dispatch_voice_verification(plan) -> VoiceVerificationResult

BEHAVIOR
1. `plan` must be exactly a `VoiceVerificationPlan` (None, a dict, a look-alike, a subclass-free spoofed `__class__`, ... is not). Anything else gives a
   REJECTED result: status "REJECTED", code `VOICE_VERIFICATION_DISPATCHER_INVALID_PLAN`, metadata None. The executor is NOT called and nothing is read
   from the input. The result is the existing `VoiceVerificationResult` (Prompt 801), built through its own public factory; it needs non-empty ids, so
   it carries the executor's `UNKNOWN` placeholder marker for request_id and profile_id (not an identity).
2. An exact plan is passed, unchanged, to the public `execute_voice_verification_plan(plan)` EXACTLY ONCE, and the object it returns is returned
   as-is (same identity, not copied, wrapped, inspected or altered). Whatever the executor decides (including its own rejection of a malformed exact
   plan) is final.

NOTHING IS DUPLICATED
No plan field is read, no metadata is built, no status is chosen for valid plans and no executor rule is re-implemented here.

WHAT THIS MODULE DOES NOT DO
No audio capture, recording, voice recognition, speaker verification or biometric processing, no embeddings, no I/O, networking, filesystem,
persistence, database, subprocess, AI model or external/cloud service. No clock or randomness, no module-level mutable state, no retention of the plan or
the result. Existing voice contracts, plan, result and executor are unchanged. Not wired into `process_input()`, Core, the Planner, the Agent Loop,
Android or runtime voice processing. Nothing calls it automatically.
"""

from .voice_verification_executor import UNKNOWN_ID, execute_voice_verification_plan
from .voice_verification_plan import VoiceVerificationPlan
from .voice_verification_result import create_voice_verification_result

STATUS_REJECTED = "REJECTED"
CODE_INVALID_PLAN = "VOICE_VERIFICATION_DISPATCHER_INVALID_PLAN"
CODES = (CODE_INVALID_PLAN,)


def _rejected():
    return create_voice_verification_result({"request_id": UNKNOWN_ID, "profile_id": UNKNOWN_ID, "status": STATUS_REJECTED,
                                             "code": CODE_INVALID_PLAN, "metadata": None}).result


def dispatch_voice_verification(plan):
    """Dispatch `plan` (an exact `VoiceVerificationPlan`) to `execute_voice_verification_plan` once and return its result unchanged.
    Anything else gives a REJECTED `VoiceVerificationResult`. Performs no I/O, is deterministic, never raises for bad inputs."""
    if type(plan) is not VoiceVerificationPlan:
        return _rejected()
    return execute_voice_verification_plan(plan)
