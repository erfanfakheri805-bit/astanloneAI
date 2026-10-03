# Prompt 677 - Section 3: knowledge retrieval vs current answer evidence

Audit of the complete boundary between knowledge RETRIEVAL and CURRENT ANSWER EVIDENCE. Raw APIs were not
changed and no retrieval API was made to behave like another one; the raw/current split from Prompts 663-676 is
intentional and was only verified.

Classification: **R** raw/diagnostic, **C** current conversational, **I** current reasoning, **E** generated-answer
evidence, **L** learning target selection, **H** historical/audit.

## Retrieval paths audited (24)

| # | Path | Final consumer | Class | Inactive concept | Inactive endpoint | Result |
|---|------|----------------|-------|------------------|-------------------|--------|
| 1 | `KnowledgeSystem.get` | callers needing exact stored row; `learn`, `_resolve_name` | R/L | returned | n/a | raw, unchanged |
| 2 | `KnowledgeSystem.all` | `Core` implicit-correction scan (skips inactive itself, P665); `check_consistency` | R | returned | n/a | raw, unchanged; **`check_consistency` consumer fixed** |
| 3 | `KnowledgeSystem.search` | `Core._find_best_known_concept` (filters inactive); `LearningSystem.search` (no production caller) | R | returned | n/a | raw, unchanged |
| 4 | `resolve_name` | learned-context ambiguity detection; `correct`/`set_status` targets | R/L | returned | n/a | raw, unchanged |
| 5 | `resolve_current_name` | `Core._find_best_known_concept`, `ReasoningEngine._reason` | C, I, E | excluded (`"inactive"` status) | n/a | ok |
| 6 | `find_by_name_case_insensitive` | learned-context lookup, `LearningSystem` name resolution, `ConceptSystem` | R/L | returned | n/a | raw, unchanged |
| 7 | `find_current_by_name_case_insensitive` | none in production (current helper) | C | excluded | n/a | ok |
| 8 | `relationships_for` | `ConceptSystem.get_with_relations` -> `LearningSystem.recall` -> AEL ASK | R | returned | rows kept | raw, unchanged |
| 9 | `current_relationships_for` | `ReasoningEngine._current_rels`, learned-context rows | I, E | excluded | rows dropped | ok |
| 10 | `ReasoningEngine.lookup` | no production caller | R | returned | n/a | raw by contract |
| 11 | `LearningSystem.recall` / `ConceptSystem.get_with_relations` | AEL `ASK` | R | returned | rows kept | raw by contract (P669) |
| 12 | AEL `ASK` contradiction NOTE | user-visible listing | R + I | n/a | dropped | ok (P668/669) |
| 13 | `select_learned_knowledge` | `Core._attach_learned_knowledge` -> gate -> generation context | C, E | not selected | rows dropped | ok (P664/P670) |
| 14 | learned-knowledge context / gate evidence | response generation | E | absent | absent | ok |
| 15 | `Core._find_best_known_concept` | conversational "Here's what I know" fallback | C, E | excluded (name and search) | via `_current_rels` | ok (P667/672) |
| 16 | `ReasoningEngine.reason` retrieval | `Core` reasoning replies | C, I | unknown | dropped | ok |
| 17 | traversal / `find_path` / transitive closure / rules / `summarize_relationships` | reasoning | I | n/a | dropped, no hop through | ok |
| 18 | `contradictions_for` / `check_new_relationship` | reasoning, AEL NOTE, `LearningDecisionEngine` | I | n/a | ignored | ok |
| 19 | **`ReasoningEngine.check_consistency()` name enumeration** | consistency verdict | I | **was enumerated** | rows current | **DEFECT, fixed** |
| 20 | `MeaningResolver.resolve` | `Core.resolve_language_meaning`, `disambiguate_learned_meaning` | R | listed, labelled | n/a | raw, unchanged (P673) |
| 21 | `MeaningResolver.resolve_current` | fallback backend -> plan -> generation context | C, E | not followed | not followed | ok (P673) |
| 22 | `LearningSystem` name resolution / `teach` / `correct` / `set_status` | mutation targets | L | may be resolved and reactivated explicitly | n/a | unchanged (P637/665/666/672) |
| 23 | language-relationship store (`language_relationships`, variation matcher, pattern binder) | language graph | H | endpoint existence only | n/a | not knowledge evidence |
| 24 | Learning events / provenance reads | audit | H | n/a | n/a | not evidence, untouched |

