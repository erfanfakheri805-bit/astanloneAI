# Prompt 566 — Define a Safe Deterministic Correction Retrieval Trigger

## 1. Existing correction signals found

Re-inspecting the full flow named in Prompt 566 section 1 (raw user
input -> `LanguageIntelligenceCore`/`DeterministicFallbackBackend` ->
`LanguageUnderstandingResult` -> correction detection -> correction
understanding -> correction retrieval adapter -> context -> intent/
request classification -> ambiguity/semantic signals) confirms Prompt
563's own audit finding
(`no_trigger_exists_for_when_to_look_up_a_stored_correction`,
`diagnostics/section2_correction_retrieval_application_audit_prompt563.py`)
still holds: nothing in `core/core.py`, `understanding/`, or
`language_intelligence/` decides *when* an ordinary message should
attempt a stored-correction lookup.

One existing, deterministic, already-computed signal was found that
safely narrows this question, though:

- `understanding/correction_detection.py`'s `detect_explicit_correction()`
  (Prompt 440) recognizes exactly ONE fixed, explicit textual marker -
  `"not <original>, i mean/meant <corrected>"` - and nothing else. It
  never guesses from tone, keywords ("mean", "actually", "not" in
  isolation), or general conversation.
- `language_intelligence/correction_understanding.py`'s
  `build_correction_understanding()` (Prompt 439) turns that candidate
  (when present) into a `CorrectionUnderstandingResult` with a fixed
  status - `RESOLVED`, `AMBIGUOUS`, `UNRESOLVED`, or `NOT_CORRECTION` -
  and is exposed, already wired in, as
  `LanguageUnderstandingResult.correction_understanding` (a
  `.to_dict()`, or `None` when no candidate exists at all - the
  ordinary case for almost every message).

