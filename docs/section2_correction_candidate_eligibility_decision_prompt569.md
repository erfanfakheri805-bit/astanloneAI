# Prompt 569 — Add a Safe Correction Candidate Decision Boundary

## 1. Audit of the existing candidate/eligibility structure

Traced the real, verified Section 2 pipeline (Prompts 561-568):

```
CorrectionUnderstanding                              (Prompt 439/440)
  -> build_correction_retrieval_trigger()             (Prompt 566)
  -> retrieve_and_attach_correction_application_candidate()  (Prompt 565)
       -> build_correction_application_candidate_from_store()
            -> select_unique_stored_correction()      (Prompt 469)
            -> build_correction_application_candidate() (Prompt 470)
                 -> CorrectionApplicationCandidate
  -> LanguageUnderstandingResult.correction_application_candidate
                                                        (Prompt 564)
  -> ResponseGenerationContext.correction_application_candidate
                                                        (Prompt 471/568)
```

Also inspected the `CorrectionApplicationCandidate` class itself
(correction_application_candidate.py, Prompt 470) and every existing
module whose name mentions "eligib"/"readiness"/"usability" in
`language_intelligence/`:

- `correction_learning_input_eligibility.py` (Prompt 456) — eligibility
  of a *learning input dict*, a different object.
- `correction_lookup_usability.py` (Prompt 468) — usability of a
  `CorrectionLookupContext`, a different, earlier object in the chain.
- `correction_application_candidate_readiness.py` (Prompt 472) —
  **operates on `CorrectionApplicationCandidate` itself** and asks,
  word for word, the same question this prompt poses: "does this
  already-built candidate contain enough valid information for a
  future, separately-scoped correction-application step to use?"

## 2. Finding: the eligibility guarantee already exists

`is_correction_application_candidate_ready()` (Prompt 472) was built
and tested against `CorrectionApplicationCandidate` before the Section
2 retrieval pipeline (Prompts 561-568) existed. It was never narrowed
to any particular candidate *source* — it inspects only the
candidate's own four fields (`is_valid`, `original_expression`,
`corrected_expression_or_meaning`, `language`), the exact fields
`build_correction_application_candidate()` populates for every caller,
including `build_correction_application_candidate_from_store()`, the
constructor the Section 2 pipeline itself uses. Confirmed directly:
a candidate produced end-to-end by `Core.understand_language()` from a
real stored correction is reported ready by the unmodified Prompt 472
function (see `test_end_to_end_pipeline_candidate_is_eligible` below).

So the "existing eligibility concept" this prompt's section 6 asks to
reuse already exists and already applies to this exact pipeline's
candidate. Prompt 569 does not re-implement or duplicate any of its
checks (`_is_blank`, `canonical_language`) — both stay imported only
inside `correction_application_candidate_readiness.py`.

## 3. What was still missing, and the smallest addition for it

A bare boolean does not let a caller distinguish "no candidate was
ever attached" (the ordinary case for a non-correction message, or for
an AMBIGUOUS/UNRESOLVED correction understanding — Prompt 566/567's
own conservative behavior) from "a candidate was attached but
rejected." A later application stage benefits from knowing which case
produced an ineligible decision without re-deriving it from the
candidate's own fields. That is the one small gap this prompt fills.

**New module**: `language_intelligence/correction_application_candidate_eligibility.py`

```
evaluate_correction_application_candidate_eligibility(candidate)
    -> CorrectionApplicationCandidateEligibility(eligible: bool, reason: str)
```

`reason` is one of four fixed constants:

| Constant                      | Value                 | When                                                         |
|--------------------------------|------------------------|---------------------------------------------------------------|
| `REASON_ELIGIBLE`              | `"candidate_ready"`    | `candidate` is a `CorrectionApplicationCandidate` and Prompt 472's readiness check accepts it |
| `REASON_NO_CANDIDATE`          | `"no_candidate"`       | `candidate is None`                                           |
| `REASON_INVALID_CANDIDATE`     | `"invalid_candidate"`  | `candidate` is neither `None` nor a `CorrectionApplicationCandidate` |
| `REASON_CANDIDATE_NOT_READY`   | `"candidate_not_ready"`| a real candidate, but Prompt 472's readiness check rejects it |

