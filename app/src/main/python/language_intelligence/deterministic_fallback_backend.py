"""
Language Intelligence - Deterministic Fallback Backend
==========================================================
`DeterministicFallbackBackend` is today's only real
`LanguageIntelligenceBackend` (backend.py). It is a thin structuring
layer over systems that already exist and are unchanged by this
module:

    raw_text
      -> UnderstandingEngine.understand(raw_text, context)   (REUSED,
         understanding/engine.py - the exact same stateless engine
         instance Core already owns as `self.understanding`, passed
         into this backend's constructor; this module never
         constructs a second one)
      -> UnderstandingResult                                  (REUSED,
         understanding/result.py)
      -> intent classification                                 (this
         module's only new logic: a small, fixed mapping - see
         `_classify_intent` below - from the existing sentence-type
         classifier plus the existing goal-oriented-prefix check;
         never a modeled/scored classification)
      -> LanguageUnderstandingResult                     (this package,
         language_understanding_result.py)

Reuses, never duplicates:
  - `understanding.engine.UnderstandingEngine` - the raw engine call
    here (`self._understanding_engine.understand(raw_text,
    context=context)`) never calls `context.add_understanding(...)` -
    exactly the same "analysis only, no side effect" convention
    Core._construct_fallback_reply's own direct
    `self.understanding.understand(current_input)` call already
    follows (core/core.py). Context is only ever *read* here (via the
    engine's own optional context-resolution step), never written to -
    so calling this backend as many times as a caller likes for the
    same message never changes what a later, real
    `Core.understand()`/`Core.learn_from_text()` call for that same
    message sees.
  - `planning.goal_detection.is_goal_oriented` - the exact same fixed
    prefix check `Core._handle_goal_or_conversation` already uses to
    decide whether to create a Goal - read here only to *label* intent
    as INTENT_GOAL_REQUEST, never to create a Goal or call
    `Core.create_goal` itself. This backend never creates a Goal, a
    Plan, or anything else with a side effect.
  - `context.relevance.RelevantContextResult`,
    `context.message_reference_resolution.ResolvedReference`,
    `context.active_topic.ActiveTopicResult` - all three are accepted
    as already-computed arguments and only ever read (`.to_dict()`,
    plain attribute access), never recomputed.

Confidence and clarification (spec requirement: represent uncertainty
explicitly, never invent information):
  - `confidence` starts as the existing UnderstandingResult's own
    deterministic score, unchanged, UNLESS `resolved_reference` reports
    an ambiguous reference (`resolved_reference.has_reference and
    resolved_reference.ambiguous`) - in which case it is multiplied by
    `_AMBIGUOUS_REFERENCE_CONFIDENCE_PENALTY` and a warning noting this
    is appended. This is the one, single, fixed, documented arithmetic
    adjustment this module makes to an existing score - never a second,
    competing confidence model.
  - `needs_clarification` is True whenever `ambiguity` is True, the
    existing engine could not determine a sentence type at all
    (SENTENCE_UNKNOWN), or the (possibly-penalized) confidence is at or
    below `_NEEDS_CLARIFICATION_CONFIDENCE_THRESHOLD` - three fixed,
    inspectable conditions, never a guess.

Language context (Prompt 401): alongside the fields above, `understand()`
attaches a `LanguageContext` (language_context.py) built from the SAME
engine result: the verbatim `original_text`, the engine's normalized
text (analysis only), the script-level detection, the scripts present in
the prose, the conversation language (read from `context`'s recent user
turns, never written to), any explicit requested language, and the
resulting preferred response language. This backend still generates no
text; the context is what a local-model backend later hands to its
provider next to the original message. `default_language` (constructor
argument, None by default) is the configured fallback used only when
nothing else determines the response language.

`generate_response()` never produces reply text - see
response_generation.py's own module docstring for exactly why, and
where reply text for a conversational turn is actually produced
today (Core._handle_conversation, unchanged).

Prompt 419 - learned meanings during understanding
-----------------------------------------------------
An optional constructor argument, `meaning_resolver` (a `MeaningResolver`,
meaning_resolution.py - typically Core's own `self.meaning_resolver`,
never a second instance), lets `understand()` attach what the Learned
Meaning Resolution system (Prompt 418) already knows about this
message's candidate expressions - REUSED, not reimplemented:

    UnderstandingResult.entities   (REUSED, understanding/
                                   entity_extraction.py - candidate
                                   words/phrases the Understanding
                                   Engine already found; this module
                                   extracts no candidates a second way)
      -> MeaningResolver.resolve(expression, language=...)   (REUSED,
         meaning_resolution.py - one bounded, read-only lookup per
         candidate; never a second resolution algorithm)
      -> LanguageUnderstandingResult.learned_meanings    (this module's
         only new logic: collecting each lookup's
         `MeaningResolutionResult.to_dict()` unchanged - see
         `_resolve_learned_meanings` below)

`meaning_resolver=None` (the default) reproduces the exact previous
behaviour: `learned_meanings` stays `[]` and nothing about this
backend's existing logic runs differently, so every caller/test built
before Prompt 419 is unaffected. Lookups use the language this SAME
call already detected (`result.language`) when it is a real language,
and search every language (language=None, see meaning_resolution.py's
own docstring) when detection was undetermined - never assuming an
expression means the same thing in every language. A lookup failure is
caught per-expression (matching the context-resolution try/except
above) and recorded as a warning, never allowed to break understanding
or to invent a meaning for the expression that failed.

Prompt 420 - learned meaning disambiguation
-----------------------------------------------
A second optional constructor argument, `meaning_disambiguator` (a
`LearnedMeaningDisambiguator`, learned_meaning_disambiguation.py -
typically Core's own `self.meaning_disambiguator`, never a second
instance), lets `understand()` attach one more, purely additive field:
`disambiguated_meanings`. For each entry `learned_meanings` above
already produced (REUSED, never re-resolved a second way), it asks the
disambiguator to decide - using only the SAME context pieces this
method already has in hand (`active_topic`, `context`,
`resolved_reference`, and the message's own other candidate
expressions as `nearby_expressions`) - whether one learned meaning
applies, several genuinely remain undecided (STATUS_AMBIGUOUS - the
one status Prompt 418 could not represent), or none were ever learned.
Never a second understanding/NLU system: see
learned_meaning_disambiguation.py's own module docstring for exactly
what this is (a small, bounded, deterministic word-overlap check) and
is not (no guessing, no ML).

`meaning_disambiguator=None` (the default) reproduces the exact
pre-Prompt-420 behaviour: `disambiguated_meanings` stays `[]` and
`learned_meanings` itself is completely untouched either way - this is
a strictly additive field, never a replacement for it. A disambiguation
failure is caught per-expression, exactly like a lookup failure above,
and recorded as a warning rather than allowed to break understanding.

Prompt 421 - learned sentence pattern matching
-----------------------------------------------
A third optional constructor argument, `pattern_matcher` (a
`LearnedPatternMatcher`, learned_pattern_matching.py - typically Core's
own `self.pattern_matcher`, never a second instance), lets `understand()`
attach one more, purely additive field: `learned_pattern_match`. Unlike
`learned_meanings`/`disambiguated_meanings` above (one entry per
candidate expression from `result.entities`), this asks the matcher
about the message AS A WHOLE (`result.normalized_text` - REUSED, the
exact same Understanding Engine output every other field on this result
already comes from), since a sentence pattern describes the message's
own structure. The SAME detected language this call already has
(`result.language`, treated as unknown exactly like
`_resolve_learned_meanings` already does) is passed through - never a
second, competing language detector.

`pattern_matcher=None` (the default) reproduces the exact
pre-Prompt-421 behaviour: `learned_pattern_match` stays `None` and
nothing else about this backend's existing logic runs differently. A
matching failure is caught exactly like a lookup/disambiguation failure
above and recorded as a warning, never allowed to break understanding
or to invent a match.

Prompt 422 - learned sentence structure extraction
---------------------------------------------------
A fourth optional constructor argument, `structure_extractor` (a
`LearnedSentenceStructureExtractor`, learned_sentence_structure.py -
typically Core's own `self.sentence_structure_extractor`), attaches one
more purely additive field: `learned_sentence_structure`. It is built
from the SAME `LearnedPatternMatchResult` the Prompt 421 step above
already produced (`extractor.from_match(...)`) - the message is matched
once, never twice, and there is no second pattern-matching path. The
user's untouched `result.original_text` is passed as the structure's
original message (the matcher itself is handed the normalized text, as
in Prompt 421). Nothing else on the result changes.

`structure_extractor=None` (the default), or no `pattern_matcher`,
reproduces the exact pre-Prompt-422 behaviour: `learned_sentence_structure`
stays `None`. An extraction failure is caught like the failures above and
recorded as a warning; `learned_pattern_match` is kept either way.

Prompt 424 - learned pattern meaning binding
---------------------------------------------
A fifth optional constructor argument, `pattern_meaning_binder` (a
`LearnedPatternMeaningBinder`, learned_pattern_meaning.py - typically
Core's own `self.pattern_meaning_binder`), attaches one more purely
additive field: `learned_pattern_meaning`. It is resolved FROM the same
`LearnedPatternMatchResult` dict the Prompt 421 step above already
produced (no second match) and reads the meaning/intention that was
EXPLICITLY bound to the matched pattern. When several are bound, the
existing Prompt 420 disambiguator (inside the binder) decides using the
SAME context pieces this method already has in hand (`active_topic`,
`context`, `resolved_reference`, and the message's own candidate
expressions as `nearby_expressions`). The user's untouched
`result.original_text` is the result's original message. Nothing is
inferred: a pattern with no bound meaning is reported NOT_FOUND.

`pattern_meaning_binder=None` (the default), or no pattern match at all,
reproduces the exact pre-Prompt-424 behaviour: `learned_pattern_meaning`
stays `None`; `learned_pattern_match` and `learned_sentence_structure`
are identical either way. A resolution failure is caught like the
failures above and recorded as a warning.

Prompt 440 - explicit correction exposure
--------------------------------------------
One more purely additive field, `correction_understanding`. Built by
`_build_correction_understanding()` from the SAME `UnderstandingResult`
this method already has (`result.correction_candidate` -
understanding/correction_detection.py's fixed, explicit marker; REUSED,
never re-detected here) through Prompt 439's own
`build_correction_understanding()` - no new detection logic in this
module, no second understanding pass. `None`, not a NOT_CORRECTION
result, for every message where no candidate was found - the exact
pre-Prompt-440 shape for ordinary messages. Nothing is stored, and
nothing here feeds it to the meaning resolver, pattern matcher, response
planning or response generation above - those stay exactly as they were.
"""

