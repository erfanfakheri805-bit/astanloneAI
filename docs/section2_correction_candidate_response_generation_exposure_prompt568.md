# Prompt 568 — Expose Correction Candidate to Response Generation Safely

## 1. Audit of the existing response-generation flow

Traced the real runtime path already established by Prompts 397–567:

```
raw_text
  -> Core._handle_conversation() step 1c
  -> LanguageIntelligenceCore.understand()
       -> LanguageUnderstandingResult.correction_understanding populated (Prompt 439/440)
  -> Core._attach_conversation_state()                (existing)
  -> Core._attach_learned_knowledge()                 (existing)
  -> Core._attach_correction_application_candidate()  (Prompt 567)
       -> build_correction_retrieval_trigger()            (Prompt 566, pure)
       -> retrieve_and_attach_correction_application_candidate()  (Prompt 565)
       -> LanguageUnderstandingResult.correction_application_candidate populated
                                                            (Prompt 564's own field)
  -> Core._attach_response_plan() (via LanguageIntelligenceCore)  (existing, Prompt 425)
  -> Core.language_intelligence.generate_response(understanding, context=...)
       -> LanguageIntelligenceCore.generate_response()
            -> LanguageIntelligenceCore._route_response()
                 -> DeterministicFallbackBackend.generate_response() (STATUS_DEFERRED, unchanged)
            -> LanguageIntelligenceCore._build_outcome()
                 -> ResponseGenerationRequest(understanding, context=...)   (response_generation.py, Prompt 421)
                 -> build_response_generation_outcome(response, request=request)
                      -> request.generation_context   (response_generation.py property)
                           -> ResponseGenerationRequest._generation_context_object()
                                -> build_generation_context(...)   (response_generation_context.py, Prompt 426)
                                     -> ResponseGenerationContext.correction_application_candidate
                                        (Prompt 471's own, pre-existing field)
```

Also inspected the second real consumer of an understanding,
`LocalLanguageModelBackend.generate_response()`
(local_model_backend.py), which builds its own
`InferenceRequest.generation_context` from the **module-level**
`generation_context_from_understanding(understanding)`
(response_generation_context.py) rather than from a
`ResponseGenerationRequest` instance.

## 2. What already existed (reused, not rebuilt)

Every piece of infrastructure Prompt 568 needed already existed,
built incrementally across several earlier, differently-numbered
prompts:

- `LanguageUnderstandingResult.correction_application_candidate`
  (Prompt 564) — the slot a real candidate is attached to.
- `Core._attach_correction_application_candidate()` (Prompt 567) —
  the real call site that actually populates that slot on the
  conversation path, using the unchanged Prompt 565 adapter and
  Prompt 566 trigger.
- `ResponseGenerationContext.correction_application_candidate` and
  `build_generation_context(..., correction_application_candidate=...)`
  (response_generation_context.py, Prompt 471) — the existing,
  already-tested transport all the way to the response-generation
  layer's own bounded, read-only bridge object.
- `generation_context_from_understanding()` (response_generation_context.py,
  Prompt 471) — the module-level helper that already reads
  `understanding.correction_application_candidate` via `getattr(...,
  None)` and forwards it unchanged. `LocalLanguageModelBackend`
  already calls this helper directly, so its own
  `InferenceRequest.generation_context` already carried a real
  candidate correctly, with no change needed.

## 3. The one gap found, and the smallest fix for it

`ResponseGenerationRequest._generation_context_object()`
(response_generation.py, Prompt 496) — the method behind the
`.generation_context` and `.selected_response_target` properties, and
the one `build_response_generation_outcome()`
(response_generation_outcome.py) itself reads through
`request.generation_context` for language/locale — called
`build_generation_context()` with `sentence_structure` and (Prompt
501) `learned_knowledge_context` forwarded, but **not**
`correction_application_candidate**. Since `build_generation_context()`
defaults that keyword argument to `None`, the property silently
returned `None` for `correction_application_candidate` even when
`understanding` carried a real one — the one place the existing,
already-built transport chain was not yet connected end to end.

This is exactly the "smallest existing object/path" the audit above
was asked to find: **one keyword argument**, added the same way
`learned_knowledge_context` immediately below it already was:

```python
context = build_generation_context(
    plan, sentence_structure=sentence_structure,
    correction_application_candidate=getattr(
        self.understanding, "correction_application_candidate", None),
    learned_knowledge_context=getattr(
        self.understanding, "learned_knowledge_context", None))
