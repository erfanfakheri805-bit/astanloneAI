# Prompt 801 - Section 10: Voice Verification Result Contract

Status: **implemented.** `voice/voice_verification_result.py` (pinned by `tests/test_voice_verification_result_prompt801.py`). It mirrors the
Prompt 790 `VoiceEnrollmentResult` contract as a **separate, verification-specific** type. It shares no code, type or failure code with the enrollment
result, and the enrollment contract is unchanged. It fills the gap the upcoming verification execution chain needs: Prompts 798-800 produced a
`VoiceVerificationRequest`, its validator and a `VoiceVerificationPlan`, but no result contract existed for the chain to return.

## What it represents
`VoiceVerificationResult` is an immutable record that only DESCRIBES the outcome of one voice-verification request: `request_id`, `profile_id`,
`status`, `code`, `metadata`. Nothing here performs a verification.

## Public API
- `create_voice_verification_result(data)` returns a `VoiceVerificationResultResult` with `ok`, `result` (`None` unless `ok`), `failures`, `codes()` and
  `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `VoiceVerificationResult`: read-only properties for the five fields; `metadata` and `to_dict()` return a FRESH plain dict on every call (`to_dict()` has
  exactly the five fields, in fixed order); deterministic equality (exact type only); direct construction and subclassing refused (`TypeError`);
  `copy`/`deepcopy` return the same object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.

## Validation rules
| field | type | rule |
|---|---|---|
| `request_id` | exactly `str` | not empty (not looked up) |
| `profile_id` | exactly `str` | not empty (not looked up in any registry) |
| `status` | exactly `str` | not empty; any text, no fixed status list |
| `code` | exactly `str` | not empty; any text, no fixed code list |
| `metadata` | `None` or exactly `dict` | contents are not inspected |

1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All five fields are required (`metadata` must be supplied, even as `None`); nothing is defaulted. Unexpected fields (and non-`str` / `str`-subclass
   keys) are rejected, never ignored.
3. Exact types only: a `bool` is rejected for every string field, as are `int`, `None`, `bytes` and `str` subclasses; a dict subclass or any other
   mapping is rejected for `metadata`. No caller-supplied method is ever run.
4. "Not empty" means exactly `value != ""`: whitespace-only text is accepted, nothing is trimmed or normalized; the same `str` objects are stored.

**Note on `status` and `code`.** The Prompt 801 text names `request_id` and `profile_id` as the non-empty fields. Because the instruction is to mirror
the Prompt 790 contract, and Prompt 790 requires all four strings to be non-empty, `status` and `code` are non-empty here too. This keeps one rule for
both result contracts and means a result can never carry an empty outcome label.

Failures are reported together, in a fixed order (input, unexpected fields sorted by name, then the five fields in declared order). Each failure is
`{"code", "field", "message"}`.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `VOICE_VERIFICATION_RESULT_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `VOICE_VERIFICATION_RESULT_UNEXPECTED_FIELD` |
| missing field | `VOICE_VERIFICATION_RESULT_MISSING_FIELD` |
| bad `request_id` / `profile_id` / `status` / `code` / `metadata` | `VOICE_VERIFICATION_RESULT_INVALID_REQUEST_ID` / `_INVALID_PROFILE_ID` / `_INVALID_STATUS` / `_INVALID_CODE` / `_INVALID_METADATA` |

## Isolation
The caller's `data` dict and `metadata` dict are not retained: the metadata entries are copied into a private tuple (same key order, same value
objects). Editing or clearing the input afterwards, or mutating a dict returned by `metadata` / `to_dict()`, never affects the result. Metadata VALUES are
preserved as given and are not deep-copied (same convention as `VoiceEnrollmentResult`). The hash covers the four strings only, so unhashable metadata
values do not break hashing.

## What this module does NOT do
- It stores NO audio, recordings, embeddings, biometric samples, external-service data or credentials of its own - only the five fields above.
- It does NOT perform verification, voice recognition, matching, execution or any audio processing, does not look up `request_id` / `profile_id`, and
  does not check `status` or `code` against a list.
- It does NOT use networking, the filesystem, a database, subprocesses, an AI model, any API key, a clock or randomness; it imports nothing and keeps no
  module-level mutable state.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner, Android or runtime voice processing. `VoiceVerificationRequest`, its validator
  and `VoiceVerificationPlan` are unchanged, and no `VoiceVerificationExecutor` exists yet.

## Regression-guard changes
Existing pins that enumerate the voice package were extended by exact path only: the ten `test_voice_*` package-contents tests (Prompts 787-800) now
expect `voice/voice_verification_result.py`. Any production-tree pins outside `voice` that count production files were extended by exact path as well
(listed in the final report). Their other checks are unchanged.

## Section 10 position
Prompt 801 adds the verification result contract. The `VoiceVerificationExecutor` (`execute_voice_verification_plan(plan)`) is NOT part of this prompt
and has NOT been started; Prompt 802 has NOT been started.
