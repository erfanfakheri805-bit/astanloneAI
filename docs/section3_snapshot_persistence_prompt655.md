# Prompt 655 - Current-knowledge snapshot consistency across save / close / reopen / continue (Section 3)

Result: audit only. No genuine defect found; **no production changes**.
Tests: `tests/test_knowledge_snapshot_persistence_prompt655.py` (14 tests).

- **Reopen is read-only.** Repeated reopens, through Core or a bare `MemorySystem`, leave every knowledge, relationship, event and language row unchanged. That includes ids, versions, status, source, confidence, source_text, learning_method, created_at and updated_at, compared verbatim (timestamps are never normalized). Reopening writes no events and no version bumps, and the AUTOINCREMENT counters are unchanged.
- **Readers:** every current reader returns identical values before close and after reload. No stale pre-close value is returned once a new write lands after reload.
- **History:** event ids stay contiguous and ordered. Replaying them (the Prompt 654 test helper) still equals the live rows after reload.
- **Continue after reload:**
  - Versions continue from the persisted value (+1 per real change).
  - New knowledge ids and event ids continue without reuse.
  - `id` and `created_at` never move.
  - A stub -> taught -> corrected record stays one identity across three reloads.
- **No-ops and failures after reload:** exact no-ops stay no-ops. A failing atomic op leaves state and history unchanged, before and after a further reload, and the store stays usable. An uncommitted `_atomic` scope is discarded by close(). A bare-stack write is visible to Core.
- **Ambiguity:** `resolve_name` returns identical candidates after reload. An exact name still wins. Ambiguous `correct()` raises and writes nothing.
- **Language stores:** items and relationships persist verbatim. Their intentional semantics stay unchanged after reload: every repeat is a real update (version+1, one event), and a relationship restatement returns created False. The concept endpoint keeps its language relationship through knowledge lifecycle and reload.

Limitation (out of scope, unchanged): constructing `Core` re-enables built-in capabilities, which refreshes `capabilities.updated_at` on each open. That table is not knowledge or learning state, so it is excluded from the snapshots. A bare `MemorySystem` reopen does not touch it.
