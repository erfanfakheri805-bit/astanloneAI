# Prompt 664 — Inactive Knowledge Learning and Selection Semantics

## Investigation result
Genuine defect: **yes**. `select_learned_knowledge()` (and therefore `Core.select_learned_knowledge`, and the
`learned_knowledge_context` attached by `Core._attach_learned_knowledge` after the Prompt 502 gate) ignored the
Prompt 663 lifecycle status. An explicitly `inactive` record with valid content was SELECTED and reached response
generation as current knowledge. The Prompt 502 gate only judges relevance/confidence, never status, so it could not
catch it (confidence high or low made no difference). Prompt 663 had pinned this as "unchanged"; that pin is
superseded (test + doc updated).

## Fix (smallest)
`language_intelligence/learned_knowledge_context.py`: a record with stored `status == "inactive"` is not a candidate
(neither in the usable set nor among case-only-duplicate ambiguity candidates). Nothing else changed; public shapes
(`LearnedKnowledgeSelection`, `to_dict`, `to_context`, context dict) are identical.

## Semantics
- Selection/context APIs answer "what knowledge may support CURRENT assistance": inactive is excluded.
- Raw retrieval APIs answer "what is stored": `get`, `resolve_name`, `all`, `search`, `relationships_for`, `recall`
  are unchanged and still return inactive rows. Search ranking, name resolution (637), input validation (660) and the
  lifecycle API (663) are untouched.
- Only the explicit `inactive` state is excluded. `active`, `stub`, and legacy values (e.g. `deprecated`) behave as before.
- Selected/excluded per case: active -> selected; inactive (any confidence) -> NOT_FOUND; active+inactive for one
  query -> only the active one counts (SELECTED, or AMBIGUOUS among actives); inactive-only -> NOT_FOUND;
  inactive with no content -> NOT_FOUND; stub with relationship -> unchanged (selected).
- Case-only duplicates: the name-resolution ambiguity of Prompt 637 is preserved (never silently picks one);
  an inactive duplicate is simply never listed as a candidate.
- Lifecycle: no caching; active->inactive->active flips selection/context immediately, also after close/reopen,
  fresh Core/KnowledgeSystem/LearningSystem. `teach`/`correct` reactivate (write "active") and the record is selected again.
- NL learning: still leaves inactive records untouched (so they stay unselected); related-concept NL learning does not alter them.
- Relationships: never deleted or disabled. An active entry keeps exposing its relationship rows even when the other
  endpoint is inactive (they are stored data of the active entry); an inactive entry with relationships is excluded.
- Read-only: selection/context never change version, timestamps, events, status or relationships (tests snapshot all
  knowledge/relationship/event/language tables); reload generates no events.

## Intentional limitations
- `Core._find_best_known_concept` (raw name/search lookup) and the ReasoningEngine read stored rows through the raw
  retrieval contract and are not changed here.
- (Superseded by Prompt 670.) Relationship rows to inactive endpoints were not filtered from an active entry's context; the context is now current-only.
- No new state, table, deletion, replay or snapshot.