Because `detect_explicit_correction()`'s regex requires BOTH the
original and corrected spans to match before it returns anything,
`correction_understanding`'s status is, in the actual current call
site (`deterministic_fallback_backend._build_correction_understanding()`),
only ever `RESOLVED` or `None` in practice - `AMBIGUOUS`/`UNRESOLVED`
are real states the underlying function can compute (and this
prompt's trigger still handles them, conservatively), but the fixed
marker can never actually produce them today.

This is exactly the "meaningful correction expression" Prompt 566
section 3 asks to reuse instead of writing another natural-language
detector. No new detection logic was written anywhere in this prompt.

## 2. The trigger contract

New module: `language_intelligence/correction_retrieval_trigger.py`.

`CorrectionRetrievalTrigger` - four fields only:

| field                | meaning                                                                 |
|----------------------|--------------------------------------------------------------------------|
| `should_attempt`     | `True` only when a `RESOLVED` correction understanding was found        |
| `reason`             | one of six fixed `REASON_*` constants - always explains the decision    |
| `original_expression`| minimal lookup info, copied through ONLY when `should_attempt` is `True`|
| `language`           | minimal lookup info, copied through ONLY when `should_attempt` is `True`|

`build_correction_retrieval_trigger(correction_understanding)` accepts
`None`, a `CorrectionUnderstandingResult` instance, or its `.to_dict()`
shape (the exact value `LanguageUnderstandingResult.correction_understanding`
already carries) and applies this fixed table:

| input status                         | `should_attempt` | `reason`                              |
|---------------------------------------|:---------------:|-----------------------------------------|
| `None` (no candidate at all)          | `False`          | `no_correction_signal`                   |
| `RESOLVED` (valid `original_expression`)| `True`         | `resolved_correction_identified`         |
| `RESOLVED` but malformed/missing expr  | `False`          | `invalid_correction_understanding_input` |
| `AMBIGUOUS`                            | `False`          | `correction_understanding_ambiguous`     |
| `UNRESOLVED`                           | `False`          | `correction_understanding_unresolved`    |
| `NOT_CORRECTION`                       | `False`          | `correction_understanding_not_correction`|
| missing/unknown status                 | `False`          | `invalid_correction_understanding_input` |

No new database call, no new detector, no scoring model - a single,
fixed lookup table over a status the existing pipeline already
computed.

## 3. Why the trigger is conservative

Only the single, fully explicit `RESOLVED` case ever returns
`should_attempt=True`. Every other outcome - including a message that
merely *looks* correction-shaped (`AMBIGUOUS`, `UNRESOLVED`) - stays
`False`. A generic conversational phrase can never even reach a
non-`None` correction_understanding in the first place, because
`correction_detection.py` recognizes only the one fixed marker; this
module adds no keyword or heuristic that could loosen that.

An unrecognized/malformed status (or a `RESOLVED` result missing its
own `original_expression`, which should not happen given how
`build_correction_understanding()` works but is handled defensively
anyway) is treated the same as "no usable signal" rather than raising
- the same "malformed input is treated like absent input" posture
`deterministic_fallback_backend._build_correction_understanding()`
already uses for a malformed correction candidate. A genuinely wrong
input *type* (not `None`, not a dict, not a `CorrectionUnderstandingResult`)
does raise `TypeError` - the same "isinstance check, then raise"
posture used throughout this package for caller contract violations.

## 4. Examples

Triggers (`should_attempt=True`):
- `"not dgo, I mean dog."` -> `original_expression="dgo"`

Does NOT trigger (`should_attempt=False`), all `no_correction_signal`
since none of these match the one fixed marker at all:
- `"I mean this is interesting."`
- `"What do you mean?"`
- `"I meant to ask you something."`
- `"Actually, tell me about dogs."`
- `"No, that's not what I asked"`
- any ordinary message ("What is the weather like today?", "Hello, how
  are you?", ...)

Does NOT trigger even when a `CorrectionUnderstandingResult` is
supplied directly with a real status:
- `AMBIGUOUS` (`corrected_candidates=["dog", "doge"]`) -> `correction_understanding_ambiguous`
- `UNRESOLVED` (only `original_expression="dgo"` supplied, no
  corrected form) -> `correction_understanding_unresolved`
- `NOT_CORRECTION` (`"hello there"`) -> `correction_understanding_not_correction`

## 5. Files changed

- **Added:**
  `app/src/main/python/language_intelligence/correction_retrieval_trigger.py`
- **Added:**
  `app/src/main/python/tests/test_correction_retrieval_trigger_prompt566.py`
- **Added:** this document.
- **Modified:** none. `CorrectionUnderstandingResult`,
  `LanguageUnderstandingResult`, `correction_detection.py`,
  `deterministic_fallback_backend.py`, `core/core.py`,
  `language_intelligence_core.py`, `correction_retrieval_understanding_adapter.py`,
  and every backend are byte-for-byte unchanged from the Prompt 565
  project.

## 6. Test results

- Focused tests (this prompt,
  `test_correction_retrieval_trigger_prompt566.py`): **27**, all
  passing, covering all 11 areas Prompt 566 section 6 lists (area 11 -
  the Prompt 565 adapter's own test file - was run unmodified as part
  of the regression counts below and remains fully passing).
- Correction-related tests (`test_*correction*.py`): **1343**, all
  passing (1316 pre-existing + 27 new).
- Language-intelligence tests (`test_*language_intelligence*.py`):
  **65**, all passing - unchanged from Prompt 565.
- Core tests (`test_core*.py`): **99**, all passing - unchanged from
  Prompt 565.
- Full suite (`test_*.py`, entire project): **11013**, all passing, 0
  failures, 0 errors (10986 pre-existing + 27 new).

Determinism was verified directly
(`TestDeterminism`): repeated calls to
`build_correction_retrieval_trigger()` with the same dict, the same
`CorrectionUnderstandingResult` instance, or `None`, always produce an
equal (`==`) trigger.

Confirmed explicitly: `build_correction_retrieval_trigger()` performs
**zero retrieval/storage operations**. The module imports only
`language_intelligence.correction_understanding` (verified by an
AST-based import check in
`TestZeroRetrievalStorageSideEffects.test_module_does_not_import_retrieval_chain`)
- it never imports `correction_learning_exact_lookup_result`,
`correction_lookup_context`, `correction_lookup_selection`,
`correction_application_candidate`,
`correction_retrieval_understanding_adapter`, or
`language_learning_store`, and its own function signature takes
exactly one argument (`correction_understanding`) - there is no store,
database, or connection parameter to pass in the first place.

## 7. Remaining work before retrieval is connected

Unchanged in kind from Prompt 565's own conclusion, now narrower in
scope:

1. **Connect the trigger to the Prompt 565 adapter.** A future,
   separately-scoped stage calls
   `build_correction_retrieval_trigger(understanding.correction_understanding)`
   after `LanguageIntelligenceCore`/a backend produces `understanding`,
   and - only when `trigger.should_attempt` is `True` - calls
   `retrieve_and_attach_correction_application_candidate(understanding,
   store, trigger.original_expression, language=trigger.language)`
   from `correction_retrieval_understanding_adapter.py`. Nothing in
   this prompt performs that call.
2. **The broader "referring to a previously learned correction"
   question stays open.** This trigger only ever fires when the
   CURRENT message itself supplies a complete, explicit correction
   (`"not X, I mean Y"`) - it does not yet identify an ordinary later
   message that merely *reuses* an expression a past correction was
   stored under, without restating the correction. Per Prompt 566
   section 5's own instruction, no such broader trigger was invented
   here, since doing so safely would require either a new, currently
   nonexistent expression-extraction signal for ordinary messages, or
   a store lookup inside the trigger itself (explicitly forbidden by
   section 5) - both out of scope for this prompt.
