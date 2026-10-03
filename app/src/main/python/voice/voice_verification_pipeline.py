"""
Voice Verification Pipeline (Prompt 804, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
================================================================================================================
A thin, deterministic entry point in front of the Prompt 803 dispatcher. It adds a strict exact-type gate and otherwise delegates; it holds no dispatch,
execution or verification logic of its own. It follows the Prompt 795 enrollment pipeline convention as a separate, unrelated type.

    run_voice_verification_pipeline(plan) -> VoiceVerificationResult

BEHAVIOR
1. `plan` must be exactly a `VoiceVerificationPlan` (None, a dict, a look-alike, a spoofed `__class__`, ... is not). Anything else gives a REJECTED
   result: status "REJECTED", code `VOICE_VERIFICATION_PIPELINE_INVALID_PLAN`, metadata None. The dispatcher is NOT called and nothing is read from the
   input. The result is the existing `VoiceVerificationResult` (Prompt 801), built through its own public factory; it needs non-empty ids, so it carries
   the executor's `UNKNOWN` placeholder marker for request_id and profile_id (a marker, not an identity).
2. An exact plan is passed, unchanged, to the public `dispatch_voice_verification(plan)` EXACTLY ONCE, and the object it returns is returned as-is
   (same identity, not copied, wrapped, inspected or altered). Whatever the dispatcher (and, through it, the executor) decides is final.

NOTHING IS DUPLICATED
No plan field is read, no metadata is built, no status is chosen for valid plans and no dispatcher or executor rule is re-implemented here.

WHAT THIS MODULE DOES NOT DO
No audio capture, recording, voice recognition, speaker verification or biometric processing, no embeddings, no I/O, networking, filesystem, persistence,
database, subprocess, AI model or external/cloud service. No clock or randomness, no module-level mutable state, no retention of the plan or the result.
Existing voice contracts, plan, result, executor and dispatcher are unchanged. Not wired into `process_input()`, Core, the Planner, the Agent Loop,
Android or runtime voice processing. Nothing calls it automatically.
"""

from .voice_verification_dispatcher import dispatch_voice_verification
from .voice_verification_executor import UNKNOWN_ID
from .voice_verification_plan import VoiceVerificationPlan
from .voice_verification_result import create_voice_verification_result

STATUS_REJECTED = "REJECTED"
CODE_INVALID_PLAN = "VOICE_VERIFICATION_PIPELINE_INVALID_PLAN"
CODES = (CODE_INVALID_PLAN,)


def _rejected():
    return create_voice_verification_result({"request_id": UNKNOWN_ID, "profile_id": UNKNOWN_ID, "status": STATUS_REJECTED,
                                             "code": CODE_INVALID_PLAN, "metadata": None}).result


def run_voice_verification_pipeline(plan):
    """Run `plan` (an exact `VoiceVerificationPlan`) through `dispatch_voice_verification` once and return its result unchanged.
    Anything else gives a REJECTED `VoiceVerificationResult`. Performs no I/O, is deterministic, never raises for bad inputs."""
    if type(plan) is not VoiceVerificationPlan:
        return _rejected()
    return dispatch_voice_verification(plan)