from understanding.sentence_analysis import (
    SENTENCE_QUESTION, SENTENCE_STATEMENT, SENTENCE_COMMAND, SENTENCE_UNKNOWN,
)
from understanding.language_detection import LANGUAGE_UNKNOWN
from planning.goal_detection import is_goal_oriented

from .backend import LanguageIntelligenceBackend, BACKEND_KIND_DETERMINISTIC_FALLBACK
from .language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)
from .language_context import build_language_context
from .response_generation import ResponseGenerationResult, STATUS_DEFERRED
from .correction_understanding import build_correction_understanding

# Fixed mapping from the existing sentence-type vocabulary to this
# module's own intent vocabulary - a plain lookup, never inferred.
_SENTENCE_TYPE_TO_INTENT = {
    SENTENCE_QUESTION: INTENT_ASK_QUESTION,
    SENTENCE_STATEMENT: INTENT_PROVIDE_INFORMATION,
    SENTENCE_COMMAND: INTENT_REQUEST_ACTION,
    SENTENCE_UNKNOWN: INTENT_UNKNOWN,
}

# A fixed, documented penalty - not a learned or tuned weight. Halving
# is a deliberately simple, inspectable choice: confidence in an
# understanding that hinges on an unresolved "it"/"that" should drop
# noticeably, without this module claiming a more precise number than
# it actually has grounds for.
_AMBIGUOUS_REFERENCE_CONFIDENCE_PENALTY = 0.5
_AMBIGUOUS_REFERENCE_WARNING = "confidence_reduced_ambiguous_reference"

