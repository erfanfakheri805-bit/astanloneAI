# Prompt 794 - Section 10: Voice Enrollment Dispatcher

Status: **implemented.** `voice/voice_enrollment_dispatcher.py` (pinned by `tests/test_voice_enrollment_dispatcher_prompt794.py`). Eighth Section 10 module.
A thin dispatch layer in front of the Prompt 793 executor. It adds an exact-type gate and delegates; it holds no enrollment logic.

## Public API
`dispatch_voice_enrollment(plan)` returns the existing `VoiceEnrollmentResult` (Prompt 790). No new result type is defined.

| input | outcome |
|---|---|
| not exactly a `VoiceEnrollmentPlan` | `REJECTED`, code `VOICE_ENROLLMENT_DISPATCHER_INVALID_PLAN`, metadata `None`; executor not called, input not read |
| an exact `VoiceEnrollmentPlan` | `execute_voice_enrollment_plan(plan)` called exactly once; its result returned unchanged (same object) |

The rejected result needs non-empty ids, so it carries the executor's `UNKNOWN` placeholder marker for `request_id` and `profile_id`.

## What this module does NOT do
- It does NOT duplicate executor logic: no plan field is read, no metadata built, no status chosen for valid plans.
- It does NOT capture or record audio, recognize voices, enroll, or do biometric processing; no I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It does NOT modify any existing voice contract, validator, plan or executor, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.
- It retains neither the plan nor the result; it is deterministic and side-effect free.

## Section 10 position
Prompt 794 is the eighth Section 10 prompt. Prompt 795 has NOT been started.
