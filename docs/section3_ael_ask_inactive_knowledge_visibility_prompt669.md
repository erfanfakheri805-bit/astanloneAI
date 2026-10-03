# Prompt 669 - Section 3: AEL ASK vs the current-knowledge lifecycle

## Audit (traced call graph)
`Core.process_input("ASK X")` -> parser kind `ael` -> `AELInterpreter._execute_ask` -> `LearningSystem.recall(X)` ->
`ConceptSystem.get_with_relations` -> `KnowledgeSystem.get(X)` (exact, case-sensitive) + raw `relationships_for(X)`.
Rendering is a literal listing: `"<name>: <description>"` then one `"  A REL B"` line per stored row (outgoing,
then incoming). No inference, no name resolution, no answer synthesis, no reload-specific state.
The only interpreted output is the contradiction NOTE, produced by `ReasoningEngine.contradictions_for()`,
which is current-only since Prompt 668.

## Contract found: A - explicit RAW recall
- Established by code (recall == raw `get` + raw `relationships_for`), by Prompt 663 (retrieval does not filter by
  status; inactive rows stay visible), by Prompt 667 docs (explicit AEL `ASK`/`RECALL` are raw reads that keep their
  contract) and by existing tests (`test_learning_pipeline` asserts ASK shows stored relation rows; `test_core` /
  `test_reasoning_engine` pin the `[AEL OK]` output and the NOTE).
- ASK never presents a stored row as an inferred/current answer, and is never reached by conversational or
  reasoning paths, so no inactive endpoint can contribute to a current answer through it.
- **No genuine defect; production code unchanged.** Changing ASK to filter rows would alter the pinned AEL output
  contract and hide stored data the user explicitly asked to inspect.

## Confirmed behavior
- Active subject + active endpoint: exact listing, unchanged. Unknown / wrong-case name: "I don't know anything
  about '<name>' yet." Stub and legacy-status records: unchanged.
- Inactive subject, source or target: still readable; every stored row is listed. Multi-hop chains are not
  traversed by ASK (one stored hop per row), so nothing passes through an inactive node.
- Contradiction NOTE: shown only when the contradicting rows are current (subject and endpoint not inactive);
  dropped when either is inactive, restored on reactivation. Reasoning (`reason()`, Core replies) stays current-only.
- Transitions active -> inactive -> active and close/reopen behave identically (nothing cached).
- ASK writes nothing: no knowledge/relationship changes, no learning events. `relationships_for`, `recall`, `get`,
  `relate`, `set_status` unchanged; rows are never deleted.

## Tests
`tests/test_ael_ask_inactive_knowledge_visibility_prompt669.py` (16 tests): exact output, unknown/case names,
stub/legacy, inactive target/source/subject, recall == raw retrieval, raw recall vs current inference, no multi-hop,
NOTE behavior and transitions, reopen, no mutation/events, raw APIs, output shape.

## Intentional limitations
- ASK output does not label inactive rows; it is a raw stored-data listing by design. A current-only view of
  relationships is available via `KnowledgeSystem.current_relationships_for()` and the reasoning engine.
- ASK is exact-case (Prompt 637 case-insensitive resolution is not applied to it).
