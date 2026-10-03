# Prompt 651 - Knowledge state-transition integrity (Section 3)

Result: audit only. No genuine state-transition defect found; **no production changes**.
Tests: `tests/test_knowledge_version_state_integrity_prompt651.py` (controlled, strictly increasing clock patched into the `_now` helpers).

Contract (asserted, unchanged):

- **Creation:** version 1, `created_at == updated_at`, status `active` (`relate()` stubs are `stub`).
- **Genuine change:** a change to any of description, kind, status, source, confidence, source_text or learning_method (using None-preserving effective values) bumps the version by exactly 1 and moves `updated_at`. `created_at`, id and name never change.
- **Exact repeat:** a true no-op. No write, no version bump, no timestamp change, no event.
- **Status:** a plain persisted field. `learn()`/`teach()` default to `active`; `correct()` with status None becomes `active`; an explicit status is stored and counts as a change. A stub taught later keeps its row (same id and `created_at`), version +1, status `active`.
- **Events:** only real transitions log one. A status-only correction logs `'d' -> 'd'` (known limitation L2 from Prompt 647). Knowledge and event writes are atomic: if the event insert fails, the whole knowledge mutation rolls back (checked for teach create/update, correct and relate).
- **Relationships:** `relate()` never mutates existing endpoint records or bystanders. Relationship rows have no version; `updated_at` moves only when an effective value changes.
- **Intentionally different repeat semantics (unchanged):** the language item and language relationship stores treat every repeat, even an identical one, as a real update (version +1, `updated_at` moves, an `..._updated` event).
- **Rejected or ambiguous operations** (blank names or descriptions, unknown or ambiguous correction targets, invalid relate arguments) change nothing.