# At or below this, the result is honest about not being reliable
# enough to act on without asking the user - same spirit as
# reasoning_result.py's STATUS_AMBIGUOUS, surfaced here as a boolean
# flag instead of a terminal status so a caller can still see whatever
# partial understanding was produced. Inclusive ("<=", not "<") so a
# message carrying only the two weakest possible signals (a
# recognizable sentence type and nothing else - e.g. language
# undetermined, no entities, no relations) is still honestly flagged
# rather than waved through by a hairline margin.
_NEEDS_CLARIFICATION_CONFIDENCE_THRESHOLD = 0.35

_DEFERRED_REASON = (
    "The deterministic fallback backend does not generate reply text. "
    "Core's existing conversation pipeline (skills / learning / "
    "reasoning / knowledge lookup / fallback construction) already "
    "produces the reply for this understanding."
)

# A fixed, small bound on how many candidate expressions one message can
# trigger a learned-meaning lookup for - keeps this stage small and
# deterministic (no unbounded per-message cost) even for a message with
# an unusually long entities list. Not configurable: raising it is a
# deliberate future change, not a per-call tuning knob.
_MAX_LEARNED_MEANING_LOOKUPS = 20

_LEARNED_MEANING_LOOKUP_ERROR_PREFIX = "learned_meaning_lookup_error"

