"""
Language Intelligence - Select a Unique Stored Correction
========================================================================
Prompt 469. A small, deterministic selection operation over the
EXISTING Prompt 465 `CorrectionLookupContext`
(correction_lookup_context.py) and its Prompt 468 usability rules
(`correction_lookup_usability.py`). This module answers exactly one
question - "does this already-built lookup context resolve to exactly
one usable stored correction?" - and nothing else. It does not perform
a lookup, does not perform fuzzy or semantic matching, does not rank
or score candidates, does not guess user intent, does not apply a
correction, does not modify the user's message, does not generate any
response text, and does not learn or write anything.

    build_correction_lookup_context(...)        (Prompt 465, unchanged)
        -> CorrectionLookupContext
    is_correction_lookup_context_usable(...)     (Prompt 468, unchanged)
        -> True / False  (reused here as `_is_usable_record()`)
    select_unique_stored_correction(...)         (THIS module)
        -> CorrectionSelectionResult

Outcomes
---------
    SELECTED    exactly one usable stored correction record exists
                (`status == FOUND` and exactly one record in
                `context.records` is usable - see "usable" below).
                `correction` holds that record, deep-copied, with
                every one of its existing fields preserved unchanged.
    AMBIGUOUS   more than one usable stored correction record exists.
                `candidates` holds every usable record, deep-copied,
                in the SAME order `context.records` already has them
                in - never ranked, scored, or reduced to one.
    NOT_FOUND   `status == FOUND` but no usable record exists (empty
                `records`, or every record present is unusable), OR
                `status == NOT_FOUND` - both mean "no usable
                correction" from this operation's point of view.
    FAILED      `status == FAILED` - the underlying lookup/context
                itself failed. `reason` carries the context's own
                existing `reason`, unchanged; no correction is
                invented in its place.

What "usable" means
---------------------
Exactly Prompt 468's own definition, reused rather than
re-implemented: a record counts only when it is a dict with both a
non-blank `key` and a non-blank `meaning` (`correction_lookup_usability.
_is_usable_record()`, imported here, never redefined - the SAME
existing correction-record structure and validation rules; no new
semantic rule is introduced). Any other field on a record
(`language`, `confidence`, `source`, `source_context`, `id`,
`version`, timestamps, ...) plays no part in this decision.

Read-only and non-mutating
-----------------------------
`select_unique_stored_correction()` only reads `context.status`,
`context.records`, and `context.reason` - it never sets, appends, or
otherwise mutates `context`, any record dict inside `context.records`,
or the underlying store. `correction` and `candidates` are built with
`copy.deepcopy()`, the SAME convention `CorrectionLookupContext`
already uses for its own `records` field - mutating the returned
result never reaches back into `context`, and mutating `context`
afterwards never changes an already-built result. The same
`CorrectionLookupContext` always produces an equal
`CorrectionSelectionResult`.

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`,
`LanguageUnderstandingResult`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`LearningAnalyzer`, Memory, Knowledge, Response Generation, or the
Local Model Runtime; it adds no new persistence, no new database, no
ranking/scoring/fuzzy/semantic matching, no inference, and makes no
network/API call. It does not modify `CorrectionLookupContext`,
`build_correction_lookup_context()`, `is_correction_lookup_context_
usable()`, or anything upstream of them - a thin, read-only selection
over an object that already exists.
"""

import copy

from language_intelligence.correction_lookup_context import CorrectionLookupContext
from language_intelligence.correction_learning_exact_lookup_result import (
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
)
from language_intelligence.correction_lookup_usability import _is_usable_record

OUTCOME_SELECTED = "SELECTED"
OUTCOME_AMBIGUOUS = "AMBIGUOUS"
OUTCOME_NOT_FOUND = "NOT_FOUND"
OUTCOME_FAILED = "FAILED"
ALL_OUTCOMES = (OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED)


class CorrectionSelectionResult:
    """The minimum useful fields describing one selection attempt -
    nothing more. See the module docstring for the exact meaning of
    each outcome.

        outcome       one of ALL_OUTCOMES.
        correction    the single usable record, deep-copied with all
                       of its existing fields preserved, ONLY for
                       SELECTED. `None` otherwise.
        candidates    every usable record, deep-copied, in their
                       existing order, ONLY for AMBIGUOUS. `[]`
                       otherwise.
        reason        the context's own existing `reason`, unchanged,
                       ONLY for FAILED. `None` otherwise.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`.
    """

    __slots__ = ("outcome", "correction", "candidates", "reason")

    def __init__(self, outcome, correction=None, candidates=None, reason=None):
        if outcome not in ALL_OUTCOMES:
            raise ValueError(
                "outcome must be one of %r, got %r" % (ALL_OUTCOMES, outcome)
            )
        self.outcome = outcome
        self.correction = copy.deepcopy(correction) if correction is not None else None
        self.candidates = copy.deepcopy(list(candidates)) if candidates else []
        self.reason = reason

    def to_dict(self):
        """This result as a plain, JSON-shaped dict - the same
        `to_dict()` convention used throughout this package.
        `correction`/`candidates` are deep-copied again here, so
        mutating the returned dict never reaches back into this
        result."""
        return {
            "outcome": self.outcome,
            "correction": copy.deepcopy(self.correction),
            "candidates": copy.deepcopy(self.candidates),
            "reason": self.reason,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionSelectionResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionSelectionResult(%r)" % (self.to_dict(),)


def select_unique_stored_correction(context):
    """Select the single usable stored correction from an EXISTING
    `CorrectionLookupContext` (Prompt 465 - required; `TypeError`
    otherwise, the SAME "isinstance check, then raise" posture
    `is_correction_lookup_context_usable()` already uses), reporting
    the outcome as a `CorrectionSelectionResult` - see the module
    docstring for exactly what each outcome means and when it applies.

    Pure and deterministic: the same `CorrectionLookupContext` always
    produces an equal result, and nothing is mutated, chosen among
    ties, ranked, scored, applied, or stored here.
    """
    if not isinstance(context, CorrectionLookupContext):
        raise TypeError(
            "context must be a CorrectionLookupContext "
            "(language_intelligence.correction_lookup_context."
            "CorrectionLookupContext) instance"
        )

    if context.status == STATUS_FAILED:
        return CorrectionSelectionResult(OUTCOME_FAILED, reason=context.reason)

    if context.status == STATUS_NOT_FOUND:
        return CorrectionSelectionResult(OUTCOME_NOT_FOUND)

    # context.status == STATUS_FOUND
    usable_records = [
        record for record in context.records if _is_usable_record(record)
    ]

    if not usable_records:
        return CorrectionSelectionResult(OUTCOME_NOT_FOUND)

    if len(usable_records) == 1:
        return CorrectionSelectionResult(OUTCOME_SELECTED, correction=usable_records[0])

    return CorrectionSelectionResult(OUTCOME_AMBIGUOUS, candidates=usable_records)
