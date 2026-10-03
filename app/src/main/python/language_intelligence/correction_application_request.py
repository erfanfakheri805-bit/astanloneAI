"""
Language Intelligence - Correction Application Request
========================================================================
Prompt 473. A small, deterministic, READ-ONLY request structure built
ONLY from an already-built Prompt 470 `CorrectionApplicationCandidate`,
gated by the EXISTING Prompt 472 readiness check
(`correction_application_candidate_readiness.
is_correction_application_candidate_ready()`). This request is what a
LATER, separately-scoped conversation step MAY use to explicitly apply
the learned correction - this module never applies it itself.

    build_correction_application_candidate(...)     (Prompt 470, unchanged)
        -> CorrectionApplicationCandidate
    is_correction_application_candidate_ready(...)   (Prompt 472, unchanged)
        -> True / False
    build_correction_application_request(...)        (THIS module)
        -> CorrectionApplicationRequest

This module adds no new lookup, selection, matching, ranking, or
readiness logic of its own - it only copies an already-ready
candidate's existing fields into one small, flat, read-only structure,
the SAME "wrap an existing result as a small, flatter, read-only
structure" posture `correction_application_candidate.py` (Prompt 470)
already uses for `CorrectionSelectionResult` ->
`CorrectionApplicationCandidate`.

Only a READY candidate may produce a valid request
------------------------------------------------------------
Prompt 472's `is_correction_application_candidate_ready()` (imported,
never re-implemented or re-derived here) is the single source of truth
for readiness. A candidate that is not ready - whether because
`is_valid` is `False` or because a required field is missing/blank -
never produces a valid request; this module does not second-guess
that decision or invent a request where none is warranted.

Fields (only these eight; nothing else is carried)
----------------------------------------------------
    is_valid                          `True` only when
                                       `is_correction_application_candidate_ready(candidate)`
                                       was `True`. The one field a
                                       later step needs to check before
                                       doing anything else with this
                                       request.
    kind                               `REQUEST_KIND_APPLY_CORRECTION`
                                       when valid, else `None` - the
                                       fixed marker that clearly
                                       identifies this as an explicit
                                       correction-application request
                                       (never any other value, never
                                       inferred).
    original_expression                `candidate.original_expression`
                                        when valid, else `None` -
                                        copied straight through.
    corrected_expression_or_meaning    `candidate.
                                        corrected_expression_or_meaning`
                                        when valid, else `None` -
                                        copied straight through
                                        (deep-copied; see below).
    language                           `candidate.language` when
                                        valid, else `None` - copied
                                        straight through.
    locale                             `candidate.locale` when valid,
                                        else `None` - copied straight
                                        through (Prompt 470's own
                                        `CorrectionApplicationCandidate.
                                        locale` is always `None`
                                        today, so this is too, but the
                                        field is preserved rather than
                                        hard-coded, exactly like every
                                        other field here).
    source                             `candidate.source` when valid,
                                        else `None` - copied straight
                                        through.
    confidence                         `candidate.confidence` when
                                        valid, else `None` - copied
                                        straight through.

Never applies anything
-------------------------
`build_correction_application_request()` and
`CorrectionApplicationRequest` never apply the correction, never
modify the user's message, never modify generated response text,
never modify any stored learning record, never write to storage,
never touch Memory, Knowledge, the Learning algorithms, Response
Generation, Language Understanding, or the Local Model Runtime, and
never perform fuzzy/semantic matching, ranking, scoring, or inference.
Building a request is the entire operation - actually applying one is
a separate, future, explicitly scoped step.

Read-only and non-mutating
-----------------------------
`build_correction_application_request()` only reads
`candidate.is_valid` (via the Prompt 472 readiness check) and the six
existing candidate fields listed above - it never sets, appends, or
otherwise mutates `candidate` or anything upstream of it. The one
field that can carry a mutable, caller-shaped value
(`corrected_expression_or_meaning`) is deep-copied at construction
time, the SAME `copy.deepcopy()` convention
`CorrectionApplicationCandidate` already uses for its own field of the
same name. `to_dict()` also returns a fresh, independent structure on
every call. The same candidate always produces an equal request.

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`,
`LanguageUnderstandingResult`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`LearningAnalyzer`, Memory, Knowledge, Response Generation, or the
Local Model Runtime; it adds no new persistence, no new database, no
ranking/scoring/fuzzy/semantic matching, no inference, and makes no
network/API call. It does not modify `CorrectionApplicationCandidate`,
`build_correction_application_candidate()`,
`is_correction_application_candidate_ready()`, or anything upstream of
them.
"""

