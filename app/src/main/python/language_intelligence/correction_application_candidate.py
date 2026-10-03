"""
Language Intelligence - Selected Correction Application Candidate
========================================================================
Prompt 470. A small, deterministic, READ-ONLY candidate built ONLY
from the EXISTING Prompt 469 `CorrectionSelectionResult`
(correction_lookup_selection.py:
`select_unique_stored_correction()`/`CorrectionSelectionResult`). This
candidate represents a correction that a LATER, separately-scoped
conversation step MAY choose to apply - this module never applies it
itself.

    select_unique_stored_correction(...)          (Prompt 469, unchanged)
        -> CorrectionSelectionResult
    build_correction_application_candidate(...)    (THIS module)
        -> CorrectionApplicationCandidate

This module adds no new lookup, selection, matching, or ranking logic
- it only copies the already-selected correction's existing fields
(when there is one) into one small, flat, read-only structure, the
SAME "wrap an existing result as a small, flatter, read-only
structure" posture `correction_lookup_context.py` (Prompt 465) already
uses for `CorrectionLearningExactLookupResult` ->
`CorrectionLookupContext`.

Only a `SELECTED` result may produce a valid candidate
------------------------------------------------------------
`AMBIGUOUS`, `NOT_FOUND`, and `FAILED` never produce a usable
candidate - choosing one of several candidates, or inventing one where
none/no single one exists, is exactly the kind of selection Prompt 469
already refused to make, and this module does not second-guess that
decision. `is_valid` (see below) is how a caller distinguishes a
usable candidate from an empty placeholder without inspecting the
originating `CorrectionSelectionResult` itself.

Fields (only these seven; nothing else is carried)
----------------------------------------------------
    is_valid                          `True` only when the originating
                                       `CorrectionSelectionResult.outcome`
                                       was `SELECTED` (Prompt 469's own
                                       `OUTCOME_SELECTED`, imported here,
                                       never redefined) - `False` for
                                       `AMBIGUOUS`, `NOT_FOUND`, and
                                       `FAILED`. The one field a later
                                       step needs to check before doing
                                       anything else with this candidate.
    original_expression                `selection_result.correction["key"]`
                                        when valid, else `None` - the
                                        SAME `key` field Prompt 463's own
                                        stored record shape already uses
                                        for this piece of information.
    corrected_expression_or_meaning    `selection_result.correction
                                        ["meaning"]` when valid, else
                                        `None` - that SAME stored
                                        record's own `meaning` field,
                                        copied through unchanged (never
                                        split, reworded, or re-derived).
    language                           `selection_result.correction
                                        ["language"]` when valid, else
                                        `None` - copied straight through.
    locale                             always `None`. `locale` was
                                        never part of the stored
                                        correction-learning record shape
                                        in the first place (Prompt 455's
                                        own documented decision, carried
                                        unchanged through Prompt 465's
                                        own `CorrectionLookupContext.
                                        locale`); this candidate does
                                        not invent a place for it either.
    source                             `selection_result.correction
                                        ["source"]` when valid, else
                                        `None` - copied straight
                                        through, the SAME field
                                        `CorrectionLookupContext.source`
                                        already reports.
    confidence                         `selection_result.correction
                                        ["confidence"]` when valid, else
                                        `None` - copied straight
                                        through, unchanged.

Never applies anything
-------------------------
`build_correction_application_candidate()` and
`CorrectionApplicationCandidate` never modify the user's message, never
modify any stored learning record, never write to storage, never touch
Memory, Knowledge, the Learning algorithms, Response Generation, or the
Local Model Runtime, never generate response text, and never perform
fuzzy/semantic matching, ranking, scoring, or inference. Building a
candidate is the entire operation - deciding whether or how to use one
is a separate, future, explicitly scoped step, exactly as Prompt 469's
own module docstring already says about choosing among several
candidates.

Read-only and non-mutating
-----------------------------
`build_correction_application_candidate()` only reads
`selection_result.outcome` and `selection_result.correction` - it
never sets, appends, or otherwise mutates `selection_result`, the
`correction` dict inside it, or anything upstream of it. The one field
that can carry a mutable, caller-shaped value
(`corrected_expression_or_meaning`, which may be any JSON-shaped
`meaning`) is deep-copied at construction time, the SAME
`copy.deepcopy()` convention `CorrectionLookupContext` already uses
for its own `records` field - mutating the `CorrectionSelectionResult`
the candidate was built from afterwards never changes the candidate,
and mutating the candidate never reaches back into the selection
result. `to_dict()` also returns a fresh, independent structure on
every call, the SAME "never hand back shared mutable state" posture
already used throughout this package. The same `CorrectionSelectionResult`
always produces an equal candidate.

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`,
`LanguageUnderstandingResult`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`LearningAnalyzer`, Memory, Knowledge, Response Generation, or the
Local Model Runtime; it adds no new persistence, no new database, no
ranking/scoring/fuzzy/semantic matching, no inference, and makes no
network/API call. It does not modify `CorrectionSelectionResult`,
`select_unique_stored_correction()`, or anything upstream of them - a
thin, read-only candidate built from a result that already exists.
"""

