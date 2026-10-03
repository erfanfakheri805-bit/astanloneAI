# Prompt 810 - Section 10: Voice Verification Execution Handoff

Status: **implemented.** `voice/voice_verification_handoff.py` (pinned by `tests/test_voice_verification_handoff_prompt810.py`).
It connects the existing `VoiceVerificationDecision` (Prompt 809) to the existing `VoiceVerificationPlan` (Prompt 800) as an immutable
`VoiceVerificationHandoff`. It only describes whether a plan may be handed on; it executes nothing and introduces no new decision or plan model.

## Plan contract note
The existing `VoiceVerificationPlan` stores `request_id`, `profile_id` and `verification_mode` directly and has no `request` attribute. The profile check therefore
compares `decision.profile_id` with `plan.profile_id` (public properties only). No existing contract is changed.

## Public API
`create_voice_verification_handoff(decision, plan)` returns a `VoiceVerificationHandoff`. It never raises for bad inputs and never changes what it is given.

| input | approved | profile_id | failure_codes (prefix `VOICE_VERIFICATION_HANDOFF_`) |
|---|---|---|---|
| decision not exactly a `VoiceVerificationDecision`, or plan not exactly a `VoiceVerificationPlan` | `False` | `None` | `("..._INVALID_INPUT",)` |
| decision with `approved` False (plan not read) | `False` | `None` | `("..._REJECTED_DECISION",)` |
| approved decision, `profile_id` differs from `plan.profile_id` | `False` | `None` | `("..._PROFILE_MISMATCH",)` |
| decision `approved` not a bool, or a missing/malformed profile id on either side, or an unreadable public property | `False` | `None` | `("..._INVALID_INPUT",)` |
| approved decision, same `profile_id` as the plan | `True` | the decision's `profile_id` string, unchanged | `()` |

Approval means only that the decision and the plan name the same profile. Nothing is executed, dispatched or verified.

## Handoff object
`VoiceVerificationHandoff` has exactly `approved`, `profile_id`, `failure_codes` (tuple of str) and `to_dict()` (fresh plain data). It retains neither the decision nor the
plan. Immutable, not subclassable, direct construction refused, equality and hash by value (exact type only), `copy`/`deepcopy` return the same object,
pickling raises `TypeError`.

## What this module does NOT do
- It never calls the executor, dispatcher, pipeline or batch, and never touches any profile store.
- It does NOT perform voice recognition, verification, matching, biometrics, embeddings, ML models or audio processing.
- It does NOT use microphone, files, network, database, external AI, cloud services or Android APIs, and starts no automatic execution.
- It does NOT modify any earlier voice module and is NOT wired into Core, the Agent Loop or `process_input()`.

## Section 10 position
Prompt 810 follows Prompt 809. Prompt 811 has NOT been started.
