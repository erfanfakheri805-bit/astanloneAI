# Section 2: Carry an Existing CorrectionApplicationCandidate Through
# Language Understanding (Prompt 564)

Roadmap position: Section 2 of 10 — Language Intelligence and Request
Understanding, current position Prompt 564 (approximate range
559–630).

## Objective

Per Prompt 563's own "smallest concrete missing foundation" note
(item 2): add the smallest safe, backward-compatible data path for
carrying an existing `CorrectionApplicationCandidate`
(`correction_application_candidate.py`, Prompt 470) through the
existing `LanguageUnderstandingResult`
(`language_intelligence/language_understanding_result.py`) — nothing
else. No automatic retrieval, no automatic application, no new
trigger, no Core/database ownership change.

## What was inspected

- `language_understanding_result.py` — the target class and its
  existing `correction_lookup_context` field (Prompt 466), which is
  the established, directly analogous precedent for this exact kind
  of change (an optional constructor parameter carrying an already-
  built, purely-informational structure, default `None`, exposed in
  `to_dict()` via the existing `hasattr(..., "to_dict")` convention).
- `correction_application_candidate.py` (Prompt 470) — the existing
  `CorrectionApplicationCandidate` type and
  `build_correction_application_candidate()`; confirmed unchanged and
  reused as-is, no duplicate/parallel candidate representation created.
- `language_intelligence_core.py` — `LanguageIntelligenceCore.
  understand()`; confirmed it constructs no
  `CorrectionApplicationCandidate` and needed no change.
- `response_generation_context.py` — `ResponseGenerationContext`
  already carries a `correction_application_candidate` field (Prompt
  471); its constructor-parameter/attribute/`to_dict()` shape was used
  as the second confirming precedent for this exact field name and
  handling.
- `core/core.py` — confirmed it never constructs, reads, or assigns a
  `CorrectionApplicationCandidate`, and needed no change.
- The Prompt 563 audit report/tests
  (`docs/section2_correction_retrieval_application_audit_prompt563.md`,
  `tests/test_section2_correction_retrieval_application_audit_
  prompt563.py`) — the direct source of this prompt's scope.

## What was changed

**`language_understanding_result.py` only.** One new, optional,
keyword-only constructor parameter,
`correction_application_candidate=None`, added after the existing
`correction_lookup_context` parameter (last positional-compatible
slot, matching where `correction_lookup_context` itself was added in
Prompt 466). Stored as `self.correction_application_candidate`.
Exposed in `to_dict()` using the exact existing
`hasattr(value, "to_dict")` pattern already used for
`correction_lookup_context` (and, in `ResponseGenerationContext`, for
`correction_application_candidate` itself) — so a
`CorrectionApplicationCandidate` object, a plain dict, or `None` are
all handled correctly with no new branching logic.

**Candidate type used:** the existing
`language_intelligence.correction_application_candidate.
CorrectionApplicationCandidate` (Prompt 470), unmodified. No new class,
no parallel/duplicate representation.

## How backward compatibility was preserved

- The new parameter is keyword-only-by-convention (declared after
  every existing parameter, all of which are either positional or
  already keyword-with-default) and defaults to `None` — every
  existing positional call site (`LanguageUnderstandingResult(text,
  lang, ..., False, False)`) is untouched and produces
  `correction_application_candidate is None`, exactly the same as
  before this field existed.
- `to_dict()` gained one new key; no existing key was renamed, removed,
  or reordered.
- No backend (`deterministic_fallback_backend.py`, the local-model
  backend) was changed — neither ever sets this field, confirmed by a
  focused test running the real `DeterministicFallbackBackend` against
  several inputs.
- `LanguageIntelligenceCore.understand()` and `core/core.py` are
  byte-for-byte unchanged — confirmed by inspection and by the
  Prompt 563 regression test (updated, see below) still passing.

## Whether a new interface/adapter was necessary

No. The existing `correction_lookup_context` field on the same class,
and the existing `correction_application_candidate` field on
`ResponseGenerationContext`, are both established, working precedents
for "an optional constructor parameter carries an already-built,
purely-informational value object, default `None`, exposed via
`to_dict()`'s `hasattr` convention." Reusing that exact convention
needed no new interface, adapter, protocol, or base class.

## Whether Core/database ownership remained isolated

Yes. This change touches only a plain data-holder class
(`LanguageUnderstandingResult`). It does not give the class access to
`Core`'s `LanguageLearningStore`, does not create a global store or
singleton, does not reach into Core internals, and does not implement
a retrieval trigger. Per the audit's own remaining two "missing
foundation" items (an explicit trigger decision, and a way for
`LanguageIntelligenceCore.understand()` or a Core-side step to reach
`self.language_learning` and perform a lookup) — both are explicitly
out of scope for this prompt and remain unimplemented.

## Files changed

- `app/src/main/python/language_intelligence/language_understanding_result.py`
  (modified — one new constructor parameter/attribute, one new
  `to_dict()` key, one new docstring section)
