"""
Language Intelligence - Correction Understanding Result Validation
========================================================================
Prompt 443. A small, deterministic structural check over a
`CorrectionUnderstandingResult` (Prompt 441,
correction_understanding_result.py) - same "wrap the value, report
issues, never mutate" posture already used for
`ResponseGenerationResult` (Prompt 430,
response_generation_validation.py: `ResponseGenerationValidation` /
`validate_response_generation_result`). Nothing new is invented here:
the VALID/INVALID status pair, the `{"code", "message"}` issue shape,
and the "return an INVALID validation instead of raising" rule are all
reused exactly as that module defines them.

This module checks only STRUCTURE - never re-detects, re-resolves or
re-derives a correction, never touches `CorrectionUnderstanding`
(Prompt 439) or correction detection, and is not connected to Learning,
Memory, Knowledge, Meaning Resolution, Pattern Matching or Response
Generation. Nothing is stored anywhere.

Rules (status -> what must hold)
------------------------------------------------------------------------
    RESOLVED        original_expression is non-blank text AND
                     corrected_expression_or_meaning is non-blank text -
                     both sides of the correction are present, exactly
                     what Prompt 439's own decision order requires
                     before it ever returns RESOLVED.
    AMBIGUOUS        corrected_expression_or_meaning is None - Prompt
                     439 never fills it in for an ambiguous correction
                     (original_expression may be present or None; it is
                     not itself what makes the result ambiguous).
    UNRESOLVED       exactly one of original_expression /
                     corrected_expression_or_meaning is non-blank -
                     never both (that would be RESOLVED) and never
                     neither (that would be NOT_CORRECTION).
    NOT_CORRECTION   both original_expression and
                     corrected_expression_or_meaning are None.

Result-level rules that apply regardless of status:
    - the value must be a `CorrectionUnderstandingResult` with a known
      status (one of `ALL_STATUSES`, imported from
      `correction_understanding.py` - never redefined here);
    - `source_text` must be present, non-blank text (the same
      "required and non-blank" rule `correction_understanding.py`'s own
      `build_correction_understanding()` already enforces at
      construction time for the structure this one is built from);
    - `confidence` must be a real, finite number (never a bool) in
      [0.0, 1.0] - the same range `correction_understanding.py`'s own
      `_clamp_confidence()` already enforces.

Behavior
------------------------------------------------------------------------
Pure and deterministic: no model, no inference, no network, no
scoring, no randomness. Never raises for a bad input - it returns an
INVALID validation. Never mutates the result it is given; `result` on
the returned validation is a plain-dict COPY (`result.to_dict()`), not
the original object.
"""

from .correction_understanding import (
    ALL_STATUSES, _is_blank,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
)
from .correction_understanding_result import CorrectionUnderstandingResult

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"

ISSUE_NOT_A_RESULT = "not_a_result"
ISSUE_UNKNOWN_STATUS = "unknown_status"
ISSUE_MISSING_SOURCE_TEXT = "missing_source_text"
ISSUE_INVALID_CONFIDENCE = "invalid_confidence"
ISSUE_RESOLVED_MISSING_ORIGINAL = "resolved_missing_original_expression"
ISSUE_RESOLVED_MISSING_CORRECTED = "resolved_missing_corrected_expression_or_meaning"
ISSUE_AMBIGUOUS_HAS_CORRECTED = "ambiguous_has_corrected_expression_or_meaning"
ISSUE_UNRESOLVED_MISSING_FIELD = "unresolved_missing_original_or_corrected"
ISSUE_UNRESOLVED_HAS_BOTH_FIELDS = "unresolved_has_both_original_and_corrected"
ISSUE_NOT_CORRECTION_HAS_ORIGINAL = "not_correction_has_original_expression"
ISSUE_NOT_CORRECTION_HAS_CORRECTED = "not_correction_has_corrected_expression_or_meaning"


