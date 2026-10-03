# Section 2 Correction-Learning Storage/Retrieval Architecture Audit (Prompt 561)

Read-only audit. Structured, machine-checkable data lives in
`app/src/main/python/diagnostics/section2_correction_learning_storage_audit_prompt561.py`,
covered by
`app/src/main/python/tests/test_section2_correction_learning_storage_audit_prompt561.py`.
**No application behavior was changed to produce this audit** — no
storage system, database, or memory system was implemented,
duplicated, or modified. This is audit only, per Prompt 561's scope.

Roadmap position: Section 2 of 10 — Language Intelligence and Request
Understanding, current position Prompt 561.

## Files inspected

24 files: the full `correction_understanding` /
`correction_feedback_*` / `correction_learning_*` / `correction_lookup_*`
/ `correction_application_candidate*` family under
`language_intelligence/`, plus `language_learning_store.py`,
`memory/memory_system.py`, `core/core.py`,
`understanding/correction_detection.py`, and `understanding/engine.py`.
See the audit artifact's `files_inspected` list for the exact set.

## Headline finding

**The storage and retrieval layer Prompt 460's docs asked about
already exists, already works in isolation, and needs no new
architecture.** Core already owns exactly one real, SQLite-backed
`LanguageLearningStore` (`self.language_learning`,
`core/core.py`, Prompt 416). `correction_learning_input_storage.py`
(Prompt 461) and `_retrieval.py` (Prompts 462–463) already write to
and read from that exact store correctly. **The actual gap is a
missing call, not a missing capability**: nothing in `core/core.py` or
`understanding/` ever calls them with real data, because the one piece
of real data they need — a reconstructed `CorrectionUnderstandingResult`
object — is discarded one step upstream, inside
`DeterministicFallbackBackend._build_correction_understanding()`,
which flattens it to a plain dict via `.to_dict()` before Core ever
sees it.

## 1. Implemented and working

- SQLite-backed `LanguageLearningStore`, owned once by Core, backed by
  the project's one existing `MemorySystem` (`language_learning_items`
  table). No second database exists or is needed.
- `correction_learning_input_storage.py`'s
  `store_accepted_correction_learning_input()` — correct, tested,
  works when called directly with a real store.
- `correction_learning_input_retrieval.py`'s
  `retrieve_stored_correction_learning_input()` and
  `lookup_stored_correction_learning_input_by_original_expression()` —
  correct, tested, direct pass-throughs to `get_item()`/`find_items()`.
- The full read chain `CorrectionLearningExactLookupResult` ->
  `CorrectionLookupContext` -> `CorrectionSelectionResult` ->
  `CorrectionApplicationCandidate` — internally complete and
  self-consistent, each stage tested in isolation.

## 2. Implemented but not integrated

- The entire `correction_feedback_record` / `correction_learning_*`
  eligibility/handoff/adapter family: zero importers outside
  `language_intelligence/` and `tests/`.
- `correction_learning_input_storage.py` / `_retrieval.py` themselves:
  zero importers outside their own package and tests — Core's real
  store is never handed to them.