- `app/src/main/python/tests/test_correction_application_candidate_exposure.py`
  (new — 24 focused regression tests; see below)
- `app/src/main/python/tests/test_section2_correction_retrieval_application_audit_prompt563.py`
  (modified — one assertion in
  `test_candidate_chain_is_still_never_triggered_automatically`
  updated from "attribute absent" to "attribute present and `None`",
  since Prompt 564 is exactly the change that fills in the missing
  field the Prompt 563 audit documented; the test's actual guarantee —
  that `Core.process_input()` never computes or attaches a candidate
  on its own — is unchanged and still verified)
- `docs/section2_correction_application_candidate_data_path_prompt564.md`
  (this report)

No other file was modified. `core/core.py`, `language_intelligence_core.py`,
`correction_application_candidate.py`, `response_generation_context.py`,
and every backend file are byte-for-byte unchanged from Prompt 563.

## Focused test results

`tests.test_correction_application_candidate_exposure`: **24/24 pass.**
Covers, matching the prompt's 8 required regression areas:

1. Existing `LanguageUnderstandingResult` construction still works
   without a candidate (3 tests)
2. A result can safely carry an existing `CorrectionApplicationCandidate`
   — valid and invalid candidates alike (3 tests)
3. The candidate is preserved through the result unchanged, including
   all seven fields and non-mutation after attach (3 tests)
4. No correction candidate is automatically retrieved merely because
   the field now exists — real backend never populates it, plain
   construction performs no lookup (2 tests)
5. Existing correction acknowledgement behavior remains unchanged (3
   tests)
6. Existing language-understanding fields/behavior remain unaffected
   (2 tests)
7. Identical input/state remains deterministic (2 tests)
8. No Core database/store is accessed merely by constructing a result
   (1 test)

Plus 5 additional backward-compatibility tests (positional
construction, coexistence with `correction_lookup_context`,
ambiguous/not-found/failed outcomes never fabricating a valid
candidate, etc.).

## Relevant existing test results

- `test_correction*.py`: **790/790 pass** (766 + 24 new)
- `test_language*.py`: **203/203 pass**
- `test_core*.py`: **99/99 pass**
- `tests.test_section2_correction_retrieval_application_audit_prompt563`:
  **14/14 pass** (one assertion updated as described above; the
  test's core guarantee re-confirmed, not weakened)

## Full-suite result

**10,966 tests, 0 failures, 0 errors** (Prompt 563 baseline: 10,942;
+24 new focused tests via this prompt, 0 regressions).

## Whether any existing runtime behavior changed

No. `deterministic_fallback_backend.py`, the local-model backend,
`language_intelligence_core.py`, and `core/core.py` are unchanged.
Every existing caller of `LanguageUnderstandingResult` that does not
pass `correction_application_candidate` continues to receive exactly
the same object it always did, with one additional attribute that is
always `None` and one additional, always-`None`-by-default key in
`to_dict()`. No normal conversation response, correction
acknowledgement, AEL request, Memory/Knowledge request, reasoning,
planning, execution, or Agent Loop behavior changed.

## Smallest logical next step for Prompt 565 (not implemented here)

Per Prompt 563's audit, two pieces of the missing foundation remain,
and this prompt filled in only the third (this field). The smallest
next step is a single, narrow, explicit, deterministic trigger
condition for "attempt a stored-correction lookup for this message" —
scoped only to *deciding when*, still not wiring the lookup itself
into `Core` or `LanguageIntelligenceCore.understand()`, and still not
touching `self.language_learning` from the language-understanding
layer. The store-access wiring itself (giving `Core`, or a Core-side
step immediately after `understand()` returns, a path to call the
already-working retrieval → lookup-context → selection → candidate
chain and assign the result to this new field) should remain a
separate, later, explicitly-scoped prompt, exactly as Prompt 563's own
audit already recommended.

## Scope confirmation

Not implemented, per this prompt's explicit restriction: automatic
correction retrieval, correction application, new correction storage,
new databases, new memory systems, external AI APIs, LLM integration,
internet/cloud services, automatic self-modification, voice,
multimodal systems, programming/game creation, validator-of-validator
chains. `LanguageUnderstandingResult` was given no store ownership, no
global store, and no hidden singleton state. The duplicate structures
identified by Prompt 561 were not touched.

## Packaging

The complete project was packaged into exactly 8 balanced ZIP parts
(`Project_Prompt564_Part1of8.zip` ... `Part8of8.zip`), with
`PROJECT_PARTS_MANIFEST_Prompt564.json` recording every file's path,
size, SHA-256 checksum, and part assignment. All 8 ZIPs were extracted
into a clean reconstruction directory; file-set comparison found zero
missing and zero unexpected files, and per-file SHA-256 comparison
against both the source tree and the manifest found zero mismatches —
byte-identical reconstruction. The focused suite (24 tests) and the
complete test suite (10,966 tests) were re-run from the reconstructed
copy with identical results.
