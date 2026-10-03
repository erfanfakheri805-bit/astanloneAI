# Prompt 560 — Language Intelligence → Core Integration

Section 2, first real runtime integration (audit-only Prompt 559 → this
implementation prompt).

## Component integrated

`language_intelligence/correction_understanding.py`'s
`build_correction_understanding()` output — specifically the
`correction_understanding` field already attached to every
`LanguageUnderstandingResult` by
`DeterministicFallbackBackend._build_correction_understanding()` (Prompt
440), itself fed by `understanding/correction_detection.py`'s
`detect_explicit_correction()` (Prompt 440 again — all pre-existing,
unchanged).

## Why this component, not the audit's original suggestion

Prompt 559's audit named the full correction-application pipeline
(`correction_application_candidate.py` and its storage-backed
`CorrectionSelectionResult` inputs) as the smallest safe integration
point. Re-reading that code at implementation time
(`correction_application_candidate.build_correction_application_candidate`)
showed it requires a `CorrectionSelectionResult`, which itself requires a
`CorrectionLookupContext` built from a stored-correction lookup
(`correction_learning_input_retrieval.py` /
`correction_learning_input_storage.py`) — a whole separate,
not-yet-wired storage subsystem. Wiring that in would mean adding real
persistence and a lookup path in one prompt, which exceeds "smallest
safe integration" and risks becoming new architecture rather than
connecting existing architecture.

A project-wide grep at implementation time found something smaller and
squarely in scope: `correction_understanding` itself — already computed
on every message, fully implemented, fully tested — had **zero readers**
anywhere in the Core-reachable code (`response_planning.py`,
`response_generation.py`, `response_generation_context.py`,
`conversation_response.py`, `learned_response_decision.py`,
`language_intelligence_core.py`, `core/core.py` — none referenced it).
This is a strictly smaller, self-contained, storage-free capability that
still matches Prompt 559's category exactly: genuinely implemented,
suitable for runtime use, not reached by the normal Core path.

## Previous call path

```
Core._handle_conversation
  step 1c: self.last_language_understanding = language_intelligence.understand(...)
           (correction_understanding computed and attached here)
  step 1d: language_intelligence.generate_response(...) (always STATUS_DEFERRED today)
  step 2:  learn_from_text(...)   <- every message, including "not X, I mean Y", landed here
  step 3:  reasoning.reason(...)
  step 4:  concept lookup fallback
  step 5:  _construct_fallback_reply(...)  <- "not dgo, I mean dog." ended up here
```

Confirmed before this change: `Core().process_input("not dgo, I mean dog.")`
returned the generic
`"I don't have enough information to answer that yet. You can teach me using AEL..."`
fallback, even though `last_language_understanding.correction_understanding`
already held `{"status": "RESOLVED", "original_expression": "dgo",
"corrected_expression": "dog", ...}` at that point.

## New call path

```
Core._handle_conversation
  step 1c: self.last_language_understanding = language_intelligence.understand(...)
  step 1d: language_intelligence.generate_response(...) (unchanged, still deferred)
  step 1e: (NEW) if last_language_understanding.correction_understanding
                 and its status == STATUS_RESOLVED:
               return self._format_correction_acknowledged_reply(...)
  step 2:  learn_from_text(...)   <- unchanged for every other message
  step 3:  reasoning.reason(...)
  step 4:  concept lookup fallback
  step 5:  _construct_fallback_reply(...)
```

`Core().process_input("not dgo, I mean dog.")` now returns:

```
[CORRECTION ACKNOWLEDGED]
original_expression: dgo
corrected_expression: dog
language: english
```

## Behavior now enabled

An explicit, single fixed marker — `"not <original>, i mean <corrected>"`
/ `"not <original>, i meant <corrected>"` — is acknowledged with a
structured reply reflecting exactly what
`build_correction_understanding()` already resolved: `original_expression`,
`corrected_expression` (or `corrected_meaning`, whichever is present),
and `language`, when present. Nothing is invented: fields absent from the
result are simply omitted from the reply, never guessed.

