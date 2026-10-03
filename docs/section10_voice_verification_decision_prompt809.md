# Prompt 809 - Section 10: Voice Verification Decision Gate

Status: **implemented.** `voice/voice_verification_decision.py` (pinned by `tests/test_voice_verification_decision_prompt809.py`).
It follows the Prompt 808 profile resolver and turns its `VoiceVerificationProfileResolutionResult` into an immutable approved / rejected
`VoiceVerificationDecision`. It verifies nothing and introduces no new resolution, request or profile model.

## Public API
`decide_voice_verification(resolution_result)` returns a `VoiceVerificationDecision`. It never raises for bad inputs and never changes what it is given.
Only the public `ok`, `profile` and `codes()` of the resolution are read; private internals are never inspected.

| input | approved | profile_id | failure_codes | code (prefix `VOICE_VERIFICATION_DECISION_`) |
|---|---|---|---|---|
| successful resolution with an exact `VoiceIdentityProfile` | `True` | the profile's own `profile_id` string | `()` | `APPROVED` |
| failed resolution (no profile, one or more failure codes) | `False` | `None` | the resolution's codes, in order | `REJECTED` |
| not exactly a `VoiceVerificationProfileResolutionResult` (None, dict, look-alike, spoofed `__class__`, ...) | `False` | `None` | `("VOICE_VERIFICATION_DECISION_INVALID_RESULT",)` | `INVALID_RESULT` |
| an exact result whose public data contradicts itself or cannot be read | `False` | `None` | same as above | `INVALID_RESULT` |

`enabled` and `enrollment_status` of the profile are not interpreted: approval means only that a profile was resolved.

## Decision object
`VoiceVerificationDecision` has exactly `approved`, `profile_id`, `failure_codes` (tuple of str), `code` and `to_dict()` (fresh plain data). It retains neither the
resolution object nor the profile. Immutable, not subclassable, direct construction refused, equality and hash by value (exact type only),
`copy`/`deepcopy` return the same object, pickling raises `TypeError`. Decisions are deterministic.

## What this module does NOT do
- It does NOT perform voice recognition, verification, matching, biometrics, embeddings, ML models or audio processing.
- It does NOT use microphone, files, network, database, external AI, cloud services or Android APIs, and starts no automatic execution.
- It does NOT modify any earlier voice module and is NOT wired into Core, the Agent Loop or `process_input()`.

## Section 10 position
Prompt 809 follows Prompt 808. Prompt 810 has NOT been started.
