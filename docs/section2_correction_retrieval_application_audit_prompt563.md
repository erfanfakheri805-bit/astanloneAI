# Section 2: Correction-Learning Retrieval/Application Audit (Prompt 563)

Roadmap position: Section 2 of 10 — Language Intelligence and Request
Understanding, current position Prompt 563 (approximate range
559–630).

## Objective

Per Prompt 562's own "smallest logical next capability" note: trace
whether the existing, already-tested correction-learning retrieval
path (`correction_learning_input_retrieval.py`) and the existing
`CorrectionApplicationCandidate` chain can already be connected to
Core with only a small missing runtime connection — and, if so,
implement only that connection; if not, document the exact missing
foundation and leave the implementation unchanged.

## What was inspected

`core/core.py`, `correction_learning_input_retrieval.py`,
`correction_learning_exact_lookup_result.py`,
`correction_lookup_context.py`, `correction_lookup_selection.py`,
`correction_lookup_usability.py`, `correction_application_candidate.py`,
`correction_application_candidate_readiness.py`,
`language_understanding_result.py`, `language_intelligence_core.py`,
`response_generation_context.py`, `response_generation.py`,
`local_model_backend.py`, `language_learning_store.py`. Full findings:
`diagnostics/section2_correction_retrieval_application_audit_prompt563.py`.

## What was actually missing (and what wasn't)

**Not missing — confirmed working, including against real data:**

1. **Storage → retrieval.** Prompt 562's real Core write path
   (`_store_resolved_correction_learning`) writes under exactly
   `(language, ITEM_TYPE_CORRECTION, original_expression)`. The
   existing retrieval functions
   (`lookup_correction_learning_input_by_original_expression_with_result`,
   `retrieve_stored_correction_learning_input`) read that exact same
   identity. Verified end to end against a real `Core` instance: a
   RESOLVED correction processed through `Core.process_input()` was
   read back correctly by the existing retrieval function, with no
   code changes.
2. **Retrieval → `CorrectionApplicationCandidate`.** The full chain
   `lookup_correction_learning_input_by_original_expression_with_result()`
   → `build_correction_lookup_context()` →
   `select_unique_stored_correction()` →
   `build_correction_application_candidate()` was run against that
   same real data and produced a correct, valid candidate
   (`is_valid=True`, `original_expression="car"`,
   `corrected_expression_or_meaning="bus"`, `language="english"`).
   Also confirmed the "nothing found" path: with no stored
   correction, the same chain correctly ends in an invalid,
   non-fabricated candidate — no new logic was needed for either
   case.

**Still missing, and NOT closeable by a call alone:**

1. **No existing trigger for "look this expression up."** Prompt
   562's write-side call site had a ready-made trigger already sitting
   in Core — step 1e's existing
   `correction_understanding["status"] == CORRECTION_STATUS_RESOLVED`
   check. Nothing equivalent exists for the read side: there is no
   concept anywhere in the codebase today of "this expression, in
   this ordinary message, is one Core has a stored correction for; go
   look it up before replying." Inventing one is a new design
   decision, not a missing call between existing pieces — and Prompt
   563's own instructions are explicit that new confidence thresholds,
   automatic application of uncertain corrections, and fabricated
   candidates are all out of scope, which rules out guessing at this
   trigger casually.
2. **No field to hold the candidate on the object retrieval would
   need to attach it to.** `LanguageUnderstandingResult` (the object
   `Core` actually holds as `self.last_language_understanding`) has a
   `correction_lookup_context` parameter (Prompt 466) but **no
   `correction_application_candidate` parameter or attribute at all**
   — confirmed directly:
   `getattr(core.last_language_understanding, "correction_application_candidate", "<absent>")`
   returns `"<absent>"`, not `None`. Only `ResponseGenerationContext`,
   one stage further downstream, has that field. Adding it means a new
   constructor parameter on a shared, foundational class — a real
   (if small) contract change, not a call using only what already
   exists.
3. **No path for Core's own store instance to reach the code that
   builds the understanding object.** Core's real,
   SQLite-backed `LanguageLearningStore` (`self.language_learning`)
   is owned by `Core`. `LanguageIntelligenceCore.understand()` — the
   method that actually constructs the `LanguageUnderstandingResult` —
   has no store parameter and no other existing path to reach it
   today.

Given all three, this is the "would require a new subsystem or
architectural redesign" case Prompt 563 itself distinguishes from a
small connection. Per Prompt 563's explicit instructions, **no broad
change was made**; this audit documents the exact missing foundation
instead, and no project files outside the three listed below were
touched.

