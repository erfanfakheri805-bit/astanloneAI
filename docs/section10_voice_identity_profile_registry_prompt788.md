# Prompt 788 - Section 10: Voice Identity Profile Registry

Status: **implemented.** `voice/voice_identity_profile_registry.py` (pinned by `tests/test_voice_identity_profile_registry_prompt788.py`). It follows the
conventions of the Prompt 774 `WebResourceRegistry`, applied to the Prompt 787 `VoiceIdentityProfile`. `VoiceIdentityProfile` itself is unchanged.

## Public API
- `create_voice_identity_profile_registry(profiles)` returns a `VoiceIdentityProfileRegistryResult` with `ok`, `registry` (`None` unless `ok`),
  `failures`, `codes()` and `to_dict()`. It never raises for bad input and never changes what it is given.
- `VoiceIdentityProfileRegistry`: `.profiles` (tuple, registration order), `.profile_ids` (tuple), `.lookup(profile_id)`, `.to_dict()` returning
  `{"profiles": [VoiceIdentityProfile.to_dict(), ...]}` (fresh on every call). Immutable (`__slots__`, assignment/deletion raises `AttributeError`),
  not subclassable, direct construction refused (`TypeError`), deterministic equality and hash (order matters), copy/deepcopy return the same object,
  pickling refused (`TypeError`).
- `.lookup()` returns a `VoiceIdentityProfileLookupResult` with `found`, `profile`, `failures`, `codes()` and `to_dict()`.

## Input rules
1. `profiles` must be exactly a `tuple` (lists, sets, dicts, generators, strings and tuple subclasses are rejected). An empty tuple is valid.
2. Every item must be exactly a `VoiceIdentityProfile`. Look-alikes, dicts and subclasses are rejected.
3. `profile_id` values must be unique by exact comparison (no trimming, no case folding).
4. Input order is preserved and never sorted; the same `VoiceIdentityProfile` objects are stored (identity preserved) in an immutable tuple.
5. Every problem is reported at once, in input order. A bad item is reported once and never also counted as a duplicate.

## Lookup rules
- Exact `str` that matches a registered `profile_id` exactly: `found=True`, `profile` is the very registered object (identity preserved).
- Exact `str` with no exact match (including differently cased or padded text, and the empty string): `found=False`, code `PROFILE_NOT_FOUND`.
- Anything that is not exactly a `str` (None, bytes, int, a `str` subclass...): `found=False`, code `INVALID_PROFILE_ID`. A `str` subclass is never
  compared, so none of its methods run.
- No trimming, case folding, normalization or coercion, and **no search by `display_name`, `enabled` or `enrollment_status`**.

## Codes
| problem | code |
|---|---|
| input is not exactly a tuple | `VOICE_IDENTITY_PROFILE_REGISTRY_INVALID_COLLECTION` |
| item is not exactly a `VoiceIdentityProfile` | `VOICE_IDENTITY_PROFILE_REGISTRY_INVALID_PROFILE` |
| repeated `profile_id` | `VOICE_IDENTITY_PROFILE_REGISTRY_DUPLICATE_PROFILE_ID` |
| lookup: no exact match | `VOICE_IDENTITY_PROFILE_REGISTRY_PROFILE_NOT_FOUND` |
| lookup: id is not exactly a `str` | `VOICE_IDENTITY_PROFILE_REGISTRY_INVALID_PROFILE_ID` |

The factory emits only the first three; `lookup()` emits only the last two. Each failure is `{"code", "field", "message"}`.

## What this module does NOT do
- It stores NO raw audio, embeddings, biometric samples or external-service data - only the immutable `VoiceIdentityProfile` metadata objects.
- It does NOT perform voice recognition, enrollment, matching or audio processing.
- It does NOT use networking, the filesystem, persistence, a database, an AI model, an external service, a clock or randomness. Its only import is
  `voice.voice_identity_profile`; there is no module-level mutable state and no global registry.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner or Android, and no existing behavior changed.

## Regression-guard changes
Three existing pins were extended by exact path only, because they enumerate the production files outside the frozen Section 1-8 tree: the Prompt 718
frozen production-tree test lists `voice/voice_identity_profile_registry.py` as one further exact-path exemption; the Prompt 787 package-contents
test now expects the new file; and the Prompt 786 non-web production count/digest (which already included the two Prompt 787 voice files) now
covers this one additional file (353 -> 354 files). Their other checks are unchanged.

## Section 10 position
Prompt 788 is the second Section 10 prompt (Voice Identity Profile Registry). Prompt 789 has NOT been started.
