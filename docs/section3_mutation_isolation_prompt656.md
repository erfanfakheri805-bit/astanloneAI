# Prompt 656 - Mutation isolation across knowledge, relationships and learning history (Section 3)

Result: audit only. No genuine defect found; **no production changes**.
Tests: `tests/test_knowledge_mutation_isolation_prompt656.py` (20 tests).

- **Single-target mutation.** `teach()`, `correct()` (including case-insensitive resolution), a relationship update, a stub -> taught upgrade, natural-language learning of another concept and a conversational correction each change only their own target. Unrelated knowledge rows, relationship rows, language items and language relationships stay equal, compared verbatim (ids, versions, created_at/updated_at, source, confidence, source_text, learning_method, status).
- **History.** `learning_events` is append-only (existing rows verbatim). New events exist only for the actual target and have the expected type, and exact no-ops add none.
- **Versions/timestamps.** Only the mutated record's version and updated_at move. `id` and `created_at` never move.
- **No-ops, failures, invalid input.** Exact no-ops, failed atomic ops (event write raising, including NL learning), blank/None inputs and `correct()` of an unknown name change nothing, before and after reopen.
- **Ambiguity.** An ambiguous case-insensitive name raises or resolves to None and mutates no candidate or bystander. An exact name still updates only its own record.
- **Reopen / ordering.** Isolation holds across close/reopen. A second sequential connection sees the committed change with bystanders unchanged. Independent scenarios run forward, reversed and alternating reach the same final state (ids and timestamps excluded).
- **Documented shared metadata (preserved, not redefined).** `sqlite_sequence` advances only with real inserts. A `relate()` to an unknown name legitimately adds a new stub row and never edits an existing one. The language layer and knowledge layer do not mutate each other. Reopening through Core changes no knowledge/learning table.

Concurrency limitation (unchanged, out of scope): the store uses one connection with a lock and a re-entrant single-connection `_atomic` scope. True concurrent writers are not supported and no thread/process infrastructure was added; the tests are sequential.
