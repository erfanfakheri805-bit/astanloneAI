# Prompt 661 - Knowledge retrieval API consistency (Section 3)

## Result
Validation + hardening by tests. **No production defect found; no production file changed.**
All retrieval APIs read the one `knowledge` / `relationships` store and observe the same current row.

## APIs covered
`KnowledgeSystem.get / resolve_name / find_by_name_case_insensitive / search / all(kind) / relationships_for`,
`language_intelligence.learned_knowledge_context.select_learned_knowledge`, `LearningSystem.recall / search`,
and `Core._find_best_known_concept` (the Core wrapper that exposes current knowledge).

## Pinned behaviour (tests/test_knowledge_retrieval_api_consistency_prompt661.py)
- Identity: teach, conversational correction, natural-language provenance, stub -> taught (same id / created_at, version+1),
  relationship-created stubs, exact-case, unique case-insensitive, ambiguous case-insensitive, whitespace-distinct names.
- Current state after create / update / correct / stub upgrade / relationship update / no-op / failed / rejected / ambiguous
  mutations: every API returns the same row values for every field in its contract
  (id, name, description, kind, status, source, source_text, confidence, learning_method, version, created_at, updated_at).
  Superseded descriptions live only in `learning_events` and never surface as current knowledge.
- Ordering unchanged: Prompt 637 (name, id), Prompt 658 ranking + 200 cap, Prompt 660 validation, `all(kind)` by (name, id),
  relationships by (relation_type, other name, id).
- Ambiguity: exact wins; unique case-insensitive resolves; ambiguous never selects (resolve_name -> None + candidates,
  learned context -> AMBIGUOUS with no context); search stays independent of resolve_name ambiguity; ambiguity never writes.
- Reload: close/reopen, fresh KnowledgeSystem, fresh learned-context calls observe identical persisted state.
- Read-only: every retrieval (valid, blank, unknown, invalid) leaves knowledge, relationships and learning_events byte-identical;
  returned rows / selections are detached copies.
- Failure isolation: invalid search input, blank/ambiguous corrections, rejected relates change nothing.

## Intentional differences (not bugs)
- `get()` and `relationships_for()` are exact-case only; `resolve_name()` / `find_by_name_case_insensitive()` add unique case-insensitive resolution.
- `search()` is token/substring overlap over name + description (name-matching stubs are returned); it is not gated by resolve_name ambiguity.
- `select_learned_knowledge()` only looks up caller-supplied candidate terms plus 2-4 word phrases, and requires learned content
  (description or a relationship); a bare stub is not selected.
- SQLite `LOWER()` folds ASCII only, so case-insensitive resolution is ASCII-case-insensitive for every API alike (consistent, unchanged).
