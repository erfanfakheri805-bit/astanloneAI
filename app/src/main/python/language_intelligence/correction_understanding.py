"""
Language Intelligence - Explicit Correction Structure
=======================================================
Prompt 439. A small, deterministic structure for representing ONE user
correction that the existing understanding/conversation flow has ALREADY
identified explicitly - e.g. an original expression the user used and the
corrected expression or corrected meaning they explicitly supplied in its
place.

This module does not detect, parse or infer a correction from free-form
conversation text. It takes only already-identified pieces (whatever
upstream, deterministic step recognized them) and turns them into one
plain, JSON-shaped result with a fixed status - the same "structure,
don't fabricate" posture as every other result in this package
(MeaningResolutionResult, LearnedExpressionVariationMatchResult,
LearnedResponseDecision, ...). Nothing here:

    - guesses at a correction from ordinary conversation text
    - invents a meaning, synonym, translation or relationship
    - fills in a missing original or corrected expression
    - stores anything in memory or the language-learning database
    - touches LearnedMeaningResolution, LearnedExpressionVariationMatcher,
      LearnedPatternMatcher, response pattern selection or response
      generation - those integrations are out of scope for this stage

Fields (the minimum useful set; nothing else is carried)
----------------------------------------------------------
    status                 one of the STATUS_* constants below
    original_expression    the expression being corrected, exactly as
                            supplied - never normalized, translated or
                            reworded
    corrected_expression   the corrected wording, exactly as supplied, or
                            None
    corrected_meaning      the corrected meaning/interpretation, exactly
                            as supplied (any caller-shaped JSON value), or
                            None
    language                exactly as supplied, or None
    locale                  exactly as supplied, or None
    source_text             the original user message, verbatim,
                            untouched - the one field a caller can always
                            trust to be exactly what the user typed
    confidence               a float in [0.0, 1.0]; 0.0 when not supplied

Statuses
--------
    STATUS_RESOLVED        an original expression AND a corrected
                            expression and/or corrected meaning were both
                            supplied - the correction is fully identified
    STATUS_AMBIGUOUS        more than one candidate corrected form was
                            supplied (`corrected_candidates`) and nothing
                            picked one - `corrected_expression` and
                            `corrected_meaning` stay None; nothing is
                            guessed
    STATUS_UNRESOLVED       some correction-relevant piece was supplied
                            (an original expression, a corrected
                            expression/meaning, or candidates) but not
                            enough to resolve it (e.g. only one side of
                            the correction is present)
    STATUS_NOT_CORRECTION   nothing correction-related was supplied at
                            all

Decision order (first match wins; fixed, no scoring model):

    1. `corrected_candidates` has more than one distinct, non-blank
       entry                                         -> AMBIGUOUS
    2. an original expression AND (a corrected expression or a corrected
       meaning) are both present                     -> RESOLVED
    3. anything correction-relevant is present at all
       (original expression, corrected expression, corrected meaning, or
       exactly one candidate)                        -> UNRESOLVED
    4. nothing at all                                 -> NOT_CORRECTION

`build_correction_understanding()` is pure and deterministic: the same
arguments always produce the same result, and nothing is mutated,
stored or looked up anywhere.
"""

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_NOT_CORRECTION = "NOT_CORRECTION"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION)


def _is_blank(value):
    """True for the 'nothing supplied' shapes (None, blank text, empty
    list/dict/tuple). 0 and False are real values, not blank."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _clean(value):
    """None through unchanged; a string is passed through as-is; a blank
    value becomes None. Never rewrites, trims meaning, or invents."""
    return None if _is_blank(value) else value


def _clamp_confidence(confidence):
    if confidence is None:
        return 0.0
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be a real number or None")
    return max(0.0, min(1.0, float(confidence)))


def _distinct_candidates(corrected_candidates):
    """Non-blank, de-duplicated candidate strings, in the order first
    seen - or [] when `corrected_candidates` is not a usable list/tuple."""
    if not isinstance(corrected_candidates, (list, tuple)):
        return []
    seen = []
    for candidate in corrected_candidates:
        if isinstance(candidate, str):
            normalized = candidate.strip()
            if normalized and normalized not in seen:
                seen.append(normalized)
    return seen


class CorrectionUnderstandingResult:
    """Plain, read-only, JSON-shaped record of one explicit correction -
    same `to_dict()` convention used throughout this package. Never
    constructed directly by conversation-flow code from raw text; built
    only from pieces an existing deterministic step already identified.
    """

    def __init__(self, status, source_text, original_expression=None,
                 corrected_expression=None, corrected_meaning=None,
                 language=None, locale=None, confidence=0.0):
        if status not in ALL_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        self.status = status
        self.source_text = source_text
        self.original_expression = original_expression
        self.corrected_expression = corrected_expression
        self.corrected_meaning = corrected_meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence

    def to_dict(self):
        return {
            "status": self.status,
            "original_expression": self.original_expression,
            "corrected_expression": self.corrected_expression,
            "corrected_meaning": self.corrected_meaning,
            "language": self.language,
            "locale": self.locale,
            "source_text": self.source_text,
            "confidence": self.confidence,
        }

    def __repr__(self):
        return (f"CorrectionUnderstandingResult(status={self.status!r}, "
                f"original_expression={self.original_expression!r}, "
                f"corrected_expression={self.corrected_expression!r}, "
                f"corrected_meaning={self.corrected_meaning!r})")


def build_correction_understanding(source_text, original_expression=None,
                                    corrected_expression=None, corrected_meaning=None,
                                    corrected_candidates=None, language=None,
                                    locale=None, confidence=None):
    """Build one `CorrectionUnderstandingResult` from pieces an existing
    deterministic understanding/conversation-flow step already
    identified. Pure and deterministic - the same arguments always give
    the same result. Never stores, looks up, infers or guesses anything.

    `source_text` is required and preserved exactly (the caller's
    original message). Every other argument is optional; a missing or
    blank one is represented as None in the result, never filled in.
    `corrected_candidates` is used only to detect an AMBIGUOUS
    correction (more than one distinct candidate, none of them chosen) -
    it is not itself part of the result.
    """
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text is required and must be non-blank text")

    original = _clean(original_expression)
    corrected_text = _clean(corrected_expression)
    corrected_meaning_value = _clean(corrected_meaning)
    lang = _clean(language)
    loc = _clean(locale)
    conf = _clamp_confidence(confidence)
    candidates = _distinct_candidates(corrected_candidates)

    def result(status, **fields):
        return CorrectionUnderstandingResult(
            status, source_text, language=lang, locale=loc, confidence=conf, **fields)

    if len(candidates) > 1:
        return result(STATUS_AMBIGUOUS, original_expression=original)

    if original is not None and (corrected_text is not None or corrected_meaning_value is not None):
        return result(
            STATUS_RESOLVED, original_expression=original,
            corrected_expression=corrected_text, corrected_meaning=corrected_meaning_value)

    if original is not None or corrected_text is not None or corrected_meaning_value is not None \
            or len(candidates) == 1:
        return result(
            STATUS_UNRESOLVED, original_expression=original,
            corrected_expression=corrected_text, corrected_meaning=corrected_meaning_value)

    return result(STATUS_NOT_CORRECTION)
