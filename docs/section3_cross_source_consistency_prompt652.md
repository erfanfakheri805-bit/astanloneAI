# Prompt 652 - Current-knowledge consistency across learning sources (Section 3)

Result: audit only. No genuine defect found; **no production changes**.
Tests: `tests/test_knowledge_cross_source_consistency_prompt652.py`.

Sequence verified: NL relate-stub -> `teach()` -> conversational correction -> re-`teach()` -> NL again.

- **Identity:** one current record per exact name. id, name and `created_at` never change. The version goes up by 1 per real change, and `updated_at` moves only on a real change.
- **Provenance is unchanged and not normalized:**
  - The NL stub gets source `understanding_engine` and method `natural_language_understanding`.
  - `teach()` replaces the source (default `ael`) and keeps the older `source_text`, method and confidence.
  - `correct()` keeps the source unless one is given. Core's conversational correction passes `user_correction`, method `explicit_correction` and the sentence as `source_text`.
  - NL on an existing record only touches the relationship row.
- **No-op rules:** each API keeps its own rules (teach with the same source, correct with source None, and identical NL repeats change nothing). A different explicit source is a real update.
- **Current readers vs history:** `get`, `all`, `search`, `resolve_name`, `relationships_for` and `recall` always show the latest row. `learning_events` keep historical values (for example, the teach event detail is the old description) and are never current state.
- **Relationships** keep resolving to the current record through updates.
- **Case identity:** exact names resolve exactly, and ambiguous names raise and mutate nothing.
- **Atomicity:** a failing event insert leaves knowledge, relationships and events unchanged for teach, correct, relate and NL learning (NL reports `persist_error`), including when a later source updates a record created by another source.
- **Language stores** never alter knowledge records.
