# Prompt 789 - Section 10: Voice Enrollment Request Contract

Status: **implemented.** `voice/voice_enrollment_request.py` (pinned by `tests/test_voice_enrollment_request_prompt789.py`). It follows the shape and
conventions of the Prompt 775 `WebRequest` and the Prompt 787 `VoiceIdentityProfile`.

## What it represents
`VoiceEnrollmentRequest` is an immutable record that only DESCRIBES one voice-enrollment request: `request_id`, `profile_id`, `enrollment_mode`.
Nothing here performs an enrollment.

## Public API
- `create_voice_enrollment_request(data)` returns a `VoiceEnrollmentRequestResult` with `ok`, `request` (`None` unless `ok`), `failures`, `codes()`
  and `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `VoiceEnrollmentRequest`: read-only properties for the three fields; `to_dict()` returns a FRESH plain dict with exactly those three fields, in
  fixed order; deterministic equality and hashing (exact type only); direct construction and subclassing refused (`TypeError`); `copy`/`deepcopy`
  return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.

## Validation rules
| field | type | rule |
|---|---|---|
| `request_id` | exactly `str` | not empty |
| `profile_id` | exactly `str` | not empty (not looked up in any registry) |
| `enrollment_mode` | exactly `str` | not empty; any text, no fixed mode list |

1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All three fields are required; nothing is defaulted. Unexpected fields (and non-`str` / `str`-subclass keys) are rejected, never ignored.
3. Exact types only: a `bool` is rejected for every field, as are `int`, `None`, `bytes` and `str` subclasses (no caller-supplied method is ever run).
4. "Not empty" means exactly `value != ""` (the existing contract convention): whitespace-only text is accepted, nothing is trimmed or normalized.
5. The same `str` objects are stored (identity preserved).

Failures are reported together, in a fixed order (input, unexpected fields sorted by name, then the three fields in declared order). Each failure is
`{"code", "field", "message"}`.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `VOICE_ENROLLMENT_REQUEST_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `VOICE_ENROLLMENT_REQUEST_UNEXPECTED_FIELD` |
| missing field | `VOICE_ENROLLMENT_REQUEST_MISSING_FIELD` |
| bad `request_id` / `profile_id` / `enrollment_mode` | `VOICE_ENROLLMENT_REQUEST_INVALID_REQUEST_ID` / `_INVALID_PROFILE_ID` / `_INVALID_ENROLLMENT_MODE` |

## What this module does NOT do
- It stores NO audio, embeddings, biometric samples, recordings or external-service data - only the three fields above.
- It does NOT perform enrollment, voice recognition, matching or any audio processing, does not look up `profile_id`, and does not check
  `enrollment_mode` against a list.
- It does NOT use networking, the filesystem, a database, subprocesses, an AI model, any API key, a clock or randomness; it imports nothing and keeps
  no module-level mutable state.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner or Android, and `VoiceIdentityProfile` and its registry are unchanged.

## Regression-guard changes
Four existing pins that enumerate production files were extended by exact path only: the Prompt 718 frozen production-tree test (one more exact-path
exemption), the Prompt 786 non-web production count/digest (354 -> 355 files), and the package-contents tests of Prompts 787 and 788 (which now expect
`voice/voice_enrollment_request.py`). Their other checks are unchanged.

## Section 10 position
Prompt 789 is the third Section 10 prompt (Voice Enrollment Request Contract). Prompt 790 has NOT been started.
