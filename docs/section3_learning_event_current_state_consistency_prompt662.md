# Prompt 662 — Learning Event and Current Knowledge Consistency

**Result: audit only. No genuine production defect found; no production files changed.**

Authoritative rule (unchanged): current `knowledge` / `relationships` rows are the source of truth;
`learning_events` are historical records ordered by `learning_events.id` (never by timestamp).

## Verified (tests/test_learning_event_current_state_consistency_prompt662.py)
- **Creation:** teach, stub -> taught (v1 -> v2, `stub` -> `active`), natural-language relate (stub endpoints v1, one `relate` event).
- **Update:** each real change (description, confidence, source_text, source) = +1 version and one `teach` event; identical repeats write nothing; `correct` resolves case-insensitively, no-ops silently, never creates; earlier events are never rewritten.
- **Relationships:** create / update / exact repeat / None-preserving repeat; stub endpoints keep version 1 through relationship updates; invalid names/relation leave no stub, row or event.
- **Language:** `learn_item` repeats are real updates (version+1, event) by design; omitted source logs persisted source; omitted context logs `detail=None`; targets use the canonical language (`english:word:Run`). Relationship learned/updated events; failures leave no artifacts.
- **Provenance:** event source = persisted source; correct-event chain ends at the current description.
- **Version:** current version = number of applicable knowledge mutations; no-ops and rolled-back operations leave no gap. Relationship/language/stub operations have their own version semantics and are not equated with events.
- **Ordering:** equal timestamps still order by id; `recent_learning_events` is id-deterministic; rolled-back ops reuse no ids.
- **Atomicity:** event-insert failure, mutation failure, and failure between stub creation and edge insert all restore the prior database state; NL learning reports the error and leaves state unchanged.
- **Reopen / cross-source:** state and history byte-identical across repeated close/reopen (no reload events); NL -> teach -> correct -> re-teach -> NL repeat and relate -> teach endpoint -> correct -> relate update keep current state authoritative and history historical.

## Remaining intentional limitations (unchanged, not "fixed")
1. Stub concepts created by relate/NL have no event of their own.
2. teach/correct events carry no confidence/source_text/learning_method/status/kind values; status- or confidence-only changes log an event with unchanged description.
3. relate events carry no confidence/source_text/learning_method values.
4. Language events record only `source_context` as detail (no meaning/examples diff; None context logs None).
5. Direct `KnowledgeSystem.learn()/relate()` calls below LearningSystem write no events.
6. Events are not a snapshot/replay system; current tables are never derived from them.
