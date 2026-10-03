# Prompt 658 - Section 3: knowledge search / resolution / listing / retrieval semantics

Audit of the CURRENT retrieval contract (no new search architecture, no fuzzy/semantic matching, no normalisation,
no public return-structure change). Tests: `tests/test_knowledge_retrieval_semantics_prompt658.py` (39 tests).

## Verified (unchanged behaviour)
- Resolution: exact-case always wins; a unique case-insensitive match resolves; several case-insensitive matches are
  `ambiguous` (record `None`, candidates sorted by binary name) and never resolve arbitrarily; whitespace variants are
  distinct identities; non-string names are `not_found`. `get`, `resolve_name`, `find_by_name_case_insensitive` share
  one resolution path.
- `search()` rank key: (whole-phrase name hit, token overlap, name, id). Never timestamp / insertion order. Equal
  timestamps, reversed insertion, case variants, similar names/descriptions, and `limit` all deterministic.
- Every reader (`get`, `all`, `search`, `resolve_name`, `LearningSystem.search/recall`) returns the CURRENT persisted
  row field-for-field; corrected/obsolete descriptions never appear as current; `learning_events` history is never
  returned as knowledge. Stubs and non-active rows are returned with their persisted status (no status filtering).
- `relationships_for()` is deterministic (`relation_type, other_name, id`), attached to exact names, endpoints are
  current rows, provenance/confidence equal the persisted edge row.
- Identical ordering/content after close/reopen and via a second stack; failed, ambiguous, missing and no-op operations
  leave search results and all tables unchanged; reads never write.
- Non-ASCII (pinned, unchanged): SQLite `LOWER()`/`LIKE` are ASCII-only and the query tokenizer is `[A-Za-z0-9_']`,
  so Persian names resolve exact-case only, and a Persian-only query has no tokens (`search` -> `[]`); mixed queries
  match via their ASCII tokens.

## Genuine defects found and fixed (`knowledge/knowledge_system.py`, `search()` only)
- D1 LIKE wildcards unescaped: `_` is a legal query token but matched any character, so `search("a_b")` returned
  `axb` and `search("_")` returned every row. Query text is now matched literally (`ESCAPE '\'`).
- D2 The 200-row candidate cap was a SQL `LIMIT` applied BEFORE relevance ranking, so an exact-name record could be
  dropped when 200+ earlier-sorting rows merely mentioned it. The cap is now applied AFTER ranking (still at most
  200 rows; `limit=None` means the cap). Result ordering rules are unchanged.

## Remaining limitations (by design / out of scope)
- Persian/non-ASCII-only queries return no search results; non-ASCII case folding is not performed.
- `search()` still fetches all matching candidates before ranking (fine at local scale; no pagination).
- Stub/non-active rows are not filtered from `search()`/`all()` (existing Prompt 657 contract).
