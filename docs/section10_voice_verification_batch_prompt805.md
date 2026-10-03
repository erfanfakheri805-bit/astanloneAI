# Prompt 805 - Section 10: Voice Verification Batch

Status: **implemented.** `voice/voice_verification_batch.py` (pinned by `tests/test_voice_verification_batch_prompt805.py`).
A thin batch layer over the Prompt 804 pipeline, following the Prompt 796 `VoiceEnrollmentBatch` conventions as a separate, unrelated type.
It validates a whole collection first and then delegates; it holds no pipeline, dispatcher, executor or verification logic.

## Public API
`run_voice_verification_batch(plans)` returns an immutable `VoiceVerificationBatchResult` with `ok`, `outputs` (tuple) and `failures` (tuple of fresh `{"code", "field", "message"}` dicts), plus `codes()`.

| input | outcome |
|---|---|
| not exactly a `tuple` (list, tuple subclass, None, spoofed `__class__`, generator, other collections) | `VOICE_VERIFICATION_BATCH_INVALID_COLLECTION`, field `plans`; zero pipeline calls |
| a tuple with any item that is not exactly a `VoiceVerificationPlan` (None, look-alike, spoofed `__class__`, dict, other voice types, ...) | one `VOICE_VERIFICATION_BATCH_INVALID_ITEM` per bad item, field `plans[<index>]`, all reported in order; zero pipeline calls (atomic) |
| an empty tuple | valid: zero pipeline calls, `ok` True, `outputs` `()` |
| a valid tuple | public `run_voice_verification_pipeline(plan)` called exactly once per plan, in order; each returned object kept as-is (same identity) in the same position |
| the pipeline raises for a plan | stop at that plan; `ok` False, `outputs` `()`, one `VOICE_VERIFICATION_BATCH_PIPELINE_ERROR` with field `plans[<index>]`; earlier calls are not undone, no retry, exception not retained |

## What this module does NOT do
- It does NOT duplicate pipeline, dispatcher or executor logic and never reads a plan field.
- It does NOT capture or record audio, recognize voices, verify speakers, or do biometric processing; no embeddings, I/O, networking, files, persistence, database, subprocess, or AI / cloud calls.
- It does NOT modify `VoiceVerificationPlan`, `VoiceVerificationResult`, the validator, executor, dispatcher or pipeline, nor the enrollment batch, and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.
- It retains neither the input tuple, the plans nor raised exceptions; it is deterministic and side-effect free.

## Regression-guard changes
By exact path only: the tests that list the `voice/` package contents (and the Prompt 718 exemption list and the Prompt 804 / 803 "no other module mentions the pipeline" checks) now include `voice/voice_verification_batch.py`.

## Section 10 position
Prompt 805 adds the verification batch. Prompt 806 has NOT been started.
