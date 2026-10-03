# Prompt 812 - Section 10: Voice Verification Execution Request

Status: **implemented.** `voice/voice_verification_execution_request.py` (pinned by `tests/test_voice_verification_execution_request_prompt812.py`).
It sits after authorization: it combines an authorized `VoiceVerificationAuthorization` (Prompt 811) with the matching `VoiceVerificationPlan` (Prompt 800) into an
immutable `VoiceVerificationExecutionRequest`. It describes what could be run; it executes, dispatches and verifies nothing and recreates no earlier contract.

## Public API
`create_voice_verification_execution_request(authorization, plan)` returns a `VoiceVerificationExecutionRequest`. It never raises for bad inputs and never changes
what it is given. Only public properties are read.

| input | ok | request_id / profile_id / verification_mode | failure_codes (prefix `VOICE_VERIFICATION_EXECUTION_REQUEST_`) |
|---|---|---|---|
| `authorization` not exactly a `VoiceVerificationAuthorization`, or `plan` not exactly a `VoiceVerificationPlan` | `False` | all `None` | `("..._INVALID_INPUT",)` |
| authorization with `authorized` False (plan not read) | `False` | all `None` | `("..._NOT_AUTHORIZED",)` |
| authorized, `profile_id` differs from `plan.profile_id` | `False` | all `None` | `("..._PROFILE_MISMATCH",)` |
| `authorized` not a bool, or a missing/malformed id or mode on either side, or an unreadable public property | `False` | all `None` | `("..._INVALID_INPUT",)` |
| authorized, same `profile_id` as the plan | `True` | the plan's `request_id` and `verification_mode`, the authorization's `profile_id`, the very same `str` objects | `()` |

Nothing is normalized, trimmed, case-folded or coerced, and the profile comparison is exact. `ok` means only that the authorization and the plan agree.

## Execution request object
`VoiceVerificationExecutionRequest` holds exactly `request_id`, `profile_id`, `verification_mode` and `failure_codes` (tuple of str); `ok` is derived from an empty `failure_codes`.
`to_dict()` returns fresh plain data (`ok`, the three fields, `failure_codes`). It retains neither the authorization nor the plan. Immutable, not subclassable, direct
construction refused, equality and hash by value (exact type only), `copy`/`deepcopy` return the same object, pickling raises `TypeError`.

## What this module does NOT do
- It never calls the verification executor, the dispatch step, the pipeline or the batch runner, and executes nothing.
- It does NOT perform voice recognition, verification, matching, biometrics, embeddings, ML models or audio processing.
- It does NOT use microphone, files, network, database, external AI, cloud services or Android APIs, and starts no automatic execution.
- It does NOT modify any earlier voice module and is NOT wired into Core, the Agent Loop or `process_input()`.

## Section 10 position
Prompt 812 follows Prompt 811. Prompt 813 has NOT been started.
