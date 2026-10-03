# Prompt 666 — Inactive Implicit-Target Integrity

## Audit result
Genuine new production defect: **no**. Production code is unchanged in this prompt (tests/docs only).

Every knowledge-mutating call site was traced (`grep` of teach / correct / relate / define / link / set_status /
learn_from_understanding across the tree):

| Path | Target selection | Inactive handling |
|---|---|---|
| Conversational correction (`Core._apply_resolved_correction_to_knowledge`) | implicit, by description text | inactive never a candidate (Prompt 665 guard); inactive-only -> nothing written; active+inactive -> the active one; two actives stay ambiguous -> nothing written |
| NL learning (`learn_from_understanding`) | names resolved to existing records (exact, else single case-insensitive) | relationships only; existing inactive record resolved but never written; case-variant reference makes no duplicate; case-duplicates (ambiguous) never pick one - existing Prompt 637 behavior creates a stub with the written casing, existing records untouched |
| `LearningSystem.teach(name)` / `KnowledgeSystem.learn` | explicit exact name | reactivates the named record only (intentional) |
| `LearningSystem.correct(name)` / `KnowledgeSystem.correct` | explicit name, exact else single case-insensitive; ambiguous raises | reactivates that same record (intentional); no write on ambiguity |
| `relate()` (AEL, NL, direct) | explicit endpoints | rows stored/updated; endpoints untouched (Prompt 665 contract) |
| `set_status()` | explicit name | the only lifecycle control; no-op is silent |
| Learned-knowledge selection / context (664) | read-only | never feeds a mutation path; no snapshot change (incl. events, versions) |
| AEL `TEACH` / `RELATE` | explicit names | same as teach / relate |

No helper other than the one fixed in 665 selects a knowledge record for a *write* without an explicit name.

## Tests
`tests/test_inactive_implicit_target_integrity_prompt666.py` (16 tests): correction target rules incl. three-record
mixes, reload, atomic failure on an active target, no write attempt for an inactive one; NL resolution with case
variants / ambiguity / both endpoints inactive; explicit teach / correct / set_status unchanged; selection and context
read-only; full cycle with no hidden transition. The Section 2 `language_item_learned` event that every resolved
correction writes is excluded from knowledge-side comparisons (it is independent of knowledge targeting).

## Intentional limitations
- `Core._find_best_known_concept` (used by the conversational fallback reply "Here's what I know about ...") and the
  ReasoningEngine read stored rows through the raw retrieval contract and can still surface an inactive record in a
  conversational answer. They are read-only, never feed a write, and were left unchanged (same limitation recorded in
  Prompt 664). Aligning them with the 664 "current use" semantics would be a separate, deliberate change.
- Explicit teach / correct by name reactivate; a direct `teach("python")` creates a new record next to an inactive
  `Python` (exact-case identity, Prompt 637).
- Section 2's correction storage handoff writes its own `language_item_learned` event even when the knowledge side declines
  to target anything.
