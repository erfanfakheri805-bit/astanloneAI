"""
Language Intelligence - Structured Understanding Result
===========================================================
`LanguageUnderstandingResult` is the single structured object every
`LanguageIntelligenceBackend.understand()` call returns (see
backend.py) - the "LANGUAGE UNDERSTANDING RESULT" box in the pipeline
described in language_intelligence_core.py's module docstring.

Same plain, JSON-shaped, `to_dict()`-carrying convention already used
throughout this project (UnderstandingResult, ReasoningResult,
RelevantContextResult, ResolvedReference, ActiveTopicResult) - a
caller gets everything it needs without re-deriving anything from a
raw message string, and every field is either a verbatim value taken
from the request, or a value copied/derived from an existing,
already-documented system's own result. Nothing here is invented:

    original_input        - `raw_text`, verbatim, untouched. Never
                             normalized, translated, or rewritten -
                             the one field a caller can always trust
                             to be exactly what the user typed.
    detected_language      - straight from the existing Understanding
                             Engine's language detector
                             (understanding/language_detection.py) -
                             one of LANGUAGE_ENGLISH / LANGUAGE_PERSIAN
                             / LANGUAGE_UNKNOWN today. This field is a
                             plain string, not a fixed two-value enum,
                             specifically so a *future* stage can teach
                             understanding/language_detection.py more
                             languages (French, German, ...) without
                             this class, or anything that reads this
                             field, needing to change at all - see this
                             package's own module docstring, item 7.
    normalized_input       - the existing Understanding Engine's own
                             whitespace-collapsed text
                             (understanding/normalization.py) - kept
                             separate from `original_input` on purpose
                             (spec requirement: "preserve original user
                             input separately from normalized/derived
                             information").
    intent                 - one of the INTENT_* constants below,
                             derived deterministically from the
                             existing sentence-type classifier
                             (understanding/sentence_analysis.py) plus
                             the existing goal-oriented-prefix check
                             (planning/goal_detection.is_goal_oriented) -
                             see deterministic_fallback_backend.py for
                             the exact, fixed mapping. Never a modeled
                             or scored "intent classification" - this
                             is the same heuristic Core already applies
                             elsewhere, just surfaced here as a labeled
                             field instead of being buried in branching
                             logic.
    entities                - the existing Understanding Engine's own
                             candidate-entity list
                             (understanding/entity_extraction.py:
                             `[{"text", "status"}]`, `status` always
                             "candidate" at this stage) - copied
                             through unchanged, never re-extracted a
                             second way.
    referenced_items        - built from the existing message-level
                             reference resolution
                             (context/message_reference_resolution.py:
                             ResolvedReference) - empty list when there
                             is no reference in the message; otherwise
                             one dict describing it (see
                             deterministic_fallback_backend.py). Never
                             a second, competing reference-resolution
                             attempt.
    active_topic            - the existing Active Conversation Topic
                             result's own `to_dict()`
                             (context/active_topic.py: ActiveTopicResult),
                             or None when no topic is tracked yet.
    conversation_context     - the existing Relevance Selection result's
                             own `to_dict()`
                             (context/relevance.py: RelevantContextResult),
                             or None when the caller supplied none.
    confidence              - starts from the existing Understanding
                             Engine's own deterministic confidence
                             score, optionally lowered by one fixed,
                             documented penalty when the message's
                             reference is ambiguous - see
                             deterministic_fallback_backend.py for the
                             exact arithmetic. Always a float in
                             [0.0, 1.0], never randomized, never a bare
                             guess - same rule ReasoningResult already
                             documents for its own `confidence`.
    ambiguity                - True exactly when the existing
                             ResolvedReference reports `ambiguous`
                             (a reference like "it" was found but could
                             not be pinned to one earlier turn) -
                             copied through, never re-derived.
    needs_clarification      - True whenever `ambiguity` is True, the
                             sentence type could not be determined at
                             all (SENTENCE_UNKNOWN), or `confidence`
                             falls at or below a small, fixed, documented
                             threshold (see deterministic_fallback_backend.py).
                             This is the field the spec asks for
                             explicitly: "if the current system cannot
                             reliably determine something, represent
                             that uncertainty explicitly" - it is
                             never left False by default just because
                             nothing crashed.
    warnings                 - the existing Understanding Engine's own
                             `warnings` list, copied through unchanged
                             (e.g. "empty_input", "no_entities_extracted") -
                             plus, only when applicable, one additional,
                             clearly-labeled warning this class itself
                             adds when it lowers confidence for
                             ambiguity (see backend for the exact
                             string) - never removed or reworded.
    source_backend           - the `backend_kind` (see backend.py) of
                             whichever `LanguageIntelligenceBackend`
                             produced this result (e.g.
                             "deterministic_fallback") - so a caller
                             (or a test) can tell which backend
                             actually ran without needing to know which
                             one was configured.
    language_context         - Prompt 401: the `LanguageContext`
                             (language_context.py) of this message -
                             original text, detected language and
                             confidence, scripts present, conversation
                             language, requested language and the
                             preferred response language. None when the
                             producer did not supply one. This is what
                             a local model provider receives next to
                             `original_input`; `detected_language`
                             above is unchanged and always equals
                             `language_context.detected_language` when
                             both come from the deterministic backend.

    conversation_state       - Prompt 405: the compact conversation state
                             (context/conversation_state.py:
                             ConversationState.to_dict()) - earlier
                             topics, explicit preferences, unresolved
                             references - or None when the producer did
                             not supply one. Attached by Core after
                             understanding; never produced by a backend.
                             Only the part relevant to the message is
                             ever forwarded to a model
                             (local_model_mapping.py).
    learned_meanings          - Prompt 419: what the Learned Meaning
                             Resolution system (Prompt 418,
                             meaning_resolution.py) already knows about
                             the candidate expressions in `entities`
                             above, one entry per expression actually
                             looked up. Each entry IS that expression's
                             `MeaningResolutionResult.to_dict()`
                             (meaning_resolution.py) unchanged - status
                             RESOLVED or NOT_FOUND, `meanings` populated
                             only when RESOLVED - so a resolved item and
                             an unresolved one are always clearly
                             distinguishable, and nothing here ever
                             fabricates a meaning for an expression the
                             system has not learned. `[]` when the
                             producing backend was given no meaning
                             resolver, when `entities` was empty, or when
                             the lookup itself failed (see
                             deterministic_fallback_backend.py) - in
                             every case the rest of this result, and the
                             existing deterministic understanding it
                             carries, is unaffected. This never replaces
                             or duplicates `entities`; it only annotates
                             some of them with what has already been
                             learned.
    disambiguated_meanings   - Prompt 420: one entry per `learned_meanings`
                             entry above (REUSED, never re-resolved),
                             each that entry's `DisambiguationResult.
                             to_dict()` (learned_meaning_disambiguation.py) -
                             status RESOLVED / AMBIGUOUS / NOT_FOUND.
                             AMBIGUOUS is new here: it is how this result
                             represents "the system learned more than one
                             meaning for this expression and nothing
                             available (language, topic, nearby
                             expressions, recent turns, a resolved
                             reference) distinguishes them" - never
                             collapsed into one meaning and never guessed
                             at. `[]` when the producing backend was
                             given no disambiguator, when `learned_meanings`
                             was empty, or when disambiguation itself
                             failed for an entry (see
                             deterministic_fallback_backend.py) - in every
                             case `learned_meanings` above, and the rest of
                             this result, is completely unaffected; this
                             is a strictly additive field.

    learned_pattern_match    - Prompt 421: whether `original_input`, as a
                             whole, is recognized as an instance of a
                             learned sentence pattern (Prompt 416,
                             `item_type=ITEM_TYPE_PATTERN`) - one
                             `LearnedPatternMatchResult.to_dict()`
                             (learned_pattern_matching.py) - status
                             MATCHED / NOT_FOUND / AMBIGUOUS /
                             NOT_RESOLVED. Unlike `learned_meanings`
                             above (one entry per candidate expression),
                             this is a single, whole-message result,
                             since a sentence pattern describes the
                             message's own structure, not one word or
                             phrase within it. `None` when the producing
                             backend was given no pattern matcher, or
                             when matching itself failed (see
                             deterministic_fallback_backend.py) - in
                             every case the rest of this result is
                             completely unaffected; this is a strictly
                             additive field, never a replacement for
                             `entities`, `learned_meanings`, or anything
                             else already computed.

    learned_sentence_structure - Prompt 422: the structure of `original_input`
                             as the matched learned sentence pattern
                             defines it - one
                             `LearnedSentenceStructureResult.to_dict()`
                             (learned_sentence_structure.py): ordered
                             `components`, each a fixed part of the
                             pattern or a named variable with its
                             extracted value (or, for a NOT_RESOLVED
                             pattern, one `unresolved` component
                             preserving text the pattern does not define
                             a split for), plus the matched pattern's id,
                             text, meaning, language, locale, confidence
                             and source. Built FROM the same match
                             `learned_pattern_match` above reports (never
                             a second match), and its `original_message`
                             is this result's own `original_input`
                             (untouched). `None` when the producing
                             backend was given no structure extractor (or
                             no pattern matcher), or when extraction
                             itself failed - in every case the rest of
                             this result, `learned_pattern_match`
                             included, is completely unaffected; this is
                             a strictly additive field.

    learned_pattern_meaning  - Prompt 424: the meaning/intention EXPLICITLY
                             bound (Prompt 424, learned_pattern_meaning.py)
                             to the learned sentence pattern
                             `learned_pattern_match` recognized - one
                             `LearnedPatternMeaningResult.to_dict()`:
                             `original_message` (this result's own
                             `original_input`, untouched), the whole Prompt
                             421 `pattern_match`, its extracted `variables`,
                             `status` RESOLVED / AMBIGUOUS / NOT_FOUND,
                             the one `meaning` (with id, name, language,
                             locale, confidence, source, learning context)
                             when exactly one applies, and EVERY bound
                             meaning in `candidates`. Several bound
                             meanings are decided (or left AMBIGUOUS) by
                             the existing Prompt 420 disambiguator, using
                             the same context this result was built from.
                             A pattern with no bound meaning is NOT_FOUND
                             (reason no_learned_meaning) - nothing is ever
                             inferred. `None` when the producing backend
                             was given no meaning binder, when no pattern
                             match was produced, or when resolution itself
                             failed - in every case the rest of this
                             result is completely unaffected; this is a
                             strictly additive field, and the `meaning`
                             of the raw `learned_pattern_match` (Prompt
                             421) is untouched.

    response_plan            - Prompt 425: the structured requirements of a
                             response to this message - one
                             `ResponsePlan.to_dict()` (response_planning.py):
                             status RESOLVED / AMBIGUOUS / UNRESOLVED, the
                             resolved meaning (or every undecided candidate),
                             the matched pattern and extracted variables, the
                             `response_action` (e.g. "greet",
                             "provide_information") and required items, the
                             active topic, references and context, and what
                             is still unresolved. Derived ONLY from the other
                             fields of this same result (never a second
                             understanding pass), and never response text.
                             Attached by `LanguageIntelligenceCore` after any
                             backend has produced the understanding - never
                             by a backend. `None` when no plan was made (a
                             result built directly, or planning failed - a
                             `response_plan_error` warning says so); the
                             rest of this result is completely unaffected.
                             ResponseGeneration reads it from here.

    correction_understanding - Prompt 440: exposes Prompt 439's
                             `CorrectionUnderstanding` - one
                             `CorrectionUnderstandingResult.to_dict()`
                             (correction_understanding.py): `status`
                             (RESOLVED / AMBIGUOUS / UNRESOLVED /
                             NOT_CORRECTION), `original_expression`,
                             `corrected_expression`/`corrected_meaning`,
                             `language`, `locale`, `source_text`
                             (`original_input`, untouched) and
                             `confidence`. Built ONLY from the existing
                             Understanding Engine's own
                             `correction_candidate` (Prompt 440,
                             understanding/correction_detection.py) - a
                             fixed, explicit textual marker, never
                             inferred from general conversation. `None`
                             - not a NOT_CORRECTION result - when that
                             candidate is absent, so an ordinary message
                             creates no correction data at all (see
                             deterministic_fallback_backend.py). Not
                             stored anywhere and not yet connected to
                             Learning, Memory, Knowledge, Learned
                             Meaning Resolution, Learned Expression
                             Variation Matching, response pattern
                             selection or response generation - those
                             are later, separately-scoped stages.

    correction_lookup_context - Prompt 466: exposes Prompt 465's
                             `CorrectionLookupContext`
                             (correction_lookup_context.py) - one
                             `CorrectionLookupContext.to_dict()`:
                             `status` (FOUND / NOT_FOUND / FAILED),
                             `original_expression`, `records`,
                             `language`, `locale`, `source`, `reason`.
                             Purely informational, EXACTLY like
                             `correction_understanding` above: this
                             field only carries through a context an
                             existing caller already built elsewhere
                             (Prompt 465's
                             `build_correction_lookup_context()`); this
                             class does not perform a lookup, does not
                             decide when one should happen, and does
                             not apply any correction. `None` when no
                             lookup was performed / no context was
                             supplied - the common case for an ordinary
                             message - so nothing changes for existing
                             callers that never pass this argument.

    correction_application_candidate - Prompt 564: exposes Prompt 470's
                             `CorrectionApplicationCandidate`
                             (correction_application_candidate.py) -
                             one `CorrectionApplicationCandidate.
                             to_dict()`: `is_valid`,
                             `original_expression`,
                             `corrected_expression_or_meaning`,
                             `language`, `locale`, `source`,
                             `confidence`. Purely informational, the
                             SAME posture `correction_lookup_context`
                             above already established (Prompt 466):
                             this field only carries through a
                             candidate an existing caller already
                             built elsewhere (Prompt 470's
                             `build_correction_application_candidate()`);
                             this class does not build, select, or
                             apply a candidate itself, and does not
                             decide when a lookup should happen.
                             `None` when no candidate was supplied -
                             the common case for an ordinary message,
                             including every message today, since
                             nothing in this project yet computes one
                             automatically - so nothing changes for
                             existing callers that never pass this
                             argument. This is the smallest safe data
                             path Prompt 563's audit identified as
                             missing: a place for an already-existing
                             `CorrectionApplicationCandidate` to be
                             carried on this result. It adds no
                             retrieval trigger, no automatic lookup, no
                             automatic application, and no access to
                             Core's correction-learning store - see
                             deterministic_fallback_backend.py (still
                             never sets this field) and core/core.py
                             (still never reads or assigns it).

    correction_application_result - Prompt 571: exposes Prompt 474's
                             `CorrectionApplicationResult`
                             (correction_application_result.py) - one
                             `CorrectionApplicationResult.to_dict()`:
                             `status` (APPLIED / NOT_APPLIED / FAILED),
                             `applied`, `original_text`,
                             `corrected_text`, `reason`, `metadata`,
                             `matched_text`, `replacement_text`,
                             `match_count`, `text_before`, `text_after`.
                             Purely informational, the SAME posture
                             `correction_application_candidate` above
                             already established (Prompt 564): this
                             field only carries through a result an
                             existing caller already built elsewhere
                             (Prompt 570's correction-application
                             operation); this class does not apply,
                             attempt, or decide anything about a
                             correction itself. `None` when no
                             application result was supplied - the
                             common case for an ordinary message - so
                             nothing changes for existing callers that
                             never pass this argument.

    learned_knowledge_context - Prompt 501: the one already-taught
                             knowledge entry directly relevant to this
                             message (`LearnedKnowledgeSelection.
                             to_context()`, learned_knowledge_context.py),
                             or None. Attached by Core; this class does
                             no lookup. Carried to response generation
                             by ResponseGenerationContext; not part of
                             `to_dict()`.

This class never writes to memory/knowledge/context itself - purely a
description of what was understood, exactly like UnderstandingResult
before it.
"""

