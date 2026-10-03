# Prompt 787 - Section 10: Voice Identity Profile Contract

Status: **implemented.** `voice/voice_identity_profile.py` (pinned by `tests/test_voice_identity_profile_prompt787.py`). This is the first Section 10 module.

## What it represents
`VoiceIdentityProfile` is an immutable record of the BASIC METADATA of one voice-identity profile: `profile_id`, `display_name`, `enabled`, `enrollment_status`.
It is only the stable contract for the later voice-identity pipeline. It follows the same shape and conventions as `WebResource` (Prompt 773).

## Public API
- `create_voice_identity_profile(data)` returns a `VoiceIdentityProfileResult` with `ok`, `profile` (`None` unless `ok`), `failures`, `codes()` and `to_dict()`.
  It never raises for bad data and never changes the caller's dict.
- `VoiceIdentityProfile`: read-only properties for the four fields; `to_dict()` returns a FRESH plain dict with exactly those four fields, in fixed order;
  deterministic equality and hashing (exact type only); direct construction and subclassing refused (`TypeError`); `copy`/`deepcopy` return the same
  object; pickling refused (`TypeError`); attribute assignment/deletion raises `AttributeError`.

## Validation rules
| field | type | rule |
|---|---|---|
| `profile_id` | exactly `str` | not empty |
| `display_name` | exactly `str` | not empty |
| `enabled` | exactly `bool` | `True` or `False` only (`0`/`1`, `"true"` and any other type rejected) |
| `enrollment_status` | exactly `str` | not empty; any text, no fixed status list |

1. `data` must be exactly a plain `dict` (a dict subclass is rejected).
2. All four fields are required; nothing is defaulted. Unexpected fields (and non-`str` / `str`-subclass keys) are rejected, never ignored.
3. Exact types only: a `bool` is rejected for every `str` field, a `str` or `int` is rejected for `enabled`, and `str` subclasses are rejected, so no
   caller-supplied method is ever run.
4. "Not empty" means exactly `value != ""`: a whitespace-only value is accepted, because nothing is trimmed or normalized (same rule as Prompt 773).
5. Nothing is trimmed, normalized, coerced or mutated. The same `str` objects are stored.

Failures are reported together, in a fixed order (input, unexpected fields sorted by name, then the four fields in declared order). Each failure is
`{"code", "field", "message"}`.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `VOICE_IDENTITY_PROFILE_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `VOICE_IDENTITY_PROFILE_UNEXPECTED_FIELD` |
| missing field | `VOICE_IDENTITY_PROFILE_MISSING_FIELD` |
| bad `profile_id` / `display_name` / `enabled` / `enrollment_status` | `VOICE_IDENTITY_PROFILE_INVALID_PROFILE_ID` / `_DISPLAY_NAME` / `_ENABLED` / `_ENROLLMENT_STATUS` |

## What this module does NOT do
- It stores NO raw audio, embeddings, biometric samples or external-service data - only the four fields above.
- It does NOT perform voice recognition, enrollment, matching or any audio processing, and does not validate `enrollment_status` against a list.
- It does NOT use networking, the filesystem, a database, subprocesses, an AI model, any API key, a clock or randomness; it imports nothing and keeps no
  module-level mutable state.
- It is NOT wired into Core, `process_input()`, the Planner or the Agent Loop, and no existing behavior changed.

## Section 10 position
Prompt 787 is the first Section 10 prompt. Prompt 788 has NOT been started.
