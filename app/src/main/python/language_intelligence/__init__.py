"""
Language Intelligence
=======================
Prompt 397: the first Language Intelligence Core - a small, focused
boundary layer between the existing conversational systems (Parser,
Understanding Engine, Context, Memory, Knowledge, Reasoning, Response
Construction - all in core/core.py and their own packages) and a
*future* real language-understanding/generation engine (most likely an
on-device/local language model, not built in this stage).

This package intentionally contains almost no new intelligence. It
reuses, wraps, and structures what the existing Understanding Engine
and Context systems already produce - see
language_intelligence_core.py's own module docstring for the exact
reuse map. What it adds is a *stable shape* three things can agree on:

    a caller (Core, a test, a future UI)
        -> LanguageIntelligenceCore.understand(...)
        -> LanguageUnderstandingResult   (language_understanding_result.py)

    a caller
        -> LanguageIntelligenceCore.generate_response(understanding, ...)
        -> ResponseGenerationResult      (response_generation.py)

and one small, explicit interface (`LanguageIntelligenceBackend`,
backend.py) that both today's deterministic fallback
(deterministic_fallback_backend.py) and a future local-model backend
(local_model_backend.py - connected in Prompt 398 to the local-model
runtime boundary described below) implement identically. Swapping the
backend a `LanguageIntelligenceCore` is constructed with is the *only*
thing a future local model integration needs to do - Core, Memory,
Context, Planning, Execution, and Self-Upgrade are never touched by
that swap.

No cloud AI API, API key, or network call exists anywhere in this
package. No huge model is downloaded or bundled here. The only backend
that actually runs today is the deterministic one, which is exactly as
capable (and exactly as limited) as the existing Understanding Engine
it wraps - see that backend's own module docstring for precisely what
it does and does not claim to understand.

Prompt 398 - Local Language Model Runtime Foundation
-------------------------------------------------------
    LocalLanguageModelBackend            (local_model_backend.py)
      -> LocalModelRuntime               (local_model_runtime.py)
           configuration: local_model_config.LocalModelConfig
           request/result: inference.InferenceRequest / InferenceResult
           today's only concrete runtime: unavailable_runtime.
             UnavailableLocalModelRuntime - an explicit "no engine
             installed" state, NOT a model
      -> (future) a real on-device engine subclass -> a local model

No real model or inference engine exists in this project yet; see
docs/local_model_runtime.md for exactly what is required and how it
will be connected. The deterministic fallback remains a separate
backend and is never used to answer for the local-model backend.

Prompt 399 - Real backend -> runtime integration
-------------------------------------------------------
    local_model_mapping.py    the ONE explicit translation point:
                              LanguageUnderstandingResult/context ->
                              InferenceRequest, and InferenceResult ->
                              ResponseGenerationResult (+ safe metadata)
    LocalModelRuntime.availability() / LocalLanguageModelBackend.
    check_availability()      structured ModelAvailability (configured,
                              enabled, runtime_available, loadable, loaded,
                              can_infer) - never loads, never infers
No fake model output, cloud call, API key, or download was added; the
deterministic fallback is still a separate backend.

Prompt 400 - Local model provider / adapter layer
-------------------------------------------------------
    LocalLanguageModelBackend -> LocalModelProvider -> LocalModelRuntime
    local_model_provider.py   LocalModelProvider (interface),
                              RuntimeBackedProvider (pure delegate to a
                              LocalModelRuntime), ProviderRegistry
                              (register / select / default), ModelInfo
                              (honest model metadata; unknown = None)
A future local model = one more provider registered in a registry; nothing
above the backend changes. No provider other than test doubles exists, and
none produces text without a real model.

Prompt 401 - Multilingual / Persian language readiness
-------------------------------------------------------
    user message (verbatim) -> LanguageContext -> LocalModelProvider
    language_context.py       LanguageContext (original text, detected
                              language + confidence, scripts present,
                              conversation / requested / response
                              language), build_language_context,
                              resolve_response_language (explicit request
                              > conversation > detection > default),
                              canonical_language
    LanguageUnderstandingResult.language_context and
    InferenceRequest.language_context carry it next to - never instead of
    - the original text; ModelInfo / LocalModelConfig can DECLARE
    supported languages, scripts, multilingual and default language
    (unknown stays None). understanding/language_detection.py now counts
    letters only (not digits/punctuation) and ignores code/URLs.
No language model, translation, canned reply, cloud call, API key or
download was added; Persian ability must come from a real local model.

Prompt 416 - Language Learning Foundation
-------------------------------------------------------
    language_learning_store.py   LanguageLearningStore / LanguageLearningItem -
                                 record and retrieve structured words,
                                 phrases and sentence patterns, one
                                 language/locale at a time, backed by ONE
                                 more MemorySystem table (schema migration
                                 5) - not a second memory system. Reuses
                                 canonical_language() (Prompt 401) for the
                                 language/locale field and the same
                                 "look up, then UPDATE or INSERT"
                                 deterministic-identity shape
                                 KnowledgeSystem already uses. Core owns
                                 one instance (self.language_learning) via
                                 two thin passthrough methods
                                 (learn_language_item / get_language_item).
No grammar for any specific language is hard-coded here; meaning,
examples and relationships are caller-shaped JSON, not a fixed schema.
This is a storage foundation for a future learning module, not a
natural-language learner itself.

Prompt 417 - Learned Language Relationships
-------------------------------------------------------
    language_relationships.py    LanguageRelationshipStore - structured,
                                 persistent links between learned items
                                 (synonym, antonym, translation, related
                                 meaning, example usage, grammatical
                                 relation, word -> phrase, phrase ->
                                 sentence pattern, concept -> expression,
                                 or any caller-chosen relation_type -
                                 the RELATION_* constants are only
                                 suggestions). An endpoint is a Prompt 416
                                 item (any item_type, so phrase -> meaning
                                 and expression -> concept work, not just
                                 word -> word) or an existing Knowledge
                                 concept. Backed by ONE more MemorySystem
                                 table (schema migration 6) with real
                                 foreign keys, so a relationship can never
                                 point at something that was not learned;
                                 endpoints are never auto-created. The
                                 existing Knowledge `relationships` table
                                 could not be reused (its foreign keys only
                                 reach knowledge names, and relate()
                                 auto-creates stubs) - it is left
                                 untouched. Repeating a relationship
                                 refreshes its metadata instead of
                                 duplicating it; symmetric relationships
                                 are stored once and retrievable from
                                 either side; results can be filtered by
                                 language/locale. Core owns one instance
                                 (self.language_relationships) via
                                 relate_language_items /
                                 get_language_relationships.
Nothing is invented: no synonym, translation or grammar is supplied by
this package - it only stores and returns what a caller taught it.

Prompt 418 - Learned Meaning Resolution
-------------------------------------------------------
    meaning_resolution.py        MeaningResolver / MeaningResolutionResult -
                                 given an expression (word, phrase,
                                 pattern), report what has been LEARNED it
                                 means: the matching Prompt 416 item(s),
                                 their stored meaning/context, and - via a
                                 small, bounded, deterministic walk over
                                 the Prompt 417 relationships - related
                                 translations, related meanings and
                                 Knowledge concepts. Status RESOLVED or
                                 NOT_FOUND (with a reason: unknown
                                 expression, or a known one with no
                                 learned meaning). Language-aware: the same
                                 written form in two languages stays two
                                 separate meanings, never merged; several
                                 matches stay distinguishable. Read-only
                                 and storage-free - it composes the
                                 existing stores (one read-only addition,
                                 LanguageLearningStore.find_items) and the
                                 Knowledge System; Core owns one instance
                                 (self.meaning_resolver) via
                                 resolve_language_meaning.
This is a lookup over learned data, not a language model or an NLU engine:
no parsing, fuzzy matching, inference or invented meaning.

Prompt 419 - Learned Meaning in Message Understanding
-------------------------------------------------------
    deterministic_fallback_backend.py   understand() now optionally
                                        takes a `meaning_resolver`
                                        (Core passes its own
                                        self.meaning_resolver, Prompt
                                        418 - never a second instance)
                                        and, for each candidate
                                        expression the existing
                                        Understanding Engine already
                                        found (`UnderstandingResult.
                                        entities` - REUSED, nothing
                                        re-extracted), asks it what has
                                        been LEARNED that expression
                                        means.
    language_understanding_result.py    LanguageUnderstandingResult
                                        gains one field,
                                        `learned_meanings`: a list of
                                        `MeaningResolutionResult.
                                        to_dict()` (Prompt 418, one per
                                        expression looked up) -
                                        RESOLVED entries carry the
                                        matched item's stored meaning,
                                        confidence, source/context and
                                        any relationships followed;
                                        NOT_FOUND entries carry none of
                                        that, so an unresolved
                                        expression is never presented
                                        as understood. `[]` when no
                                        resolver is configured (every
                                        caller/test from before this
                                        stage is unaffected) or when
                                        the message has no candidate
                                        expressions.
The original message is never altered, translated or normalized by this
stage; a lookup uses the language this same call already detected, and
searches every language when detection was undetermined - an expression
is never assumed to mean the same thing in every language. No parser,
grammar engine or dictionary was added; this stage only connects two
already-existing systems (understanding/, Prompt 418) and is bounded and
deterministic, exactly like the resolver it calls.

Prompt 424 - Learned pattern meaning binding
-------------------------------------------------------
    learned_pattern_meaning.py  LearnedPatternMeaningBinder: `bind()` links
                                a taught sentence pattern (Prompt 423) to a
                                caller-NAMED meaning/intention - the
                                meaning is an item_type="meaning" item
                                (Prompt 416), the link a Prompt 417
                                relationship (`pattern_meaning`) carrying
                                its own locale, examples, confidence,
                                source and learning context. `resolve()`
                                reads the meaning bound to the pattern a
                                Prompt 421 match recognized, keeps that
                                match and its variables whole, and hands
                                several bound meanings to the existing
                                Prompt 420 disambiguator (AMBIGUOUS when
                                context cannot tell).
    language_understanding_result.py  one more additive field,
                                `learned_pattern_meaning`.
Nothing is inferred: a pattern with no bound meaning is reported
NOT_FOUND. No new store, matcher, resolver or disambiguator was added.

Prompt 425 - Structured response planning
-------------------------------------------------------
    response_planning.py        ResponsePlanner: turns the existing
                                LanguageUnderstandingResult into a
                                `ResponsePlan` - what a response must
                                contain, never response text. Status
                                RESOLVED (one explicitly learned meaning),
                                AMBIGUOUS (several learned meanings /
                                patterns undecided - all kept, none
                                picked) or UNRESOLVED (the existing
                                unknown state, reason preserved). Carries
                                the original message, language, locale,
                                meaning, matched pattern, variables,
                                active topic, references, context, the
                                `response_action` ("greet",
                                "provide_information", or one explicitly
                                taught) with required items, and the
                                unresolved requirements. A pure function
                                of the understanding: no store, knowledge
                                or memory is read or written, and an
                                information need is described
                                (`retrieval.performed == False`), never
                                retrieved.
    language_intelligence_core.py   plans every understanding it returns
                                (primary or fallback backend) and stores
                                the plan on `understanding.response_plan`;
                                `plan_response()` plans on demand.
    language_understanding_result.py  one more additive field,
                                `response_plan`.
    response_generation.py      `ResponseGenerationRequest.response_plan`
                                (read-only accessor) - ResponseGeneration
                                itself is unchanged.
See docs/response_planning.md for the plan's fields. No backend (the Local
Language Model one included), no store and no model was changed.

Prompt 426 - Response generation context
-------------------------------------------------------
    response_generation_context.py  ResponseGenerationContext /
                                build_generation_context /
                                generation_context_from_understanding:
                                the bounded, read-only bridge from the
                                existing `ResponsePlan` (Prompt 425) to
                                a backend's generation path - original
                                message, status, response action (only
                                when explicit), meaning, meaning
                                candidates, matched pattern, variables,
                                active topic, references, context,
                                language, locale, unresolved
                                requirements. Nothing is recomputed or
                                invented; an AMBIGUOUS/UNRESOLVED plan's
                                status is preserved and its
                                `response_action` stays None. Deep
                                copies throughout, so mutating a built
                                context (or its `to_dict()`) can never
                                reach the plan, the understanding, or
                                any store.
    response_generation.py      `ResponseGenerationRequest.
                                generation_context` (read-only
                                accessor, built from the same
                                `response_plan` the request already
                                exposes) - works for any backend.
    local_model_backend.py      `generate_response()` also builds this
                                context and forwards it, unmodified, as
                                `InferenceRequest.generation_context`
                                (inference.py) - additional structured
                                input next to the existing prompt
                                construction. Model loading, readiness,
                                resource guards, timeout/cancellation
                                and fallback selection are unchanged.
    deterministic_fallback_backend.py  unchanged: still returns
                                STATUS_DEFERRED and generates no text;
                                the same `ResponseGenerationRequest.
                                generation_context` already makes this
                                available for it too.
This is still no natural-language generation: the context describes
what a response must contain, never response text, and no new
planning, store, or memory/conversation-context system was added.

Prompt 427 - Structured backend generation request
-------------------------------------------------------
    response_generation_request.py  BackendGenerationRequest /
                                build_generation_request /
                                generation_request_from_understanding:
                                the bounded, read-only request a
                                backend's OWN inference-request
                                construction consumes - exactly the
                                `ResponseGenerationContext` (Prompt
                                426) fields PLUS `sentence_structure`
                                (`understanding.
                                learned_sentence_structure`, Prompt
                                422 - the one field a
                                `ResponseGenerationContext` alone
                                cannot supply). Named
                                `BackendGenerationRequest`, not
                                `ResponseGenerationRequest`, to avoid
                                colliding with the existing
                                `ResponseGenerationRequest` accessor
                                (response_generation.py, Prompt 421) -
                                see this module's own docstring.
                                Nothing is recomputed or invented;
                                AMBIGUOUS/UNRESOLVED status and a None
                                `response_action` are preserved
                                exactly as `ResponseGenerationContext`
                                preserves them. Deep copies throughout,
                                so mutating a built request (or its
                                `to_dict()`) can never reach the
                                context, the plan, the understanding,
                                or any store.
    response_generation.py      `ResponseGenerationRequest.
                                generation_request` - a third
                                read-only accessor alongside
                                `response_plan` / `generation_context`
                                - works for any backend.
    local_model_backend.py      `generate_response()` also builds this
                                request and forwards it, unmodified, as
                                `InferenceRequest.generation_request`
                                (inference.py), alongside the
                                still-present `generation_context`
                                field (426, unchanged). Model loading,
                                readiness, resource guards, timeout/
                                cancellation and fallback selection are
                                unchanged.
    deterministic_fallback_backend.py  unchanged: still returns
                                STATUS_DEFERRED and generates no text;
                                the same `ResponseGenerationRequest.
                                generation_request` already makes this
                                available for it too, and it is free
                                to use none of its fields.
Still no natural-language generation and no new planning/context/
conversation system: `BackendGenerationRequest` describes what a
response must contain, in the shape a backend consumes, and nothing
more.

Prompt 428 - Structured response-generation outcome
-------------------------------------------------------
    response_generation_outcome.py  ResponseGenerationOutcome /
                                build_response_generation_outcome():
                                a small, additive, read-only summary
                                built FROM an already-produced
                                `ResponseGenerationResult`
                                (response_generation.py) - never a
                                replacement for its own six statuses,
                                never a second place a caller must keep
                                in sync. Answers one narrow question
                                directly: SUCCESS (real generated
                                text), FALLBACK (a fallback backend is
                                handling a failed/not-ready primary -
                                `fallback_backend_kind`), FAILED (a
                                model failure with no fallback
                                available - `failure_reason` is exactly
                                what the result already carried), or
                                UNRESOLVED (STATUS_DEFERRED /
                                STATUS_NOT_IMPLEMENTED - nothing is
                                guessed at). `language`/`locale` are
                                read from the same `generation_context`
                                (Prompt 426) the caller's own
                                `ResponseGenerationRequest` already
                                exposes. Pure: never calls a backend,
                                never runs inference, never mutates the
                                result or request it is given.
No backend, no `LanguageIntelligenceCore`, and no existing
`ResponseGenerationResult` / `ResponseGenerationRequest` field changed;
this is a read-only summary layer over what already exists.

Prompt 429 - Exposing the structured outcome through the core
-------------------------------------------------------
    language_intelligence_core.py   `LanguageIntelligenceCore.
                                generate_response()` now also builds the
                                Prompt 428 `ResponseGenerationOutcome`
                                from the result it returns and keeps it
                                as `last_response_generation_result`,
                                read via `get_last_response_generation_
                                result()` (same `last_*` pattern as
                                `last_backend_selection`).
                                `generate_response_outcome()` returns it
                                directly. `generate_response()` still
                                returns the same `ResponseGenerationResult`
                                as before - every existing caller,
                                backend selection, fallback marking and
                                failure result is unchanged, and nothing
                                is mutated.

Prompt 430 - Response-generation result validation
-------------------------------------------------------
    response_generation_validation.py  `validate_response_generation_
                                result()` / `ResponseGenerationValidation`:
                                a deterministic consistency check over a
                                `ResponseGenerationResult` and its
                                Prompt 428 outcome (SUCCESS needs text and
                                no failure, FALLBACK needs text and
                                fallback_used, FAILED needs a failure
                                reason and is never a success, UNRESOLVED
                                stays unresolved with no invented text).
                                Reports VALID/INVALID with issue codes and
                                carries the original outcome unchanged.
                                `LanguageIntelligenceCore` records it as
                                `get_last_response_generation_validation()`;
                                it changes no result, text or routing.

Prompt 431 - Unified conversation response
-------------------------------------------------------
    conversation_response.py    `ConversationResponse` /
                                `build_conversation_response()`: one small,
                                immutable value for the final conversational
                                response (response_text, status SUCCESS /
                                FALLBACK / FAILED / UNRESOLVED, language,
                                locale, backend_kind, fallback_used,
                                failure_reason, metadata, plus Prompt 430
                                validity and the underlying result's own
                                fields), derived deterministically from a
                                `ResponseGenerationResult` via its outcome
                                and validation - no text is invented and no
                                internal state is shared.
                                `LanguageIntelligenceCore` exposes it as
                                `get_last_conversation_response()` /
                                `generate_conversation_response()`;
                                `generate_response()` is unchanged.

Prompt 432 - Conversation response classification
-------------------------------------------------------
    conversation_response.py    `ConversationResponse.classification`:
                                NORMAL / FALLBACK / FAILURE / UNRESOLVED,
                                a fixed one-to-one function of the existing
                                `status` (SUCCESS / FALLBACK / FAILED /
                                UNRESOLVED). Convenience only - `status`
                                and every other field are unchanged, and it
                                reaches callers through the same
                                `LanguageIntelligenceCore` conversation
                                response.

Prompt 434 - Learned response pattern selection
-------------------------------------------------------
    learned_response_pattern_selection.py  LearnedResponsePatternSelector /
                                LearnedResponsePatternSelection /
                                select_learned_response_pattern /
                                response_pattern_selection_from_understanding:
                                a small deterministic selector that picks
                                the one already-taught learned response
                                pattern that applies to the language
                                information the response-generation path
                                already has (resolved meaning, sentence
                                pattern, expressions, structure, language,
                                locale, topic, resolved references).
                                Patterns are entries under the
                                `response_patterns` key of a learned
                                item's open stored value (the same place
                                `response_action` is taught) - no new
                                storage, matcher or learning mechanism.
                                RESOLVED (unique strongest candidate),
                                AMBIGUOUS (equally strong candidates, or
                                an undecided understanding - all kept,
                                none picked) or NOT_FOUND (nothing
                                invented). Bounded, read-only, no text.
    response_generation_context.py  `ResponseGenerationContext.
                                response_pattern_selection`: selected
                                right after the Prompt 433 guidance, from
                                the same plan.
    response_generation_request.py  `BackendGenerationRequest.
                                response_pattern_selection`: carried
                                through unchanged.
Prompt 435 - Learned response pattern variable binding
-------------------------------------------------------
    learned_response_pattern_binding.py  LearnedResponsePatternBinder /
                                LearnedResponsePatternBinding /
                                bind_learned_response_pattern /
                                response_pattern_binding_from_understanding:
                                binds the variables of the ONE pattern
                                Prompt 434 selected to values the pipeline
                                already extracted (sentence-structure /
                                pattern variables, or a routed active
                                topic, context topic, resolved reference,
                                learned expression, resolved meaning,
                                language, locale). RESOLVED (every
                                required variable bound), UNRESOLVED
                                (missing variables named, resolved ones
                                kept) - an AMBIGUOUS / NOT_FOUND selection
                                is preserved and never bound. Nothing is
                                guessed, defaulted or rendered; no text is
                                generated. Bounded, read-only, no storage.
    response_generation_context.py  `ResponseGenerationContext.
                                response_pattern_binding`: bound right
                                after the Prompt 434 selection, from the
                                same plan.
    response_generation_request.py  `BackendGenerationRequest.
                                response_pattern_binding`: carried
                                through unchanged.
Prompt 436 - Learned response pattern rendering
------------------------------------------------
    learned_response_pattern_rendering.py  LearnedResponsePatternRenderer /
                                LearnedResponsePatternRendering /
                                render_learned_response_pattern /
                                response_pattern_rendering_from_understanding:
                                substitutes the bound variables of the ONE
                                selected pattern into its own `{{name}}`
                                template - plain single-pass string
                                replacement, no model, no network, no
                                inference, nothing invented. RESOLVED
                                (`rendered_text` set), UNRESOLVED (missing
                                variables named, NO text), AMBIGUOUS /
                                NOT_FOUND (the binding's state preserved,
                                nothing rendered; an empty / invalid
                                pattern is NOT_FOUND). Deterministic
                                learned-response output; bound values,
                                language, locale, pattern id, confidence
                                and source are preserved exactly.
    response_generation_context.py  `ResponseGenerationContext.
                                response_pattern_rendering`: rendered right
                                after the Prompt 435 binding, from that
                                binding.
    response_generation_request.py  `BackendGenerationRequest.
                                response_pattern_rendering`: carried
                                through unchanged, for the existing
                                response-generation layer to read.
Prompt 437 - Learned response integration
------------------------------------------
    learned_response_decision.py  decide_learned_response /
                                LearnedResponseDecision: a small
                                deterministic decision run by
                                LanguageIntelligenceCore.generate_response()
                                BEFORE backend routing. A uniquely selected,
                                bound, rendered learned response that passes
                                the Prompt 430 validation becomes an ordinary
                                ResponseGenerationResult (STATUS_GENERATED,
                                text exactly as rendered, backend_kind
                                "learned_response", metadata.response_source)
                                and no backend is called; anything else
                                (ambiguous / not found / unresolved / failed
                                render / failed validation) falls through to
                                the existing routing unchanged.
    language_intelligence_core.py  `_learned_response()` /
                                `last_learned_response_decision`.
Nothing else changed: the local model runtime/provider, model loading,
readiness, resource limits, timeout/cancellation and backend selection are
untouched; ResponseGenerationResult / ConversationResponse keep their fields.
"""