## Fallback behavior

- `correction_understanding is None` (no marker detected) → step 1e does
  nothing; falls through to step 2 exactly as before.
- `status == AMBIGUOUS` or `UNRESOLVED` → step 1e does nothing; falls
  through exactly as before. No partial or guessed acknowledgment is
  ever produced for these.
- Nothing is stored, learned, looked up, or "applied" anywhere else —
  this integration only makes an already-built, already-structured
  result reach a decision point for the first time; it does not add new
  detection, storage, or correction-application logic.

## Backward compatibility confirmed

- AEL commands (`TEACH ...`) — unaffected; they return before
  `_handle_conversation` even runs.
- Goal-oriented requests (`"I want to ..."`) — unaffected; they also
  return before `_handle_conversation` runs, so `last_language_understanding`
  stays `None` for them, exactly as before.
- Ordinary statements/questions — unaffected; `correction_understanding`
  is `None` for these, so step 1e is a no-op and steps 2–5 run exactly as
  before.
- Memory/context logging (`memory.log_message`, `context.add_turn`) —
  unchanged; they still happen exactly once, after `_handle_conversation`
  returns, for every reply including the new acknowledgment reply.
- Reasoning, planning/goal creation, and memory logging were verified to
  still work correctly on requests that came *after* a
  correction-acknowledged turn (see the focused tests).

## Files changed

- `core/core.py` — one new import
  (`STATUS_RESOLVED as CORRECTION_STATUS_RESOLVED` from
  `language_intelligence.correction_understanding`), one new step ("1e")
  inside `_handle_conversation`, one new private method
  `_format_correction_acknowledged_reply`. No other method changed.
- `tests/test_language_intelligence_core_integration_prompt560.py` — new,
  16 focused tests.
- `docs/section2_language_intelligence_prompt560_integration.md` — this
  file.

Nothing in `language_intelligence/`, `understanding/`, or the Section 1
validator chain (`learning/learned_knowledge_statistics.py`) was
modified.

## Test results

- New focused tests: **16/16 pass**
  (`tests.test_language_intelligence_core_integration_prompt560`),
  covering all 6 required scenarios (reaches Language Intelligence,
  understanding available to Core's decision path, AEL/structured
  requests unchanged, ambiguous/unsupported input falls back safely,
  Memory/Reasoning/Planning/Execution routing not bypassed,
  deterministic for identical input/state).
- Relevant existing tests: `test_core*.py` 99/99,
  `test_language*.py` 203/203, `test_correction_understanding*.py`
  150/150 — all pass.
- Full suite: **10,894 tests, 0 failures, 0 errors** (up from the
  Prompt 558 baseline of 10,868; +16 new tests via Prompt 559's own
  additions plus this prompt's, 0 regressions).
- Determinism: confirmed directly — the same input on two independent
  fresh `Core` instances (separate temp databases) produces byte-identical
  replies, and the same `Core` instance produces the same reply for the
  same message sent twice.

## Next Section 2 target (not implemented in this prompt)

Per Prompt 559's audit and this prompt's own findings, the next
candidate is wiring a real stored-correction lookup: connect
`correction_learning_input_storage.py` / `_retrieval.py` to an actual
store (there is currently none configured for corrections specifically),
so that `correction_lookup_selection.select_unique_stored_correction()`
→ `correction_application_candidate.build_correction_application_candidate()`
can produce a real, non-empty `CorrectionApplicationCandidate` for
`response_generation_context.py`'s existing transport field — the
storage-dependent integration this prompt intentionally deferred.

## Scope discipline

No new language-intelligence architecture, no rebuilt components, no new
validator-of-validator chain, no external AI APIs, no network/cloud
access, no automatic self-modification, and no changes to the Prompt
541–556 validator chain. Only one existing, already-computed field was
connected to one existing decision point.
