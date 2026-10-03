# Prompt 808 - Section 10: Voice Verification Profile Resolver

Status: **implemented.** `voice/voice_verification_profile_resolver.py` (pinned by `tests/test_voice_verification_profile_resolver_prompt808.py`).
It connects the existing `VoiceVerificationRequest` (Prompt 798) to the existing `VoiceVerificationRegistry` (Prompt 807) through the registry's public
`lookup()` API. It verifies nothing and introduces no new request or profile model.

## Public API
`resolve_voice_verification_profile(request, registry)` returns a `VoiceVerificationProfileResolutionResult`. It never raises for bad inputs and never
changes what it is given.

| input | ok | profile | failure code (prefix `VOICE_VERIFICATION_PROFILE_RESOLVER_`) |
|---|---|---|---|
| `request` not exactly a `VoiceVerificationRequest`, or failing the Prompt 799 validator | `False` | `None` | `INVALID_REQUEST` (no lookup) |
| `registry` not exactly a `VoiceVerificationRegistry` | `False` | `None` | `INVALID_REGISTRY` (no lookup) |
| both inputs valid, `request.profile_id` registered | `True` | the registry's very same `VoiceIdentityProfile` object | none |
| both inputs valid, `request.profile_id` not registered | `False` | `None` | `PROFILE_NOT_FOUND` |

Both inputs are checked before anything else and all problems are reported together (request, then registry). Only `registry.lookup()` is used - never
registry internals - and it is called exactly once, and only for valid inputs. The profile is returned as registered; `enabled` and `enrollment_status`
are not interpreted.

## Result object
`VoiceVerificationProfileResolutionResult` has `ok`, `profile`, `failures`, `codes()` and `to_dict()` (fresh `{"ok", "profile", "failures"}`), following the
Prompt 799 result conventions. It is immutable, not subclassable, cannot be constructed directly, compares and hashes by value, returns itself from
`copy`/`deepcopy` and refuses pickling. It retains neither the request nor the registry - only the profile on success and plain failure data.

## What this module does NOT do
- It does NOT perform voice recognition, verification, matching, biometrics or audio processing, and handles no embeddings or microphone.
- It does NOT use files, network, database, AI models, cloud services or Android APIs.
- It does NOT modify the request, plan, profile, either registry, result, executor, dispatcher, pipeline, batch or summary modules, and is NOT wired into
  Core, the Agent Loop or `process_input()`.

## Section 10 position
Prompt 808 follows Prompt 807. Prompt 809 has NOT been started.
