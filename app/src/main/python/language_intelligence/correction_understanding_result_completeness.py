"""
Language Intelligence - Correction Understanding Result Completeness
========================================================================
Prompt 444. A small, deterministic COMPLETENESS check over a
`CorrectionUnderstandingResult` (Prompt 441,
correction_understanding_result.py) - same "wrap the value, report
issues, never mutate" posture already used by
`validate_correction_understanding_result()` (Prompt 443,
correction_understanding_result_validation.py). Nothing new is
invented here: the pass/fail status pair, the `{"code", "message"}`
reason shape, and the "return a failing value instead of raising" rule
are all reused exactly as that module defines them; the field-presence
rules below are the same status-conditional rules Prompt 443 already
enforces for RESOLVED, UNRESOLVED and NOT_CORRECTION.

This module answers a narrower question than full validation: does the
result carry ENOUGH information for its current status to be
considered structurally complete? It does not check internal
consistency (e.g. whether a status carries a field it should never
have, or whether confidence is in range) - that is what Prompt 443's
validation already covers. A result can be complete by this module's
rules and still be flagged by validation for an unrelated consistency
problem, and vice versa; the two checks are independent and neither
replaces the other.

This module checks only STRUCTURE - never re-detects, re-resolves or
re-derives a correction, never touches `CorrectionUnderstanding`
(Prompt 439) or correction detection, and is not connected to Learning,
Memory, Knowledge, Meaning Resolution, Pattern Matching or Response
Generation. Nothing is stored anywhere.

Rules (status -> what must be present to be COMPLETE)
------------------------------------------------------------------------
    RESOLVED        original_expression is non-blank text AND
                     corrected_expression_or_meaning is non-blank text -
                     both sides of the correction are the information
                     required to represent a resolved correction.
    AMBIGUOUS        source_text is non-blank text - enough is preserved
                     to show a correction was attempted even though it
                     could not be uniquely resolved (corrected_expres-
                     sion_or_meaning is never populated for AMBIGUOUS;
                     its absence is not incompleteness here, see Prompt
                     443 for that consistency rule).
    UNRESOLVED       source_text is non-blank text (the original source
                     information is preserved) AND at least one of
                     original_expression / corrected_expression_or_meaning
                     is non-blank text.
    NOT_CORRECTION   source_text is non-blank text - complete without
                     any correction-specific fields.

Result-level rule that applies regardless of status:
    - the value must be a `CorrectionUnderstandingResult` with a known
      status (one of `ALL_STATUSES`, imported from
      `correction_understanding.py` - never redefined here); an
      unrecognized value is reported INCOMPLETE, never guessed at.
    - `source_text` must be present, non-blank text for every status -
      the one field every status of `CorrectionUnderstanding` always
      carries (Prompt 439's own `build_correction_understanding()`
      requires it at construction time).

Behavior
------------------------------------------------------------------------
Pure and deterministic: no model, no inference, no network, no
scoring, no randomness. Never raises for a bad input - it returns an
INCOMPLETE completeness value. Never mutates the result it is given;
`result` on the returned value is a plain-dict COPY (`result.to_dict()`),
not the original object.
"""

from .correction_understanding import (
    ALL_STATUSES, _is_blank,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
)
from .correction_understanding_result import CorrectionUnderstandingResult

COMPLETENESS_COMPLETE = "COMPLETE"
COMPLETENESS_INCOMPLETE = "INCOMPLETE"

REASON_NOT_A_RESULT = "not_a_result"
REASON_UNKNOWN_STATUS = "unknown_status"
REASON_MISSING_SOURCE_TEXT = "missing_source_text"
REASON_RESOLVED_MISSING_ORIGINAL = "resolved_missing_original_expression"
REASON_RESOLVED_MISSING_CORRECTED = "resolved_missing_corrected_expression_or_meaning"
REASON_UNRESOLVED_MISSING_FIELD = "unresolved_missing_original_or_corrected"


class CorrectionUnderstandingResultCompleteness:
    """Plain, JSON-shaped, read-only value (same `to_dict()` convention as
    the rest of this package).

        status   COMPLETENESS_COMPLETE or COMPLETENESS_INCOMPLETE.
        reasons  list of `{"code": ..., "message": ...}` - empty when
                 complete.
        result   `CorrectionUnderstandingResult.to_dict()` of the
                 checked result (a copy), or None when the value was
                 not a `CorrectionUnderstandingResult` at all.
    """

    def __init__(self, status, reasons=None, result=None):
        if status not in (COMPLETENESS_COMPLETE, COMPLETENESS_INCOMPLETE):
            raise ValueError("status must be COMPLETE or INCOMPLETE")
        self.status = status
        self.reasons = [dict(reason) for reason in (reasons or [])]
        self.result = dict(result) if result else None

    @property
    def complete(self):
        return self.status == COMPLETENESS_COMPLETE

    @property
    def reason_codes(self):
        return [reason["code"] for reason in self.reasons]

    def __repr__(self):
        return (f"CorrectionUnderstandingResultCompleteness(status={self.status!r}, "
                f"reasons={self.reason_codes})")

    def to_dict(self):
        return {
            "status": self.status,
            "reasons": [dict(reason) for reason in self.reasons],
            "result": dict(self.result) if self.result else None,
        }


def _reason(code, message):
    return {"code": code, "message": message}


def _completeness_reasons(result):
    if result.status not in ALL_STATUSES:
        return [_reason(REASON_UNKNOWN_STATUS, f"unknown result status {result.status!r}")]

    reasons = []
    if _is_blank(result.source_text):
        reasons.append(_reason(REASON_MISSING_SOURCE_TEXT,
                               "source_text is required and must be non-blank text"))

    has_original = not _is_blank(result.original_expression)
    has_corrected = not _is_blank(result.corrected_expression_or_meaning)

    if result.status == STATUS_RESOLVED:
        if not has_original:
            reasons.append(_reason(REASON_RESOLVED_MISSING_ORIGINAL,
                                   "RESOLVED requires a non-blank original_expression"))
        if not has_corrected:
            reasons.append(_reason(REASON_RESOLVED_MISSING_CORRECTED,
                                   "RESOLVED requires a non-blank corrected_expression_or_meaning"))
    elif result.status == STATUS_UNRESOLVED:
        if not has_original and not has_corrected:
            reasons.append(_reason(REASON_UNRESOLVED_MISSING_FIELD,
                                   "UNRESOLVED requires original_expression or "
                                   "corrected_expression_or_meaning to be present"))
    # STATUS_AMBIGUOUS and STATUS_NOT_CORRECTION need nothing beyond the
    # source_text check above to be considered complete.

    return reasons


def check_correction_understanding_result_completeness(result):
    """Check whether `result` (a `CorrectionUnderstandingResult`) carries
    enough information to be considered structurally complete for its
    current status. Returns a `CorrectionUnderstandingResultCompleteness`;
    never raises, never mutates `result`."""
    if not isinstance(result, CorrectionUnderstandingResult):
        return CorrectionUnderstandingResultCompleteness(
            COMPLETENESS_INCOMPLETE,
            [_reason(REASON_NOT_A_RESULT, "the value is not a CorrectionUnderstandingResult")])

    reasons = _completeness_reasons(result)
    return CorrectionUnderstandingResultCompleteness(
        COMPLETENESS_INCOMPLETE if reasons else COMPLETENESS_COMPLETE,
        reasons, result=result.to_dict())


def is_correction_understanding_result_complete(result):
    """Convenience boolean form of
    `check_correction_understanding_result_completeness()` for callers
    that only need a yes/no answer."""
    return check_correction_understanding_result_completeness(result).complete
