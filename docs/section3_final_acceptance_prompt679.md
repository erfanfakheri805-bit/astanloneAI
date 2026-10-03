# Prompt 679 - Section 3 final acceptance, regression lock & boundary verification

## 1. Final acceptance result
**PASSED.** Acceptance areas A-I were verified through the real production APIs (`Core`, `LearningSystem`,
`KnowledgeSystem`, `ReasoningEngine`, AEL via `Core.process_input`, language understanding / meaning resolution,
learned-knowledge context, conversational correction). No genuine defect was found, so **no production file was
changed**. `tests/test_section3_final_acceptance_prompt679.py` locks the cross-boundary invariants.

## 2. Current-state ownership
`KnowledgeSystem` rows (`knowledge`, `relationships`) are the only source of current truth. Current consumers
(`resolve_current_name`, `current_relationships_for`, learned-knowledge context, Core conversational fallback,
`ReasoningEngine`, language meaning resolution) resolve that state at call time; nothing caches a copy (a direct row
edit is visible to every consumer on the next call). `LearningSystem` owns controlled mutation workflows and the
`learning_events` history. Events are audit records: they keep old descriptions, but the last event type or its detail
never decides current status or content.

## 3. Knowledge / Learning / Language boundaries
- Language items and language relationships are references/history. They carry no knowledge status, never write
  knowledge rows or knowledge events, and never revive an inactive concept (an item's *own* language meaning is language
  state and does not surface the concept's description).
- A language link to a concept requires the exact stored concept name; a case variant is never substituted.
- Status changes never rewrite language rows.

## 4. Raw vs current APIs
| Kind | APIs |
|---|---|
| Current | `KnowledgeSystem.resolve_current_name`, `find_current_by_name_case_insensitive`, `current_relationships_for`; `select_learned_knowledge`; Core conversational fallback / `_find_best_known_concept`; `ReasoningEngine.reason`; `Core.understand_language` (meaning resolution current path) |
| Raw / historical (may expose inactive) | `get`, `resolve_name`, `find_by_name_case_insensitive`, `all`, `search`, `relationships_for`; `Core.resolve_language_meaning` (`resolve()`); AEL `ASK` / `LearningSystem.recall`; `learning_events` / `recent_learning_events` |
| Mutating | `LearningSystem.teach`, `correct`, `set_status`, `relate`; `Core.learn_from_text` (NL learning); conversational correction; AEL `TEACH` / `RELATE` |

## 5. Inactive behavior
An inactive record stops influencing retrieval, learned context, language meaning, Core fallback and reasoning. Raw
APIs, AEL ASK/recall and the language `resolve()` still expose it. Only explicit `teach`, `correct`, `set_status(active)`
and AEL `TEACH` reactivate. NL learning, implicit conversational correction and every read leave it inactive and write no
status event.

## 6. Ambiguity behavior
Exact-case identity wins; a unique case-insensitive match resolves; several current variants are `ambiguous` and no
consumer picks one (retrieval, context `AMBIGUOUS`, reasoning `unknown`, Core answers nothing; `correct`/`set_status`
raise and write nothing). Inactive variants never take part in current resolution (raw `resolve_name` still reports
ambiguity). Behavior is identical after close/reopen.

## 7. Relationship behavior
Rows to/from inactive endpoints stay stored (raw APIs unchanged). `current_relationships_for` and reasoning (direct and
transitive) ignore them, reactivation restores the effect immediately, and nothing stale survives close/reopen.

## 8. Language-intelligence behavior
Meaning resolution (current path) excludes inactive concept endpoints, keeps exact concept identity, and is restored by
each explicit reactivation path. Language learning records are not knowledge status records.

## 9. Event and provenance behavior
Exactly one event per real mutation: `teach`, `correct`, `status`, `relate`. Target = persisted stored name; source =
persisted source (`correct`/`set_status`/`relate` keep the stored value for `None`; `teach` replaces source and logs its
argument, which equals the persisted value - documented in Prompt 649). `source_text` / `learning_method` are stored on the
knowledge row (events have no such columns) and keep the stored value when `None`. True no-ops, reads, ambiguous and failed
operations write no event.

## 10. Atomicity guarantees
Knowledge mutation and its event share one transaction (`LearningSystem._atomic`). If the event write fails, teach,
correct, set_status, relate and NL learning leave knowledge, relationships, events and language tables unchanged. A
conversational correction whose language-store event write fails raises out of `process_input` without committing
anything (knowledge description/version unchanged; a retry succeeds).

## 11. Same-process / reload behavior
Every current observation (status, reasoning, Core reply, current relationships, language meaning) is identical live and
after close/reopen for the active, inactive and reactivated states; reopen and reads add no events or rows.

## 12. Test-isolation guarantees
Every test uses a per-test temp database via `Core(memory_db_path=..., skill_definitions_dir=...)`. The new tests assert the
shipped `data/memory.db` SHA-256 (`0d79f26a...957bb`), that an explicit-path `Core` never opens it (audit hook), and an AST
guard that no test module builds a bare `Core()` / `MemorySystem()` (unless it installs its own platform adapter). The
database is never restored after tests.

## 13. Genuine defect
**None found.** Candidates examined and judged intended behavior, not defects:
- `teach(..., source=None)` replaces the stored source with `None` and logs `None` (persisted = logged; documented in
  Prompt 649 - `teach` replaces provenance source).
- Conversational correction raises `RuntimeError` out of `process_input` if the language-store event write fails; no state
  is committed.
- An item's own language `meaning` resolves as language state independent of concept status.

## 14. Remaining intentional limitations
- Raw APIs, AEL ASK/recall and `resolve()` intentionally expose inactive records.
- `teach` with an exact case variant creates a distinct record (exact identity); `correct` targets the single existing one.
- The bare-`Core()` guard is name-based; indirect construction is covered by the dynamic traces (Prompt 671).
- Learning events are not replayed into state (no event sourcing).

## 15. Section 4 boundary
Section 4 may build on: the current-resolution APIs above for anything user-visible; `LearningSystem` mutators as the only
write path (they preserve atomicity, provenance and one-event-per-mutation); the raw APIs for administration/audit; and
`learning_events` for history only. It must not read events as current state, add a parallel knowledge store, or
reactivate knowledge implicitly.
