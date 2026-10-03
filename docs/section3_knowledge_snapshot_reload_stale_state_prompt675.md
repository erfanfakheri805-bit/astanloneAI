# Prompt 675 - Section 3: Knowledge Snapshot, Reload, and Stale-State Integrity

**Result: no genuine stale-state defect. No production change.** Lifecycle invariants are pinned by
`tests/test_knowledge_snapshot_reload_stale_state_prompt675.py`.

## Retained knowledge-derived state discovered

| Owner | State | Kind | Read back as current knowledge? |
|---|---|---|---|
| `MemorySystem` | one SQLite connection (`_conn`), `_atomic_depth`, lock | persistence, not a cache | it IS the source of truth |
| `KnowledgeSystem` | `self.memory` only (no attributes besides it) | none | no state to go stale |
| `KnowledgeSystem.current_relationships_for` | local `usable` dict | per-call memo, discarded on return | no |
| `LearningSystem` / `ReasoningEngine` / `RuleRegistry` | collaborator references; per-call budget counters (`rules_evaluated`, `limit_hit`) | none / per-query | no |
| `Core` | `last_learned_knowledge_gate`, `last_learned_knowledge_gate_trace`, `last_response_context`, `last_language_understanding` and other `last_*` | per-turn diagnostics | no; reset at the start of each attach/turn |
| `Core` | `learned_knowledge_decision_statistics` | in-memory diagnostic counter | no (Prompt 504, diagnostic only) |
| `LanguageIntelligenceCore` | `last_*` result fields | per-reply diagnostics | no; reset per reply |
| `learned_knowledge_statistics` | `_snapshots` (bounded, diagnostic) | diagnostic history of statistics | no |

There are no explicit caches, memoization, `lru_cache`, retained resolver results or retained relationship lists
on any knowledge path. `select_learned_knowledge`, `resolve_current_name`, `_find_best_known_concept`,
`ReasoningEngine._current_rels` and `Core.reason` re-query SQLite on every call.

## Ownership / lifecycle / invalidation

State of record is SQLite, written by `KnowledgeSystem`/`LearningSystem` inside `MemorySystem._atomic()` scopes
(commit on the outermost exit, rollback on exception). Because nothing derived is retained, there is nothing to
invalidate: every current consumer sees the persisted state immediately after any mutation, in the same object
lifetime, and identically after close/reopen. Per-turn `last_*` fields are overwritten (or reset to `None`) at the
start of the next turn and are not consumed as knowledge.

## Mutation -> current-read invariants (verified)

- active -> inactive -> active (`set_status`), `teach` reactivation, description `correct`, relationship creation,
  stub -> taught: immediately visible to `Core.reason`, conversational fallback (`process_input`),
  `select_learned_knowledge`/`understand_language().learned_knowledge_context`, `resolve_current_name`,
  `current_relationships_for`.
- Multi-hop (DEPENDS_ON chain): an inactive middle or far endpoint removes the inferred answer at once;
  reactivation restores it; same after reopen.
- Case variants: exact-case wins; unique case-insensitive resolves; ambiguous current variants stay ambiguous
  (nothing chosen) and clear immediately when one variant goes inactive; inactive-only variants report `inactive`.
- Rejected / failed mutations (`ValueError` status, unknown-name `correct`, forced write failure inside `relate`)
  leave tables byte-equal and consumers unchanged (no partially applied state).
- Read-only consumers (`reason`, `select_learned_knowledge`, `resolve_current_name`, `current_relationships_for`,
  `understand_language`) write no rows and emit no learning events.

## Same-process vs reload

Identical results: a sequence of mutations in one Core lifetime yields the same reason/fallback/context output as
a fresh Core over the same database. `last_learned_knowledge_gate*` do not leak across reopen and are reset each turn.

## Raw vs current

Unchanged: `get`, `resolve_name`, `find_by_name_case_insensitive`, `relationships_for`, `all`, `recall`, and AEL
`ASK` remain raw and still return inactive records/rows. Only the documented current consumers filter.

## Genuine defect / fix

None found; no production file was changed.

## Remaining limitations

- Relationship removal/change is not supported by KnowledgeSystem (no delete/unrelate path), so it is not testable
  through production paths; relationship "change" is creation of a new row.
- `Core.last_*` diagnostics may describe an earlier turn until the next turn runs; they are documented diagnostics,
  not current knowledge, and must not be read as such by future consumers.
- Multi-process concurrent writers are out of scope (single connection per MemorySystem).
