# Prompt 676 - Section 3: Knowledge Mutation and Learning-Event Consistency

**Result: no genuine defect. No production change.** Pinned by
`tests/test_learning_event_mutation_consistency_prompt676.py` (26 tests, real production paths only).

## Event-producing mutation paths (all in `learning/learning_system.py`, each inside `MemorySystem._atomic()`)

| # | Path | Event | Target | Detail | Source |
|---|---|---|---|---|---|
| 1 | `LearningSystem.teach` | `teach` | name as given (exact-case identity) | new description | source argument (= what `learn()` persists) |
| 2 | `LearningSystem.correct` | `correct` | STORED name (exact, else single case-insensitive) | `repr(old) -> repr(new)` (`None -> 'x'` for a stub) | PERSISTED source (omitted argument keeps stored) |
| 3 | `LearningSystem.set_status` | `status` | STORED name | `'old' -> 'new'` | PERSISTED source |
| 4 | `LearningSystem.relate` | `relate` | from-name | `TYPE -> to-name` | PERSISTED relationship source |
| 5 | NL learning (`learn_from_understanding` / `Core.learn_from_text` / `ingest_understanding`) | via #4, one per learned item | resolved canonical names | via #4 | via #4 |
| 6 | Conversational correction (`Core._apply_resolved_correction_to_knowledge`) | via #2, `source="user_correction"` | the single matching record | via #2 | `user_correction` |
| 7 | AEL `TEACH` / `RELATE` | via #1 / #4 | - | - | - |

There is **no `LearningSystem.learn`**; `learn_from_understanding` is the NL entry point (#5).
Language-item learning and the correction-storage handoff write their own `language_*` events (separately handled since
Prompts 644-654) and are not knowledge events.

## Direct, intentionally non-eventing paths

`KnowledgeSystem.learn / correct / set_status / relate` and `ConceptSystem.define / link` change rows and write NO
events (verified: version bumps, stub creation, relationship rows, zero `learning_events`). No events were added for
symmetry. Read APIs (`get/all/search/resolve*/relationships_for/current_relationships_for/recall/reason/
understand_language/recent_learning_events`) write nothing.

## Invariants (verified)

- **Exactly one event per real mutation**, in the same transaction; `version` increments equal knowledge events for a record.
- **No event on true no-op:** identical teach/correct repeat, `set_status` to the current status (source is NOT refreshed),
  identical or None-preserving relationship repeat, identical NL repeat, unknown target, conversational correction with nothing left to correct.
- **Metadata**: a change to effective metadata (confidence / source / source_text / learning_method) is a real mutation
  (version + 1, one event). Equal effective values are a no-op. Metadata-only events keep an unchanged detail (documented L2/L3).
- **Reactivation:** `teach`/`correct` by explicit name reactivate with ONE `teach`/`correct` event (no separate `status` event).
  `relate` never touches endpoint status. Conversational/NL paths never reactivate inactive records.
- **Stub -> taught:** `teach` (v1 -> v2) or `correct` (`None -> 'x'`); stub creation by `relate`/NL has no event of its own (L1).
- **Case handling:** targets are stored names; ambiguous names raise `ValueError` for `correct`/`set_status` with no write and no event.
- **Atomicity:** an event-insert failure rolls back teach / new teach / correct / set_status / relate (existing and stub-creating);
  a mutation failure leaves no orphan event; NL persist failure is reported and leaves state unchanged; rejected inputs
  (blank name/description, bad status, blank endpoint, `None` relation, stub status change) consume no event id and create no stub.
- **Ordering:** ids are the only ordering; a rejection between two real mutations leaves no id gap.
- **Close/reopen:** rows and events are byte-identical across repeated reopens; reload writes nothing; no-ops stay no-ops
  after reopen and the next real mutation continues the id chain.

## Genuine defect / fix

None found; no production file changed.

## Intentional non-reconstructable fields (unchanged)

Stub creation has no event; teach/correct events omit confidence/source_text/learning_method/status/kind; relate events omit
confidence/source_text/learning_method; status is not logged when `teach`/`correct` reactivate; language events carry only `source_context`.

## Remaining limitations

- `LearningSystem.relate` defaults `source="ael"`, so omitting `source` on a repeat is a real source change (existing contract, Prompt 654).
- The event table is a history, not an event-sourcing store; current rows are authoritative.
- Direct `KnowledgeSystem` callers bypass history by design.
