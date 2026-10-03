# Prompt 670 - Section 3: learned_knowledge_context vs the current lifecycle

## Trace
`Core._attach_learned_knowledge` -> `select_learned_knowledge` (Prompt 501/664) -> Prompt 502 reliability gate
(`_evidence_records` counts every relationship row's confidence as evidence) -> `understanding.learned_knowledge_context`
-> `ResponseGenerationContext` -> `InferenceRequest.generation_context.to_dict()` -> a configured local-model
backend; text it generates (`is_generated`) is returned directly as the reply. With the default
`DeterministicFallbackBackend` the step is deferred and nothing in Core reads the rows itself.

## Classification
1. Raw context? The rows are carried unchanged by ResponseGenerationContext/requests.
2-4. But the context is the designated channel for handing "directly relevant learned knowledge" to generation as
current knowledge (Prompt 664 already excludes inactive entries for that reason), the rows feed the gate's
reliability decision, and a generating backend can state them as facts. **Genuine current-use defect:** a row to an
inactive endpoint could influence a generated answer and count as gate evidence.

## Fix (selection/context boundary only)
- `language_intelligence/learned_knowledge_context.py`: `_current_relationships()` uses
  `KnowledgeSystem.current_relationships_for()` (Prompt 668; raw fallback for test doubles) for both the exposed rows
  and the "has content" check. Context structure and public shapes unchanged.
- Consequences: rows to/from inactive endpoints are omitted from the context and the gate evidence; a description-less
  entry whose only rows touch inactive endpoints has no current content and is not selected. Immediate on
  active -> inactive -> active; identical after close/reopen (nothing cached).
- Not changed: `relationships_for()`, `recall`/AEL ASK (Prompt 669 raw recall), `relate()`, `set_status()`,
  `teach()`/`correct()` reactivation, entry selection/ambiguity (Prompt 664), Prompt 668 reasoning, stored rows.

## Tests
`tests/test_learned_knowledge_context_lifecycle_prompt670.py` (17 tests; 7 fail against the pre-fix code). The Prompt 664
test that pinned "rows kept" was updated (stored rows still kept; context rows are current-only) and its doc line marked
superseded.

## Intentional limitations
- Only status `"inactive"` is excluded; active/stub/legacy statuses behave as before.
- The context is still a stored-data snapshot (descriptions/rows as stored); no inference is added.
