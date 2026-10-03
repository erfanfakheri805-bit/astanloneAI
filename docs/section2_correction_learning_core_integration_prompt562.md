# Section 2: Core -> Correction-Learning Storage Integration (Prompt 562)

Roadmap position: Section 2 of 10 — Language Intelligence and Request
Understanding, current position Prompt 562 (approximate range
559–630).

## Objective

Connect the EXISTING correction-learning storage handoff (audited by
Prompt 561 and found fully implemented, fully tested in isolation, and
unreachable) to Core's existing correction path. No new storage
system, database, or memory system; no redesign of the
correction-learning architecture.

## Exact Core location changed

`app/src/main/python/core/core.py`:

- `Core.__init__` — one new attribute, `self.last_correction_learning_
  handoff_result = None`, following the exact scope/lifecycle
  convention already used by `self.last_language_understanding` /
  `self.last_language_response`.
- `Core._handle_conversation`, step **1e** (Prompt 560's existing
  `correction_understanding["status"] == CORRECTION_STATUS_RESOLVED`
  branch) — one new call, `self._store_resolved_correction_learning(
  correction_understanding)`, made immediately before the existing
  `return self._format_correction_acknowledged_reply(...)` in that
  same branch. The condition itself is unchanged; AMBIGUOUS,
  UNRESOLVED, and `None` still fall through to step 2 exactly as
  before.
- One new method, `Core._store_resolved_correction_learning()`, added
  next to `Core._format_correction_acknowledged_reply` (the existing
  "one place shapes/handles this" convention).

## Exact existing adapter/factory used

