"""
Conversation Context - Importance Scoring
============================================
A small, deterministic (never randomized, never "AI-scored") importance
heuristic for a piece of conversational context, per the project's
"do not invent complex AI scoring" requirement.

Every contribution below is a fixed weight tied to an actual signal
already available on an UnderstandingResult - the same style already
used by understanding/engine.py:_compute_confidence for its own
confidence score.
"""

from understanding.sentence_analysis import SENTENCE_COMMAND

_WEIGHT_BASE = 0.1
_WEIGHT_HAS_RELATIONS = 0.4
_WEIGHT_HAS_ENTITIES = 0.2
_WEIGHT_IS_COMMAND = 0.1
_WEIGHT_EXPLICIT_MEMORY_CUE = 0.3
_PENALTY_VERY_SHORT = 0.1

# Small, explicit set of phrases that signal the user is deliberately
# asking to have something remembered/kept - a strong, real signal, not
# a guess. Kept short and easy to extend.
_MEMORY_CUE_PHRASES_EN = ("remember that", "remember this", "keep in mind", "note that", "don't forget")
_MEMORY_CUE_PHRASES_FA = ("یادت باشد", "به خاطر بسپار", "فراموش نکن")
_ALL_MEMORY_CUE_PHRASES = _MEMORY_CUE_PHRASES_EN + _MEMORY_CUE_PHRASES_FA

IMPORTANCE_MIN = 0.0
IMPORTANCE_MAX = 1.0


def compute_importance(understanding_result):
    """Return a 0.0-1.0 importance score for `understanding_result`,
    using only deterministic signals already present on it. Never
    raises - a result with no normalized text scores the minimum."""
    if not understanding_result.normalized_text:
        return IMPORTANCE_MIN

    score = _WEIGHT_BASE

    if understanding_result.relations:
        score += _WEIGHT_HAS_RELATIONS
    if understanding_result.entities:
        score += _WEIGHT_HAS_ENTITIES
    if understanding_result.sentence_type == SENTENCE_COMMAND:
        score += _WEIGHT_IS_COMMAND

    text_lower = understanding_result.normalized_text.lower()
    if any(phrase in text_lower for phrase in _ALL_MEMORY_CUE_PHRASES):
        score += _WEIGHT_EXPLICIT_MEMORY_CUE

    if len(understanding_result.tokens) <= 2:
        score -= _PENALTY_VERY_SHORT

    return max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, score))
