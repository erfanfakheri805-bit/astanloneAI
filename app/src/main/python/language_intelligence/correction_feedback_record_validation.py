"""
Language Intelligence - Correction Feedback Record Validation
========================================================================
Prompt 450. A small, deterministic structural check over a
`CorrectionFeedbackRecord` (Prompt 449, correction_feedback_record.py) -
same "wrap the value, report issues, never mutate" posture already used
for `CorrectionUnderstandingResult`
(correction_understanding_result_validation.py:
`CorrectionUnderstandingResultValidation` /
`validate_correction_understanding_result`). Nothing new is invented
here: the VALID/INVALID status pair, the `{"code", "message"}` issue
shape, and the "return an INVALID validation instead of raising" rule
are all reused exactly as that module defines them.

This module checks only STRUCTURE - never re-detects, re-resolves or
re-derives a correction, never touches `CorrectionUnderstandingResult`
(Prompt 441), `CorrectionUnderstanding` (Prompt 439) or correction
detection, and is not connected to Learning, Memory, Knowledge, Meaning
Resolution, Pattern Matching or Response Generation. Nothing is stored
anywhere.

Rules (is_valid_feedback -> what must hold)
------------------------------------------------------------------------
    True    original_expression is non-blank text AND
             corrected_expression_or_meaning is non-blank text - the
             same "both sides of the correction are present" rule
             `correction_understanding_result_validation.py` already
             requires of a RESOLVED result (the only status Prompt
             449's mapping ever turns into `is_valid_feedback=True`).
    False    original_expression and corrected_expression_or_meaning
             may be missing, partial, or present - nothing about them
             is checked. A record that only claims "not valid
             feedback" is never made structurally invalid by
             incomplete correction fields.

Record-level rules that apply regardless of is_valid_feedback:
    - the value must be a `CorrectionFeedbackRecord`;
    - `source` must be one of `ALL_SOURCES` (imported from
      correction_feedback_record.py - never redefined here; for this
      stage that is exactly `SOURCE_USER_CORRECTION`);
    - `is_valid_feedback` must be an actual `bool` (never a truthy
      string, an int, or None - same "never a bool" / "never coerced"
      posture `correction_understanding_result_validation.py`'s own
      `_is_valid_confidence()` already applies in reverse to
      `confidence`);
    - `source_text` must be present, non-blank text - the same
      "required and non-blank" rule already enforced for
      `CorrectionUnderstandingResult.source_text`;
    - `confidence` must be a real, finite number (never a bool) in
      [0.0, 1.0] - the same range already enforced there.

Behavior
------------------------------------------------------------------------
Pure and deterministic: no model, no inference, no network, no
scoring, no randomness. Never raises for a bad input - it returns an
INVALID validation. Never mutates the record it is given; `record` on
the returned validation is a plain-dict COPY (`record.to_dict()`), not
the original object. No new information is inferred or generated -
every check here reads an already-existing field and reports on it;
nothing is guessed, normalized or filled in.
"""

from language_intelligence.correction_understanding import _is_blank
from language_intelligence.correction_feedback_record import (
    ALL_SOURCES,
    CorrectionFeedbackRecord,
)

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"

ISSUE_NOT_A_RECORD = "not_a_record"
ISSUE_UNKNOWN_SOURCE = "unknown_source"
ISSUE_IS_VALID_FEEDBACK_NOT_BOOL = "is_valid_feedback_not_a_boolean"
ISSUE_MISSING_SOURCE_TEXT = "missing_source_text"
ISSUE_INVALID_CONFIDENCE = "invalid_confidence"
ISSUE_VALID_FEEDBACK_MISSING_ORIGINAL = "valid_feedback_missing_original_expression"
ISSUE_VALID_FEEDBACK_MISSING_CORRECTED = "valid_feedback_missing_corrected_expression_or_meaning"