"""
Prompt 438 - Learned Expression Variation Matching
====================================================================
Goal: let equivalent learned expressions and known language variations be
connected during message understanding and response-pattern selection -
so an expression the system was never taught VERBATIM, but that an
already-stored relationship (Prompt 417) explicitly connects to one it
WAS taught, can still be understood.

New file:
    learned_expression_variation_matcher.py  LearnedExpressionVariationMatcher
                                / ExpressionVariationCandidate /
                                LearnedExpressionVariationMatchResult. A
                                small, deterministic, READ-ONLY layer
                                composing the existing
                                LanguageLearningStore (Prompt 416) and
                                LanguageRelationshipStore (Prompt 417) -
                                no new storage, no new identity scheme.
                                Exact match is tried FIRST and always
                                wins (never replaced); only when it finds
                                nothing does an explicit, already-stored
                                relationship (synonym, translation,
                                related-meaning, grammatical, or any
                                other caller-taught type) get followed -
                                symmetric relationships from either side,
                                directed ones only in their stated
                                direction. STATUS_MATCHED /
                                STATUS_AMBIGUOUS / STATUS_NOT_FOUND;
                                AMBIGUOUS keeps every candidate and picks
                                none; NOT_FOUND is never a guess from
                                spelling or intuition. Bounded
                                (MAX_SOURCE_ITEMS / MAX_CANDIDATES) and
                                deterministic. See that module's own
                                docstring for the full contract.

Integrated as an OPTIONAL, backward-compatible fallback (left unset,
nothing before Prompt 438 changes):
    meaning_resolution.py      MeaningResolver(..., variation_matcher=...).
                                resolve() consults it only when the
                                direct item lookup finds nothing at all;
                                a single variation match continues
                                resolution through the matched item
                                (each meaning entry marked
                                matched_via_variation); an ambiguous or
                                not-found variation result is recorded on
                                the new MeaningResolutionResult.variation_match
                                field for transparency only - it never
                                changes `status` away from NOT_FOUND on
                                its own (nothing here is guessed).
    learned_pattern_matching.py  LearnedPatternMatcher(..., variation_matcher=...).
                                match() consults it only when the
                                existing structural matching (regex over
                                every learned pattern's template) finds
                                no candidate at all, and only for a
                                candidate pattern with NO variable
                                placeholders - extracting variables
                                through a variation is out of this
                                stage's scope. New reasons:
                                REASON_SINGLE_PATTERN_MATCHED_VIA_VARIATION /
                                REASON_MULTIPLE_PATTERNS_MATCHED_VIA_VARIATION.
    learned_response_pattern_selection.py  Unchanged - it already
                                consumes whatever meaning_resolution.py /
                                learned_pattern_matching.py produce, so a
                                meaning or pattern resolved through a
                                variation reaches it as an ordinary
                                RESOLVED / MATCHED result, automatically.
    core/core.py                Core owns one instance
                                (self.expression_variation_matcher),
                                constructed from the SAME
                                self.language_learning /
                                self.language_relationships Core already
                                owns, and hands it to self.meaning_resolver
                                and self.pattern_matcher. Reached directly
                                through match_learned_expression_variation().

Nothing else changed: ResponseGenerationResult, ConversationResponse, the
local model runtime/provider, model loading, readiness, resource limits,
timeout/cancellation, backend selection, memory architecture, reasoning,
planning, self-upgrade, web, automation and multimodal systems are
untouched.
"""


