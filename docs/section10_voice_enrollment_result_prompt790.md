# Prompt 790 - Section 10: Voice Enrollment Result Contract

Status: **implemented.** `voice/voice_enrollment_result.py` (pinned by `tests/test_voice_enrollment_result_prompt790.py`). It follows the shape and
conventions of the Prompt 789 `VoiceEnrollmentRequest` and the Prompt 779 `WebRequestOutput` (status / code / metadata carrier).

## What it represents
`VoiceEnrollmentResult` is an immutable record that only DESCRIBES the outcome of one voice-enrollment request: `request_id`, `profile_id`, `status`,
`code`, `metadata`. Nothing here performs an enrollment.

## Public API
- `create_voice_enrollment_result(data)` returns a `VoiceEnrollmentResultResult` with `ok`, `result` (`None` unless `ok`), `failures`, `codes()` and
  `to_dict()`. It never raises for bad data and never changes the caller's dict.
- `VoiceEnrollmentResult`: read-only properties for the five fields; `metadata` and `to_dict()` return a FRESH plain dict on every call (`to_dict()` has
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

Failures are reported together, in a fixed order (input, unexpected fields sorted by name, then the five fields in declared order). Each failure is
`{"code", "field", "message"}`.

| problem | code |
|---|---|
| `data` is not exactly a `dict` | `VOICE_ENROLLMENT_RESULT_INVALID_INPUT` |
| unexpected field (or non-`str` field name) | `VOICE_ENROLLMENT_RESULT_UNEXPECTED_FIELD` |
| missing field | `VOICE_ENROLLMENT_RESULT_MISSING_FIELD` |
| bad `request_id` / `profile_id` / `status` / `code` / `metadata` | `VOICE_ENROLLMENT_RESULT_INVALID_REQUEST_ID` / `_INVALID_PROFILE_ID` / `_INVALID_STATUS` / `_INVALID_CODE` / `_INVALID_METADATA` |

## Isolation
The caller's `data` dict and `metadata` dict are not retained: the metadata entries are copied into a private tuple (same key order, same value
objects). Editing or clearing the input afterwards, or mutating a dict returned by `metadata` / `to_dict()`, never affects the result. Metadata VALUES are
preserved as given and are not deep-copied (same convention as `WebRequestOutput`). The hash covers the four strings only, so unhashable metadata values
do not break hashing.

## What this module does NOT do
- It stores NO audio, embeddings, biometric samples, recordings, external-service data or credentials of its own - only the five fields above.
- It does NOT perform enrollment, voice recognition, matching or any audio processing, does not look up `request_id` / `profile_id`, and does not check
  `status` or `code` against a list.
- It does NOT use networking, the filesystem, a database, subprocesses, an AI model, any API key, a clock or randomness; it imports nothing and keeps no
  module-level mutable state.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner, Android or runtime voice processing. `VoiceIdentityProfile`,
  `VoiceEnrollmentRequest` and the registry are unchanged.

## Regression-guard changes
Five existing pins that enumerate the voice package or production files were extended by exact path only: the Prompt 718 frozen production-tree test
(one more exact-path exemption), the Prompt 786 non-web production count/digest (355 -> 356 files), and the package-contents tests of Prompts 787, 788
and 789 (which now expect `voice/voice_enrollment_result.py`). Their other checks are unchanged.

## Section 10 position
Prompt 790 is the fourth Section 10 prompt (Voice Enrollment Result Contract). Prompt 791 has NOT been started.