- The lookup/candidate family
  (`correction_learning_exact_lookup_result.py`,
  `correction_lookup_context.py`, `_selection.py`, `_usability.py`,
  `correction_application_candidate.py`, `_candidate_readiness.py`):
  zero Core-reachable callers.
  `response_generation_context.py`'s `correction_application_candidate`
  / `correction_lookup_context` transport fields are always `None` on
  a real call (reconfirms Prompt 559's finding).

## 3. Partially implemented

- **The correction-understanding object is discarded before Core sees
  it.** `build_correction_understanding()` returns a real
  `CorrectionUnderstandingResult` object (from
  `correction_understanding.py`), but
  `DeterministicFallbackBackend._build_correction_understanding()`
  immediately returns `correction.to_dict()`. Only that plain dict
  reaches Core (accessed via `["status"]` / `.get(...)` in
  `core.py`'s step 1e, added by Prompt 560). Every downstream function
  needs the original object, not the dict.
- The eligibility/handoff/storage chain is reachable only from a
  `CorrectionFeedbackRecord`, which is reachable only from the
  discarded object above — so the write path is code-complete but has
  never executed outside a test.

## 4. Missing

- Exactly one thing: **a call site**. No function in `core/core.py` or
  `understanding/` calls any correction-learning storage or retrieval
  function with Core's own store. Nothing else is missing — every
  function such a call site would use already exists and already has
  a passing test.

## 5. Duplicate or overlapping

- **Two classes named `CorrectionUnderstandingResult`.**
  `correction_understanding.py` defines one (Prompt 439, the one Core
  actually builds and flattens). `correction_understanding_result.py`
  (Prompt 441) imports that same class aliased as
  `CorrectionUnderstanding` and then defines its own, different class
  under the identical name in the same package. Only the import alias
  keeps `isinstance` checks correct.
- **Two write paths to the same `learn_item()` call.**
  `handoff_correction_learning_input_with_result()` (Prompt 458)
  already performs the real write (via
  `handoff_correction_learning_input()` -> `store.learn_item()`) and
  reports ACCEPTED/REJECTED/FAILED.
  `store_accepted_correction_learning_input()` (Prompt 461) then
  requires that same ACCEPTED result and the same `learning_input`,
  and calls `store.learn_item()` a **second** time for the identical
  data. Harmless (upsert by identity) but genuinely redundant — a
  correct integration uses exactly one of these two entry points, not
  both.

## 6. Integration gaps (the full lifecycle, traced)

```
USER CORRECTS SOMETHING
  -> correction detection                    CONNECTED (unchanged, Prompt 440)
  -> correction understanding                CONNECTED, but flattened to a dict
                                              here — the real object is discarded
  -> learning input                          NOT CONNECTED (nothing rebuilds the
                                              discarded object)
  -> storage                                 NOT CONNECTED (same reason; the call
                                              itself is fully implemented)
  -> retrieval                               NOT CONNECTED (same reason; fully
                                              implemented)
  -> correction application candidate        NOT CONNECTED (zero Core-reachable
                                              callers, independent of the storage gap)
  -> Core response/application                NOT CONNECTED (transport field exists,
                                              nothing assigns it)
```

## Can existing Memory/Knowledge storage safely support this without duplication?

**Yes.** Core already owns one `LanguageLearningStore` backed by the
project's one existing SQLite `MemorySystem`. The storage/retrieval
modules already use it correctly under the existing
`ITEM_TYPE_CORRECTION` item type. No new database, table, or memory
system is needed — only a real call site supplying Core's own store
instance and real data built from a real correction.

## Smallest implementation target for Prompt 562

Add one small, explicit call sequence reachable from Core's existing
step 1e (where `correction_understanding["status"] ==
CORRECTION_STATUS_RESOLVED` is already checked) that:

1. Reconstructs a `correction_understanding.CorrectionUnderstandingResult`
   from the dict Core already has — its `to_dict()` keys already match
   that class's constructor keyword arguments exactly, so this is a
   direct, lossless reconstruction, not new logic.
2. Passes it through the existing, already-tested chain:
   `map_correction_understanding_to_result()` ->
   `map_correction_understanding_result_to_feedback_record()` ->
   `convert_correction_feedback_to_learning_input()`.
3. Calls `handoff_correction_learning_input_with_result(learning_input,
   self.language_learning)` **exactly once** (never followed by
   `store_accepted_correction_learning_input()` for the same data —
   see the duplicate-write finding above), using Core's own real store.

No new module, class, or storage mechanism is required. Retrieval and
`CorrectionApplicationCandidate` wiring (the remaining two integration
gaps) are intentionally **out of** this smallest target — they depend
on a second, later message referencing an already-stored correction, a
distinct trigger from the one storage needs — and are left for a later
prompt.

## Test results

- New focused tests: **13/13 pass**
  (`tests.test_section2_correction_learning_storage_audit_prompt561`).
- Relevant existing tests: `test_correction*.py` 766/766,
  `test_verified_correction*.py` 180/180, `test_language*.py` 203/203,
  `test_response*.py` 331/331, `test_core*.py` 99/99 — all pass.
- Full suite: **10,907 tests, 0 failures, 0 errors** (up from the
  Prompt 560 baseline of 10,894; +13 new tests via this audit, 0
  regressions).

## Scope discipline

No storage system was implemented, no database was created, no memory
system was created or duplicated, no SQLite infrastructure was
duplicated, no new validator chain was added, the Prompt 541–556
diagnostic chain was not touched, Core was not redesigned, no LLM or
external AI API was added, no internet/cloud service was added, no
automatic self-modification was added, and no unrelated learning
system was modified. Prompt 562's solution is not implemented here.
