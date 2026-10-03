# Prompt 653 - Current relationship consistency across knowledge lifecycle changes (Section 3)

Result: audit only. No genuine defect found; **no production changes**.
Tests: `tests/test_relationship_lifecycle_consistency_prompt653.py` (14 tests).

- **Edges reference endpoints by exact knowledge name.** Description, source, confidence, status, kind and version changes never touch, duplicate or redirect an edge. Stub -> teach -> correct -> re-teach keeps the same relationship row.
- **Reads show the current endpoint.** `relationships_for`, `recall` and language `relationships_for` reflect the latest state. `learning_events` keep history only.
- **Created contract:** `relate()` returns True only for a new row. An identical repeat is a true no-op (no write, no event). A real metadata change refreshes the row, adds one event and still returns False.
- **Atomicity:** a failing event insert leaves knowledge, relationships and events unchanged for relate, teach and correct (refresh, create and stub cases). Invalid names or relation types write nothing.
- **Case identity is unchanged.** `relate("python", ...)` never resolves to `"Python"`. `correct()` on an ambiguous name raises. NL learning reuses a unique case-insensitive match. For an ambiguous NL name it does not redirect to an existing record. It creates the exact written name as its own new stub, and existing records and edges stay untouched.
- **Cross-source updates** (NL, teach, correct, relate) keep one row per triple. An NL restatement with a different `source_text` refreshes that row's metadata (existing contract).
- **Language relationships to concepts** survive knowledge lifecycle changes. A restatement returns created False, bumps the version and keeps the id and `created_at`. A None metadata value keeps the stored one. Failed writes are atomic and endpoints are never auto-created. The language store never modifies knowledge records or edges.
