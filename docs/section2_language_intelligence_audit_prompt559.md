# Section 2 Language Intelligence Architecture/Capability Audit (Prompt 559)

Read-only audit. Structured, machine-checkable data lives in
`app/src/main/python/diagnostics/section2_language_intelligence_audit.py`,
covered by
`app/src/main/python/tests/test_section2_language_intelligence_audit.py`.
No application behavior was changed to produce this audit.

Roadmap position: Section 2 of 10 - Language Intelligence and Request
Understanding, current position Prompt 559 (audit only; no
implementation this prompt).

## Total language-intelligence files inspected

74 files under `language_intelligence/` (73 excluding `__init__.py`).

## Method

For each finding, "integrated" means traced by an actual import-graph
reachability check from the 13 names `core/core.py` imports directly
from `language_intelligence` (lines ~92-107), cross-checked against the
real call sites in `_handle_conversation` / `process_input`.
"Not integrated" means grep-confirmed zero importers outside
`language_intelligence/` and `tests/` at audit time. A static script
walked every `.py` file's `from .X import` / `from language_intelligence.X
import` lines and computed the transitive closure reachable from Core's
13 roots:

- **37 of 73** files reachable (implemented_and_core_integrated /
  partially_implemented)
- **36 of 73** files not reachable (implemented_but_not_core_integrated)

## Current request-processing path

```
USER INPUT (raw_text)
  -> Core.process_input -> InputSystem.normalize
  -> Core.process_input -> Parser.parse (kind: ael | other)
       ael branch    -> Core._handle_ael -> AELInterpreter.run -> reply
       other branch  -> Core._handle_goal_or_conversation
         -> planning.goal_detection.is_goal_oriented(text)
              goal-oriented     -> Core.create_goal -> "GOAL CREATED" reply
              not goal-oriented -> Core._handle_conversation
                1. SkillSystem.find_matching_skill (short-circuits if matched)
                1b. context/relevance.py, message_reference_resolution.py,
                    active_topic.py (read-only)
                1c. LanguageIntelligenceCore.understand(...)
                    -> LanguageUnderstandingResult (recorded; does not
                       select the branch taken below)
                1d. LanguageIntelligenceCore.generate_response(...)
                    -> ResponseGenerationResult; if is_generated, returns
                       response_text directly (never happens with the
                       default DeterministicFallbackBackend)
                2. Core.learn_from_text -> UnderstandingEngine +
                   LearningSystem (returns early if something new learned)
                3. ReasoningEngine.reason(text) (returns early if
                   STATUS_ANSWERED)
                4. KnowledgeSystem concept lookup fallback
                5. Core._construct_fallback_reply
  -> Core.process_input -> memory.log_message + context.add_turn
