# Prompt 674 - Section 3: current-knowledge safety of the variation matcher and pattern-meaning binder

**Result: no genuine current-use defect. No production file was changed.** The direct relationship-store access
noted in Prompt 673 is safe because neither component can reach Knowledge concepts or their status.

## What each component does

- **`LearnedExpressionVariationMatcher.match()`** (`learned_expression_variation_matcher.py`): finds the learned
  language item for an expression (exact match first, never replaced). Only if there is none, it follows an EXPLICIT
  `language_item_relationships` row from another language item whose key equals the expression to a target language
  item. Endpoints of kind `concept` are skipped in code (`related["kind"] != "item" -> continue`); directed
  relationships are honoured only in their stated direction; several candidates give AMBIGUOUS with none picked.
  It has no `KnowledgeSystem` reference.
- **`LearnedPatternMeaningBinder`** (`learned_pattern_meaning.py`): `bind()` explicitly stores a
  pattern -> meaning-item relationship (explicit learning); `resolve()/bindings_for()` read only outgoing
  `pattern_meaning` relationships whose other end is a language item of type `meaning` (`_bound_relationships`).
  Candidates carry `related: []`. It has no `KnowledgeSystem` reference.
- Language items and language relationships have **no lifecycle status column**; only Knowledge concepts have
  `active` / `inactive` / `stub` / legacy status.

## Audited production paths (10)

| # | Path | Category | Inactive / ambiguity exposure |
|---|------|----------|-------------------------------|
| 1 | `Core.match_learned_expression_variation` -> matcher | raw/explicit lookup | language items only; none |
| 2 | `MeaningResolver._resolve` fallback -> matcher (only when no exact item) | current conversational understanding (via `resolve_current`) / raw (`resolve`) | matcher itself none; the matched item's concept links are then filtered by Prompt 673 (`resolve_current`) or labelled (`resolve`) |
| 3 | `DeterministicFallbackBackend._resolve_learned_meanings` -> #2 | current conversational understanding | filtered (Prompt 673) |
| 4 | `LearnedPatternMatcher.match()` variation fallback -> matcher (`item_type=pattern`, literal patterns only) | current conversational understanding | language items only; none |
| 5 | `Core.match_learned_pattern` | raw/explicit lookup | none |
| 6 | `LearnedPatternMeaningBinder.resolve/bindings_for` -> `Core.resolve_pattern_meaning` | raw/explicit lookup | none (no concept endpoints, `related: []`) |
| 7 | `DeterministicFallbackBackend._resolve_pattern_meaning` -> `LanguageUnderstandingResult.learned_pattern_meaning` | current conversational understanding | none |
| 8 | `ResponsePlanner` (`learned_pattern_meaning`, `expression_meanings`, concept references) | planning | receives only #3/#7 output; no inactive evidence |
| 9 | `build_language_guidance` -> `ResponseGenerationContext` -> `InferenceRequest.generation_context` | generated-answer evidence | copies #8; no inactive evidence |
| 10 | `Core.bind_pattern_meaning` -> `bind()` | explicit learning | writes only the relationship between language items; no knowledge read/written |

Reasoning (`ReasoningEngine`) and AEL do not use either component.

## Checks (all hold; pinned by `tests/test_variation_pattern_current_knowledge_prompt674.py`, 19 tests)

- **Source or target concept inactive, active/inactive combinations:** a variation match and a pattern-meaning
  resolution are byte-identical for `active`, `inactive`, `stub` and legacy status of any linked concept.
- **Concept endpoint as variation candidate / binding:** never (`NOT_FOUND`).
- **Traversal:** neither component traverses beyond one explicit language-item link (no multi-hop); the multi-hop
  behaviour in the meaning resolver is the Prompt 673 walk, which does not traverse inactive concepts.
- **Case variants / ambiguous current names:** concept case variants (`Ada`/`ADA`) do not create or resolve
  ambiguity here because concept names are never looked up; ambiguity arises only among language items and is
  reported as AMBIGUOUS with every candidate kept.
- **RESOLVED because of inactive evidence:** a word matched by variation is RESOLVED through the explicit
  language-item link that produced the match; after `resolve_current` no concept entry for an inactive concept
  remains. An inactive concept never makes anything RESOLVED.
- **Planning / guidance / generation context:** contain no inactive concept description when the linked concept is
  inactive (understanding, plan and guidance inspected).
- **Read-only:** none of the read paths writes knowledge, relationships, language rows or learning events.
- **Lifecycle:** active -> inactive -> active transitions and close/reopen give the expected results; stub and
  legacy-status concepts stay current.

## Intentional distinctions preserved

Raw `resolve()` still lists inactive concepts labelled `inactive`; `KnowledgeSystem.get/resolve_name`, AEL ASK/recall,
Prompt 664 learned-context, Prompt 637/672 case-ambiguous learning and explicit teach/correct reactivation are untouched.
No consistency change was made merely to align consumers.

## Remaining limitations

- Language items have no status, so a learned word/pattern/binding cannot be "deactivated"; that would be a new
  lifecycle feature (schema change) and is out of scope.
- If a future change lets the matcher or binder follow concept endpoints, it must use the current-use rules of
  Prompts 667-673 (this prompt's tests would then fail and flag it).
- Raw explicit lookups (`resolve()`, `Core.resolve_language_meaning`) continue to expose inactive concepts by design.