# Prompt 420: same per-message bound as lookups above, applied to
# disambiguation instead - keeps this stage small and deterministic
# even when every one of _MAX_LEARNED_MEANING_LOOKUPS entries turned
# out to be ambiguous.
_MAX_LEARNED_MEANING_DISAMBIGUATIONS = 20
_LEARNED_MEANING_DISAMBIGUATION_ERROR_PREFIX = "learned_meaning_disambiguation_error"

# Prompt 421: a matching failure must never break understanding.
_LEARNED_PATTERN_MATCH_ERROR_PREFIX = "learned_pattern_match_error"

# Prompt 422: a structure-extraction failure must never break understanding.
_LEARNED_SENTENCE_STRUCTURE_ERROR_PREFIX = "learned_sentence_structure_error"

# Prompt 424: a meaning-binding failure must never break understanding.
_LEARNED_PATTERN_MEANING_ERROR_PREFIX = "learned_pattern_meaning_error"


class DeterministicFallbackBackend(LanguageIntelligenceBackend):
    def __init__(self, understanding_engine, default_language=None, meaning_resolver=None,
                 meaning_disambiguator=None, pattern_matcher=None, structure_extractor=None,
                 pattern_meaning_binder=None):
        """`understanding_engine` must be the caller's own existing
        `understanding.engine.UnderstandingEngine` instance (Core
        passes its own `self.understanding`) - never constructed here,
        so there is exactly one such engine in the whole application,
        exactly as before this module existed. `default_language`
        (optional code/name, e.g. "en" or "persian") is the configured
        fallback response language; None = no default.

        `meaning_resolver` (Prompt 419, optional) must be the caller's
        own existing `meaning_resolution.MeaningResolver` instance (Core
        passes its own `self.meaning_resolver`) - never constructed
        here, so there is exactly one such resolver in the whole
        application. `None` (the default) disables learned-meaning
        lookup entirely: `understand()` behaves exactly as it did before
        Prompt 419, and `learned_meanings` on every result it produces
        stays `[]`.

        `meaning_disambiguator` (Prompt 420, optional) must be the
        caller's own existing `learned_meaning_disambiguation.
        LearnedMeaningDisambiguator` instance (Core passes its own
        `self.meaning_disambiguator`) - never constructed here. `None`
        (the default) disables disambiguation entirely:
        `disambiguated_meanings` on every result stays `[]`, and
        `learned_meanings` is completely unaffected either way.

        `pattern_matcher` (Prompt 421, optional) must be the caller's
        own existing `learned_pattern_matching.LearnedPatternMatcher`
        instance (Core passes its own `self.pattern_matcher`) - never
        constructed here. `None` (the default) disables sentence-pattern
        matching entirely: `learned_pattern_match` on every result stays
        `None`, and nothing else about this backend's existing logic
        runs differently.

        `structure_extractor` (Prompt 422, optional) must be the
        caller's own existing `learned_sentence_structure.
        LearnedSentenceStructureExtractor` instance (Core passes its own
        `self.sentence_structure_extractor`) - never constructed here.
        It only ever reads the match `pattern_matcher` produced. `None`
        (the default) disables structure extraction entirely:
        `learned_sentence_structure` on every result stays `None`.

        `pattern_meaning_binder` (Prompt 424, optional) must be the
        caller's own existing `learned_pattern_meaning.
        LearnedPatternMeaningBinder` instance (Core passes its own
        `self.pattern_meaning_binder`) - never constructed here. It only
        ever reads the match `pattern_matcher` produced. `None` (the
        default) disables meaning binding entirely:
        `learned_pattern_meaning` on every result stays `None`."""
        self._understanding_engine = understanding_engine
        self._default_language = default_language
        self._meaning_resolver = meaning_resolver
        self._meaning_disambiguator = meaning_disambiguator
        self._pattern_matcher = pattern_matcher
        self._structure_extractor = structure_extractor
        self._pattern_meaning_binder = pattern_meaning_binder

    @property
    def backend_kind(self):
        return BACKEND_KIND_DETERMINISTIC_FALLBACK

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        result = self._understanding_engine.understand(raw_text, context=context)

        intent = self._classify_intent(result.normalized_text, result.sentence_type)
        referenced_items = self._build_referenced_items(resolved_reference)
        confidence, warnings = self._score_confidence(result.confidence, resolved_reference,
                                                        result.warnings)
        ambiguity = bool(resolved_reference is not None and resolved_reference.has_reference
                          and resolved_reference.ambiguous)
        needs_clarification = (
            ambiguity
            or result.sentence_type == SENTENCE_UNKNOWN
            or confidence <= _NEEDS_CLARIFICATION_CONFIDENCE_THRESHOLD
        )
        learned_meanings, warnings = self._resolve_learned_meanings(
            result.entities, result.language, warnings,
        )
        disambiguated_meanings, warnings = self._disambiguate_learned_meanings(
            learned_meanings, result.entities, active_topic, context, resolved_reference, warnings,
        )
        learned_pattern_match, learned_sentence_structure, warnings = self._match_learned_pattern(
            result.normalized_text, result.language, warnings, result.original_text,
        )
        learned_pattern_meaning, warnings = self._resolve_pattern_meaning(
            learned_pattern_match, result.original_text, result.entities, active_topic, context,
            resolved_reference, warnings,
        )
        correction_understanding = self._build_correction_understanding(result)

        return LanguageUnderstandingResult(
            original_input=result.original_text,
            detected_language=result.language,
            normalized_input=result.normalized_text,
            intent=intent,
            entities=result.entities,
            referenced_items=referenced_items,
            active_topic=active_topic.to_dict() if active_topic is not None else None,
            conversation_context=(
                relevant_context.to_dict() if relevant_context is not None else None
            ),
            confidence=confidence,
            ambiguity=ambiguity,
            needs_clarification=needs_clarification,
            warnings=warnings,
            source_backend=self.backend_kind,
            language_context=build_language_context(
                result.original_text, normalized_text=result.normalized_text,
                conversation=context, requested_language=requested_language,
                default_language=self._default_language),
            learned_meanings=learned_meanings,
            disambiguated_meanings=disambiguated_meanings,
            learned_pattern_match=learned_pattern_match,
            learned_sentence_structure=learned_sentence_structure,
            learned_pattern_meaning=learned_pattern_meaning,
            correction_understanding=correction_understanding,
        )

    def generate_response(self, understanding, context=None, cancellation_token=None,
                          verified_correction_instruction=None):
        # Runs no inference, so there is nothing to cancel (Prompt 411).
        # Prompt 500: generates no text, so a supplied verified correction
        # instruction is accepted (for interface parity) but not used -
        # the result's `used_verified_correction` stays False.
        return ResponseGenerationResult(
            status=STATUS_DEFERRED,
            response_text=None,
            reason=_DEFERRED_REASON,
            backend_kind=self.backend_kind,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _classify_intent(normalized_text, sentence_type):
        """Fixed, deterministic mapping - see module docstring. A
        goal-oriented prefix (the same check Core already applies)
        takes priority over the plain sentence-type mapping so that,
        for example, "Build me a script that ..." is labeled
        INTENT_GOAL_REQUEST rather than the less specific
        INTENT_REQUEST_ACTION, matching Core's own routing priority in
        `_handle_goal_or_conversation`. Read-only: never calls
        `Core.create_goal` or anything else with a side effect."""
        if normalized_text and is_goal_oriented(normalized_text):
            return INTENT_GOAL_REQUEST
        return _SENTENCE_TYPE_TO_INTENT.get(sentence_type, INTENT_UNKNOWN)

    @staticmethod
    def _build_referenced_items(resolved_reference):
        if resolved_reference is None or not resolved_reference.has_reference:
            return []
        return [{
            "reference_text": resolved_reference.reference_text,
            "resolved_context": resolved_reference.resolved_context,
            "confidence": round(resolved_reference.confidence, 4),
            "ambiguous": resolved_reference.ambiguous,
        }]

    @staticmethod
    def _build_correction_understanding(result):
        """Prompt 440: expose Prompt 439's CorrectionUnderstanding, but
        ONLY when the existing Understanding Engine already identified
        an explicit correction (`result.correction_candidate` -
        understanding/correction_detection.py, REUSED, never
        re-detected here). Returns None - never a NOT_CORRECTION
        result - when no candidate is present, so an ordinary message
        creates no correction data at all; this is the exact
        pre-Prompt-440 behaviour for every message that is not that one
        fixed marker. Never raises: a malformed candidate is treated
        the same as "no candidate" rather than aborting understanding."""
        candidate = result.correction_candidate
        if not candidate:
            return None
        language = result.language if result.language != LANGUAGE_UNKNOWN else None
        try:
            correction = build_correction_understanding(
                result.original_text,
                original_expression=candidate.get("original_expression"),
                corrected_expression=candidate.get("corrected_expression"),
                language=language,
            )
        except (TypeError, ValueError):
            return None
        return correction.to_dict()

    def _resolve_learned_meanings(self, entities, detected_language, warnings):
        """Prompt 419: for each distinct candidate expression already
        found by the existing Understanding Engine (`entities` -
        REUSED, never re-extracted here), ask `self._meaning_resolver`
        (if configured) what has been LEARNED it means, and collect the
        results. Returns `(learned_meanings, warnings)` - `warnings` is
        `existing_warnings` unchanged, or with one added entry per
        lookup that raised (never allowed to propagate; see the module
        docstring). `entities`/`detected_language` are read-only here -
        this method never mutates either.

        No resolver configured, or no candidate expressions at all,
        returns `([], existing_warnings)` unchanged - the exact
        pre-Prompt-419 shape."""
        warnings = list(warnings) if warnings else []
        if self._meaning_resolver is None or not entities:
            return [], warnings

        # detected_language is None-safe against `_resolve_language`
        # ("unknown" is a placeholder, not a real language - see
        # language_learning_store.py); the resolver already searches
        # every language when language=None.
        language = detected_language if detected_language != LANGUAGE_UNKNOWN else None

        learned_meanings = []
        seen = set()
        for entity in entities:
            expression = (entity.get("text") or "").strip()
            key = expression.lower()
            if not expression or key in seen:
                continue
            seen.add(key)
            if len(learned_meanings) >= _MAX_LEARNED_MEANING_LOOKUPS:
                break
            try:
                # Prompt 673: conversational understanding is CURRENT use - prefer the
                # resolver's current-use lookup (inactive concepts excluded); a resolver
                # without one (e.g. a caller-supplied stub) keeps plain resolve().
                resolve = getattr(self._meaning_resolver, "resolve_current", None) \
                    or self._meaning_resolver.resolve
                resolution = resolve(expression, language=language)
            except Exception as e:  # noqa: BLE001 - a lookup failure must never break understanding
                warnings.append(f"{_LEARNED_MEANING_LOOKUP_ERROR_PREFIX}: {e}")
                continue
            learned_meanings.append(resolution.to_dict())
        return learned_meanings, warnings

    def _disambiguate_learned_meanings(self, learned_meanings, entities, active_topic, context,
                                        resolved_reference, warnings):
        """Prompt 420: for each entry `learned_meanings` above already
        produced (REUSED, never re-resolved), ask
        `self._meaning_disambiguator` (if configured) to decide between
        several learned meanings when there are more than one - using
        only context pieces this method already has: `active_topic`,
        `context` (a ConversationContext), `resolved_reference`, and the
        message's OTHER candidate expressions (from `entities`, REUSED)
        as `nearby_expressions`. Returns `(disambiguated_meanings,
        warnings)` - same shape/failure-handling convention as
        `_resolve_learned_meanings` above.

        No disambiguator configured, or no learned-meaning entries at
        all, returns `([], existing_warnings)` unchanged."""
        warnings = list(warnings) if warnings else []
        if self._meaning_disambiguator is None or not learned_meanings:
            return [], warnings

        all_expressions = [
            (entity.get("text") or "").strip() for entity in entities
        ]
        disambiguated = []
        for resolution in learned_meanings:
            if len(disambiguated) >= _MAX_LEARNED_MEANING_DISAMBIGUATIONS:
                break
            expression = resolution.get("expression")
            nearby = [e for e in all_expressions if e and e != expression]
            try:
                result = self._meaning_disambiguator.disambiguate(
                    resolution, language=resolution.get("language"),
                    active_topic=active_topic, conversation_context=context,
                    resolved_reference=resolved_reference, nearby_expressions=nearby,
                )
            except Exception as e:  # noqa: BLE001 - must never break understanding
                warnings.append(f"{_LEARNED_MEANING_DISAMBIGUATION_ERROR_PREFIX}: {e}")
                continue
            disambiguated.append(result.to_dict())
        return disambiguated, warnings

    def _match_learned_pattern(self, normalized_text, detected_language, warnings,
                                original_text=None):
        """Prompt 421: ask `self._pattern_matcher` (if configured)
        whether `normalized_text` - the message AS A WHOLE (REUSED, the
        exact same Understanding Engine output every other field on this
        result already comes from) - is an instance of a previously
        learned sentence pattern. Returns `(learned_pattern_match,
        learned_sentence_structure, warnings)` - same failure-handling
        convention as `_resolve_learned_meanings`/
        `_disambiguate_learned_meanings` above.

        Prompt 422: when a `structure_extractor` is configured, the
        structure is built from THIS call's match result (no second
        match) with `original_text` as its original message.

        No matcher configured, or no text to match against at all,
        returns `(None, None, existing_warnings)` unchanged - the exact
        pre-Prompt-421 shape."""
        warnings = list(warnings) if warnings else []
        if self._pattern_matcher is None or not normalized_text:
            return None, None, warnings

        language = detected_language if detected_language != LANGUAGE_UNKNOWN else None
        try:
            result = self._pattern_matcher.match(normalized_text, language=language)
        except Exception as e:  # noqa: BLE001 - a match failure must never break understanding
            warnings.append(f"{_LEARNED_PATTERN_MATCH_ERROR_PREFIX}: {e}")
            return None, None, warnings

        structure = None
        if self._structure_extractor is not None:
            try:
                structure = self._structure_extractor.from_match(
                    result, original_message=original_text,
                ).to_dict()
            except Exception as e:  # noqa: BLE001 - must never break understanding
                warnings.append(f"{_LEARNED_SENTENCE_STRUCTURE_ERROR_PREFIX}: {e}")
        return result.to_dict(), structure, warnings

    def _resolve_pattern_meaning(self, learned_pattern_match, original_text, entities,
                                 active_topic, context, resolved_reference, warnings):
        """Prompt 424: ask `self._pattern_meaning_binder` (if configured)
        for the meaning EXPLICITLY bound to the pattern
        `learned_pattern_match` (this call's own Prompt 421 result dict -
        never re-matched) recognized. Returns `(learned_pattern_meaning,
        warnings)` - same failure-handling convention as the methods
        above.

        No binder configured, or no match result at all, returns
        `(None, existing_warnings)` unchanged - the exact
        pre-Prompt-424 shape."""
        warnings = list(warnings) if warnings else []
        if self._pattern_meaning_binder is None or learned_pattern_match is None:
            return None, warnings
        nearby = [(entity.get("text") or "").strip() for entity in (entities or [])]
        try:
            resolution = self._pattern_meaning_binder.resolve(
                learned_pattern_match, original_message=original_text,
                active_topic=active_topic, conversation_context=context,
                resolved_reference=resolved_reference,
                nearby_expressions=[text for text in nearby if text],
            )
        except Exception as e:  # noqa: BLE001 - must never break understanding
            warnings.append(f"{_LEARNED_PATTERN_MEANING_ERROR_PREFIX}: {e}")
            return None, warnings
        return resolution.to_dict(), warnings

    @staticmethod
    def _score_confidence(base_confidence, resolved_reference, existing_warnings):
        warnings = list(existing_warnings) if existing_warnings else []
        confidence = base_confidence
        if (resolved_reference is not None and resolved_reference.has_reference
                and resolved_reference.ambiguous):
            confidence = confidence * _AMBIGUOUS_REFERENCE_CONFIDENCE_PENALTY
            warnings = warnings + [_AMBIGUOUS_REFERENCE_WARNING]
        return max(0.0, min(1.0, confidence)), warnings
