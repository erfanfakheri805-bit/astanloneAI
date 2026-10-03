# Prompt 806 - Section 10: Voice Verification Batch Summary

Status: **implemented.** `voice/voice_verification_batch_summary.py` (pinned by `tests/test_voice_verification_batch_summary_prompt806.py`). Section 10 module following the verification batch (Prompt 805).
A small immutable summary of a `VoiceVerificationBatchResult` (Prompt 805). It only counts what the batch result preserved.

## Public API
`create_voice_verification_batch_summary(batch_result)` returns `VoiceVerificationBatchSummary(output_count, failure_count, total_count, status_counts, code_counts, success)`.

| input | outcome |
|---|---|
| not exactly a `VoiceVerificationBatchResult` | rejected summary, `VOICE_VERIFICATION_BATCH_SUMMARY_INVALID_RESULT`; nothing read |
| exact type but malformed (unreadable/non-tuple outputs, output not exactly a `VoiceVerificationResult`, non-`str` status/code, outputs and failures together) | rejected summary, `VOICE_VERIFICATION_BATCH_SUMMARY_MALFORMED_RESULT` |
| valid | counts; `total_count == output_count + failure_count`; `status_counts` and `code_counts` ordered by key ascending; `success == batch_result.ok is True` |

A rejected summary has all counts 0, empty mappings, `success=False` and `codes()` equal to the single code. Output `metadata` is never read. Neither the batch result nor any output is retained.

## What this module does NOT do
- It does NOT call or duplicate batch, pipeline, dispatcher, executor or verification logic.
- It does NOT capture or record audio, recognize voices, verify speakers, or do biometric processing; no I/O, networking, persistence, database, subprocess, or AI / cloud calls.
- It is NOT wired into Core, the Agent Loop, `process_input()`, Android or runtime voice processing.

## Section 10 position
Prompt 806 adds the verification batch summary. Prompt 807 has NOT been started.

## Regression-guard changes
By exact path only: the tests that list the `voice/` package contents (and the Prompt 718 exemption list, the Prompt 805 "no other module mentions the batch" check and the Prompt 786 production count/digest) now include `voice/voice_verification_batch_summary.py`.
