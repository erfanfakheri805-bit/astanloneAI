# Prompt 811 - Section 10: Voice Verification Authorization Boundary

Status: **implemented.** `voice/voice_verification_authorization.py` (pinned by `tests/test_voice_verification_authorization_prompt811.py`).
It composes the existing Section 10 contracts into one immutable `VoiceVerificationAuthorization`. It authorizes only in the sense that every stage agrees;
it executes nothing, verifies nothing, and recreates no earlier contract.

## Composition (fixed order, existing functions)
1. `resolve_voice_verification_profile(request, registry)` (Prompt 808)
2. `decide_voice_verification(resolution)` (Prompt 809)
3. `create_voice_verification_handoff(decision, plan)` (Prompt 810)

Only the public `approved`, `profile_id` and `failure_codes` of the stage results are read. Each stage runs exactly once, and only when all three inputs have the exact types.

## Public API
`authorize_voice_verification(request, registry, plan)` returns a `VoiceVerificationAuthorization`. It never raises for bad inputs and mutates nothing it is given.

| situation | authorized | profile_id | failure_codes |
|---|---|---|---|
| `request`, `registry` or `plan` not exactly a `VoiceVerificationRequest`, `VoiceVerificationRegistry`, `VoiceVerificationPlan` (no stage runs) | `False` | `None` | `("VOICE_VERIFICATION_AUTHORIZATION_INVALID_INPUT",)` |
| final handoff approved | `True` | the handoff's `profile_id`, unchanged | `()` |
| any stage rejects (missing profile, malformed request, rejected decision, profile mismatch, ...) | `False` | `None` | `("VOICE_VERIFICATION_AUTHORIZATION_REJECTED",)` + the decision's codes + the handoff's codes, in that order |

Failure codes are only prepended, never rewritten, deduplicated or reordered, so each underlying code keeps its own stage prefix. Example, missing profile:
`(AUTHORIZATION_REJECTED, PROFILE_RESOLVER_PROFILE_NOT_FOUND, HANDOFF_REJECTED_DECISION)`.

Only `INVALID_INPUT` and `REJECTED` (prefix `VOICE_VERIFICATION_AUTHORIZATION_`) are new codes. `enabled` and `enrollment_status` of the profile are not interpreted.

## Authorization object
`VoiceVerificationAuthorization` has exactly `authorized`, `profile_id`, `failure_codes` (tuple of str) and `to_dict()` (fresh plain data). It retains none of the request, registry, plan,
resolution, decision or handoff objects. Immutable, not subclassable, direct construction refused, equality and hash by value (exact type only), `copy`/`deepcopy`
return the same object, pickling raises `TypeError`.

## What this module does NOT do
- It never calls the verification executor, the dispatch step, the pipeline or the batch runner.
- It does NOT perform voice recognition, verification, matching, biometrics, embeddings, ML models or audio processing.
- It does NOT use microphone, files, network, database, external AI, cloud services or Android APIs, and starts no automatic execution.
- It does NOT modify any earlier voice module and is NOT wired into Core, the Agent Loop or `process_input()`.

## Section 10 position
Prompt 811 follows Prompt 810. Prompt 812 has NOT been started.