"""
Prompt 439 - Explicit Correction Structure
====================================================================
Goal: a small, deterministic structure for representing ONE user
correction that the existing understanding/conversation flow has ALREADY
identified explicitly - e.g. an original expression and the corrected
expression or corrected meaning the user explicitly supplied for it.

New file:
    correction_understanding.py  build_correction_understanding() /
                                CorrectionUnderstandingResult. Takes only
                                already-identified pieces (original
                                expression, corrected expression and/or
                                corrected meaning, language, locale,
                                confidence, and - for detecting an
                                ambiguous correction only -
                                corrected_candidates) and the caller's
                                verbatim source_text, and turns them into
                                one plain, JSON-shaped result: STATUS_
                                RESOLVED (both sides present),
                                STATUS_AMBIGUOUS (more than one distinct
                                candidate, none chosen - nothing
                                guessed), STATUS_UNRESOLVED (only part of
                                a correction present), STATUS_NOT_
                                CORRECTION (nothing correction-related
                                supplied). Pure and deterministic; never
                                parses or infers a correction from free
                                conversation text; never stores anything
                                in memory or the language-learning
                                database.

Not integrated anywhere yet, by design: NOT connected to Learned Meaning
Resolution, Learned Expression Variation Matching, Learned Pattern
Matching, response pattern selection or response generation. Those
integrations are later, separately-scoped prompts.

Nothing else changed: LocalModelRuntime, LocalModelProvider, response
generation, backend selection, memory architecture, the learning
database, reasoning, planning, self-upgrade, web, automation and
multimodal systems are untouched.
"""