No production consumer reads the `knowledge` or `relationships` tables by SQL except inside KnowledgeSystem / LearningSystem / MemorySystem mutation and storage code (LearningSystem.relate diffs its own written row).

## Genuine cross-boundary defect (1)

`ReasoningEngine.check_consistency()` (no `name`) enumerated `self.knowledge.all()` - the RAW list, inactive rows
included - and applied its `max_entities` budget (default 200) afterwards. Consequences:

- inactive records consumed the budget, so a real contradiction among ACTIVE records could be left unchecked while
  the result still reported `"consistent": True` (probe: 200 inactive records sorting first + an active
  `IS_A`/`IS_NOT_A` pair -> `checked` = 200 inactive names, `contradictions` = 0, `consistent` = True);
- inactive names were reported as "checked".

Prompt 672 classified this path "names only, rows via `_current_rels`" and did not consider the budget. The contradiction
rows themselves were always current-only; the leak was raw enumeration crossing into a current verdict.

### Fix (`reasoning/reasoning_engine.py`, one statement)

```python
names = [row["name"] for row in self.knowledge.all() if row.get("status") != "inactive"][:max_entities]
```

The status filter runs before the cap. An explicit `name` argument is checked as asked (an inactive `name` simply has
no current rows). `KnowledgeSystem.all()` and every other retrieval API are unchanged. Stub and legacy-status records
are enumerated as before; only status exactly `"inactive"` is excluded.

## Contracts after the audit

- **Raw** (`get`, `all`, `search`, `resolve_name`, `find_by_name_case_insensitive`, `relationships_for`, `recall`,
  `lookup`, AEL `ASK`, `MeaningResolver.resolve`): return inactive concepts and rows to inactive endpoints; nothing is
  filtered, nothing deleted.
- **Current** (`resolve_current_name`, `find_current_by_name_case_insensitive`, `current_relationships_for`, Core
  fallback, `ReasoningEngine`, learned-knowledge selection/context, `resolve_current`): inactive concepts and rows
  with an inactive endpoint never become evidence.
- Name resolution order (current): exact case among non-inactive records wins; else a single case-insensitive
  non-inactive match; else `"ambiguous"` (never silently chosen, candidates sorted); else `"inactive"` if only
  inactive records matched; else `"not_found"`. An exact-case match on an INACTIVE record does not win; the unique
  active case-variant is used instead (Prompt 667).
- Deterministic: ordering is by name then id; identical queries give identical results.
- Nothing is cached: active -> inactive -> active changes are visible immediately in the same process and after
  close/reopen. Explicit `teach`/`correct`/`set_status` reactivation restores current evidence.
- Multi-hop: a chain with an inactive middle endpoint is unavailable; an active alternative path is still used.
- All retrieval is read-only: knowledge, relationships, language tables and `learning_events` are byte-identical
  after exercising every layer.

## Intentional behavior preserved (not defects)

- AEL `ASK`/`recall` print stored rows unfiltered (P669); raw AEL output is never used as generated evidence.
- Learned-knowledge context stays conservatively AMBIGUOUS/NOT_FOUND when an inactive case-sibling exists (P664/672).
- `MeaningResolver.resolve` and explicit language-meaning lookups list inactive concepts labelled `status: inactive`.
- Natural-language learning onto case-ambiguous names creates a new concept (P637/672); implicit correction never
  reactivates an inactive record (P665).

## Remaining limitations

- Term extraction lower-cases message words, so in the Core fallback a lower-case-named record wins for any casing of
  the word (exact case applies to the extracted term).
- Raw APIs remain unfiltered, so a UI built directly on them must inspect `status` itself.
- Only status exactly `"inactive"` is excluded; no other status has lifecycle meaning.
- `ReasoningEngine.lookup` and `LearningSystem.search` have no production caller and are documented raw helpers.

## Tests

`tests/test_knowledge_retrieval_evidence_boundary_prompt677.py` (44 tests, real Core paths only): raw vs current
contracts, stub/legacy status, Core fallback, reasoning evidence and endpoint matrix, multi-hop, the
`check_consistency` defect (5 of these fail on the pre-fix code), learned-knowledge context, case-variant matrix,
meaning-resolution current path, same-process mutation, close/reopen, and read-only/no-event verification.
