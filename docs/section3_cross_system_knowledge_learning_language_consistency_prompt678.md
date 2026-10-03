# Prompt 678 - Section 3: cross-system knowledge / learning / language-intelligence consistency

Audit of how one underlying knowledge state is interpreted when it crosses KnowledgeSystem, LearningSystem and
Language Intelligence. Intentional differences between the subsystems were preserved. **Result: no genuine
cross-system defect; no production change.** The verified invariants are pinned by
`tests/test_cross_system_knowledge_learning_language_consistency_prompt678.py` (44 tests, real production paths).

## State ownership

| State | Owner | Nature |
|-------|-------|--------|
| concept rows (`knowledge`: description, status, source, source_text, learning_method, version) | KnowledgeSystem | **current truth** |
| `relationships` rows | KnowledgeSystem | current truth (current view = endpoints not inactive) |
| `learning_events` types `teach` / `correct` / `status` / `relate` | LearningSystem (via MemorySystem) | **history only**; never read to answer or to decide status |
| `language_learning_items`, `language_item_relationships` and their `language_*` events | Language stores | separate reference / history stream; no status field; concept endpoints are exact stored names |
| learned-knowledge context, learned meanings, plans, Core replies, reasoning results | derived, computed per call | never cached, never stored |

No state is duplicated between subsystems and no synchronisation layer exists or was added.

## Cross-system transitions audited (22)

Columns: mutates / event / current-or-historical / inactive respected / ambiguity preserved / provenance.

| # | Source -> target | Data crossing | Mutates | Event | C/H | Inactive | Ambiguity | Provenance |
|---|------------------|---------------|---------|-------|-----|----------|-----------|------------|
| 1 | `Core.learn_from_text` -> `LearningSystem.learn_from_understanding` | subject / relation / object | no (analysis) | - | - | - | - | - |
| 2 | learn_from_understanding -> `_resolve_concept_name` | candidate name -> stored name | no | - | C | resolves onto inactive record, no duplicate, no reactivation (P665/666) | ambiguous CI -> new concept, never picks one (P637/672) | - |
| 3 | learn_from_understanding -> `LearningSystem.relate` -> `KnowledgeSystem.relate` | relation + stubs | yes (atomic) | one `relate`, target = persisted subject, source = `understanding_engine` | C | endpoint stays inactive | as #2 | source, source_text, learning_method persisted on relationship and stub |
| 4 | NL-created stub -> `teach` | description | yes | `teach` | C | activates (explicit) | exact identity | source replaced by teach's; source_text / learning_method kept (None keeps) |
| 5 | NL-created stub -> `correct` (CI name) | description | yes | `correct` | C | activates | unique CI resolves; ambiguous raises, writes nothing | source kept unless supplied |
| 6 | `teach` -> NL reference | stored name | yes (relate only) | `relate` | C | - | unique CI resolves onto stored casing | - |
| 7 | conversational correction -> `Core._apply_resolved_correction_to_knowledge` -> `correct` | corrected text | yes | one `correct`, source `user_correction` | C | inactive record is never the implicit target (P665) | several matches -> nothing written | `explicit_correction`, source_text = sentence |
| 8 | conversational correction -> language-learning handoff | correction item | language store only | `language_item_*` (separate stream) | H | n/a | n/a | - |
| 9 | `set_status` -> Core fallback / reasoning / learned context / meaning resolution | status | yes | one `status`, persisted name and source | C | excluded from all current consumers | P664 / P672 kept | - |
| 10 | status inactive -> NL reference | see #2, #3 | relate only | `relate`, no `status` event | C | not resurrected | - | - |
| 11 | inactive -> `teach` / `correct` / AEL `TEACH` | description | yes | `teach` / `correct` (AEL source `ael`) | C | reactivated, relationships current again | - | - |
| 12 | relationship creation -> `ReasoningEngine` | rows | no | - | C | inactive endpoint dropped (P668) | - | - |
| 13 | endpoint deactivation / reactivation -> reasoning | status | - | - | C | immediate, nothing cached | - | - |
| 14 | language item -> concept endpoint (`relate_language_items`) | exact concept name | language store only | `language_*` | H reference | endpoint stays inactive; language row untouched | exact name only; missing / wrong-case name raises, writes nothing | - |
| 15 | language item -> `MeaningResolver.resolve` | concept description + status | no | - | raw | listed and labelled | - | - |
| 16 | language item -> `MeaningResolver.resolve_current` (conversation, plans, generation context) | concept description | no | - | C | not followed (P673) | exact endpoints, no redirect to an active case-variant | - |
| 17 | concept correction -> language meaning / Core reply | new description | yes (correct) | `correct` | C | - | - | - |
| 18 | events -> current state | `correct` detail keeps the old description | no | - | H | - | - | history never read back into current answers |
| 19 | AEL `TEACH` / `RELATE` -> LearningSystem | same primitives as NL | yes | `teach` / `relate` source `ael` | C | TEACH reactivates | AEL keeps exact-case identity | - |
| 20 | AEL `ASK` -> `recall` | raw record + rows | no | none | raw | listed (P669) | exact case | - |
| 21 | failing event write -> knowledge mutation | - | rolled back | none | - | - | - | - |
| 22 | close / reopen | all of the above | no | none | C + raw | unchanged | unchanged | unchanged |