import copy

from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, OUTCOME_SELECTED,
)


class CorrectionApplicationCandidate:
    """The minimum useful fields describing one possible correction
    application - nothing more. See the module docstring for the
    exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()` and `copy()`. Never applies anything -
    see the module docstring.
    """

    __slots__ = (
        "is_valid", "original_expression", "corrected_expression_or_meaning",
        "language", "locale", "source", "confidence",
    )

    def __init__(self, is_valid, original_expression=None,
                 corrected_expression_or_meaning=None, language=None,
                 locale=None, source=None, confidence=None):
        self.is_valid = bool(is_valid)
        self.original_expression = original_expression
        self.corrected_expression_or_meaning = copy.deepcopy(
            corrected_expression_or_meaning)
        self.language = language
        self.locale = locale
        self.source = source
        self.confidence = confidence

    def to_dict(self):
        """This candidate as a plain, JSON-shaped dict - the same
        `to_dict()` convention used throughout this package.
        `corrected_expression_or_meaning` is deep-copied again here,
        so mutating the returned dict never reaches back into this
        candidate."""
        return {
            "is_valid": self.is_valid,
            "original_expression": self.original_expression,
            "corrected_expression_or_meaning": copy.deepcopy(
                self.corrected_expression_or_meaning),
            "language": self.language,
            "locale": self.locale,
            "source": self.source,
            "confidence": self.confidence,
        }

    def copy(self):
        """Return a new, independent `CorrectionApplicationCandidate`
        with the same seven fields (`self.copy() == self`). The SAME
        "deep-copy the one mutable field, pass everything else
        through" convention `CorrectionLookupContext.copy()` (Prompt
        465) already follows. Never mutates `self`."""
        return CorrectionApplicationCandidate(
            is_valid=self.is_valid,
            original_expression=self.original_expression,
            corrected_expression_or_meaning=copy.deepcopy(
                self.corrected_expression_or_meaning),
            language=self.language,
            locale=self.locale,
            source=self.source,
            confidence=self.confidence,
        )

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationCandidate):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationCandidate(%r)" % (self.to_dict(),)


def build_correction_application_candidate(selection_result):
    """Build a `CorrectionApplicationCandidate` from an EXISTING
    `CorrectionSelectionResult` (Prompt 469 - required; `TypeError`
    otherwise, the SAME "isinstance check, then raise" posture
    `build_correction_lookup_context()` already uses).

    Only `selection_result.outcome == OUTCOME_SELECTED` produces a
    valid candidate (`is_valid=True`, every field populated from
    `selection_result.correction` - see the module docstring).
    `AMBIGUOUS`, `NOT_FOUND`, and `FAILED` all produce the SAME empty,
    invalid candidate (`is_valid=False`, every other field `None`) -
    this function never chooses among several candidates or invents
    one where none/no single one exists.

    Pure and deterministic: the same `CorrectionSelectionResult`
    always produces an equal candidate, and nothing is mutated,
    stored, applied, or connected to the conversation pipeline here.
    """
    if not isinstance(selection_result, CorrectionSelectionResult):
        raise TypeError(
            "selection_result must be a CorrectionSelectionResult "
            "(language_intelligence.correction_lookup_selection."
            "CorrectionSelectionResult) instance"
        )

    if selection_result.outcome != OUTCOME_SELECTED:
        return CorrectionApplicationCandidate(is_valid=False)

    correction = selection_result.correction or {}
    return CorrectionApplicationCandidate(
        is_valid=True,
        original_expression=correction.get("key"),
        corrected_expression_or_meaning=correction.get("meaning"),
        language=correction.get("language"),
        locale=None,
        source=correction.get("source"),
        confidence=correction.get("confidence"),
    )
