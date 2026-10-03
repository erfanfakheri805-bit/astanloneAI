# Prompt 673 - Section 3: current-knowledge semantics of `meaning_resolution._describe`

## Audited call paths (9)

`_describe` has exactly **one** call site: `MeaningResolver._entry`, reached only from `_collect_related`
(concept endpoints get `description` + `status`; item endpoints get their own meaning/examples).

| # | Path | Uses `_describe` output? | Classification | Result |
|---|------|--------------------------|----------------|--------|
| 1 | `Core.resolve_language_meaning` -> `MeaningResolver.resolve` | yes | raw / explicit lookup | unchanged: inactive concept listed, labelled `status: inactive` |
| 2 | `Core.disambiguate_learned_meaning` -> `resolve` | yes | raw / explicit lookup | unchanged |
| 3 | `DeterministicFallbackBackend._resolve_learned_meanings` (-> `understand_language`, `LanguageUnderstandingResult.learned_meanings`) | yes | **current conversational use** | **DEFECT, fixed** |
| 4 | `LearnedMeaningDisambiguator` on the entries of #3 | derived from #3 | reasoning over current meanings | consistent after fix (receives filtered entries) |
| 5 | `ResponsePlanner` `expression_meanings` / `_concept_references` | derived from #3 | current planning | consistent after fix (no inactive concept name or description) |
| 6 | `language_guidance` -> `ResponseGenerationContext` -> `InferenceRequest.generation_context` | derived from #3 | generated-answer evidence | consistent after fix |
| 7 | `learned_pattern_meaning` binder | no (reads the relationship store directly) | learning/binding target | not applicable, untouched |
| 8 | `LearnedExpressionVariationMatcher` | no (relationship store directly) | matching | not applicable, untouched |
| 9 | Reasoning engine, AEL ASK/recall, `Core._find_best_known_concept` | no (no resolver use) | see Prompts 663-672 | untouched |

## Genuine defect

For current conversational understanding, a word linked to a Knowledge concept whose status is `inactive`
still (a) carried the concept's description into `learned_meanings` and, through the plan/guidance/generation
context, into the evidence handed to a backend, and (b) could be `RESOLVED` **only** because of the link to the
inactive concept. This contradicts "inactive knowledge must not influence current conversational answers".
The public `resolve()` labelling is not itself the defect; the conversational consumer using it unfiltered is.

## Production change (smallest, at the consumer boundary)

- `language_intelligence/meaning_resolution.py`: new `MeaningResolver.resolve_current()` (same signature and
  result shape as `resolve()`); `resolve()` and `resolve_current()` share one `_resolve()`. In current mode
  `_collect_related` skips a relationship whose reached endpoint is a concept with stored status exactly
  `"inactive"` (helper `_is_inactive_concept`, exact-name `knowledge.get`, read-only). A skipped endpoint is not
  reported, not expanded, does not consume `max_related` and cannot make an item RESOLVED.
- `language_intelligence/deterministic_fallback_backend.py`: `_resolve_learned_meanings` calls
  `resolve_current` when the resolver has it, else plain `resolve` (caller-supplied stub resolvers such as the
  one in `test_learned_meaning_in_understanding.py` keep working; Core still passes its own `meaning_resolver`).

No `current=True` layer was added anywhere else; no knowledge API changed; `resolve()` output is byte-for-byte as before.

## Intentional distinctions preserved

- Raw: `resolve()`, `Core.resolve_language_meaning`, `Core.disambiguate_learned_meaning`, `KnowledgeSystem.get/resolve_name`,
  AEL ASK/recall keep returning inactive data (labelled).
- Current: conversational understanding (and everything derived from it) excludes inactive concept endpoints.
- Learning: untouched (Prompt 637/672 case-ambiguous learning may create a new concept; 664 learned-context and
  665/666 inactive-target behaviour unchanged; explicit teach/correct/set_status may reactivate).

## Inactive and ambiguity semantics

- Only status exactly `inactive` is excluded. `active`, `stub` (description `None`), legacy/other status text and a
  concept row that does not exist are kept as before.
- A concept endpoint is an exact stored name, so no name resolution takes place: an inactive `Snake` is **not**
  redirected to an active `snake`, and an inactive `python` does not hide an active `Python`. Ambiguity among
  current case-variants (Prompt 637/667) is a name-resolution property and does not arise for exact endpoints.
- Inactive endpoints are not traversed through (no hop beyond them) and do not count toward the bound.
- All paths are read-only: no knowledge, relationship, language-store or learning-event writes.

## Remaining limitations

- Raw explicit lookups (#1, #2) still show inactive concepts by design; a UI built on them must treat `status` itself.
- A resolver passed to the backend that lacks `resolve_current` is used as-is (its own contract applies).
- Language items have no lifecycle status, so item endpoints are never filtered. The variation matcher (#8) is unchanged.
- Explicit-target learning is not silently skipped for inactive targets (existing semantics).

Tests: `tests/test_meaning_resolution_current_knowledge_prompt673.py` (18 tests, real call paths only).
