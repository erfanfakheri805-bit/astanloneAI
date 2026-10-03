# Prompt 804 - Section 10: Voice Verification Pipeline

Status: **implemented.** `voice/voice_verification_pipeline.py` (pinned by `tests/test_voice_verification_pipeline_prompt804.py`).
A thin entry point in front of the Prompt 803 dispatcher, in the style of the Prompt 795 enrollment pipeline (a separate, unrelated type).
It adds an exact-type gate and delegates; it holds no dispatch, execution or verification logic.

## Public API
`run_voice_verification_pipeline(plan)` returns the existing `VoiceVerificationResult` (Prompt 801). No new result type is defined.

| input | outcome |
|---|---|
| not exactly a `VoiceVerificationPlan` (None, dict, look-alike, spoofed `__class__`, other voice types, ...) | `REJECTED`, code `VOICE_VERIFICATION_PIPELINE_INVALID_PLAN`, metadata `None`; dispatcher not called, input not read |
| an exact `VoiceVerificationPlan` | `dispatch_voice_verification(plan)` called exactly once; its result returned unchanged (same object) |

The rejected result needs non-empty ids, so it carries the executor's `UNKNOWN` placeholder marker for `request_id` and `profile_id`. Dispatcher
(and executor) results, including their own rejections of a malformed exact plan, are returned unchanged; exceptions are not swallowed.

## What this module does NOT do
- It does NOT duplicate dispatcher or executor logic: no plan field is read, no metadata built, no status chosen for valid plans, and it never calls the executor directly.
- It does NOT capture or record audio, recognize voices, verify speakers, or do biometric processing; no embeddings, I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It does NOT modify any existing voice contract, plan, result, validator, executor or dispatcher, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing. Nothing calls it automatically.
- It retains neither the plan nor the result; it is deterministic and side-effect free.

## Regression-guard changes
By exact path only: the tests that list the `voice/` package contents (and the Prompt 718 exemption list and Prompt 786 production count/digest) now include `voice/voice_verification_pipeline.py`.

## Section 10 position
Prompt 804 adds the verification pipeline. Prompt 805 has NOT been started.
