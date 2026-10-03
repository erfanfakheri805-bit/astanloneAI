# Prompt 660 - Section 3: KnowledgeSystem.search() input / boundary semantics

Ranking (Prompt 659), literal wildcards and the post-ranking 200-row cap (Prompt 658) are untouched. Only argument
validation was added at the top of `KnowledgeSystem.search(term, limit=20)`. Tests:
`tests/test_knowledge_search_input_boundaries_prompt660.py` (19 tests).

## Public contract
- `term`: `str` or `None`. `None`, `""`, whitespace-only and token-less strings (`"%"`, `"!!!"`, Persian-only) -> `[]`.
  Any other type -> `TypeError` (no string coercion), for every value regardless of truthiness.
- `limit`: `None` (= the 200-row cap) or an `int` >= 0. `0` -> `[]`; positive -> top-N of the ranking, capped at 200
  (larger values behave like 200). `bool`, `float`, `str`, `bytes`, containers -> `TypeError`; negative -> `ValueError`
  (never reinterpreted). Int subclasses other than `bool` are accepted.
- Validation runs before any query and before the blank-term shortcut, so a bad `limit` is rejected even with a blank
  term; a rejected call writes nothing. `LearningSystem.search(term)` inherits the term validation.

## Defects fixed (input boundary only)
- B1 A negative `limit` sliced from the END of the ranking (`limit=-1` silently dropped only the last row).
- B2 Non-string terms were decided by truthiness (`0`, `False`, `0.0`, `[]`, `b""` returned `[]` while `5`, `b"x"`,
  `["x"]` raised); `bool` limits were silently accepted as 0/1. Production callers only pass `str` terms (or use the
  default limit), so no caller changes.

## Intentional, pinned limitations
- Non-ASCII behaviour unchanged (no tokens from Persian text; ASCII-only SQLite LIKE/LOWER).
- Non-str terms are rejected, never coerced (`search(5)` raises even though a record named `"5"` may exist).
- `limit` above 200 is silently capped rather than rejected (Prompt 658 contract).
