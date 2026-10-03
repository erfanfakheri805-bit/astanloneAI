# Prompt 659 - Section 3: KnowledgeSystem.search() relevance and ordering

Audit only; **no production change** (`knowledge/knowledge_system.py` untouched). Tests:
`tests/test_knowledge_search_ranking_prompt659.py` (33 tests).

## The ranking contract (as implemented, now pinned)
- Candidates: rows whose name/description LIKE-contains (literal, ASCII-case-insensitive) any query token or the
  whole phrase. Token = `[A-Za-z0-9_']` run, lower-cased.
- Rank key `(T1, T2, name, id)`: T1 = whole phrase is a case-insensitive substring of the NAME; T2 = number of query
  tokens in `tokens(name) | tokens(description)` (a token in both counts once); then name (code-point order), then id.
  Never timestamp, version, insertion order, learning history, or set/dict iteration order (verified across
  PYTHONHASHSEED values).
- Cap: `min(limit, 200)` applied after ranking; `limit=None` means 200 (verified against an independent oracle on
  >200-candidate data sets, including after reopen).

## Consequences that are the contract, not endorsements
- No separate exact-name / prefix / name-token tier: an exact-name record and a name merely containing the phrase
  share T1 and are separated by T2 (token membership), then name.
- A description-only phrase match gets no bonus; rows matching only by LIKE substring have T2 = 0 (returned, ranked
  last within their T1 tier); the query phrase is not whitespace-normalised.
- Non-ASCII text yields no tokens; the phrase tier uses Python `str.lower()`; Persian-only queries return `[]`.
- (Superseded by Prompt 660: `limit`/query input validation is now explicit; see
  `section3_search_input_boundaries_prompt660.md`. A negative `limit` now raises `ValueError`.)
