# Prompt 654 - Learning-history replay / reconstruction integrity (Section 3)

Result: audit only. No genuine defect found; **no production changes** and no production replay code.
Tests: `tests/test_learning_history_replay_integrity_prompt654.py` (17 tests). The replay helper lives in that file only.

Replaying `learning_events` in id order rebuilds description, version, source and relationship edges for every event-visible record, and the result equals the live rows.

- **Ordering:** ids are the only ordering. Equal or manually descending timestamps change nothing. A rolled-back write leaves no id gap and no event.
- **Version:** the persisted version equals the number of teach/correct events for that record, plus 1 if a relate() or NL stub created it. Stub creation has no event of its own.
- **No-ops, failures, rejections, ambiguity:** these write no events and leave no state. Reopening the database keeps the same history and state.
- **Correct events:** the detail is `repr(old) -> repr(new)`. Replay checks the old value against replayed state, so a description that contains ` -> ` does not break it. The event source is the persisted source, never None.
- **Relate events:** they never change endpoint versions or descriptions. Event type, not detail text, tells them apart from teach events.
- **`LearningSystem.relate()`:** it defaults `source="ael"`, like `teach()`. Omitting `source` is therefore a real source change (one event), not a no-op. Existing contract, unchanged.
- **Language stores:** they keep their own semantics. Every repeat is a real update, with one event and a version bump. They never enter knowledge replay.
- **Live rows are authoritative:** the newest teach event can be stale after a later correct(). All current readers return the live row.

Intentionally NOT reconstructable (no schema was added):

- **L1:** stub records have no event of their own.
- **L2:** teach/correct events carry no confidence, source_text, learning_method, status or kind.
- **L3:** relate events carry no confidence, source_text or learning_method. A metadata-only refresh looks identical in the event.
- **L4:** direct `KnowledgeSystem.learn()/relate()` calls write no events.
- **L5:** language events carry only source_context, with no meaning/examples diff.
