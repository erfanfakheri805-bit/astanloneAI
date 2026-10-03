# Prompt 797 - Section 10: Voice Enrollment Batch Summary

Status: **implemented.** `voice/voice_enrollment_batch_summary.py` (pinned by `tests/test_voice_enrollment_batch_summary_prompt797.py`). Eleventh Section 10 module.
A small immutable summary of a `VoiceEnrollmentBatchResult` (Prompt 796). It only counts what the batch result preserved.

## Public API
`create_voice_enrollment_batch_summary(batch_result)` returns `VoiceEnrollmentBatchSummary(output_count, failure_count, total_count, status_counts, code_counts, success)`.

| input | outcome |
|---|---|
| not exactly a `VoiceEnrollmentBatchResult` | rejected summary, `VOICE_ENROLLMENT_BATCH_SUMMARY_INVALID_RESULT`; nothing read |
| exact type but malformed (unreadable/non-tuple outputs, output not exactly a `VoiceEnrollmentResult`, non-`str` status/code, outputs and failures together) | rejected summary, `VOICE_ENROLLMENT_BATCH_SUMMARY_MALFORMED_RESULT` |
| valid | counts; `total_count == output_count + failure_count`; `status_counts` and `code_counts` ordered by key ascending; `success == batch_result.ok is True` |

A rejected summary has all counts 0, empty mappings, `success=False` and `codes()` equal to the single code. Output `metadata` is never read. Neither the batch result nor any output is retained.

## What this module does NOT do
- It does NOT call or duplicate batch, pipeline, dispatcher, executor or enrollment logic.
- It does NOT capture or record audio, recognize voices, enroll, or do biometric processing; no I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.

## Section 10 position
Prompt 797 is the eleventh Section 10 prompt. Prompt 798 has NOT been started.
