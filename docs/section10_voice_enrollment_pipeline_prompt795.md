# Prompt 795 - Section 10: Voice Enrollment Pipeline

Status: **implemented.** `voice/voice_enrollment_pipeline.py` (pinned by `tests/test_voice_enrollment_pipeline_prompt795.py`). Ninth Section 10 module.
A thin entry point in front of the Prompt 794 dispatcher. It adds an exact-type gate and delegates; it holds no dispatch, execution or enrollment logic.

## Public API
`run_voice_enrollment_pipeline(plan)` returns the existing `VoiceEnrollmentResult` (Prompt 790). No new result type is defined.

| input | outcome |
|---|---|
| not exactly a `VoiceEnrollmentPlan` | `REJECTED`, code `VOICE_ENROLLMENT_PIPELINE_INVALID_PLAN`, metadata `None`; dispatcher not called, input not read |
| an exact `VoiceEnrollmentPlan` | `dispatch_voice_enrollment(plan)` called exactly once; its result returned unchanged (same object) |

The rejected result needs non-empty ids, so it carries the executor's `UNKNOWN` placeholder marker for `request_id` and `profile_id`.

## What this module does NOT do
- It does NOT duplicate dispatcher or executor logic: no plan field is read, no metadata built, no status chosen for valid plans, and it never calls the executor directly.
- It does NOT capture or record audio, recognize voices, enroll, or do biometric processing; no I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It does NOT modify any existing voice contract, validator, plan, executor or dispatcher, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.
- It retains neither the plan nor the result; it is deterministic and side-effect free.

## Section 10 position
Prompt 795 is the ninth Section 10 prompt. Prompt 796 has NOT been started.
