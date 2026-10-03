# Prompt 570 — Define a Safe Correction Application Operation

## 1. Existing correction-application infrastructure discovered

A full audit of `language_intelligence/` found that an essentially
complete, deterministic, exact-match-only correction-application
pipeline **already existed**, built incrementally across many earlier
prompts, entirely disconnected from `Core`:

| Prompt | Module | Provides |
|---|---|---|
| 470 | `correction_application_candidate.py` | `CorrectionApplicationCandidate` (already flows through the live Section 2 pipeline) |
| 472 | `correction_application_candidate_readiness.py` | `is_correction_application_candidate_ready()` |
| 473 | `correction_application_request.py` | `build_correction_application_request(candidate)` → `CorrectionApplicationRequest` (raises `TypeError` for a non-candidate) |
| 474/478/479 | `correction_application_result.py` | `CorrectionApplicationResult` — status/applied/original_text/corrected_text/reason/matched_text/replacement_text/match_count/text_before/text_after |
| 475 | `correction_application.py` | `apply_correction_request(request, target_text)` — exact-match substring replacement |
| 476 | `correction_application_target_validation.py` | `validate_correction_application_target(request, target_text)` |
| 477 | `correction_application_guarded.py` | `apply_correction_request_with_validation(request, target_text)` — validates, applies, then verifies the result before returning it |
| 480/481/482 | `correction_application_result_validation.py`, `correction_application_verification_result.py`, `correction_application_verification.py` | structural verification of a produced `APPLIED` result |
| 483/484 | `response_generation_context.py`, `correction_application_result_usability.py` | an optional, caller-supplied `correction_application_result` field on `ResponseGenerationContext`, plus a usability check over it |
| 485 | `verified_correction_response_input.py` | a further, stricter "already applied and verified" shape for a later response-generation stage |
| 569 (this project) | `correction_application_candidate_eligibility.py` | the eligibility boundary this prompt must respect |

None of this chain is imported by `Core`, `generate_language_response()`,
`generate_response()`, or `response_planning.py` — confirmed directly
by searching those files' source for every relevant name. It is
dependency-injection surface only, exactly as each module's own "not
yet connected" section already documents.

## 2. Existing application logic was reused, not duplicated

Every actual decision Prompt 570 needs — matching rule, result shape,
validation, verification — is already implemented by Prompts 473-477
and reused here **unchanged**:

- `build_correction_application_request(candidate)` (Prompt 473)
- `apply_correction_request_with_validation(request, target_text)`
  (Prompt 477, which itself reuses Prompts 475/476/480/482)
- `CorrectionApplicationResult` (Prompt 474/478/479) as the result
  contract

The **one** gap: `build_correction_application_request()` raises
`TypeError` for anything that is not already a
`CorrectionApplicationCandidate` — the correct contract for its
existing caller, but not one that can accept `None` or a malformed
candidate and return a deterministic non-applicable result, as this
prompt requires. No existing function in the chain bridged Prompt
569's eligibility decision to this chain in a way that tolerates that.

## 3. The operation added

**New module**: `language_intelligence/correction_application_candidate_operation.py`

```
apply_correction_application_candidate(candidate, target_text)
    -> CorrectionApplicationResult
```

Behavior:
1. `candidate` is evaluated with the **existing, unmodified**
   `evaluate_correction_application_candidate_eligibility()`
   (Prompt 569) — the single source of truth for whether `candidate`
   may be considered at all.
2. **Not eligible** (`None`, wrong type, or a real-but-not-ready
   candidate) → a `CorrectionApplicationResult(STATUS_FAILED, ...)` is
   returned directly, with `reason` copied verbatim from the
   eligibility decision. `build_correction_application_request()` is
   never called in this branch, so its `TypeError` is never reached.
3. **Eligible** → `candidate` is by construction already a real, ready
   `CorrectionApplicationCandidate`, so
   `build_correction_application_request(candidate)` cannot raise;
   its request is passed straight to
   `apply_correction_request_with_validation(request, target_text)`
   (Prompt 477, unchanged), and that result is returned exactly as
   produced.

This function adds no matching rule, no new result type, and no new
validation — it is a thin, ~15-line dispatcher in front of code that
already existed.

## 4. Exact correction semantics preserved

No new fuzzy/semantic/case-insensitive matching was introduced. The
only substring-replacement behavior involved is the existing,
unmodified, exact-match-only rule `apply_correction_request()`
(Prompt 475) already defines and documents — reused precisely because
the existing architecture already explicitly defines that behavior
(satisfying section 4's condition for permitting substring
replacement at all).

## 5. Minimal result contract — reused, not duplicated

`CorrectionApplicationResult` (Prompt 474/478/479) already distinguishes
application possible (`status=APPLIED`, `applied=True`) from not
possible (`NOT_APPLIED`/`FAILED`), already carries the original
expression (`matched_text`/`text_before`/`original_text`) and
corrected expression (`replacement_text`/`text_after`/`corrected_text`)
exactly as given, and already carries a `reason` for every non-applied
outcome. No new result type was created.

## 6. Eligibility boundary respected