"""
Prompt 440 - Expose Correction Understanding
====================================================================
Goal: expose Prompt 439's `CorrectionUnderstanding` through the current
language-understanding flow - a small integration step only, not
correction learning.

New file:
    understanding/correction_detection.py  detect_explicit_correction() /
                                CorrectionCandidate: a small, deterministic
                                detector for ONE fixed, explicit textual
                                correction marker ("not X, I mean/meant
                                Y"), in the same single-regex,
                                tried-once style as relation_extraction.py's
                                own RELATION_PATTERNS. Returns the two raw
                                spans it captured, or None - never a
                                second Understanding Engine, never an
                                inference from general conversation.

Modified (small, additive changes only):
    understanding/result.py    `UnderstandingResult.correction_candidate`:
                                the detector's `CorrectionCandidate.
                                to_dict()`, or None for every message that
                                is not that one fixed marker.
    understanding/engine.py    calls the new detector once, after the
                                existing pipeline steps; never changes
                                language detection, tokenization, sentence
                                type, entities, relations, confidence or
                                warnings.
    language_intelligence/correction_understanding.py  imported, not
                                modified: `build_correction_understanding()`
                                (Prompt 439) turns the raw candidate into a
                                structured result.
    language_intelligence/language_understanding_result.py
                                `LanguageUnderstandingResult.
                                correction_understanding`: one
                                `CorrectionUnderstandingResult.to_dict()` -
                                status RESOLVED / AMBIGUOUS / UNRESOLVED /
                                NOT_CORRECTION, original_expression,
                                corrected_expression/corrected_meaning,
                                language, locale, source_text
                                (original_input, untouched), confidence.
                                `None` - never a NOT_CORRECTION result -
                                when the Understanding Engine found no
                                candidate, so an ordinary message creates
                                no correction data at all.
    language_intelligence/deterministic_fallback_backend.py
                                `_build_correction_understanding()`: reads
                                ONLY `result.correction_candidate` (REUSED,
                                never re-detected here) and calls Prompt
                                439's builder; a malformed candidate is
                                treated as "no candidate" rather than
                                raising. Not wired into the meaning
                                resolver, pattern matcher, response
                                planning or response generation calls this
                                method already makes - those run exactly
                                as before.

NOT stored anywhere and NOT yet connected to Learning, Memory, Knowledge,
Learned Meaning Resolution, Learned Expression Variation Matching,
response pattern selection or response generation - those are later,
separately-scoped prompts. Existing language detection, meaning
resolution, learned sentence-pattern matching and response-generation
behavior are unchanged; this is a single, purely additive field.
"""
