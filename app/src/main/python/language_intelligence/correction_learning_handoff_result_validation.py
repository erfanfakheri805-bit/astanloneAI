"""
Language Intelligence - Correction Learning Handoff Result Validation
========================================================================
Prompt 459. A small, deterministic STRUCTURAL check over a
`CorrectionLearningHandoffResult` (Prompt 458,
correction_learning_handoff_result.py) - the same "wrap the value,
report issues, never mutate" posture already used for
`CorrectionFeedbackRecord`
(correction_feedback_record_validation.py:
`CorrectionFeedbackRecordValidation` /
`validate_correction_feedback_record`) and, before that, for
`CorrectionUnderstandingResult`
(correction_understanding_result_validation.py). Nothing new is
invented here: the VALID/INVALID status pair and the
`{"code", "message"}` issue shape are reused exactly as those modules
define them.

This module checks only STRUCTURE of an already-built result - it does
not build a `CorrectionLearningHandoffResult`, does not call
`handoff_correction_learning_input()`/`handoff_correction_learning_
input_with_result()` (Prompt 457/458), does not touch the learning
layer, and is not connected to Memory, Knowledge, Meaning Resolution,
Pattern Matching, Response Generation, or the Local Model Runtime.
`CorrectionLearningHandoffResult` itself (its fields, its `to_dict()`,
Prompt 458's wrapper function) is not modified in any way.

What is checked (all four fields Prompt 458 defined - nothing more)
------------------------------------------------------------------------
    status
        must be one of `ALL_STATUSES` (imported from
        correction_learning_handoff_result.py - never redefined here:
        `STATUS_ACCEPTED`, `STATUS_REJECTED`, `STATUS_FAILED`). An
        unknown status makes the result structurally meaningless, so
        nothing else about it is checked in that case (same
        early-return posture `correction_feedback_record_validation.py`
        already uses for an unknown `source`).
    accepted
        must be an actual `bool` (never a truthy string, an int, or
        `None`), AND must be consistent with `status`:
        `True` exactly when `status == STATUS_ACCEPTED`, `False`
        otherwise. `CorrectionLearningHandoffResult.__init__` already
        derives `accepted` from `status` this exact way (Prompt 458),
        so this guards against a future change to that constructor
        rather than anything a normal caller can trigger today.
    source
        must be present and equal to the project's EXISTING
        `SOURCE_USER_CORRECTION` constant (imported from
        correction_feedback_record.py, never redefined) - the same
        constant Prompt 458's own `CorrectionLearningHandoffResult`
        always sets `source` to, since this handoff path exists only
        for correction-derived learning input. Any other value is
        inconsistent with that existing convention.
    reason
        checked for presence, never for truthfulness (this module
        performs no inference and invents no explanation of its own -
        it only checks whether the field already carries text where
        Prompt 458's own docstring says it should, and nothing where
        it should not):
            STATUS_FAILED               -> `reason` must be present,
                                            non-blank text (Prompt
                                            458's module docstring:
                                            the underlying exception's
                                            own message, reused
                                            verbatim - never absent
                                            for this status).
            STATUS_ACCEPTED / REJECTED  -> `reason` must be `None`
                                            (Prompt 458's own
                                            docstring: "no failure
                                            occurred" / "none exists
                                            to reuse" - a non-`None`
                                            value here would be
                                            information this module
                                            did not put there and has
                                            no existing source to
                                            confirm, i.e. fabricated).

Behavior
------------------------------------------------------------------------
Pure and deterministic: no model, no inference, no network, no
randomness, no persistence. Never raises for a bad input - it returns
an INVALID validation. Never mutates the result it is given; `result`
on the returned validation is a plain-dict COPY
(`CorrectionLearningHandoffResult.to_dict()`), not the original object.
"""

from language_intelligence.correction_understanding import _is_blank
from language_intelligence.correction_feedback_record import SOURCE_USER_CORRECTION
from language_intelligence.correction_learning_handoff_result import (
    ALL_STATUSES,
    STATUS_ACCEPTED,
    STATUS_FAILED,
    CorrectionLearningHandoffResult,
)

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"

ISSUE_NOT_A_RESULT = "not_a_correction_learning_handoff_result"
ISSUE_UNKNOWN_STATUS = "unknown_status"
ISSUE_ACCEPTED_NOT_BOOL = "accepted_not_a_boolean"
ISSUE_ACCEPTED_STATUS_MISMATCH = "accepted_does_not_match_status"
ISSUE_INVALID_SOURCE = "invalid_source"
ISSUE_MISSING_REASON_FOR_FAILED = "missing_reason_for_failed_status"
ISSUE_UNEXPECTED_REASON = "unexpected_reason_present"


class CorrectionLearningHandoffResultValidation:
    """Plain, JSON-shaped, read-only value (same `to_dict()` convention
    as the rest of this package).

        status   VALIDATION_VALID or VALIDATION_INVALID.
        issues   list of `{"code": ..., "message": ...}` - empty when
                 valid.
        result   `CorrectionLearningHandoffResult.to_dict()` of the
                 validated result (a copy), or `None` when the value
                 was not a `CorrectionLearningHandoffResult` at all.
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
        return (f"CorrectionLearningHandoffResultValidation(status={self.status!r}, "
                f"issues={self.issue_codes})")

    def to_dict(self):
        return {
            "status": self.status,
            "issues": [dict(issue) for issue in self.issues],
            "result": dict(self.result) if self.result else None,
        }


def _issue(code, message):
    return {"code": code, "message": message}


def _field_issues(handoff_result):
    if handoff_result.status not in ALL_STATUSES:
        return [_issue(ISSUE_UNKNOWN_STATUS,
                       f"unknown status {handoff_result.status!r}")]

    issues = []

    if not isinstance(handoff_result.accepted, bool):
        issues.append(_issue(ISSUE_ACCEPTED_NOT_BOOL,
                             "accepted must be an actual bool"))
    elif handoff_result.accepted != (handoff_result.status == STATUS_ACCEPTED):
        issues.append(_issue(ISSUE_ACCEPTED_STATUS_MISMATCH,
                             "accepted must be True only when status is "
                             f"{STATUS_ACCEPTED!r}"))

    if handoff_result.source != SOURCE_USER_CORRECTION:
        issues.append(_issue(ISSUE_INVALID_SOURCE,
                             f"source must be {SOURCE_USER_CORRECTION!r}"))

    if handoff_result.status == STATUS_FAILED:
        if _is_blank(handoff_result.reason) or not isinstance(handoff_result.reason, str):
            issues.append(_issue(ISSUE_MISSING_REASON_FOR_FAILED,
                                 f"status {STATUS_FAILED!r} requires a "
                                 "non-blank reason"))
    elif handoff_result.reason is not None:
        issues.append(_issue(ISSUE_UNEXPECTED_REASON,
                             f"status {handoff_result.status!r} must not "
                             "carry a reason"))

    return issues


def validate_correction_learning_handoff_result(handoff_result):
    """Validate `handoff_result` (a `CorrectionLearningHandoffResult`,
    Prompt 458). Returns a `CorrectionLearningHandoffResultValidation`;
    never raises, never mutates `handoff_result`."""
    if not isinstance(handoff_result, CorrectionLearningHandoffResult):
        return CorrectionLearningHandoffResultValidation(
            VALIDATION_INVALID,
            [_issue(ISSUE_NOT_A_RESULT,
                   "the value is not a CorrectionLearningHandoffResult")])

    issues = _field_issues(handoff_result)
    return CorrectionLearningHandoffResultValidation(
        VALIDATION_INVALID if issues else VALIDATION_VALID,
        issues, result=handoff_result.to_dict())
