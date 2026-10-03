# Prompt 807 - Section 10: Voice Verification Registry

Status: **implemented.** `voice/voice_verification_registry.py` (pinned by `tests/test_voice_verification_registry_prompt807.py`). It follows the
closest existing registry contract, the Prompt 788 `VoiceIdentityProfileRegistry`.

## Reused profile contract
The verification chain (Prompts 798-806) only carries a `profile_id` string. The established contract that identifies a profile is the Prompt 787
`VoiceIdentityProfile`, so the registry stores exactly that type. No `VoiceVerificationProfile` or other profile model was created, and
`VoiceIdentityProfile` and every earlier verification module are unchanged.

## Public API
- `create_voice_verification_registry(profiles)` returns a `VoiceVerificationRegistryResult` with `ok`, `registry` (`None` unless `ok`), `failures`,
  `codes()` and `to_dict()`. It never raises for bad input and never changes what it is given.
- `VoiceVerificationRegistry`: `.profiles` (tuple, registration order), `.profile_ids` (fresh tuple), `.lookup(profile_id)`, `.to_dict()` returning
  `{"profiles": [VoiceIdentityProfile.to_dict(), ...]}` (fresh on every call). Immutable (`__slots__`, assignment/deletion raises `AttributeError`),
  not subclassable, direct construction refused (`TypeError`), deterministic equality and hash (order matters), copy/deepcopy return the same object,
  pickling refused (`TypeError`).
- `.lookup()` returns a `VoiceVerificationLookupResult` with `found`, `profile`, `failures`, `codes()` and `to_dict()`.

## Input rules
1. `profiles` must be exactly a `tuple` (lists, sets, dicts, generators, strings, `None` and tuple subclasses are rejected). An empty tuple is valid.
2. Every item must be exactly a `VoiceIdentityProfile`, checked with `type(item) is VoiceIdentityProfile`. Look-alikes, dicts, `None`, and objects
   spoofing `__class__` are rejected.
3. `profile_id` values must be unique by exact comparison (no trimming, no case folding).
4. Input order is preserved and never sorted; the same profile objects are stored (identity preserved) in a fresh immutable tuple (the caller's tuple is not retained).
5. Every problem is reported at once, in input order. A bad item is reported once and never also counted as a duplicate.

## Lookup rules
- Exact `str` matching a registered `profile_id` exactly: `found=True`, `profile` is the very registered object.
- Exact `str` with no exact match (including differently cased or padded text, and the empty string): `found=False`, code `PROFILE_NOT_FOUND`.
- Anything not exactly a `str` (None, bytes, int, a `str` subclass...): `found=False`, code `INVALID_PROFILE_ID`. A `str` subclass is never compared.
- No trimming, case folding, normalization or coercion, and no search by `display_name`, `enabled` or `enrollment_status`.

## Codes
| problem | code |
|---|---|
| input is not exactly a tuple | `VOICE_VERIFICATION_REGISTRY_INVALID_COLLECTION` |
| item is not exactly a `VoiceIdentityProfile` | `VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE` |
| repeated `profile_id` | `VOICE_VERIFICATION_REGISTRY_DUPLICATE_PROFILE_ID` |
| lookup: no exact match | `VOICE_VERIFICATION_REGISTRY_PROFILE_NOT_FOUND` |
| lookup: id is not exactly a `str` | `VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE_ID` |

The factory emits only the first three; `lookup()` emits only the last two. Each failure is `{"code", "field", "message"}`.

## What this module does NOT do
- It stores NO raw audio, embeddings, biometric samples or external-service data - only immutable `VoiceIdentityProfile` metadata objects.
- It does NOT perform voice recognition, verification, matching, audio processing or microphone access.
- It does NOT use networking, the filesystem, persistence, a database, an AI model, a cloud service, Android APIs, a clock or randomness. Its only import is
  `voice.voice_identity_profile`; there is no module-level mutable state and no global registry.
- It is NOT wired into Core, `AgentLoop`, `process_input()`, the Planner or Android, and no existing behavior changed.

## Regression-guard changes
By exact path only: the tests that list the `voice/` package contents, the Prompt 718 production-tree exemption list and the Prompt 786 non-web
production count/digest now include `voice/voice_verification_registry.py`.

## Section 10 position
Prompt 807 adds the verification registry. Prompt 808 has NOT been started.
