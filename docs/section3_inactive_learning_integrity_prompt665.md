# Prompt 665 — Learning Against Inactive Knowledge Integrity

## Investigation
Traced `learn_from_text` -> `understand` -> `LearningSystem.learn_from_understanding` -> `_resolve_concept_name` ->
`relate` (only relationships are written; missing endpoints become stubs, existing records are never updated),
`teach` (`ConceptSystem.define` -> `KnowledgeSystem.learn`, writes `active`), `correct` (writes `active`),
`set_status`, `relate`, and Core's conversational correction path (`process_input` -> `_apply_resolved_correction_to_knowledge`).

## Genuine defect: yes (one)
`Core._apply_resolved_correction_to_knowledge` picks its target IMPLICITLY: it scans `knowledge.all()` for the one
description containing the corrected text ("not a snake, I mean a programming language."). Because `correct()` writes
`active`, an inactive record matched this way was silently rewritten AND reactivated (version + 1, "correct" event)
although the user never named it. Fix (smallest): that scan skips records with `status == "inactive"`
(`core/core.py`, one guard). Consequences: an inactive-only match writes nothing; if one active and one inactive
record both match, the active one is the single target (previously the ambiguity wrote nothing). Explicit
`LearningSystem.correct(name, ...)` is unchanged and still reactivates.

## Pinned behavior (unchanged, now tested)
- **NL learning**: touches relationships only. An inactive record keeps status, version, updated_at, description and
  provenance for same-concept / updated-description / related-concept / repeated / with-relationships inputs; the only
  events are `relate` events for actual relationship changes; an identical repeat is a true no-op. Stays unselectable (664).
- **teach(name, ...)**: same record (id kept, no duplicate), status `active`, version + 1, one `teach` event; `None`
  confidence / source_text / learning_method keep stored values. Identical description still reactivates once
  (status differs); a further identical teach is a no-op. Immediately selectable (664). Relationships intact.
- **correct(name, ...)**: same record (case-variant names resolve to it), status `active`, version + 1, one `correct`
  event whose detail is `'old' -> 'new'` (old description lives only in event history), persisted source logged.
- **set_status**: `inactive -> inactive` and `active -> active` are no-ops (no version/event). Following any sequence with
  NL learning, relate or the implicit correction never changes status; only teach/correct/set_status do.
- **Relationships**: `relate()` to an inactive endpoint (outgoing or incoming) creates/updates the relationship row and
  logs `relate`, and leaves the endpoint inactive and untouched (no version bump). Repeats are no-ops with no event;
  metadata changes update the one row and log one event. Relationships are never disabled or removed.
- **Atomicity (Prompt 645 scope)**: injected failures at the event insert, before/after `UPDATE knowledge`, and
  before/after `INSERT INTO relationships` for teach, correct and relate leave all tables unchanged and cause no version
  gap. NL learning reports a persist error (existing contract, never raises) and leaves no partial state.
- **Reload**: inactive stays inactive; teach/correct reactivation persists and is selectable; reload writes nothing.

## Intentional limitations
- `teach()`/`correct()` by explicit name reactivate; use `set_status` for lifecycle-only control.
- `relate()` may attach relationships to an inactive endpoint; they are stored data and not filtered.
- Direct `relate()` with a case-variant name that does not exist exactly creates a stub (existing Prompt 636/637 behavior).
- No new subsystem, table, deletion, replay or snapshot.
