# Prompt 799 - Section 10: Voice Verification Request Validator

Status: **implemented.** `voice/voice_verification_request_validator.py` (pinned by `tests/test_voice_verification_request_validator_prompt799.py`).
It follows `VoiceVerificationRequest` (Prompt 798) and checks the shape of that request, in the style of the Prompt 791 validator. It verifies nothing.

## Public API
`validate_voice_verification_request(request)` returns a `VoiceVerificationRequestValidationResult`. It never raises for bad inputs and never changes what it is given.

| input | ok | request | failure codes (prefix `VOICE_VERIFICATION_REQUEST_VALIDATOR_`) |
|---|---|---|---|
| not exactly a `VoiceVerificationRequest` (None, dict, look-alike, spoofed `__class__`, ...) | `False` | `None` | `INVALID_REQUEST` (nothing is read from the input) |
| an exact `VoiceVerificationRequest` whose `request_id` is not an exact non-empty `str` | `False` | `None` | `INVALID_REQUEST_ID` |
| ... `profile_id` | `False` | `None` | `INVALID_PROFILE_ID` |
| ... `verification_mode` | `False` | `None` | `INVALID_VERIFICATION_MODE` |
| an exact `VoiceVerificationRequest` with all three fields valid | `True` | the very same object | none |

Problems are reported together, in the order `request_id`, `profile_id`, `verification_mode`. A field read that raises counts as invalid. Contents are
NOT interpreted: strings are never trimmed or normalized, `verification_mode` is checked for type and emptiness only (no mode list), and `profile_id` is
not looked up.

## Result object
`VoiceVerificationRequestValidationResult` has `ok`, `request`, `failures` and `codes()`, plus `to_dict()` returning FRESH plain data
`{"ok", "request", "failures"}`. On success `request` preserves object identity. On any failure `request` is `None`: an invalid or malformed object is never
retained. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts. Immutable, not subclassable, direct construction refused, equality and hash by
value (exact type only), `copy`/`deepcopy` return the same object, pickling raises `TypeError`. Repeated validation is deterministic.

## What this module does NOT do
- It does NOT perform verification, voice recognition, matching or audio processing.
- It does NOT store or process audio, recordings, embeddings or biometric data.
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT modify `VoiceVerificationRequest` or any other voice module, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or any
  runtime voice processing.
- Its only import is the Prompt 798 request type.

## Limitations
`VoiceVerificationRequest` can only be created by `create_voice_verification_request()`, so a malformed request cannot arise in normal use; this validator is
a defensive contract check for future layers.

## Section 10 position
Prompt 799 follows Prompt 798. Prompt 800 has NOT been started.
