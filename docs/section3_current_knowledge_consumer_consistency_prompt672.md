# Prompt 672 - Section 3: current-knowledge consumer consistency

Audit of every production consumer of knowledge retrieval (raw APIs unchanged). Columns: R raw/diagnostic,
C current knowledge, I inference, E evidence for a generated answer, M picks a mutation target.

| # | Consumer | Uses | Role | Inactive can influence? | Ambiguity silently resolved? | Boundary |
|---|----------|------|------|------|------|------|
| 1 | Core._find_best_known_concept (conversation fallback) | resolve_current_name, search | C, E | no (P667) | **yes - fixed here** | now skips ambiguous current case-variants |
| 2 | Core reply for that record (+ summarize_relationships) | _current_rels | C | no (P668) | - | current_relationships_for |
| 3 | Core._apply_resolved_correction_to_knowledge | all() | M (implicit) | no (skips inactive, P665); needs exactly one match | no | ok |
| 4 | ReasoningEngine.reason knowledge retrieval | resolve_current_name | C, I | no (P667) | no (ambiguous -> no entry) | ok |
| 5 | ReasoningEngine direct/traverse/rules/find_path/summary/contradictions/check_new_relationship | _current_rels | I | no (P668) | - | ok |
| 6 | ReasoningEngine.check_consistency | all() names -> contradictions_for | I | no (names only, rows via _current_rels) | - | ok |
| 7 | ReasoningEngine.lookup | get() | R (no production caller) | raw by contract | - | unchanged |
| 8 | learned_knowledge_context (select + rows) | find_by_name_case_insensitive, resolve_name, current_relationships_for | C, E | no (P664/P670) | no (AMBIGUOUS) | ok; inactive case-sibling keeps AMBIGUOUS (P664, intentional) |
| 9 | Learned-knowledge gate | context rows | E | no (rows current-only) | - | ok |
| 10 | AEL ASK -> LearningSystem.recall -> ConceptSystem.get_with_relations | get, relationships_for | R | yes, documented (P669) | - | intentionally raw |
| 11 | LearningSystem.search | search | R (no production caller) | raw | - | unchanged |
| 12 | LearningSystem.learn_from_understanding (`_resolve_concept_name`) | get, find_by_name_case_insensitive | M (implicit) | resolves onto inactive record, not reactivated, no duplicate (P665/666, tested) | ambiguous -> creates new name, never picks one | unchanged |
| 13 | LearningSystem set_status/teach/correct/relate (explicit names) | get, find_by_name_case_insensitive | M (explicit) | teach/correct reactivate; set_status explicit | - | unchanged |
| 14 | language_relationships._lookup_endpoint | get | endpoint existence | n/a (language graph, not knowledge facts) | - | unchanged |
| 15 | meaning_resolution._describe (concept endpoints) | get | R, labelled | description returned WITH its `status` | - | see limitations |
| 16 | LearningDecisionEngine | reasoning.check_new_relationship | I | no (P668) | - | ok |
| 17 | ConceptSystem.find_by_name_case_insensitive / all_concepts | raw | R | raw by contract | - | no production caller beyond above |
| 18 | direct SQL against `knowledge`/`relationships` | only inside KnowledgeSystem/LearningSystem/MemorySystem storage code | storage | - | - | no consumer bypasses via SQL |

18 consumer paths audited.

## Defect found and fixed (1)
`Core._find_best_known_concept`: for a term ambiguous among CURRENT case-only duplicates (P637) the
`KnowledgeSystem.search()` fallback still returned one of them (ranking tie -> name order), so the conversation
answered "Here's what I know about 'PYTHON': ..." while `ReasoningEngine` reported the same subject as unknown.
Fix (use boundary only, `core/core.py`): terms resolve through `resolve_current_name`; in the search fallback a group of
current case-variants is skipped unless the message literally contains exactly one variant's exact-case name (exact case
still wins). Inactive records never count as variants. Public return shape unchanged.

## Deliberately NOT changed (proved by tests)
Raw APIs; AEL ASK; explicit teach/correct/set_status; P664 conservative AMBIGUOUS with an inactive case-sibling;
P665/P666 NL learning onto an inactive record (a first attempt to skip such writes contradicted these tests and was
reverted); stub/legacy statuses stay current; stored relationships.

## Remaining intentional limitations
- meaning_resolution `_describe` returns a concept endpoint's description together with `status` (transparent, not filtered).
- Learned-knowledge context stays AMBIGUOUS (not SELECTED) when an inactive case-sibling exists (P664).
- NL learning with a case-ambiguous name creates a new concept (P637 behavior) rather than choosing one.
- No new global `current=True` API layer.
