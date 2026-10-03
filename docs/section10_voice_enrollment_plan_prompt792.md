# Prompt 792 - Section 10: Voice Enrollment Plan

Status: **implemented.** `voice/voice_enrollment_plan.py` (pinned by `tests/test_voice_enrollment_plan_prompt792.py`). Sixth Section 10 module.
It follows `VoiceEnrollmentRequest` (Prompt 789) in the style of `WebRequestPlan` (Prompt 777). It describes a plan and enrolls nothing.

## Public API
`create_voice_enrollment_plan(validation_result)` returns a `VoiceEnrollmentPlanResult` with `ok`, `plan`, `failures`, `codes()` and `to_dict()`.
`VoiceEnrollmentPlan` has exactly `request_id`, `profile_id` and `enrollment_mode` (all `str`); `to_dict()` returns FRESH plain data with only those three fields.

The voice package has no separate request validator, so the "validation result" is the `VoiceEnrollmentRequestResult` returned by
`create_voice_enrollment_request()` (`ok`, `request`, `failures`). No existing voice contract or validator is changed.

| input | ok | plan | failure code (prefix `VOICE_ENROLLMENT_PLAN_`) |
|---|---|---|---|
| not exactly a `VoiceEnrollmentRequestResult` (None, dict, look-alike, spoofed `__class__`, ...) | `False` | `None` | `INVALID_VALIDATION_RESULT` (nothing is read) |
| an exact result that is not `ok` (failed validation) | `False` | `None` | `VALIDATION_FAILED` |
| `ok` but `request` is not exactly a `VoiceEnrollmentRequest` | `False` | `None` | `INVALID_REQUEST` |
| `request_id` / `profile_id` / `enrollment_mode` not an exact non-empty `str` | `False` | `None` | `INVALID_REQUEST_ID` / `INVALID_PROFILE_ID` / `INVALID_ENROLLMENT_MODE` (reported together, in field order) |
| a successful exact result | `True` | the plan | none |

The carrier is a mutable object, so the three values are re-checked with the exact-type and non-empty rules even when `ok` is true.
On success the plan holds the very same `str` objects (identity preserved). Nothing is trimmed, normalized or coerced; `enrollment_mode` stays free text.

## Non-retention
The plan keeps only the three strings: not the `VoiceEnrollmentRequest`, not the validation result, not any registry. A rejected input is not kept by the
failed result either. It stores no audio, recordings, embeddings, biometric data or credentials.

## Result and plan objects
Both are immutable (`__slots__`, assignment/deletion raises), not subclassable, cannot be constructed directly, compare and hash by value (exact type only),
return themselves from `copy`/`deepcopy` and refuse pickling (`TypeError`). The factory never raises for bad inputs and is deterministic.

## What this module does NOT do
- It does NOT perform enrollment, voice recognition, matching, audio processing or biometric processing.
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT modify any existing voice contract or validator, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.
- Its only imports are the Prompt 789 request and result types.

## Section 10 position
Prompt 792 is the sixth Section 10 prompt. Prompt 793 has NOT been started.
