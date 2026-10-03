# Prompt 567 — Connect the Correction Trigger to Existing Retrieval

## 1. Runtime trace and the smallest correct integration point

Tracing the real runtime path named in Prompt 567 section 1:

    raw_text
      -> Core._handle_conversation() step 1c
      -> LanguageIntelligenceCore.understand()
      -> backend.understand() (DeterministicFallbackBackend)
           -> _build_correction_understanding()   (Prompt 440/439, unchanged)
           -> LanguageUnderstandingResult.correction_understanding populated
      -> Core._attach_conversation_state(understanding)   (existing)
      -> Core._attach_learned_knowledge(understanding, text)   (existing)
      -> [NEW] Core._attach_correction_application_candidate(understanding)
      -> ... step 1d (generate_response), step 1e (acknowledgement) ...

`Core._attach_conversation_state` and `Core._attach_learned_knowledge`
already establish the exact pattern this prompt needed: both are
called immediately after `self.language_intelligence.understand(...)`
returns, both attach optional, best-effort information onto that same
`LanguageUnderstandingResult`, and both are called from the two places
Core ever produces an understanding from real text -
`_handle_conversation()`'s step 1c and the explicit `understand_language()`
entry point. This is the smallest correct location because:

1. correction understanding already exists there
   (`understanding.correction_understanding`, computed by the
   unchanged backend call just above).
2. the Prompt 566 trigger can be evaluated there (pure, synchronous,
   no I/O — see `correction_retrieval_trigger.build_correction_
   retrieval_trigger()`).
3. the Prompt 565 adapter can be called there — Core already holds the
   one real store the adapter needs, `self.language_learning`
   (`LanguageLearningStore`), the SAME store `_store_resolved_
   correction_learning()` (Prompt 562) already writes to.
