# Prompt 639 - Correction consistency (Section 3)

Result: the existing correction flow (`LearningSystem.correct` ->
`KnowledgeSystem.correct` -> `learn`) already keeps current retrieval and the
learned-knowledge context consistent, so no production code changed; the
behaviour is now pinned by `tests/test_knowledge_correction_consistency_prompt639.py`.

Data-model facts
- `knowledge` is corrected in place (same row id/name); every reader
  (`get`, `find_by_name_case_insensitive`, `search`, `all`, learned-knowledge
  context, reasoning, `recall`) reads that row. Nothing caches descriptions.
- `relationships` reference items by NAME (from_name/to_name). A correction
  never renames, so relationship rows are untouched (not deleted, recreated
  or rewritten) and none is inferred from corrected text.
- Relationship rows hold no description-derived content, so there is no
  dependent relationship content to update.
- The superseded description lives only in `learning_events` (history/audit).

Known limitation
- Provenance is preserved by design ("None = keep what is stored"). After a
  correction that omits `source_text`, the record's `source_text` (and a
  relationship's own `source_text`) still holds the ORIGINAL sentence, e.g.
  "Python is a snake.", next to the corrected description. It is exposed as
  provenance, never as a description/current-fact field. Callers that want
  the correction attributed pass `source_text` (Core's correction path does).
  Changing this would contradict the provenance-preservation rule.