## Verified invariants

- **Single source of truth.** Every current consumer (Core fallback, ReasoningEngine, learned-knowledge selection
  and context, `resolve_current`) reads KnowledgeSystem rows at call time. Learning events and language rows never
  change what is current: the latest `teach` event does not make an inactive record active; a language item that
  still references an inactive concept does not make it current and the reference is left as stored.
- **No resurrection.** Only explicit `teach`, `correct` (including AEL `TEACH`) and `set_status(..., "active")`
  reactivate. NL learning, conversational correction (implicit target), language linking and every read leave
  `inactive` untouched. `teach` with a differently-cased name creates a distinct record (exact identity), while
  `correct` / `set_status` resolve a unique case-insensitive match.
- **Ambiguity.** Exact case wins; a unique CI match resolves; several current case-variants are ambiguous in the
  Core fallback (no answer), reasoning (unknown) and learned context (AMBIGUOUS), and explicit `correct` /
  `set_status` raise without writing. An inactive variant neither wins nor creates ambiguity for current name
  resolution, while raw `resolve_name` stays ambiguous and Prompt 664's conservative context result is unchanged.
  NL learning with an ambiguous name creates a new concept rather than choosing (P637/672).
- **Relationship identity.** Knowledge relationships are (from, to, type) on exact stored names; language-to-concept
  links use the exact concept name and never create endpoints. Deactivating or reactivating an endpoint changes the
  current view only; stored rows are never deleted.
- **Provenance.** `source`, `source_text`, `learning_method`, `confidence` follow the "None keeps stored value"
  rule when data crosses (NL stub -> teach keeps the sentence and method, replaces `source` with the explicit one).
  Events log the persisted target name and persisted source, not the raw argument.
- **Events.** One event per real mutation; none for reads, true no-ops, or ambiguous / invalid / failed operations;
  stub auto-creation is covered by the single `relate` event; language stores log their own `language_*` events,
  which are not knowledge history. A failing event write rolls back the knowledge mutation (per-item `persist_error`
  for NL learning).
- **Same process / reopen.** Nothing is cached: learn -> deactivate -> correct/reactivate is reflected immediately in
  every consumer, and identically after close / reopen with no new events or writes.

## Defect assessment

Sequences probed with real APIs (NL learn / teach / correct / conversational correction / status / reactivation /
relationships / language links / AEL / case variants / rollback / reload) showed no case where one subsystem
interpreted the shared state differently from its documented contract. Probed and found consistent: stubs whose
only evidence is an inactive endpoint answer "not enough information" (Core, reasoning and context agree); NL
learning against a lower-cased inactive name attaches to the stored record; language links to an inactive concept
stay stored but produce no current meaning. Therefore **no production file was changed.** Mutation checks confirmed
the tests bite: disabling the `current_relationships_for` filter fails 6 tests and reverting the fallback backend
to raw `resolve()` fails 8.

## Intentional differences preserved

- Language items have no status; they are references, not knowledge, and are not globally filtered.
- Raw APIs and AEL `ASK` / `recall` / `MeaningResolver.resolve` return inactive data (labelled where the API labels).
- `teach` keeps exact-case identity; `correct` / `set_status` resolve a unique CI match; AEL is exact-case.
- NL learning may attach a relationship to an inactive record (kept, not current) and never reactivates it.
- Language events (`language_item_*`) are a separate stream from knowledge events.

## Remaining limitations

- Learning events are an audit trail, not an event-sourcing log: current state cannot be rebuilt from them.
- A language item linking an inactive concept is not flagged in the language store; consumers must use
  `resolve_current` (conversation paths already do).
- `source` on a stub is replaced by the first explicit `teach` (existing semantics); the NL origin remains visible
  through `source_text` / `learning_method` and the `relate` event.
- Stub records cannot be set inactive until taught (existing P663 rule).