4. the resulting candidate can be attached to the SAME
   `LanguageUnderstandingResult` object already in scope, via
   `LanguageUnderstandingResult.correction_application_candidate`
   (Prompt 564's existing field).

No other runtime path was invented. `LanguageIntelligenceCore` itself
was deliberately left untouched — its own module docstring says it
"never touches memory, knowledge, context, or storage itself", and
`self.language_learning` is a Core-level store, not something
`LanguageIntelligenceCore` holds — so the new call site belongs in
`core/core.py`, exactly where its sibling attach methods already live.

## 2. Trigger → retrieval → candidate connection

One new method, `Core._attach_correction_application_candidate()`:

```python
def _attach_correction_application_candidate(self, understanding):
    if understanding is None:
        return
    try:
        correction_understanding = understanding.correction_understanding
        trigger = build_correction_retrieval_trigger(correction_understanding)
        if not trigger.should_attempt:
            return
        retrieve_and_attach_correction_application_candidate(
            understanding, self.language_learning,
            trigger.original_expression, language=trigger.language,
        )
    except Exception:  # never breaks the conversation path
        return
```

- `should_attempt == True` (the RESOLVED case) → calls the existing
  Prompt 565 `retrieve_and_attach_correction_application_candidate()`,
  which itself runs the existing lookup → context → selection →
  candidate chain and attaches the result via `LanguageUnderstandingResult.
  correction_application_candidate` — unchanged, unmodified.
- `should_attempt == False` (AMBIGUOUS / UNRESOLVED / NOT_CORRECTION /
  no signal / invalid input) → no retrieval call is made at all; the
  candidate stays whatever it already was (`None`, per Prompt 564,
  for every ordinary message).

Called from both existing call sites, immediately after
`_attach_learned_knowledge`:

- `_handle_conversation()` step 1c (the real conversation path).
- `understand_language()` (the explicit, read-only entry point).

## 3. Exactly-once behavior

For one `understand()`/`understand_language()` call:

- the trigger is evaluated exactly once (a single, pure function call
  over the already-computed `correction_understanding` dict — no
  loop, no retry).
- when `should_attempt` is True, `retrieve_and_attach_correction_
  application_candidate()` is called exactly once, which itself
  performs exactly one store lookup
  (`lookup_correction_learning_input_by_original_expression_with_
  result`), exactly one context build, exactly one selection
  (`select_unique_stored_correction`), and attaches at most one
  candidate — all unchanged Prompt 464/465/469/470/565 behavior,
  reused verbatim.
- no correction-learning write happens here at all — this method
  never calls `handoff_correction_learning_input_with_result()` or
  `learn_item()`; that remains exclusively `_store_resolved_
  correction_learning()`'s own responsibility at step 1e, unaffected
  by this prompt.

Verified in
`tests/test_correction_retrieval_trigger_connection_prompt567.py` by
wrapping (never replacing) `retrieve_and_attach_correction_application_
candidate`, `build_correction_application_candidate_from_store`, and
`select_unique_stored_correction` with call counters that still
delegate to the real, unmodified functions — the same convention
`test_section2_correction_learning_core_integration_prompt562.py`
already uses for `learn_item`.

## 4. Conservative behavior preserved

The Prompt 566 trigger itself was not touched: no new heuristic,
keyword, or status was added anywhere. The five example messages
Prompt 567 section 4 lists —
`"I mean this is interesting."`, `"What do you mean?"`,
`"I meant to ask you something."`, `"Actually, tell me about dogs."`,
and ordinary conversation — never match `understanding/
correction_detection.py`'s one fixed marker, so `correction_
understanding` is `None` for all of them, the trigger reports
`should_attempt=False`/`REASON_NO_CORRECTION_SIGNAL`, and zero
retrieval calls occur (verified directly by the call-counter test
above).

AMBIGUOUS and UNRESOLVED stay conservative too. In the current,
unchanged detection layer, `detect_explicit_correction()`'s regex only
ever yields both an original and a corrected span together or neither
— so in practice, real text reaching `Core.process_input()` /
`understand_language()` never itself produces an AMBIGUOUS or
UNRESOLVED `correction_understanding`. Since that path is real but
unreachable through today's detector, the connection point is
exercised directly for these two statuses (`Core._attach_correction_
application_candidate()` called with a manually built AMBIGUOUS/
UNRESOLVED `correction_understanding`, mirroring how Prompt 566's own
tests exercise these statuses) to confirm zero retrieval calls and
`candidate=None` in both cases.

## 5. No automatic correction application

Nothing changed about what a `CorrectionApplicationCandidate` does:
it is only ever informational. This prompt does not replace user text,
rewrite input, modify stored memory, modify the correction-learning
database, execute anything automatically, or change future response
behavior. `_attach_correction_application_candidate()` only ever sets
one field, `understanding.correction_application_candidate` — nothing
else on `understanding`, the user's message, or the store is touched.

## 6. Existing correction acknowledgement preserved

Step 1e (`_handle_conversation()`) still reads only `understanding.
correction_understanding["status"] == CORRECTION_STATUS_RESOLVED` to
decide whether to acknowledge a correction and call `_store_resolved_
correction_learning()` — both completely unchanged by this prompt. The
new candidate is attached earlier (step 1c, before step 1d/1e ever
run) as pure additional structured information; it does not replace,
gate, or otherwise affect the acknowledgement reply text, which stays
byte-for-byte identical whether or not a matching stored correction
existed (verified by
`TestAcknowledgementUnaffectedAndNoAutoApplication`).

## 7. Candidate correctness

Every attached candidate in the new tests comes from the real existing
storage/retrieval path: a correction is first stored through the exact
same chain `Core._store_resolved_correction_learning()` itself uses
(`build_correction_understanding` → `map_correction_understanding_to_
result` → `map_correction_understanding_result_to_feedback_record` →
`convert_correction_feedback_to_learning_input` →
`handoff_correction_learning_input_with_result` →
`store_accepted_correction_learning_input`), all against Core's own
real `self.language_learning`. The subsequent `understand_language()`
call then retrieves that same real row through the unmodified Prompt
565 adapter — no synthetic `CorrectionApplicationCandidate` is ever
constructed directly in these tests.

## 8. No-candidate case

When the trigger fires but no matching learned correction exists,
retrieval is attempted once (one lookup, `NOT_FOUND` outcome), no
candidate is attached (`correction_application_candidate` stays
`None`), normal understanding continues completely unchanged
(`correction_understanding` itself is untouched), and nothing raises.

## 9. Files changed

- `app/src/main/python/core/core.py` — two new imports
  (`build_correction_retrieval_trigger`, `retrieve_and_attach_
  correction_application_candidate`), one new method
  (`_attach_correction_application_candidate`), and two new call sites
  (`_handle_conversation()` step 1c, `understand_language()`).
- `app/src/main/python/tests/test_correction_retrieval_trigger_connection_prompt567.py`
  — new, focused regression tests (21 tests, all fifteen section-9
  items covered).
- `docs/section2_correction_retrieval_trigger_connection_prompt567.md`
  — this report.

No file in `language_intelligence/correction_retrieval_trigger.py` or
`language_intelligence/correction_retrieval_understanding_adapter.py`
was modified — both Prompt 565 and Prompt 566 artifacts are reused
exactly as they already existed. No new trigger class, candidate
class, retrieval adapter, storage system, correction detector, or
validator chain was created.

## 10. Test results

| Group | Count | Result |
|---|---|---|
| New Prompt 567 tests | 21 | OK |
| Prompt 565 adapter tests (`test_correction_retrieval_understanding_adapter_prompt565.py`) | 20 | OK, unmodified |
| Prompt 566 trigger tests (`test_correction_retrieval_trigger_prompt566.py`) | 27 | OK, unmodified |
| All correction-related tests (`test_correction*.py`) | 858 | OK |
| Core tests (`test_*core*.py`) | 136 | OK |
| Complete suite (`discover -p "test_*.py"`) | 11034 | OK (11013 pre-existing + 21 new) |

No failures, no errors, no existing test weakened or removed.

## 11. Exactly-once / deterministic / no-auto-application confirmation

- Exactly-once: `TestExactlyOnceRetrievalAndSelection` wraps the
  adapter's own entry point, its internal store-chain function, and
  `select_unique_stored_correction` with counters — each is called
  exactly 1 time per `understand_language()` call when the trigger
  fires, 0 times when it does not.
- Deterministic: `TestDeterminism` runs the same message twice (with
  and without a stored match) and asserts equal (`==`) results both
  times.
- No automatic application: `TestAcknowledgementUnaffectedAndNoAutoApplication`
  confirms the user's `original_input`, the stored item's `meaning`,
  and the acknowledgement reply text are all byte-for-byte identical
  whether or not a candidate was attached.

## 12. What remains intentionally unimplemented

Per Prompt 567's own critical boundary, this prompt stops at candidate
exposure. Not implemented (deliberately, for a future, separately
scoped prompt):

- reading `understanding.correction_application_candidate` anywhere
  in response generation.
- automatically rewriting, replacing, or substituting the corrected
  expression/meaning into any reply.
- any new heuristic that would let AMBIGUOUS/UNRESOLVED/ordinary
  messages reach retrieval.