All candidate-content validation is a single delegated call to
`is_correction_application_candidate_ready()` — this module adds only
the `None`/wrong-type dispatch above it, nothing else. No new fuzzy
matching, no new heuristics, no per-field reason granularity (which
would require re-deriving Prompt 472's own internal checks).

## 4. Why a small decision object, not another plain boolean

Every prior eligibility/readiness/usability check in this package
(Prompts 456, 468, 472) is a plain boolean, each with its own "why a
plain boolean, not a new result class" rationale: a single fact about
an already-built object needs no status-plus-issues structure. This
prompt's own instructions, however, explicitly ask for an
"eligible/not eligible" plus "reason" decision so a later stage can
act on *why*. The smallest structure satisfying that — two `__slots__`
fields, `to_dict()`, `__eq__`, `__repr__`, no other behavior — keeps
the same minimalism those three modules already established, while
meeting this prompt's explicit ask. It is not a new validation
framework: every bit of actual validation is still the single,
unmodified Prompt 472 function.

## 5. Eligibility must be conservative — verified

- Any value that is not a `CorrectionApplicationCandidate` (including
  `None`, strings, numbers, lists, dicts, arbitrary objects) is
  ineligible; the function never raises.
- A candidate whose originating selection was AMBIGUOUS, NOT_FOUND, or
  FAILED (`is_valid=False`) is ineligible.
- A candidate missing `original_expression`, missing
  `corrected_expression_or_meaning`, or naming no real
  language/locale is ineligible — exactly Prompt 472's existing rule,
  unchanged.
- Candidate existence alone is never treated as eligibility — only a
  candidate that already passes Prompt 472's readiness check is
  eligible.

## 6. What this prompt does NOT do (verified by test)

- Does not apply or execute any correction.
- Does not replace or rewrite any user text.
- Does not modify `CorrectionApplicationCandidate`,
  `LanguageUnderstandingResult`, or `ResponseGenerationContext` — each
  verified unchanged (via `to_dict()` equality before/after) after
  calling the new function on their real, attached candidate.
- Does not modify memory or correction-learning storage.
- Performs zero database/storage access and zero retrieval
  operations — verified with the same call-counter convention Prompt
  567/568's own tests use, wrapping
  `build_correction_application_candidate_from_store()`,
  `select_unique_stored_correction()`, and the real learning store's
  `get_item()`.
- Performs no additional correction-learning lookup: for one
  `process_input()` / `understand_language()` turn, retrieval still
  happens exactly once, exactly as before this prompt.
- Does not change the existing correction acknowledgement reply, does
  not change ordinary non-correction message handling, and does not
  change AMBIGUOUS/UNRESOLVED correction behavior (no candidate is
  ever attached for either, so eligibility is simply
  `REASON_NO_CANDIDATE` for them, same as any ordinary message).

## 7. Placement

Added as its own small module,
`language_intelligence/correction_application_candidate_eligibility.py`,
alongside `correction_application_candidate.py` (Prompt 470) and
`correction_application_candidate_readiness.py` (Prompt 472) it
depends on — the same "one small, single-purpose module per stage"
convention this package already uses throughout the correction
pipeline (Prompts 465/468/469/470/472/473/...). No correction business
logic was placed in Core or any other unrelated infrastructure module,
and response generation was not redesigned.

## 8. Not yet connected

Exactly like Prompt 472 and Prompt 473 before it, this module is not
called from `Core`, `LanguageIntelligenceCore`, any backend, or
anywhere else in this codebase — it is dependency-injection surface
only, held ready for whichever future, separately-scoped prompt
implements actual correction application. `Core._attach_correction_application_candidate()`,
the Prompt 565 adapter, and the Prompt 566 trigger are all untouched.

## 9. Files changed

- `app/src/main/python/language_intelligence/correction_application_candidate_eligibility.py`
  — new. `CorrectionApplicationCandidateEligibility` class,
  `evaluate_correction_application_candidate_eligibility()` function,
  and the four `REASON_*` constants.
- `app/src/main/python/tests/test_correction_application_candidate_eligibility_prompt569.py`
  — new, focused test file (29 tests, all passing).
- `docs/section2_correction_candidate_eligibility_decision_prompt569.md`
  — this report.

Nothing else was changed. `CorrectionApplicationCandidate`,
`correction_application_candidate_readiness.py`,
`LanguageUnderstandingResult`, `ResponseGenerationContext`,
`Core._attach_correction_application_candidate()`, the Prompt 565
adapter, and the Prompt 566 trigger are all untouched.

## 10. Tests and results

```
python -m unittest tests.test_correction_application_candidate_eligibility_prompt569 -v
  -> Ran 29 tests ... OK

python -m unittest tests.test_correction_application_candidate_readiness
  -> Ran 12 tests ... OK

python -m unittest tests.test_correction_retrieval_understanding_adapter_prompt565
  -> Ran 20 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_prompt566
  -> Ran 27 tests ... OK

python -m unittest tests.test_correction_retrieval_trigger_connection_prompt567
  -> Ran 21 tests ... OK

python -m unittest tests.test_correction_application_candidate_in_response_generation_prompt568
  -> Ran 19 tests ... OK

python -m unittest discover -s tests -p "test_correction*.py"
  -> Ran 906 tests ... OK   (877 pre-existing + 29 new)

python -m unittest discover -s tests -p "test_language_intelligence*.py"
  -> Ran 55 tests ... OK

python -m unittest tests.test_core
  -> Ran 62 tests ... OK

python -m unittest discover -s tests -p "test_response_generation*.py"
  -> Ran 212 tests ... OK

python -m unittest discover -s . -p "test_*.py"   (complete suite)
  -> Ran 11082 tests ... OK   (11053 pre-existing + 29 new)
```

No failures, no errors, anywhere.

## 11. Explicit zero-side-effect verification

- **Zero database/storage access from the eligibility function.**
  Confirmed by wrapping the real learning store's `get_item()` around
  a call to `evaluate_correction_application_candidate_eligibility()`
  on a real, end-to-end-produced candidate: zero calls.
- **Zero retrieval.** Confirmed by wrapping
  `build_correction_application_candidate_from_store()` and
  `select_unique_stored_correction()`: zero calls either way.
- **Zero correction application.** `original_message`,
  `response_action`, and `generate_language_response()`'s
  `STATUS_DEFERRED`/`generated_text=None` result are identical whether
  or not eligibility was evaluated.
- **Deterministic results.** The same candidate (by value, including
  `None` and two separately-constructed-but-equal candidates) always
  produces an equal decision across repeated calls.
- **No mutation.** The candidate, the owning
  `LanguageUnderstandingResult`, and the owning
  `ResponseGenerationContext` are all byte-for-byte (`to_dict()`)
  identical before and after evaluation.

## 12. Remaining gap before correction application

Deciding whether, when, and how an *eligible*
`CorrectionApplicationCandidate` should actually influence generated
response text — correction *application* itself — remains
unimplemented by design and left to a later, separately-scoped
prompt, exactly as this prompt specifies. This prompt only produces
the deterministic eligibility decision a future stage can consume; it
never consumes it itself.