class CorrectionUnderstandingResultValidation:
    """Plain, JSON-shaped, read-only value (same `to_dict()` convention as
    the rest of this package).

        status   VALIDATION_VALID or VALIDATION_INVALID.
        issues   list of `{"code": ..., "message": ...}` - empty when valid.
        result   `CorrectionUnderstandingResult.to_dict()` of the
                 validated result (a copy), or None when the value was
                 not a `CorrectionUnderstandingResult` at all.
    """

    def __init__(self, status, issues=None, result=None):
        if status not in (VALIDATION_VALID, VALIDATION_INVALID):
            raise ValueError("status must be VALID or INVALID")
        self.status = status
        self.issues = [dict(issue) for issue in (issues or [])]
        self.result = dict(result) if result else None

    @property
    def valid(self):
        return self.status == VALIDATION_VALID

    @property
    def issue_codes(self):
        return [issue["code"] for issue in self.issues]

    def __repr__(self):
        return (f"CorrectionUnderstandingResultValidation(status={self.status!r}, "
                f"issues={self.issue_codes})")

    def to_dict(self):
        return {
            "status": self.status,
            "issues": [dict(issue) for issue in self.issues],
            "result": dict(self.result) if self.result else None,
        }


def _issue(code, message):
    return {"code": code, "message": message}


def _is_valid_confidence(value):
    """Same rule `correction_understanding.py`'s own `_clamp_confidence()`
    enforces at construction time: a real, finite number (never a bool),
    in [0.0, 1.0]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0.0 <= float(value) <= 1.0


def _field_issues(result):
    issues = []
    if result.status not in ALL_STATUSES:
        return [_issue(ISSUE_UNKNOWN_STATUS, f"unknown result status {result.status!r}")]

    if _is_blank(result.source_text):
        issues.append(_issue(ISSUE_MISSING_SOURCE_TEXT,
                             "source_text is required and must be non-blank text"))

    if not _is_valid_confidence(result.confidence):
        issues.append(_issue(ISSUE_INVALID_CONFIDENCE,
                             "confidence must be a real number in [0.0, 1.0]"))

    has_original = not _is_blank(result.original_expression)
    has_corrected = not _is_blank(result.corrected_expression_or_meaning)

    if result.status == STATUS_RESOLVED:
        if not has_original:
            issues.append(_issue(ISSUE_RESOLVED_MISSING_ORIGINAL,
                                 "RESOLVED requires a non-blank original_expression"))
        if not has_corrected:
            issues.append(_issue(ISSUE_RESOLVED_MISSING_CORRECTED,
                                 "RESOLVED requires a non-blank corrected_expression_or_meaning"))
    elif result.status == STATUS_AMBIGUOUS:
        if has_corrected:
            issues.append(_issue(ISSUE_AMBIGUOUS_HAS_CORRECTED,
                                 "AMBIGUOUS must not carry a corrected_expression_or_meaning"))
    elif result.status == STATUS_UNRESOLVED:
        if has_original and has_corrected:
            issues.append(_issue(ISSUE_UNRESOLVED_HAS_BOTH_FIELDS,
                                 "UNRESOLVED must not carry both original_expression and "
                                 "corrected_expression_or_meaning (that is RESOLVED)"))
        elif not has_original and not has_corrected:
            issues.append(_issue(ISSUE_UNRESOLVED_MISSING_FIELD,
                                 "UNRESOLVED requires original_expression or "
                                 "corrected_expression_or_meaning to be present"))
    elif result.status == STATUS_NOT_CORRECTION:
        if has_original:
            issues.append(_issue(ISSUE_NOT_CORRECTION_HAS_ORIGINAL,
                                 "NOT_CORRECTION must not carry an original_expression"))
        if has_corrected:
            issues.append(_issue(ISSUE_NOT_CORRECTION_HAS_CORRECTED,
                                 "NOT_CORRECTION must not carry a corrected_expression_or_meaning"))

    return issues


def validate_correction_understanding_result(result):
    """Validate `result` (a `CorrectionUnderstandingResult`). Returns a
    `CorrectionUnderstandingResultValidation`; never raises, never
    mutates `result`."""
    if not isinstance(result, CorrectionUnderstandingResult):
        return CorrectionUnderstandingResultValidation(
            VALIDATION_INVALID,
            [_issue(ISSUE_NOT_A_RESULT, "the value is not a CorrectionUnderstandingResult")])

    issues = _field_issues(result)
    return CorrectionUnderstandingResultValidation(
        VALIDATION_INVALID if issues else VALIDATION_VALID, issues, result=result.to_dict())
