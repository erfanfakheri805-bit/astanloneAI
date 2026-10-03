"""
Understanding Engine
======================
Orchestrates the pipeline described in the project's Understanding
Engine spec:

    USER INPUT
      -> INPUT NORMALIZATION        (normalization.py)
      -> LANGUAGE DETECTION         (language_detection.py)
      -> TOKENIZATION               (nl_tokenizer.py)
      -> SENTENCE ANALYSIS          (sentence_analysis.py)
      -> ENTITY / TERM EXTRACTION   (entity_extraction.py)
      -> RELATION CANDIDATE EXTR.   (relation_extraction.py)
      -> STRUCTURED UNDERSTANDING RESULT  (result.py)
      -> LEARNING ENGINE            (learning/learning_system.py)

This is a new, additional layer that sits alongside the existing
Parser (parser/parser.py) - it does not replace it, and nothing in
Core's existing process_input() flow (AEL vs. conversation routing) is
changed by its presence. Core exposes it separately via
`Core.understand(text)` for callers (a future UI panel, a future
auto-learning stage) that want structured natural-language analysis
without affecting today's conversational behaviour.

This stage never writes to permanent storage. It only ever returns a
UnderstandingResult describing what it noticed; see
learning/learning_system.py:learn_from_understanding for the bridge
into actual learning (Core.learn_from_text() runs both steps together).

Context-aware understanding
-----------------------------
`understand()` optionally accepts a `context` (a
context.conversation_context.ConversationContext, or anything exposing
the same `recent_entries()` read interface). When given, a CONTEXT
RESOLUTION step runs between relation extraction and entity extraction:

    ... -> RELATION CANDIDATE EXTR. -> CONTEXT RESOLUTION
        -> ENTITY/TERM EXTRACTION -> STRUCTURED UNDERSTANDING RESULT

so a simple reference ("It uses indentation." right after "Python is a
programming language.") is resolved to the concept it refers to
*before* entities/relations are finalized - see
context/reference_resolution.py. `context=None` (the default) skips
this step entirely and reproduces the exact previous-stage behaviour;
this module has no hard dependency on the context package unless a
caller actually asks for context-aware analysis.
"""

from .normalization import normalize
from .language_detection import detect_language, LANGUAGE_UNKNOWN
from .nl_tokenizer import tokenize
from .sentence_analysis import detect_sentence_type, SENTENCE_UNKNOWN
from .relation_extraction import extract_relation_candidates
from .entity_extraction import extract_entities
from .correction_detection import detect_explicit_correction

# Deterministic confidence weights. These are fixed contributions from
# actual signals found during analysis - never randomized and never
# guessed. Kept as module-level constants (rather than magic numbers
# inline) so a later stage can tune them without hunting through logic.
_WEIGHT_BASE = 0.20
_WEIGHT_LANGUAGE_KNOWN = 0.15
_WEIGHT_SENTENCE_TYPE_KNOWN = 0.15
_WEIGHT_HAS_ENTITIES = 0.20
_WEIGHT_RELATION_MAX = 0.30


class UnderstandingEngine:
    """Stateless: safe to reuse a single instance for every call, or
    construct one per call - there is no per-instance mutable state."""

    def understand(self, raw_text, context=None):
        """Run the full pipeline over `raw_text` and return an
        UnderstandingResult. Never raises: malformed/empty/unsupported
        input produces a result with warnings set instead of an
        exception, per the project's error-handling requirement.

        `context`, if given, enables the CONTEXT RESOLUTION step - see
        module docstring. Malformed/exhausted context resolution never
        raises out of this method either: a failure there is treated
        the same as "nothing resolved" (relations pass through
        unchanged) rather than aborting understanding altogether.
        """
        # Imported here (not at module top) only to avoid a circular
        # import at module load time - result.py has no dependency on
        # this module, so this is just defensive, not load-bearing.
        from .result import UnderstandingResult

        warnings = []

        norm = normalize(raw_text)
        original_text = norm.original_text
        normalized_text = norm.normalized_text

        if not normalized_text:
            warnings.append("empty_input")
            return UnderstandingResult(
                original_text=original_text,
                normalized_text=normalized_text,
                language=LANGUAGE_UNKNOWN,
                tokens=[],
                sentence_type=SENTENCE_UNKNOWN,
                entities=[],
                relations=[],
                confidence=0.0,
                warnings=warnings,
            )

        language = detect_language(normalized_text)
        if language == LANGUAGE_UNKNOWN:
            warnings.append("language_undetermined")

        tokens = tokenize(normalized_text)
        if not tokens:
            warnings.append("no_tokens_extracted")

        sentence_type = detect_sentence_type(normalized_text, tokens, language)
        if sentence_type == SENTENCE_UNKNOWN:
            warnings.append("sentence_type_undetermined")

        relations = extract_relation_candidates(normalized_text, sentence_type)

        context_resolutions = []
        if context is not None and relations:
            try:
                # Imported lazily so the Understanding Engine has no
                # hard/circular dependency on the context package for
                # the (still fully supported) context=None call shape.
                from context.reference_resolution import resolve_context_references
                relations, context_resolutions = resolve_context_references(relations, context)
            except Exception as e:  # context resolution must never break understanding
                warnings.append(f"context_resolution_error: {e}")

        entities = extract_entities(normalized_text, sentence_type, relations)
        if not entities:
            warnings.append("no_entities_extracted")

        confidence = self._compute_confidence(language, sentence_type, entities, relations)

        # Prompt 440: a small, additive, side-effect-free check for the
        # one fixed explicit correction marker correction_detection.py
        # recognizes. Never changes language/sentence_type/entities/
        # relations/confidence/warnings above; None for every message
        # that is not that one explicit marker (the ordinary, unchanged
        # case).
        correction_candidate = detect_explicit_correction(normalized_text)

        return UnderstandingResult(
            original_text=original_text,
            normalized_text=normalized_text,
            language=language,
            tokens=tokens,
            sentence_type=sentence_type,
            entities=entities,
            relations=relations,
            confidence=confidence,
            warnings=warnings,
            context_resolutions=context_resolutions,
            correction_candidate=(
                correction_candidate.to_dict() if correction_candidate is not None else None
            ),
        )

    @staticmethod
    def _compute_confidence(language, sentence_type, entities, relations):
        score = _WEIGHT_BASE
        if language != LANGUAGE_UNKNOWN:
            score += _WEIGHT_LANGUAGE_KNOWN
        if sentence_type != SENTENCE_UNKNOWN:
            score += _WEIGHT_SENTENCE_TYPE_KNOWN
        if entities:
            score += _WEIGHT_HAS_ENTITIES
        if relations:
            best_pattern_confidence = max(r.confidence for r in relations)
            score += _WEIGHT_RELATION_MAX * best_pattern_confidence
        return max(0.0, min(1.0, score))
