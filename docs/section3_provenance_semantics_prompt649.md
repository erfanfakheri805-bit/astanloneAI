# Prompt 649 - Provenance semantics across Knowledge / Learning paths (Section 3)

Result: audit only. No genuine contradiction or accidental provenance loss found; **no production changes**.
Tests: `tests/test_knowledge_provenance_semantics_prompt649.py`.

| API | omitted `source` | omitted `confidence` / `source_text` / `learning_method` |
|---|---|---|
| `KnowledgeSystem.learn()` | replaced by default `"user"` | preserved (new row: confidence 1.0) |
| `LearningSystem.teach()` | replaced by default `"ael"` | preserved |
| `KnowledgeSystem.correct()` / `LearningSystem.correct()` | stored source kept | preserved; status None -> `"active"` |
| `KnowledgeSystem.relate()` (`source_type`) | kept (new row: NULL) | preserved |
| `LearningSystem.relate()` | default `"ael"` | preserved |
| `learn_from_understanding()` | `"understanding_engine"` (or explicit `source`), method `natural_language_understanding`, source_text = original text | - |
| Language item / relationship stores | kept | all preserved (`source_context` too) |

- Explicit values are stored exactly; identical repeats are no-ops (no version bump, no event).
- Events log the persisted source (`teach` logs its argument, which equals the persisted value).
- Stub concepts from `relate()` take `source_type or "inferred"` plus the relation's source_text/method; a later `teach()` replaces source but keeps that stub source_text (documented None-preserving policy).
- `LearningSystem.learn()` does not exist; the equivalents are `teach()` and `learn_from_understanding()`.
- Reads never mutate; reopen preserves provenance exactly.
- These differences are intentional and were not unified.