class CorrectionFeedbackRecordValidation:
    """Plain, JSON-shaped, read-only value (same `to_dict()` convention as
    the rest of this package).

        status   VALIDATION_VALID or VALIDATION_INVALID.
        issues   list of `{"code": ..., "message": ...}` - empty when valid.
        record   `CorrectionFeedbackRecord.to_dict()` of the validated
                 record (a copy), or None when the value was not a
                 `CorrectionFeedbackRecord` at all.
    """

    def __init__(self, status, issues=None, record=None):
        if status not in (VALIDATION_VALID, VALIDATION_INVALID):
            raise ValueError("status must be VALID or INVALID")
        self.status = status
        self.issues = [dict(issue) for issue in (issues or [])]
        self.record = dict(record) if record else None

    @property
    def valid(self):
        return self.status == VALIDATION_VALID

    @property
    def issue_codes(self):
        return [issue["code"] for issue in self.issues]

    def __repr__(self):
        return (f"CorrectionFeedbackRecordValidation(status={self.status!r}, "
                f"issues={self.issue_codes})")

    def to_dict(self):
        return {
            "status": self.status,
            "issues": [dict(issue) for issue in self.issues],
            "record": dict(self.record) if self.record else None,
        }


def _issue(code, message):
    return {"code": code, "message": message}


def _is_valid_confidence(value):
    """Same rule already enforced for `CorrectionUnderstandingResult`:
    a real, finite number (never a bool), in [0.0, 1.0]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0.0 <= float(value) <= 1.0


def _field_issues(record):
    issues = []

    if record.source not in ALL_SOURCES:
        # Same early-return posture already used for `status` in
        # correction_understanding_result_validation.py: an unknown
        # source makes the record structurally meaningless, so nothing
        # else about it is checked. `CorrectionFeedbackRecord.__init__`
        # already rejects an unrecognized `source` at construction time
        # (Prompt 451), so this guards against a future change to that
        # constructor rather than anything a normal caller can trigger
        # today.
        return [_issue(ISSUE_UNKNOWN_SOURCE, f"unknown source {record.source!r}")]

    if not isinstance(record.is_valid_feedback, bool):
        # Structural bug only: CorrectionFeedbackRecord.__init__ always
        # coerces with bool(...), so this branch guards against a
        # future change to that constructor rather than anything a
        # normal caller can trigger today.
        return [_issue(ISSUE_IS_VALID_FEEDBACK_NOT_BOOL,
                       "is_valid_feedback must be an actual bool")]

    if _is_blank(record.source_text):
        issues.append(_issue(ISSUE_MISSING_SOURCE_TEXT,
                             "source_text is required and must be non-blank text"))

    if not _is_valid_confidence(record.confidence):
        issues.append(_issue(ISSUE_INVALID_CONFIDENCE,
                             "confidence must be a real number in [0.0, 1.0]"))

    if record.is_valid_feedback:
        if _is_blank(record.original_expression):
            issues.append(_issue(ISSUE_VALID_FEEDBACK_MISSING_ORIGINAL,
                                 "is_valid_feedback=True requires a non-blank "
                                 "original_expression"))
        if _is_blank(record.corrected_expression_or_meaning):
            issues.append(_issue(ISSUE_VALID_FEEDBACK_MISSING_CORRECTED,
                                 "is_valid_feedback=True requires a non-blank "
                                 "corrected_expression_or_meaning"))
    # is_valid_feedback=False: original_expression and
    # corrected_expression_or_meaning are not checked at all - missing
    # or partial correction fields never make such a record invalid.

    return issues


def validate_correction_feedback_record(record):
    """Validate `record` (a `CorrectionFeedbackRecord`). Returns a
    `CorrectionFeedbackRecordValidation`; never raises, never mutates
    `record`."""
    if not isinstance(record, CorrectionFeedbackRecord):
        return CorrectionFeedbackRecordValidation(
            VALIDATION_INVALID,
            [_issue(ISSUE_NOT_A_RECORD, "the value is not a CorrectionFeedbackRecord")])

    issues = _field_issues(record)
    return CorrectionFeedbackRecordValidation(
        VALIDATION_INVALID if issues else VALIDATION_VALID, issues, record=record.to_dict())
