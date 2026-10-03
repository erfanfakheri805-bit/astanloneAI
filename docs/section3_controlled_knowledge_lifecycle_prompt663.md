# Prompt 663 — Controlled Knowledge Lifecycle API

## Added
- `KnowledgeSystem.set_status(name, status, source=None, source_text=None, learning_method=None)`
- `LearningSystem.set_status(...)` (same operation, atomic with a `status` learning event)
- `knowledge.knowledge_system.LIFECYCLE_STATUSES = {"active", "inactive"}`

No table, schema, deletion, replay or snapshot was added; rows are never removed.

## Supported states
Writable via the API: `active`, `inactive`. `stub` remains relate()-only (a stub leaves `stub` only through
teach()/correct()); `set_status` on a stub raises ValueError. Other stored values (e.g. legacy `deprecated`
written by direct `learn()`) are preserved and can be moved to active/inactive.

## API behavior
- Target resolution: exact case, else the single case-insensitive match (Prompt 637). Ambiguous -> ValueError.
- Unknown name -> returns None, nothing created. Blank / non-string name, non-string or unknown status
  (case-sensitive), `stub` target status, or stub record -> ValueError. All fail with no mutation and no event.
- Returns the record (LearningSystem: same, like `correct()`).

## No-op
Requested status equals current -> nothing written (version, updated_at, provenance unchanged, even if a
source was supplied), no event, stored record returned.

## Version / event semantics
- Real transition: one ordinary `learn()` mutation, version + 1 exactly, updated_at moves; id/name/created_at/
  description/kind/confidence untouched; source/source_text/learning_method keep stored values unless supplied.
- LearningSystem writes one event, inside the Prompt 645 atomic scope: `event_type="status"`,
  `target=<stored name>`, `detail="'<old>' -> '<new>'"`, `source=<persisted source>`.
- Direct `KnowledgeSystem.set_status` writes no event (existing L4 convention).
- Injected failure at the event insert, at the UPDATE, or right after it rolls everything back (no status/
  version change, no orphan event, no version gap afterwards). Older events are never modified.

## Interactions (unchanged behavior, pinned by tests)
- `get`, `resolve_name`, `all`, `search`, `relationships_for`, `recall` do **not**
  filter by status; inactive records remain visible and read-only retrieval writes nothing.
- `teach()` and `correct()` still write `status="active"`, so they **reactivate** an inactive record
  (version + 1, their usual event; a status-only `correct` logs an unchanged-description detail, L2).
  Documented, not changed: use `set_status` for explicit lifecycle control.
- Natural-language learning only touches relationships; an inactive record is not modified. `relate()` to an
  inactive endpoint leaves it inactive.
- Relationships, id, description and history survive `active -> inactive -> active`; close/reopen preserves
  state, version and events with no reload events.

## Intentional limitations
No deletion, no status filtering in retrieval, no stub<->active/inactive transitions via `set_status`, no
arbitrary custom states, status events carry no source_text/method deltas, no replay/snapshot.