```

No new class, no new field, no new pipeline stage. `ResponseGenerationContext` and `build_generation_context()` were not touched.

### Reused vs. extended (section 2 of the prompt)

The existing response-generation context (`ResponseGenerationContext`)
already carries `correction_application_candidate` — it did **not**
need extending. Only the one call site that had not yet been updated
to pass the value through was fixed.

## 4. What still does NOT happen (unchanged, verified by test)

- No correction is applied to `response_action`, `meaning`,
  `language_guidance`, `response_pattern_selection`,
  `response_pattern_binding`, or `response_pattern_rendering` — all
  computed exactly as before, from `response_plan` alone (verified
  directly: same understanding, candidate toggled to `None` and back,
  every other key of the built context is unchanged).
- `original_message` is never replaced by the candidate's corrected
  text.
- The correction-learning store, memory, and the user's own input are
  never modified by anything in this prompt.
- The deterministic fallback backend still always returns
  `STATUS_DEFERRED` with `response_text=None`, candidate present or
  not.
- The existing correction acknowledgement (`process_input()`'s own
  "original_expression: ... / corrected_expression: ..." reply) is
  produced exactly as before, with or without a stored match.
- AMBIGUOUS / UNRESOLVED correction understanding never reaches this
  point with a candidate attached (Prompt 566/567's own conservative
  behavior, unchanged) — `understanding.correction_application_candidate`
  stays `None`, so the forwarded value is `None` too.

## 5. No new detection or retrieval

Nothing in this prompt imports or calls
`correction_learning_exact_lookup_result.py`,
`correction_lookup_context.py`, `correction_lookup_selection.py`,
`correction_application_candidate.py`'s builder, or
`correction_retrieval_understanding_adapter.py`. Building a response-
generation context (via either the fixed property or the pre-existing
module-level helper) performs **zero** store lookups and **zero**
selections — verified directly by wrapping
`build_correction_application_candidate_from_store` and
`select_unique_stored_correction` with call counters around calls to
both `ResponseGenerationRequest(...).generation_context` and
`generation_context_from_understanding(...)`.

## 6. Exactly-once propagation

For one `process_input()` / `understand_language()` +
`generate_response()` turn: the candidate is computed exactly once,
by `Core._attach_correction_application_candidate()` (Prompt 567,
unchanged), and every downstream read (`ResponseGenerationRequest.
generation_context`, `generation_context_from_understanding()`,
`generate_response_outcome()`) only ever reads the attribute already
set on `understanding` — verified with the same call-counter
convention Prompt 567's own tests use, both for the isolated context-
build calls and for a full `process_input()` turn.

## 7. Files changed

- `app/src/main/python/language_intelligence/response_generation.py` —
  one new keyword argument in `ResponseGenerationRequest.
  _generation_context_object()`, plus docstring notes on the
  `generation_context` property and the method itself.
- `app/src/main/python/tests/test_correction_application_candidate_in_response_generation_prompt568.py`
  — new, focused test file (19 tests, all passing).
- `docs/section2_correction_candidate_response_generation_exposure_prompt568.md`
  — this report.

Nothing else was changed. `ResponseGenerationContext`,
`build_generation_context()`, `generation_context_from_understanding()`,
`BackendGenerationRequest`, `Core._attach_correction_application_candidate()`,
the Prompt 565 adapter, and the Prompt 566 trigger are all untouched.

## 8. What remains intentionally unimplemented

- `BackendGenerationRequest` (response_generation_request.py, Prompt
  427) still does not carry `correction_application_candidate` as its
  own field. This was deliberately left alone: the model-facing
  `InferenceRequest.generation_context` (local_model_mapping.py)
  already receives the candidate correctly through
  `generation_context_from_understanding()`, so `generation_request`'s
  own omission is a pre-existing, separate, non-blocking gap in a
  redundant transport path, not the "smallest existing path" this
  prompt was scoped to fix. Extending `BackendGenerationRequest` would
  be a new field on a class this prompt was not asked to redesign.
- `ResponseGenerationOutcome` (response_generation_outcome.py, Prompt
  428) remains deliberately bounded (`status`, `generated_text`,
  `backend_kind`, `language`, `locale`, `failure_reason`,
  `fallback_used`, `metadata`, `used_verified_correction`) and does not
  itself surface the candidate — by design, exactly like
  `correction_lookup_context` and every other correction field before
  it; a caller that needs the raw candidate reads
  `request.generation_context["correction_application_candidate"]`
  directly, exactly as this prompt's tests do.
- No automatic correction application. Deciding whether/how a
  `CorrectionApplicationCandidate` should ever change generated text
  remains a separate, future, explicitly scoped prompt.

## 9. Test results

```
python -m unittest tests.test_correction_application_candidate_in_response_generation_prompt568 -v
  -> Ran 19 tests ... OK

python -m unittest tests.test_correction_retrieval_understanding_adapter_prompt565
  -> Ran 20 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_prompt566
  -> Ran 27 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_connection_prompt567
  -> Ran 21 tests ... OK

python -m unittest discover -s tests -p "test_correction*.py"
  -> Ran 877 tests ... OK

python -m unittest discover -s tests -p "test_response_generation*.py"
  -> Ran 212 tests ... OK

python -m unittest tests.test_language_intelligence tests.test_language_intelligence_core_integration_prompt560
  -> Ran 55 tests ... OK

python -m unittest tests.test_core
  -> Ran 62 tests ... OK

python -m unittest discover -s . -p "test_*.py"   (complete suite)
  -> Ran 11053 tests ... OK
```

No failures, no errors, anywhere.

## 10. Explicit confirmations

- **No second retrieval occurred.** Building a response-generation
  context (via either access path) performs zero calls into
  `correction_retrieval_understanding_adapter.py`; a full
  `process_input()` turn performs exactly one retrieval call, same as
  before Prompt 568 (verified by call-counter tests).
- **No automatic correction application occurred.** `original_message`,
  `response_action`, `language_guidance`, pattern selection/binding/
  rendering, and the deterministic backend's `STATUS_DEFERRED` result
  are all identical whether or not a candidate is attached; the
  correction acknowledgement reply is unchanged.
- **No existing behavior was weakened.** The complete pre-existing
  test suite (11,053 tests) passes unmodified, including every
  Prompt 471/564/565/566/567 test file and every existing response-
  generation test file.

## 11. Remaining gap

Deciding whether, when, and how a `CorrectionApplicationCandidate`
should actually influence generated response text — i.e. correction
*application* itself — is unimplemented by design and left to a
later, separately-scoped prompt, exactly as Prompt 568 specifies.
