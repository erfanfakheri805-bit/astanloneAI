# Prompt 800 - Section 10: Voice Verification Plan

Status: **implemented.** `voice/voice_verification_plan.py` (pinned by `tests/test_voice_verification_plan_prompt800.py`). It follows the contracts of
`VoiceEnrollmentPlan` (Prompt 792) and `WebRequestPlan` (Prompt 777) and turns a validated voice-verification request (Prompts 798/799) into an immutable plan
description. It verifies nothing.

## Public API
`create_voice_verification_plan(validation_result)` returns a `VoiceVerificationPlanResult` with `ok`, `plan` (`None` unless `ok`), `failures`, `codes()` and
`to_dict()`. It never raises for bad inputs and never changes what it is given. `VoiceVerificationPlan.to_dict()` returns a FRESH plain dict
`{"request_id", "profile_id", "verification_mode"}` in that fixed order.

The "validation result" is the `VoiceVerificationRequestValidationResult` returned by `validate_voice_verification_request()` (Prompt 799).

## Order of checks
| step | check | failure code (prefix `VOICE_VERIFICATION_PLAN_`) |
|---|---|---|
| 1 | `validation_result` is exactly a `VoiceVerificationRequestValidationResult` (None, dict, look-alike, spoofed `__class__`, the Prompt 798 factory carrier, ... are rejected without being read) | `INVALID_VALIDATION_RESULT` |
| 2 | it is successful (`ok` true; an `ok` read that raises counts as failed) | `VALIDATION_FAILED` |
| 3 | its `request` is exactly a `VoiceVerificationRequest` (a read that raises counts as invalid) | `INVALID_REQUEST` |
| 3 | `request_id` is an exact non-empty `str` | `INVALID_REQUEST_ID` |
| 3 | `profile_id` is an exact non-empty `str` | `INVALID_PROFILE_ID` |
| 3 | `verification_mode` is an exact non-empty `str` | `INVALID_VERIFICATION_MODE` |

Step 3 field problems are reported together, in field order. The exact-string rules are re-checked here and the carrier is not trusted. "Non-empty" means
`value != ""`; whitespace-only text is accepted and nothing is trimmed, normalized or coerced.

## What the plan holds
Only the three values, as the very same `str` objects (identity preserved). It does not keep the `VoiceVerificationRequest`, the validation result, any
registry or any other object, so there is no link back to them; a failed result does not keep the rejected input either. `verification_mode` stays free text
(no mode list, no meaning attached) and `profile_id` is not looked up.

## Object contract
`VoiceVerificationPlan` and `VoiceVerificationPlanResult` use `__slots__`, refuse attribute assignment/deletion (`AttributeError`), direct construction and
subclassing (`TypeError`), compare and hash by value (exact type only), return themselves from `copy`/`deepcopy`, and refuse pickling (`TypeError`).
Repeated conversion is deterministic.

## What this module does NOT do
- It does NOT perform verification, voice recognition, matching or audio processing.
- It does NOT store or process audio, recordings, embeddings, biometric samples or credentials.
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT modify any existing voice module and is NOT wired into Core, the Agent Loop, `process_input()`, Android or any runtime voice processing.
- Its only imports are `VoiceVerificationRequest` (Prompt 798) and `VoiceVerificationRequestValidationResult` (Prompt 799).

## Section 10 position
Prompt 800 follows Prompt 799. Prompt 801 has NOT been started.