In this exact, unmodified order (Prompt 561's own recommended chain):

1. `language_intelligence.correction_understanding.
   CorrectionUnderstandingResult(**correction_understanding)` — the
   Prompt 439 class, used directly as its own reconstruction
   "factory" (see reconstruction section below).
2. `language_intelligence.correction_understanding_result.
   map_correction_understanding_to_result()` (Prompt 442)
3. `language_intelligence.correction_feedback_record.
   map_correction_understanding_result_to_feedback_record()`
   (Prompt 449)
4. `language_intelligence.correction_feedback_learning_input_adapter.
   convert_correction_feedback_to_learning_input()` (Prompt 455)

## Exact existing storage handoff used

`language_intelligence.correction_learning_handoff_result.
handoff_correction_learning_input_with_result(learning_input,
self.language_learning)` (Prompt 458) — called exactly once, using
Core's own real, SQLite-backed `LanguageLearningStore` instance
(`self.language_learning`, Prompt 416). This is the SAME store every
other Core learning path (`learn_item`/`get_item` wrappers, the
expression-variation matcher, the pattern teacher, ...) already uses;
no second store instance is created.

`store_accepted_correction_learning_input()` (Prompt 461, the second
of the two duplicate write paths the Prompt 561 audit identified) is
deliberately **not** called anywhere in this integration — see
"Duplicate storage" below.

## How `CorrectionUnderstandingResult` is reconstructed

The dict Core already has at step 1e is exactly
`correction_understanding.CorrectionUnderstandingResult.to_dict()`'s
output (produced upstream by `DeterministicFallbackBackend.
_build_correction_understanding()`, unchanged by this prompt). That
`to_dict()`'s keys — `status`, `original_expression`,
`corrected_expression`, `corrected_meaning`, `language`, `locale`,
`source_text`, `confidence` — are exactly that same class's own
`__init__` keyword arguments, so:

```python
reconstructed = CorrectionUnderstandingResult(**correction_understanding)
```

is a direct, lossless reconstruction — every field round-trips
unchanged, nothing is guessed, defaulted beyond what the class's own
constructor already defaults for a caller who omits it (it never does
here, since every key is present), and no new logic or second
correction-understanding class is introduced.

## How exactly-once behavior is guaranteed

- Step 1e's `if correction_understanding is not None and ... ==
  CORRECTION_STATUS_RESOLVED:` branch runs at most once per
  `_handle_conversation()` call (it is a single `if`, not a loop), and
  `_handle_conversation()` itself is called at most once per
  `process_input()` call (confirmed: exactly one call site in
  `core.py`).
- `_store_resolved_correction_learning()` calls
  `handoff_correction_learning_input_with_result()` at most once per
  invocation — a single, non-looping call — and only when
  `convert_correction_feedback_to_learning_input()` returned something
  other than `None` (i.e. only for a genuinely valid, RESOLVED
  correction).
- `store_accepted_correction_learning_input()` (the second, redundant
  `learn_item()` write path identified by Prompt 561) is never called
  from this integration, so the same correction is never written
  twice by two different entry points for the same message.
- Two separate messages that happen to be the same correction call
  `learn_item()` once per message (two calls total across two
  `process_input()` calls) — this is `learn_item()`'s own existing,
  unchanged upsert contract (same `(language, item_type,
  normalized_key)` updates the same row rather than duplicating it),
  not new deduplication logic added here. Covered by
  `test_repeated_processing_of_the_same_correction_follows_existing_upsert_contract`.

## Files changed

- `app/src/main/python/core/core.py` (integration; see above)
- `app/src/main/python/tests/test_section2_correction_learning_core_integration_prompt562.py`
  (new, 21 focused regression tests)
- `docs/section2_correction_learning_core_integration_prompt562.md`
  (this report)

No other file was modified. In particular, none of the following were
touched: the Prompt 541–556 validator chain, unrelated Memory/Learning
systems, SQLite architecture beyond the existing
`LanguageLearningStore` call already made, Language Intelligence
architecture, AEL, Agent Loop, Planning, Execution, external AI/API
systems, internet/cloud services, automatic self-modification, voice,
multimodal systems, or programming/game-generation systems. The two
duplicate/overlapping structures Prompt 561 identified (the two
`CorrectionUnderstandingResult` classes; the two `learn_item()` write
paths) were **not** cleaned up or redesigned — the second write path
is simply never called by this integration, per the assignment's
explicit scope.

## Focused test results

`tests.test_section2_correction_learning_core_integration_prompt562`:
**21/21 pass.** Covers:

1. a valid correction reaches the existing storage handoff (ACCEPTED
   result; item actually present via `get_item()`)
2. the reconstructed `CorrectionUnderstandingResult` preserves
   `key`/`meaning`/`confidence`/`source_context`, on both the
   corrected-expression and corrected-meaning sides
3. exactly one `learn_item()` call for one eligible correction, and
   the existing upsert contract for repeated identical corrections
4. non-eligible input (ordinary statement/question, AEL, goal-oriented,
   a phrase not matching the fixed correction marker) — zero
   `learn_item()` calls
5. AMBIGUOUS / UNRESOLVED / NOT_CORRECTION status — zero calls, no
   record stored, via direct calls to
   `_store_resolved_correction_learning()`; plus a full-pipeline check
   that a correction-shaped-but-incomplete message never even reaches
   that method
6. the existing `[CORRECTION ACKNOWLEDGED]` reply text is unchanged
7. existing Core request behavior (ordinary learning, reasoning,
   planning, memory/turn logging) is unchanged after a correction turn
8. deterministic: two fresh `Core` instances given the same input
   produce the same handoff outcome and the same stored item

## Relevant existing test results

- `test_correction*.py`: 766/766 pass
- `test_language*.py`: 203/203 pass
- `test_core*.py`: 99/99 pass
- `test_verified_correction*.py`: 180/180 pass
- `test_response*.py`: 331/331 pass
- `tests.test_language_intelligence_core_integration_prompt560`:
  16/16 pass (unchanged acknowledgement behavior re-confirmed)

## Full-suite result

**10,928 tests, 0 failures, 0 errors** (Prompt 561 baseline: 10,907;
+21 new focused tests via this prompt, 0 regressions).

## Whether any existing behavior changed

No. The `[CORRECTION ACKNOWLEDGED]` reply text, its trigger condition,
ordinary conversation/learning, AEL, goal-oriented requests, and
Memory/Reasoning/Planning/Execution routing are all unchanged — the
new call is additive (a storage side effect plus one new inspectable
attribute) and happens after the existing branch condition is already
true, immediately before the existing, unmodified reply is returned.

## Whether any duplicate storage occurred

No. Only `handoff_correction_learning_input_with_result()` is called,
exactly once per eligible correction;
`store_accepted_correction_learning_input()` (the second existing
write path) is never invoked by this integration, so `learn_item()` is
called exactly once per `process_input()` call that carries an
eligible, RESOLVED correction.

## Packaging verification

The complete project (598 files, 11,448,428 bytes) was packaged into
exactly 8 balanced ZIP parts (`Project_Prompt562_Part1of8.zip` ...
`Part8of8.zip`, ~1.3–1.5 MB each), with `PROJECT_PARTS_MANIFEST_
Prompt562.json` recording every file's path, size, SHA-256 checksum,
and part assignment.

Verification performed:

- All 8 ZIPs extracted into a clean reconstruction directory.
- File-set comparison (source vs. manifest vs. reconstruction): **zero
  missing files, zero unexpected files** in every direction.
- Per-file SHA-256 comparison (source vs. reconstruction, and each
  against the manifest's recorded checksum): **zero mismatches** —
  **byte-identical reconstruction** confirmed programmatically.
- The new focused suite (21 tests) and the complete test suite were
  re-run from the reconstructed copy: **10,928 tests, 0 failures, 0
  errors** — identical to the pre-packaging result.

No project file was modified for packaging purposes.

## Smallest logical next capability for Prompt 563 (not implemented here)

Per the Prompt 561 audit's own integration-gap list, the two remaining
disconnected stages are **retrieval** and **`CorrectionApplicationCandidate`
wiring** — both already fully implemented and tested in isolation, both
still zero-Core-reachable. The smallest of the two: connect the
already-tested `retrieve_stored_correction_learning_input()` /
`lookup_stored_correction_learning_input_by_original_expression()`
(`correction_learning_input_retrieval.py`) to a real Core call site —
e.g. looking up a previously stored correction for an expression Core
is about to use in a reply — using the same real
`self.language_learning` store this prompt already connected for
writes. This is intentionally **not implemented** in Prompt 562.