import copy

from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_application_candidate_readiness import (
    is_correction_application_candidate_ready,
)

REQUEST_KIND_APPLY_CORRECTION = "apply_correction"


class CorrectionApplicationRequest:
    """The minimum useful fields describing one explicit request to
    apply a correction - nothing more. See the module docstring for
    the exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()` and `copy()`. Never applies anything -
    see the module docstring.
    """

    __slots__ = (
        "is_valid", "kind", "original_expression",
        "corrected_expression_or_meaning", "language", "locale",
        "source", "confidence",
    )

    def __init__(self, is_valid, kind=None, original_expression=None,
                 corrected_expression_or_meaning=None, language=None,
                 locale=None, source=None, confidence=None):
        self.is_valid = bool(is_valid)
        self.kind = kind
        self.original_expression = original_expression
        self.corrected_expression_or_meaning = copy.deepcopy(
            corrected_expression_or_meaning)
        self.language = language
        self.locale = locale
        self.source = source
        self.confidence = confidence

    def to_dict(self):
        """This request as a plain, JSON-shaped dict - the same
        `to_dict()` convention `CorrectionApplicationCandidate`
        already uses. `corrected_expression_or_meaning` is
        deep-copied again here, so mutating the returned dict never
        reaches back into this request."""
        return {
            "is_valid": self.is_valid,
            "kind": self.kind,
            "original_expression": self.original_expression,
            "corrected_expression_or_meaning": copy.deepcopy(
                self.corrected_expression_or_meaning),
            "language": self.language,
            "locale": self.locale,
            "source": self.source,
            "confidence": self.confidence,
        }

    def copy(self):
        """Return a new, independent `CorrectionApplicationRequest`
        with the same eight fields (`self.copy() == self`). The SAME
        "deep-copy the one mutable field, pass everything else
        through" convention `CorrectionApplicationCandidate.copy()`
        (Prompt 470) already follows. Never mutates `self`."""
        return CorrectionApplicationRequest(
            is_valid=self.is_valid,
            kind=self.kind,
            original_expression=self.original_expression,
            corrected_expression_or_meaning=copy.deepcopy(
                self.corrected_expression_or_meaning),
            language=self.language,
            locale=self.locale,
            source=self.source,
            confidence=self.confidence,
        )

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationRequest):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationRequest(%r)" % (self.to_dict(),)


def build_correction_application_request(candidate):
    """Build a `CorrectionApplicationRequest` from an EXISTING
    `CorrectionApplicationCandidate` (Prompt 470 - required;
    `TypeError` otherwise, the SAME "isinstance check, then raise"
    posture `build_correction_application_candidate()` already uses).

    Only a candidate that Prompt 472's
    `is_correction_application_candidate_ready()` reports as ready
    produces a valid request (`is_valid=True`, `kind` set to
    `REQUEST_KIND_APPLY_CORRECTION`, every other field copied from
    `candidate` - see the module docstring). A not-ready candidate
    produces the SAME empty, invalid request (`is_valid=False`, every
    other field `None`) - this function never second-guesses
    readiness or invents a request for a candidate that is not ready.

    Pure and deterministic: the same candidate always produces an
    equal request, and nothing is mutated, stored, applied, or
    connected to the conversation pipeline here.
    """
    if not isinstance(candidate, CorrectionApplicationCandidate):
        raise TypeError(
            "candidate must be a CorrectionApplicationCandidate "
            "(language_intelligence.correction_application_candidate."
            "CorrectionApplicationCandidate) instance"
        )

    if not is_correction_application_candidate_ready(candidate):
        return CorrectionApplicationRequest(is_valid=False)

    return CorrectionApplicationRequest(
        is_valid=True,
        kind=REQUEST_KIND_APPLY_CORRECTION,
        original_expression=candidate.original_expression,
        corrected_expression_or_meaning=copy.deepcopy(
            candidate.corrected_expression_or_meaning),
        language=candidate.language,
        locale=candidate.locale,
        source=candidate.source,
        confidence=candidate.confidence,
    )