# Fixed, small intent vocabulary - never a free-form/scored string, so
# callers can branch on it reliably (same convention as
# reasoning_result.py's STATUS_* / understanding/sentence_analysis.py's
# SENTENCE_* constants).
INTENT_ASK_QUESTION = "ask_question"
INTENT_PROVIDE_INFORMATION = "provide_information"
INTENT_REQUEST_ACTION = "request_action"
INTENT_GOAL_REQUEST = "goal_request"
INTENT_UNKNOWN = "unknown"

ALL_INTENTS = (
    INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION, INTENT_REQUEST_ACTION,
    INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)


class LanguageUnderstandingResult:
    def __init__(
        self,
        original_input,
        detected_language,
        normalized_input,
        intent,
        entities,
        referenced_items,
        active_topic,
        conversation_context,
        confidence,
        ambiguity,
        needs_clarification,
        warnings=None,
        source_backend=None,
        language_context=None,
        conversation_state=None,
        learned_meanings=None,
        disambiguated_meanings=None,
        learned_pattern_match=None,
        learned_sentence_structure=None,
        learned_pattern_meaning=None,
        response_plan=None,
        correction_understanding=None,
        correction_lookup_context=None,
        correction_application_candidate=None,
        correction_application_result=None,
        learned_knowledge_context=None,
    ):
        self.original_input = original_input
        self.detected_language = detected_language
        self.normalized_input = normalized_input
        self.intent = intent
        self.entities = entities if entities is not None else []
        self.referenced_items = referenced_items if referenced_items is not None else []
        self.active_topic = active_topic
        self.conversation_context = conversation_context
        self.confidence = confidence
        self.ambiguity = ambiguity
        self.needs_clarification = needs_clarification
        self.warnings = warnings if warnings is not None else []
        self.source_backend = source_backend
        self.language_context = language_context
        self.conversation_state = conversation_state
        # list[dict] - each a MeaningResolutionResult.to_dict(); see the
        # class docstring's `learned_meanings` entry above.
        self.learned_meanings = learned_meanings if learned_meanings is not None else []
        # list[dict] - each a DisambiguationResult.to_dict() (Prompt 420);
        # see the class docstring's `disambiguated_meanings` entry above.
        self.disambiguated_meanings = (
            disambiguated_meanings if disambiguated_meanings is not None else []
        )
        # dict (a LearnedPatternMatchResult.to_dict()) or None (Prompt
        # 421); see the class docstring's `learned_pattern_match` entry
        # above.
        self.learned_pattern_match = learned_pattern_match
        # dict (a LearnedSentenceStructureResult.to_dict()) or None
        # (Prompt 422); see the class docstring's
        # `learned_sentence_structure` entry above.
        self.learned_sentence_structure = learned_sentence_structure
        # dict (a LearnedPatternMeaningResult.to_dict()) or None (Prompt
        # 424); see the class docstring's `learned_pattern_meaning` entry
        # above.
        self.learned_pattern_meaning = learned_pattern_meaning
        # dict (a ResponsePlan.to_dict()) or None (Prompt 425); see the
        # class docstring's `response_plan` entry above.
        self.response_plan = response_plan
        # dict (a CorrectionUnderstandingResult.to_dict()) or None
        # (Prompt 440); see the class docstring's
        # `correction_understanding` entry above.
        self.correction_understanding = correction_understanding
        # dict (a CorrectionLookupContext.to_dict()) or None (Prompt
        # 466); see the class docstring's `correction_lookup_context`
        # entry above. Informational only - never set automatically by
        # this class, never used to apply a correction.
        self.correction_lookup_context = correction_lookup_context
        # dict (a CorrectionApplicationCandidate.to_dict()) or None
        # (Prompt 564); see the class docstring's
        # `correction_application_candidate` entry above. Informational
        # only - never set automatically by this class, never used to
        # apply a correction, and never given access to any store.
        self.correction_application_candidate = correction_application_candidate
        # dict (a CorrectionApplicationResult.to_dict()) or None (Prompt
        # 571); see the class docstring's `correction_application_result`
        # entry above. Informational only - never set automatically by
        # this class, never applies a correction itself, and never given
        # access to any store.
        self.correction_application_result = correction_application_result
        # Prompt 501: the directly relevant, already-taught knowledge entry
        # (learned_knowledge_context.py `LearnedKnowledgeSelection.
        # to_context()`), attached by Core only when exactly one entry is
        # directly relevant to this message; None otherwise (the common
        # case). Deliberately NOT part of `to_dict()` - it reaches
        # response generation through ResponseGenerationContext, and the
        # understanding's own serialized shape is unchanged.
        self.learned_knowledge_context = learned_knowledge_context

    def __repr__(self):
        return (
            f"LanguageUnderstandingResult(intent={self.intent!r}, "
            f"detected_language={self.detected_language!r}, "
            f"confidence={self.confidence:.2f}, ambiguity={self.ambiguity}, "
            f"needs_clarification={self.needs_clarification})"
        )

    def to_dict(self):
        return {
            "original_input": self.original_input,
            "detected_language": self.detected_language,
            "normalized_input": self.normalized_input,
            "intent": self.intent,
            "entities": self.entities,
            "referenced_items": self.referenced_items,
            "active_topic": self.active_topic,
            "conversation_context": self.conversation_context,
            "confidence": round(self.confidence, 4),
            "ambiguity": self.ambiguity,
            "needs_clarification": self.needs_clarification,
            "warnings": self.warnings,
            "source_backend": self.source_backend,
            "language_context": self.language_context.to_dict()
            if self.language_context is not None else None,
            "conversation_state": self.conversation_state,
            "learned_meanings": self.learned_meanings,
            "disambiguated_meanings": self.disambiguated_meanings,
            "learned_pattern_match": self.learned_pattern_match,
            "learned_sentence_structure": self.learned_sentence_structure,
            "learned_pattern_meaning": self.learned_pattern_meaning,
            "response_plan": self.response_plan,
            "correction_understanding": self.correction_understanding,
            "correction_lookup_context": (
                self.correction_lookup_context.to_dict()
                if hasattr(self.correction_lookup_context, "to_dict")
                else self.correction_lookup_context
            ),
            "correction_application_candidate": (
                self.correction_application_candidate.to_dict()
                if hasattr(self.correction_application_candidate, "to_dict")
                else self.correction_application_candidate
            ),
            "correction_application_result": (
                self.correction_application_result.to_dict()
                if hasattr(self.correction_application_result, "to_dict")
                else self.correction_application_result
            ),
        }
