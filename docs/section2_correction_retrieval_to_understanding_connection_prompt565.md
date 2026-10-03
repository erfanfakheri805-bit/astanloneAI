# Prompt 565 — Safely Connect Correction Retrieval to Language Understanding

## 1. Existing trigger found

None. The Prompt 563 audit already in this project
(`diagnostics/section2_correction_retrieval_application_audit_prompt563.py`,
finding `no_trigger_exists_for_when_to_look_up_a_stored_correction`)
confirms there is no existing, deterministic concept anywhere in
`core/core.py`, `understanding/`, or `language_intelligence/` of "this
expression, in this ordinary (non-correction) message, is one Core has
a previously stored correction for; look it up before replying." That
finding was independently re-confirmed by inspection for this prompt:
a project-wide grep shows `build_correction_lookup_context()` and
`build_correction_application_candidate()` were, before this prompt,
called only from `diagnostics/`, their own package, and `tests/` —
never from `core/core.py` or `language_intelligence_core.py`.

Per Prompt 565's own instructions, since no safe runtime trigger
exists, **no trigger was invented**. Only the smallest
dependency-injection/adapter boundary was added.

## 2. What was connected

One new module,
`language_intelligence/correction_retrieval_understanding_adapter.py`,
composing the exact, unchanged existing chain the Prompt 563 audit
confirmed already works end to end:

```
lookup_correction_learning_input_by_original_expression_with_result()   (Prompt 464)
    -> build_correction_lookup_context()                                (Prompt 465)
    -> select_unique_stored_correction()                                (Prompt 469)
    -> build_correction_application_candidate()                         (Prompt 470)
    -> attach_correction_application_candidate()                        (THIS module)
       -> LanguageUnderstandingResult.correction_application_candidate  (Prompt 564)
```

Three functions:

- `build_correction_application_candidate_from_store(store, original_expression, language=None)`
  — runs the chain once, returns a `CorrectionApplicationCandidate`.
- `attach_correction_application_candidate(understanding, candidate)`
  — assigns an already-built candidate onto an existing
  `LanguageUnderstandingResult`, never overwriting one already set
  (same rule `_attach_response_plan()` uses for `response_plan`).
- `retrieve_and_attach_correction_application_candidate(understanding, store, original_expression, language=None)`
  — convenience combining both; only an `is_valid=True` candidate is
  attached (`AMBIGUOUS`/`NOT_FOUND`/`FAILED` leave the field `None`,
  per Prompt 565's own requirement).

No new retrieval, selection, or candidate logic was written — every
intermediate step is the exact, unchanged existing function.

## 3. What was intentionally NOT connected

- **No trigger.** Nothing decides *when* to call these functions.
  The caller must already have decided which `original_expression`
  (and `language`) to check, and whether to check at all.
- **Not wired into `core/core.py` or `language_intelligence_core.py`.**
  Neither file was modified. Confirmed by a regression test
  (`test_adapter_module_not_imported_by_backend_or_core`) that this
  new module is not imported by the deterministic backend or the
  language intelligence core.
- **No automatic application.** The candidate is informational only,
  exactly as `correction_lookup_context` already is.
- No new storage layer, database, or global singleton was added.

## 4. Exact files changed

- **Added:**
  `app/src/main/python/language_intelligence/correction_retrieval_understanding_adapter.py`
- **Added:**
  `app/src/main/python/tests/test_correction_retrieval_understanding_adapter_prompt565.py`
- **Added:** this document.
- **Modified:** none. `LanguageUnderstandingResult`, `core/core.py`,
  `language_intelligence_core.py`, and every backend are byte-for-byte
  unchanged from the Prompt 564 project.

## 5. Test results

Per Prompt 565 section 6, since no safe trigger exists, the original
tests 1–5 were replaced with tests proving the new boundary/adapter is
correct and that no retrieval occurs prematurely.

- Focused tests (this prompt): **20**, all passing.
- Correction-related tests (`test_*correction*.py`): **1316**, all
  passing.
- Language-intelligence tests (`test_*language_intelligence*.py`):
  **65**, all passing.
- Core tests (`test_core*.py`): **99**, all passing.
- Full suite (`test_*.py`, entire project): **10986**, all passing,
  0 failures, 0 errors (10966 pre-existing + 20 new).

Determinism was verified directly: repeated calls to
`build_correction_application_candidate_from_store()` and to
`retrieve_and_attach_correction_application_candidate()` with the same
store state and arguments produce equal candidates and equal
`to_dict()` output (`TestDeterminism`).

## 6. Remaining architectural gap before automatic correction application

Unchanged from the Prompt 563 audit's own conclusion — closing the
remaining gap still requires a genuine, separately-scoped design
decision this prompt does not make:

**What makes an ordinary, later message eligible for a stored-correction
lookup at all.** For example (illustrative only, not a recommendation
to build without further review): "when the current message's own
detected key expression exactly matches a `key` already stored under
`ITEM_TYPE_CORRECTION` for the active language, look it up." Once that
decision is made, wiring it in is now a single line in `core/core.py`
— for example, immediately after `self.language_intelligence.understand(...)`
returns, calling
`retrieve_and_attach_correction_application_candidate(understanding, self.language_learning, <decided_expression>)`
— since this prompt's adapter already composes every other step.