The new operation's *first* action, unconditionally, is to call
Prompt 569's `evaluate_correction_application_candidate_eligibility()`.
`None`, an invalid-type value, and a real-but-not-ready candidate all
produce a deterministic `FAILED` result with the eligibility
decision's own reason (`no_candidate` / `invalid_candidate` /
`candidate_not_ready`) — verified by tests for all three cases,
including candidates derived from `AMBIGUOUS`/`NOT_FOUND`/`FAILED`
selection outcomes. The eligibility check is never bypassed, and its
outcome is never second-guessed by re-deriving readiness independently.

## 7. No automatic invocation

`apply_correction_application_candidate` is not imported by `core/core.py`
or `language_intelligence/response_planning.py` — confirmed by
searching both files' source for the module and function name (and by
a test that does the same). Normal `Core` processing —
`process_input()`, `understand_language()`,
`generate_language_response()` — behaves identically to before this
prompt: the correction acknowledgement reply is unchanged, and a
message containing a known typo is *not* silently corrected in the
reply, because nothing calls the new operation automatically. A later,
separately-scoped prompt will decide when and how it is invoked.

## 8. Files changed

- `app/src/main/python/language_intelligence/correction_application_candidate_operation.py`
  — new. `apply_correction_application_candidate()`.
- `app/src/main/python/tests/test_correction_application_candidate_operation_prompt570.py`
  — new, focused test file (33 tests, all passing).
- `docs/section2_correction_application_operation_prompt570.md` — this
  report.

Nothing else was changed. `CorrectionApplicationCandidate`,
`correction_application_candidate_eligibility.py`,
`correction_application_request.py`, `correction_application.py`,
`correction_application_target_validation.py`,
`correction_application_guarded.py`,
`correction_application_result.py`, `LanguageUnderstandingResult`,
`ResponseGenerationContext`, `Core`, and `response_planning.py` are
all untouched.

## 9. No duplicate architecture

No new candidate class, detector, retrieval mechanism, eligibility
system, storage layer, validator chain, or response-generation
pipeline was created. The new module has exactly one function and
imports four existing, unmodified pieces
(`evaluate_correction_application_candidate_eligibility`,
`build_correction_application_request`,
`apply_correction_request_with_validation`,
`CorrectionApplicationResult`/`STATUS_FAILED`).

## 10. Test results

```
python -m unittest tests.test_correction_application_candidate_operation_prompt570
  -> Ran 33 tests ... OK

python -m unittest discover -s tests -p "test_correction_application*.py"
  -> Ran 329 tests ... OK

python -m unittest discover -s tests -p "test_verified_correction*.py"
  -> Ran 180 tests ... OK

python -m unittest tests.test_correction_retrieval_understanding_adapter_prompt565
  -> Ran 20 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_prompt566
  -> Ran 27 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_connection_prompt567
  -> Ran 21 tests ... OK

python -m unittest tests.test_correction_application_candidate_in_response_generation_prompt568
  -> Ran 19 tests ... OK

python -m unittest tests.test_correction_application_candidate_eligibility_prompt569
  -> Ran 29 tests ... OK

python -m unittest discover -s tests -p "test_correction*.py"
  -> Ran 939 tests ... OK   (906 pre-existing + 33 new)

python -m unittest discover -s tests -p "test_language_intelligence*.py"
  -> Ran 55 tests ... OK

python -m unittest tests.test_core
  -> Ran 62 tests ... OK

python -m unittest discover -s tests -p "test_response_generation*.py"
  -> Ran 212 tests ... OK

python -m unittest discover -s . -p "test_*.py"   (complete suite)
  -> Ran 11115 tests ... OK   (11082 pre-existing + 33 new)
```

No failures, no errors, anywhere.

## 11. Explicit verification

- **Zero storage access.** `core.language_learning.get_item()` wrapped
  with a call counter around an end-to-end (`Core`-produced) eligible
  candidate: zero calls.
- **Zero retrieval.**
  `build_correction_application_candidate_from_store()` wrapped with a
  call counter for both an eligible and an ineligible (`None`)
  candidate: zero calls in either case.
- **Zero selection.** `select_unique_stored_correction()` wrapped with
  a call counter: zero calls.
- **Zero mutation.** The candidate (`.copy()` before/after equality),
  the target `str` (identity-preserving, strings are immutable in
  Python regardless), and the owning `LanguageUnderstandingResult`
  (`to_dict()` before/after equality) are all unchanged by calling the
  operation.
- **Zero automatic invocation.** Verified by source-inspection tests
  that neither `core/core.py` nor `response_planning.py` mention the
  new module or function, and by behavioral tests that
  `process_input()`'s correction acknowledgement and ordinary-message
  handling are byte-identical to before this prompt.
- **Deterministic behavior.** The same candidate and target text
  (including `None`/ineligible inputs) always produce an equal result
  across repeated calls and across separately-constructed-but-equal
  candidates.

## 12. Remaining gap before this operation is actually used

Deciding *when* and *how* `apply_correction_application_candidate()`
should be invoked during real conversation handling — what target text
it should be applied to, how its result should populate
`ResponseGenerationContext.correction_application_result`, and how
that should ultimately affect a generated reply — remains
unimplemented by design and is left to a future, separately-scoped
prompt, exactly as this prompt specifies.
