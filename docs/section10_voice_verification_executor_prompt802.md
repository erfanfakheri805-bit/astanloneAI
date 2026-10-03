# Prompt 802 - Section 10: Voice Verification Executor

Status: **implemented.** `voice/voice_verification_executor.py` (pinned by `tests/test_voice_verification_executor_prompt802.py`).
A deliberate placeholder after `VoiceVerificationPlan` (Prompt 800) and `VoiceVerificationResult` (Prompt 801), in the style of the Prompt 793
`VoiceEnrollmentExecutor` (a separate, unrelated type). It verifies nothing.

## Public API
`execute_voice_verification_plan(plan)` returns the existing `VoiceVerificationResult` (Prompt 801), built through its public factory
`create_voice_verification_result`. No new result type is defined, and neither the plan nor the result contract is changed.

| input | status | code | metadata |
|---|---|---|---|
| not exactly a `VoiceVerificationPlan` (None, dict, look-alike, spoofed `__class__`, a plan *result*, ...) | `REJECTED` | `VOICE_VERIFICATION_EXECUTOR_INVALID_PLAN` | `None` |
| an exact `VoiceVerificationPlan` | `NOT_IMPLEMENTED` | `VOICE_VERIFICATION_EXECUTOR_NOT_IMPLEMENTED` | exactly `request_id`, `profile_id`, `verification_mode` (in that order) |

Metadata values are the plan's own `str` objects (identity preserved, no trimming, case-folding or normalization). The result's `request_id` /
`profile_id` are the plan's own. The plan object is not retained: the result holds only four strings and a private tuple of metadata entries. A
malformed plan (unreadable or non-string / empty values, possible only through private construction) is treated as invalid. Exact type checks mean a
spoofed `__class__` or a mock is rejected without any attribute being read.

## Placeholder ids on rejection
`VoiceVerificationResult` requires a non-empty `request_id` and `profile_id`, and a rejected input has none, so the rejected result carries the fixed
text `UNKNOWN` for both. It is a marker, not an identity; status and code identify the outcome.

## Determinism and isolation
Equal plans give equal results; repeated calls are identical. Dicts returned by `result.metadata` / `result.to_dict()` are fresh, so mutating them
never affects the result, the plan or later results. No module-level mutable state, clock or randomness.

## What this module does NOT do
- It does NOT capture or record audio, recognize voices, verify speakers, match, or do any biometric processing; no embeddings or recordings are
  handled. It executes nothing.
- It does NOT perform networking, filesystem access (no microphone, no files), subprocess execution, persistence, database access, or AI-model /
  external-service calls.
- It does NOT modify any existing voice contract or validator, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime
  voice processing. Nothing calls it automatically.
- Its only imports are the Prompt 800 plan type and the Prompt 801 result factory.

## Regression-guard changes
By exact path only: the `test_voice_*` package-contents tests (Prompts 787-801) now expect `voice/voice_verification_executor.py`; the Prompt 718
frozen production-tree exemption list gained this one path; the Prompt 786 non-web production count/digest was recomputed (367 -> 368 files).
Their other checks are unchanged.

## Section 10 position
Prompt 802 adds the verification executor. Prompt 803 has NOT been started.
