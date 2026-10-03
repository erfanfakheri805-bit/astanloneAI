# Prompt 648 - Learning-event retrieval consistency (Section 3)

Result: audit only. No genuine retrieval defect found; **no production changes**.

Existing contract (unchanged): `MemorySystem.recent_learning_events(limit=50)`
(also `Core.recent_learning_events`, `GET /api/learning-history`) returns the newest
`limit` rows of `learning_events`, oldest first, as dicts with exactly the persisted
columns (`id, event_type, target, detail, source, created_at`).

- Ordering key is the unique AUTOINCREMENT `id`; `created_at` never participates, so
  equal/close/out-of-order timestamps cannot cause nondeterminism. Timestamps are never altered.
- `limit`: newest N by id; `0` -> `[]`; larger than history -> all; empty history -> `[]`.
- No type/target/source filtering exists in any read API; none was added. Callers filter the list.
- Retrieval is a single SELECT; it mutates nothing.
- Out-of-contract, left unchanged: `limit < 0` returns all rows; `limit=None` raises `sqlite3.IntegrityError`.

Tests: `tests/test_learning_event_retrieval_consistency_prompt648.py`.
