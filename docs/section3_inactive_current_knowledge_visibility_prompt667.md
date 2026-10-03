# Prompt 667 — Inactive Knowledge Must Not Surface as Current Conversational Knowledge

## Audit result
Genuine production defect: **yes** (the read-only gap recorded in Prompts 664 and 666).

| Read path | Before | After |
|---|---|---|
| `Core._find_best_known_concept` (conversational fallback "Here's what I know about ...") | name lookup via `find_by_name_case_insensitive()` and `search()` — both return inactive rows, so an inactive description was presented as current | inactive rows are not candidates by name or by search; inactive-only -> `None` -> existing "not enough information" fallback |
| `ReasoningEngine._reason` knowledge retrieval (`What is X?`, `Tell me about X`, `What does X use?`, bare name) | inactive record answered from its description, IS_A / relationships, inference and contradiction scan | inactive-only subject -> `STATUS_UNKNOWN`, message `'X' is not in the knowledge base yet.`; no description, relationship, inference or contradiction is read for it |
| `Core.process_input` step 3/4 and `Core.reason` | consumed the two paths above | inherit the fix (no change needed in them) |
| `select_learned_knowledge` (Prompt 664) | already excludes inactive | unchanged |

## Production changes (smallest possible)
- `knowledge/knowledge_system.py`: two **new** read-only methods, `resolve_current_name(name)` and `find_current_by_name_case_insensitive(name)`. Same lookup order as `resolve_name()` (exact wins, else single case-insensitive, else ambiguous) but records with `status == "inactive"` are not candidates. Extra status `"inactive"` = nothing current matched but an inactive record did. Raw APIs untouched.
- `core/core.py`: `_find_best_known_concept` uses the current-use lookup and skips inactive rows in the `search()` fallback (`limit=None`, i.e. the existing 200-row cap, so inactive rows cannot crowd out an active one). Return shape unchanged (a record dict or `None`).
- `reasoning/reasoning_engine.py`: `_reason` resolves the subject via `resolve_current_name`; the `"inactive"` outcome returns the existing UNKNOWN result early.

## Semantics confirmed
- Active knowledge: fully available. Stub and legacy statuses (e.g. `deprecated`): unchanged (only the literal status `"inactive"` is excluded).
- Active + inactive both matching: the active one is considered; an inactive exact-case record no longer shadows an active case-variant, and an inactive case-variant no longer causes ambiguity.
- Several active matches: ambiguity semantics unchanged (record `None`, nothing silently chosen).
- Inactive only: never returned as current knowledge, no fabricated "known" answer; follows the existing no-match fallback.
- Holds after close/reopen and across active -> inactive -> active transitions; `teach(name)` / `correct(name)` still reactivate; NL learning still leaves inactive records inactive.
- Raw `get()`, `all()`, `search()`, `resolve_name()`, `find_by_name_case_insensitive()`, `relationships_for()`, `ReasoningEngine.lookup()` still return inactive rows.
- Reads write nothing: knowledge, relationship and learning-event tables are identical before/after.

## Tests
`tests/test_inactive_current_knowledge_visibility_prompt667.py` (33 tests): active-only, inactive-only (fallback text, `_find_best_known_concept`, search-by-description, reasoning what-is/relation/bare), active+inactive (different names, case variants both directions), active ambiguity (with and without an inactive third), stub / legacy status, lifecycle transitions and reload, teach/correct reactivation, NL learning, inactive relationship endpoint, raw API preservation, no mutation / no events, failure paths (reasoning never raises; search errors propagate unchanged; input-boundary contract unchanged). Against the pre-fix production code 23 of the 33 fail.

## Intentional limitations
- (Superseded by Prompt 668 for reasoning/inference.) Relationship rows are not filtered by endpoint status: an active subject may still answer through a relationship whose other endpoint is inactive (Prompt 663/665 contract), and multi-hop inference may traverse such an endpoint. Only the queried subject's own status gates its answer.
- Only `Core._find_best_known_concept` and `ReasoningEngine._reason` were changed. Explicit AEL `ASK`/`RECALL`, `LearningSystem.search()`, `ConceptSystem.get()` and `ReasoningEngine.lookup()` are explicit/raw reads and keep their contracts.
- `check_consistency()` (diagnostic scan over `all()`) still includes inactive names.
- A subject that is not a stored record at all keeps the existing flow (relationship-only answers by name), unchanged.
