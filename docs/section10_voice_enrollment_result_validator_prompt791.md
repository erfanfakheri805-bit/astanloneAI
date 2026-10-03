# Prompt 791 - Section 10: Voice Enrollment Result Validator

Status: **implemented.** `voice/voice_enrollment_result_validator.py` (pinned by `tests/test_voice_enrollment_result_validator_prompt791.py`). Fifth Section 10 module.
It follows `VoiceEnrollmentResult` (Prompt 790) and checks the shape of that result, in the style of the earlier output validators (e.g. Prompt 780). It enrolls nothing.

## Public API
`validate_voice_enrollment_result(result)` returns a `VoiceEnrollmentResultValidationResult`. It never raises for bad inputs and never changes what it is given.

| input | ok | result | failure codes (prefix `VOICE_ENROLLMENT_RESULT_VALIDATOR_`) |
|---|---|---|---|
| not exactly a `VoiceEnrollmentResult` (None, dict, look-alike, spoofed `__class__`, ...) | `False` | `None` | `INVALID_RESULT` (nothing is read from the input) |
| an exact `VoiceEnrollmentResult` whose `request_id` is not an exact non-empty `str` | `False` | `None` | `INVALID_REQUEST_ID` |
| ... `profile_id` | `False` | `None` | `INVALID_PROFILE_ID` |
| ... `status` | `False` | `None` | `INVALID_STATUS` |
| ... `code` | `False` | `None` | `INVALID_CODE` |
| ... `metadata` that is neither `None` nor an exact `dict` | `False` | `None` | `INVALID_METADATA` |
| an exact `VoiceEnrollmentResult` with all five fields valid | `True` | the very same object | none |

Problems are reported together, in the order `request_id`, `profile_id`, `status`, `code`, `metadata`. A field read that raises counts as invalid. Contents are
NOT interpreted: string values are never trimmed or normalized and metadata keys and values are never inspected.

## Result object
`VoiceEnrollmentResultValidationResult` has `ok`, `result`, `failures` and `codes()`, plus `to_dict()` returning FRESH plain data `{"ok", "result", "failures"}`.
On success `result` preserves object identity. On any failure `result` is `None`: an invalid or malformed object is never retained. `failures` is a tuple of fresh
`{"code", "field", "message"}` dicts. Immutable, not subclassable, direct construction refused, equality and hash by value (exact type only), `copy`/`deepcopy`
return the same object, pickling raises `TypeError`. Repeated validation is deterministic.

## What this module does NOT do
- It does NOT perform enrollment, voice recognition, matching or audio processing.
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT modify `VoiceEnrollmentResult`, `VoiceEnrollmentRequest`, `VoiceIdentityProfile` or the profile registry, and is NOT wired into Core, the Agent Loop,
  `process_input()`, Android or any runtime voice processing.
- Its only import is the Prompt 790 result type.

## Limitations
`VoiceEnrollmentResult` can only be created by `create_voice_enrollment_result()`, so a malformed result cannot arise in normal use; this validator is a defensive
contract check for future layers.

## Section 10 position
Prompt 791 is the fifth Section 10 prompt. Prompt 792 has NOT been started.
