# Prompt 803 - Section 10: Voice Verification Dispatcher

Status: **implemented.** `voice/voice_verification_dispatcher.py` (pinned by `tests/test_voice_verification_dispatcher_prompt803.py`).
A thin dispatch layer in front of the Prompt 802 executor, in the style of the Prompt 794 enrollment dispatcher (a separate, unrelated type).
It adds an exact-type gate and delegates; it holds no verification logic.

## Public API
`dispatch_voice_verification(plan)` returns the existing `VoiceVerificationResult` (Prompt 801). No new result type is defined.

| input | outcome |
|---|---|
| not exactly a `VoiceVerificationPlan` (None, dict, look-alike, spoofed `__class__`, other voice types, ...) | `REJECTED`, code `VOICE_VERIFICATION_DISPATCHER_INVALID_PLAN`, metadata `None`; executor not called, input not read |
| an exact `VoiceVerificationPlan` | `execute_voice_verification_plan(plan)` called exactly once; its result returned unchanged (same object) |

The rejected result needs non-empty ids, so it carries the executor's `UNKNOWN` placeholder marker for `request_id` and `profile_id`. A malformed
*exact* plan (possible only through private construction) is passed on, and the executor's own `VOICE_VERIFICATION_EXECUTOR_INVALID_PLAN` result is
returned unchanged; executor exceptions are not swallowed.

## What this module does NOT do
- It does NOT duplicate executor logic: no plan field is read, no metadata built, no status chosen for valid plans.
- It does NOT capture or record audio, recognize voices, verify speakers, or do biometric processing; no embeddings, I/O, networking, persistence,
  database, subprocess, or AI / cloud calls.
- It does NOT modify any existing voice contract, plan, result or executor, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or
  runtime voice processing. Nothing calls it automatically.
- It retains neither the plan nor the result; it is deterministic and side-effect free.

## Regression-guard changes
By exact path only: the `test_voice_*` package-contents tests now expect `voice/voice_verification_dispatcher.py`; the Prompt 718 exemption list and the Prompt 717
`*dispatch*.py` allow-list each gained this one path; the Prompt 786 non-web production count/digest was recomputed (368 -> 369 files).

## Section 10 position
Prompt 803 adds the verification dispatcher. Prompt 804 has NOT been started.
