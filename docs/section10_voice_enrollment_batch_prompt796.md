# Prompt 796 - Section 10: Voice Enrollment Batch

Status: **implemented.** `voice/voice_enrollment_batch.py` (pinned by `tests/test_voice_enrollment_batch_prompt796.py`). Tenth Section 10 module.
A thin batch entry point over the Prompt 795 pipeline: validate the whole collection, then delegate one plan at a time.

## Public API
`run_voice_enrollment_batch(plans)` returns `VoiceEnrollmentBatchResult(ok, outputs, failures)`.

| input | outcome |
|---|---|
| not exactly a `tuple` | `VOICE_ENROLLMENT_BATCH_INVALID_COLLECTION`; pipeline called 0 times |
| tuple with any item not exactly a `VoiceEnrollmentPlan` | one `VOICE_ENROLLMENT_BATCH_INVALID_ITEM` per bad item (field `plans[i]`); pipeline called 0 times |
| valid tuple (including empty) | `run_voice_enrollment_pipeline(plan)` called exactly once per plan, in order; outputs kept in order with identity preserved |
| pipeline raises | stops; `VOICE_ENROLLMENT_BATCH_PIPELINE_ERROR` (field `plans[i]`), `outputs` `()` |

The result is immutable, value-comparable, non-picklable, and retains neither the input tuple nor the plans. `failures` are fresh dicts on every read.

## What this module does NOT do
- It does NOT duplicate pipeline, dispatcher, executor or enrollment logic, and reads no plan field.
- It does NOT capture or record audio, recognize voices, enroll, or do biometric processing; no I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It does NOT modify any existing voice module and is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.

## Section 10 position
Prompt 796 is the tenth Section 10 prompt. Prompt 797 has NOT been started.
