# Prompt 798 - Section 10: Voice Verification Request Contract

Status: **implemented.** `voice/voice_verification_request.py` (pinned by `tests/test_voice_verification_request_prompt798.py`). It follows the shape and
conventions of the Prompt 789 `VoiceEnrollmentRequest`.

## What it represents
`VoiceVerificationRequest` is an immutable record that only DESCRIBES one voice-verification request: `request_id`, `profile_id`, `verification_mode`.
Nothing here performs a verification.

## Public API
- `create_voice_verification_request(data)` returns a `VoiceVerificationRequestResult` with `ok`, `request` (`None` unless `ok`), `failures`, `codes()`
  and `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `VoiceVerificationRequest`: read-only properties for the three fields; `to_dict()` returns a FRESH plain dict with exactly those three fields, in
  fixed order; deterministic equality and hashing (exact type only); direct construction and subclassing refused (`TypeError`); `copy`/`deepcopy`
  return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.

## Validation rules
| field | type | rule |
|---|---|---|
| `request_id` | exactly `str` | not empty |
| `profile_id` | exactly `str` | not empty (not looked up in any registry) |
| `verification_mode` | exactly `str` | not empty; any text, no fixed mode list |

1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All three fields are required; nothing is defaulted. Unexpected fields (and non-`str` / `str`-subclass keys) are rejected, never ignored.
3. Exact types only: a `bool` is rejected for every field, as are `int`, `None`, `bytes` and `str` subclasses (no caller-supplied method is ever run).
4. "Not empty" means exactly `value != ""` (the existing contract convention): whitespace-only text is accepted, nothing is trimmed or normalized.
5. The same `str` objects are stored (identity preserved).

Failures are reported together, in a fixed order (input, unexpected fields sorted by name, then the three fields in declared order). Each failure is
`{"code", "field", "message"}`.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `VOICE_VERIFICATION_REQUEST_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `VOICE_VERIFICATION_REQUEST_UNEXPECTED_FIELD` |
| missing field | `VOICE_VERIFICATION_REQUEST_MISSING_FIELD` |
| bad `request_id` / `profile_id` / `verification_mode` | `VOICE_VERIFICATION_REQUEST_INVALID_REQUEST_ID` / `_INVALID_PROFILE_ID` / `_INVALID_VERIFICATION_MODE` |

## What this module does NOT do
- It stores NO audio, embeddings, biometric data, recordings, external-service data or credentials - only the three fields above.
- It does NOT perform verification, voice recognition, matching or any audio processing, does not look up `profile_id`, and does not check
  `verification_mode` against a list.
- It does NOT use networking, the filesystem, a database, subprocesses, an AI model, any API key, a clock or randomness; it imports nothing and keeps
  no module-level mutable state.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner or Android, and nothing executes automatically. All earlier voice modules are unchanged.

## Regression-guard changes
Existing pins that enumerate production files were extended by exact path only (the Prompt 718 frozen production-tree test and the voice package-contents
tests of Prompts 787-793), plus any digest pin that covers the production tree. Their other checks are unchanged.

## Section 10 position
Prompt 798 is the twelfth Section 10 prompt (Voice Verification Request Contract). Prompt 799 has NOT been started.