RESPONSE (string) returned to caller
```

**Where Language Intelligence enters:** steps 1c/1d of
`_handle_conversation`, on every message that reaches that method (i.e.
not an AEL command, not goal-oriented, not matched by a keyword skill).

**Where it is bypassed:** AEL commands and goal-oriented requests never
reach it at all (they return earlier). For everything else it is called,
but - see `partially_implemented` below - with today's default
configuration it never supplies the actual reply text; the reply comes
from steps 2-5 instead.

## 1. Implemented and Core-integrated

- `LanguageIntelligenceCore.understand(...)` — called on every eligible
  message; result recorded as `last_language_understanding`.
- `LanguageIntelligenceCore.generate_response(...)` — called on every
  eligible message; short-circuits the reply only if a backend reports
  `is_generated`.
- Ambiguity handling (`response_planning.py`'s `STATUS_AMBIGUOUS`,
  consumed by `learned_response_pattern_selection.py`) — part of the
  reachable subgraph.
- `Core`'s public pattern/meaning API surface (`match_learned_pattern`,
  `teach_sentence_pattern`, `bind_pattern_meaning`,
  `resolve_pattern_meaning`, `extract_sentence_structure`,
  `resolve_language_meaning`, `disambiguate_learned_meaning`) — each
  delegates directly to a `language_intelligence` instance built in
  `Core.__init__`.
- Goal/intent classification inside `DeterministicFallbackBackend`
  (read-only labeling, confirmed never to call `Core.create_goal`).

## 2. Implemented but not Core-integrated (36 files)

- **correction_application pipeline** (11 files): `correction_
  application.py` and its `candidate`, `candidate_readiness`, `guarded`,
  `request`, `result`, `result_usability`, `result_validation`,
  `target_validation`, `verification`, `verification_result` siblings.
  Not reachable from Core; 14 dedicated tests exercise them in isolation.
- **correction feedback / learning handoff** (11 files): `correction_
  feedback_record*.py`, `correction_learning_*` adapters/handoff/
  eligibility/retrieval/storage modules. Not reachable; individually
  tested.
- **correction lookup family** (3 files): `correction_lookup_context.py`,
  `_selection.py`, `_usability.py`. Not reachable — the corresponding
  `correction_lookup_context` transport field in `response_generation_
  context.py` is never given a non-`None` value on a real Core call.
- **verified_correction_response family** (6 files): `input`,
  `input_adapter`, `input_extraction`, `input_usability`, `instruction`,
  `instruction_adapter`. Not reachable. `DeterministicFallbackBackend.
  generate_response` accepts a `verified_correction_instruction`
  parameter "for interface parity" but its own comment says it is "not
  used."
- **corrected_response_target / context** (2 files): not reachable
  (distinct from `corrected_response_target_selection.py`, which IS
  reachable — see integration gaps).
- **correction_understanding_result family** (3 files): `result.py`,
  `result_completeness.py`, `result_validation.py`. Not reachable,
  although `correction_understanding.py` itself is (only its `_is_blank`
  helper is used).

## 3. Partially implemented

- **`LanguageIntelligenceCore` response generation**: called on every
  message (integrated), but `Core`'s own comment states that with the
  only default-configured backend, "this always reports
  STATUS_DEFERRED... ordinary conversation is completely unaffected."
  Confirmed in source: `DeterministicFallbackBackend.generate_response`
  unconditionally returns `STATUS_DEFERRED`; `STATUS_GENERATED` is not
  even imported by that file.
- **`local_model_backend.py`**: only wired in if
  `Core.use_local_language_model(...)` is explicitly called; never
  constructed by default and nothing else calls it automatically.
- **`response_generation_context.py`'s correction transport fields**:
  the context object carries `correction_application_candidate`,
  `correction_application_result`, `correction_lookup_context`, and
  reads them via `getattr(understanding, ..., None)` — but a project-
  wide grep found no code outside the correction-pipeline modules
  themselves that ever assigns them, so on every real Core-driven call
  they are `None`. The project's own `*_in_response_generation.py` test
  files document this explicitly as "transport only."

## 4. Diagnostic/test-only

No dedicated diagnostics-only chain (analogous to Section 1's
`learned_knowledge_statistics.py`) was found in `language_intelligence/`
at audit time. The nearest analogues are the result-validation/
usability wrapper modules, which are listed under
`implemented_but_not_core_integrated` and
`redundant_or_overlapping_components` instead, since they validate their
own package's data rather than functioning as a separate diagnostics
add-on layer.

## 5. Integration gaps

- `understanding/` never calls anything in the `correction_application_*`
  family, so no `CorrectionApplicationCandidate` is ever produced for
  `response_generation_context.py`'s transport field to carry.
- `corrected_response_target_selection.py` is reachable and integrated,
  but its similarly-named siblings `corrected_response_target.py` and
  `corrected_response_target_context.py` are not imported by it or
  anything else reachable from Core.
- `agent/agent_loop.py` has zero references to `language_intelligence` —
  the self-upgrade/code-change pipeline does not use language
  understanding, correction, or response generation at all.
- `correction_feedback_learning_input_adapter.py` and `correction_
  learning_input_storage.py` exist to hand data to `learning/`, but
  since nothing upstream of them is reachable from Core, they are never
  invoked on a real request; `learning/learning_system.py` does not
  reference them.

## 6. Important missing capabilities

- No backend configured by default ever returns `STATUS_GENERATED`; a
  useful request-understanding foundation needs either a real
  text-generation-capable backend on this path, or an explicit decision
  that it stays deferred-only for now.
- No call path exists from `understanding/` to
  `correction_application_candidate.py`, so the existing correction/
  verification pipeline cannot currently do anything on a real request.

## 7. Redundant or overlapping components (not modified this prompt)

- **`correction_application_result` trio** (`result.py`,
  `result_validation.py`, `result_usability.py`): base-then-validate-
  then-judge-usability wrapper pattern, the same shape as Section 1's
  much larger `learned_knowledge_statistics.py` chain, at a far smaller
  scale (3 layers).
- **`correction_understanding_result` trio**: the same 3-layer pattern
  applied to a different base object.
- **`verified_correction_response_input*` vs. `_instruction*`**: 4 files
  and 2 files respectively, both unreachable from Core, with similar
  enough names and adjacent responsibilities (carrying a verified
  correction in vs. carrying an instruction to act on one out) that file
  names alone don't distinguish them.

## Section 2 completion candidates

1. Decide whether the correction/verification pipeline (36 unreachable
   modules) is in scope for Section 2 integration or intentionally
   staged later — this audit found no caller path, not a missing file.
2. If in scope: add the smallest call from `understanding/` (or
   `language_intelligence_core.py`) that builds one real
   `CorrectionApplicationCandidate` and threads it into the already-
   existing `response_generation_context.py` transport fields.
3. Decide whether `DeterministicFallbackBackend` should stay
   permanently deferred-only, or whether a real generating backend
   belongs in Section 2.
4. Resolve the naming/responsibility overlap between `corrected_
   response_target_selection.py` and its unreachable siblings, without
   deleting or refactoring in this prompt.

## Smallest safe integration point

`understanding/` — specifically wherever `UnderstandingEngine` or
`Core._attach_learned_knowledge` already builds attributes read by
`generation_context_from_understanding` via `getattr(..., None)` — is
the smallest safe point to connect the correction pipeline: setting
`understanding.correction_application_candidate` there when a real
correction is detected would reach an already-existing, already-wired
transport field without changing Core's control flow,
`LanguageIntelligenceCore`'s structure, or any other subsystem.

## Recommended next implementation target for Prompt 560 (not implemented here)

Wire a single, minimal call path from a real correction signal (the
existing `understanding/correction_detection.py` candidate already used
by `_build_correction_understanding`) through `correction_application_
candidate.py` into the existing `response_generation_context.py`
transport field — the smallest change that would move the correction
pipeline from `implemented_but_not_core_integrated` to
`implemented_and_core_integrated` for at least one concrete case,
without adding new architecture or touching the Section 1 validator
chain.

## Test results

- New focused tests: 10/10 pass
  (`tests.test_section2_language_intelligence_audit`)
- Relevant existing language-intelligence tests (run as grouped by
  filename pattern): `test_correction*.py` 766/766,
  `test_verified_correction*.py` 180/180, `test_language*.py` 187/187,
  `test_response*.py` 331/331, learned-pattern/meaning/sentence/backend/
  local-model groups 258/258 — all pass.
- Full suite: **10,878 tests, 0 failures, 0 errors** (up from 10,868 at
  the Prompt 558 baseline; +10 new tests, 0 regressions).

## Scope discipline

No rewrite of the language intelligence architecture, no new NLP/LLM
engine, no external AI APIs/internet/cloud/API keys, no changes to any
existing language system, no Core redesign, no changes to the Section 1
validator chain, no programming/game-generation, web automation,
multimodal, voice, or automatic self-modification work. Nothing was
deleted or refactored; the 36 not-integrated files and the noted
redundant/overlapping components were left exactly as found.
