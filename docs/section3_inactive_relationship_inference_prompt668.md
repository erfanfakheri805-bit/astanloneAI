# Prompt 668 - Section 3: inactive relationship endpoints must not provide current inference

## Audit
Every current-reasoning read in `ReasoningEngine` went through raw `KnowledgeSystem.relationships_for()`:
direct relation answers (`_reason_relation`), the IS_A description fallback (`_reason_what_is`), relationship
summaries (`_reason_generic`, `summarize_relationships`, used by Core's conversational fallback), transitive
DEPENDS_ON/PART_OF closure (`_transitive_closure`), rule premises (`_try_rule`), `traverse`, `find_path`,
`contradictions_for` (also used by `reason()` and AEL ASK) and `check_new_relationship`. Prompt 667 only gated the
queried subject, so an active subject answered through an inactive endpoint and multi-hop chains passed through
inactive knowledge. **Genuine defect: yes.**

## Fix (read/inference boundary only)
- `knowledge/knowledge_system.py`: new read-only `KnowledgeSystem.current_relationships_for(name)` - same
  `{"outgoing", "incoming"}` shape as `relationships_for()`, dropping rows whose other endpoint (or `name` itself)
  has stored status `"inactive"`. Endpoints with active / stub / legacy status or no record are kept.
- `reasoning/reasoning_engine.py`: new `_current_rels()` (uses the above; falls back to the raw read for test
  doubles) replaces all 10 inference-side `relationships_for()` calls. No return shape changes.
- Not changed: `relate()`, `set_status()`, `relationships_for()`, stored rows, learning events, ambiguity logic.

## Semantics
- A relationship with an inactive source or target provides no IS_A answer, inherited/rule-derived fact,
  contradiction, related-concept summary, or hop in a multi-hop chain. A path containing an inactive endpoint is
  unavailable; a fully active alternative path is still used. If no active path exists the existing UNKNOWN
  outcome is returned (nothing fabricated).
- Nothing is cached: active -> inactive -> active is reflected immediately, and after close/reopen. Reactivation
  restores behavior without recreating relationships. Relationships to inactive endpoints are still stored.

## Tests
`tests/test_inactive_relationship_inference_prompt668.py` (26 tests): active/active, active->inactive,
inactive->active, inactive->inactive, direct IS_A, multi-hop, inactive intermediate/source/target, rule premises,
active alternative path, all-paths-inactive, contradictions, transitions, reopen, no deletion, raw API preserved,
no mutation/learning events from reads, stub/legacy status, ambiguity. Against the pre-fix code 16 of 26 fail.
`test_inactive_current_knowledge_visibility_prompt667.py`: one test that pinned the old limitation
(`..._still_answers`) was updated to the new semantics.

## Intentional limitations
- `learned_knowledge_context` (Prompt 664) still passes an active entry's stored relationship rows through as
  context, per its documented and tested contract; it is not an inference path and was left unchanged.
- AEL ASK (`_execute_ask`) still prints raw recalled relationship rows (raw retrieval); only its contradiction NOTE
  lines are now current-only.
- `check_new_relationship` ignores inactive endpoints, so no contradiction warning is raised against them; the
  new relationship is still stored.
- Only status `"inactive"` is excluded; no other status is treated specially.