## Files changed

- `diagnostics/section2_correction_retrieval_application_audit_prompt563.py`
  (new — fixed, deterministic audit data; no dynamic introspection, no
  side effects)
- `app/src/main/python/tests/test_section2_correction_retrieval_application_audit_prompt563.py`
  (new — 14 focused regression tests; see below)
- `docs/section2_correction_retrieval_application_audit_prompt563.md`
  (this report)

No other file was modified. In particular, `core/core.py`,
`language_intelligence_core.py`, and `language_understanding_result.py`
are byte-for-byte unchanged from Prompt 562 — no call site, no new
constructor parameter, no new trigger condition was added, per this
prompt's own "do not build it" branch.

## Focused test results

`tests.test_section2_correction_retrieval_application_audit_prompt563`:
**14/14 pass.** Covers:

1. the audit's own output is well-formed, deterministic, and free of
   forbidden score/rank/"best"/"worst" language (6 tests, mirroring
   the Prompt 559/561 audit test convention)
2. a RESOLVED correction stored through Prompt 562's real Core write
   path is read back correctly by the existing retrieval function
3. the full retrieval → lookup-context → selection → candidate chain
   produces a correct, valid candidate from that same real data
4. with no stored correction, the same chain correctly produces an
   invalid, non-fabricated candidate (no `NOT_FOUND`/`AMBIGUOUS`
   shortcut invents data)
5. **the central finding**: even with a real stored correction
   available, `Core.process_input()` never computes or attaches a
   `CorrectionApplicationCandidate` — the attribute does not exist on
   `last_language_understanding` at all
6. ordinary conversation after a stored correction is completely
   unaffected (byte-identical reply to a `Core` instance with no
   stored correction at all)
7. two fresh `Core` instances given the same input produce the same
   stored, then retrieved, record (deterministic)

## Relevant existing test results

- `test_correction*.py`: 780/780 pass (766 + 14 new)
- `test_core*.py`: 99/99 pass
- `tests.test_section2_correction_learning_core_integration_prompt562`:
  21/21 pass (Prompt 562's integration re-confirmed unchanged)
- `tests.test_section2_correction_learning_storage_audit_prompt561`:
  unchanged, still passing

## Full-suite result

**10,942 tests, 0 failures, 0 errors** (Prompt 562 baseline: 10,928;
+14 new focused tests via this prompt, 0 regressions).

## Whether any existing behavior changed

No. No production file (`core/core.py`, anything under
`language_intelligence/`, `understanding/`, `learning/`) was modified.
The new diagnostics module is a fixed data snapshot with no
side effects; the new test file only reads existing behavior (using
isolated temporary SQLite databases per test, the same pattern
Prompt 562's own test file already uses) and asserts what it finds.

## Smallest concrete missing foundation for the next prompt

Before any call-site connection can be added: (1) an explicit, narrow,
deterministic decision for when a later message should trigger a
stored-correction lookup at all (a genuine design question, not
specified here); (2) one new `LanguageUnderstandingResult` constructor
parameter, `correction_application_candidate=None`, following the
exact existing convention `correction_lookup_context` already uses;
and (3) a way for `LanguageIntelligenceCore.understand()` (or a
Core-side step immediately after it returns, working from the
already-returned `LanguageUnderstandingResult` and Core's own
`self.language_learning` — the same posture Prompt 562's storage call
already uses) to perform the lookup and assign the result. No new
storage, database, retrieval mechanism, or `CorrectionApplicationCandidate`
logic is needed for any of this — every one of those pieces already
exists, already works, and was reconfirmed against real data by this
audit.

## Packaging verification

The complete project (601 files) was packaged into exactly 8 balanced
ZIP parts (`Project_Prompt563_Part1of8.zip` ... `Part8of8.zip`), with
`PROJECT_PARTS_MANIFEST_Prompt563.json` recording every file's path,
size, SHA-256 checksum, and part assignment.

Verification performed:

- All 8 ZIPs extracted into a clean reconstruction directory.
- File-set comparison (source vs. manifest vs. reconstruction): zero
  missing files, zero unexpected files, in every direction.
- Per-file SHA-256 comparison (source vs. reconstruction, and each
  against the manifest's recorded checksum): zero mismatches —
  byte-identical reconstruction confirmed programmatically.
- The new focused suite (14 tests) and the complete test suite were
  re-run from the reconstructed copy: 10,942 tests, 0 failures, 0
  errors — identical to the pre-packaging result.

No project file was modified for packaging purposes.
