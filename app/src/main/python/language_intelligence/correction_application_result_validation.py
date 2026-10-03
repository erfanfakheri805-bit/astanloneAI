"""
Language Intelligence - Validate Applied Correction Result
========================================================================
Prompt 480. A small, deterministic, READ-ONLY STRUCTURAL check that
verifies an EXISTING Prompt 474/478/479 `CorrectionApplicationResult`
actually represents the EXACT correction its EXISTING Prompt 473
`CorrectionApplicationRequest` asked for - the SAME "wrap the value,
report issues, never mutate" posture already used for
`CorrectionApplicationTargetValidation`
(correction_application_target_validation.py, Prompt 476).

    build_correction_application_request(...)          (Prompt 473, unchanged)
        -> CorrectionApplicationRequest
    apply_correction_request(request, target_text)      (Prompt 475, unchanged)
    apply_correction_request_with_validation(...)        (Prompt 477, unchanged)
        -> CorrectionApplicationResult
    validate_applied_correction_result(request, result)  (THIS module)
        -> CorrectionApplicationResultValidation

This module never applies, retries, or modifies a correction, and
never modifies `request` or `result` - it only reads their existing
fields and reports whether they are consistent with each other, using
EXACT, literal, case-sensitive string comparison only.

Statuses
---------
    VALID     `result` is structurally consistent with `request` -
              see "What is checked" below for the exact per-status
              rules.
    INVALID   `request`/`result` are not the expected types, or
              `result`'s own status is unrecognized, or `result` fails
              one of the checks below for its status.

What is checked (per `result.status`)
------------------------------------------
    APPLIED
        - `result.applied` is `True`
        - `result.status` is `STATUS_APPLIED`
        - `result.text_before` is present (not `None`)
        - `result.text_after` is present (not `None`)
        - `result.matched_text` equals `request.original_expression`
          EXACTLY
        - `result.replacement_text` equals
          `request.corrected_expression_or_meaning` EXACTLY
        - `result.match_count` is an `int` greater than zero
        - `request.original_expression` occurs in `result.text_before`
          (EXACT substring containment)
        - `request.corrected_expression_or_meaning` occurs in
          `result.text_after` (EXACT substring containment)
        - replacing every EXACT occurrence of `result.matched_text` in
          `result.text_before` with `result.replacement_text`
          (Python's own `str.replace()`, the SAME operation Prompt 475's
          `apply_correction_request()` already performs - reused, not
          reimplemented) equals `result.text_after` EXACTLY
    NOT_APPLIED
        - `result.applied` is `False`
        - `result.status` is `STATUS_NOT_APPLIED`
        - `result.text_before` equals `result.text_after` EXACTLY
        - `result.match_count` equals `0`
    FAILED
        - `result.applied` is `False`
        - `result.status` is `STATUS_FAILED`
        - `result.match_count` equals `0`
        (a `FAILED` result is never accepted as a successful
        correction - `result.applied` being `False` is exactly what
        that means here)

Only STRUCTURAL, deterministic facts are checked
------------------------------------------------------
No fuzzy matching, semantic similarity, embeddings, spelling
correction, normalization, guessing, ranking, or automatic correction
is ever performed - every comparison here is a plain `==` or a plain
`in` containment test on the exact strings already carried by
`request` and `result`.

Never applies, retries, or modifies anything
-------------------------------------------------
`validate_applied_correction_result()` never applies a correction,
never retries a failed one, never modifies `request` or `result`, and
never writes to storage. It does not touch Memory, Knowledge, the
Learning algorithms, Response Generation, `ResponseGenerationContext`,
`AgentLoop`, Self-Upgrade, or the Local Model Runtime, and is not
connected to the normal conversation/response pipeline.

Read-only and non-mutating
-----------------------------
This function only reads `request`'s and `result`'s existing fields
and performs plain, non-mutating string comparisons - `str` is already
immutable, and nothing on `request` or `result` is ever set. The same
`request` and `result` always produce an equal validation result.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed. `CorrectionApplicationRequest`
(Prompt 473) and `CorrectionApplicationResult` (Prompt 474/478/479) are
both reused exactly as they already exist.
"""

from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)

STATUS_VALID = "VALID"
STATUS_INVALID = "INVALID"
ALL_STATUSES = (STATUS_VALID, STATUS_INVALID)


class CorrectionApplicationResultValidation:
    """The minimum useful fields describing whether a
    `CorrectionApplicationResult` is structurally consistent with the
    `CorrectionApplicationRequest` it claims to fulfill - nothing more.
    See the module docstring for the exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`. Never modifies anything and never
    applies a correction - see the module docstring.
    """

    __slots__ = ("status", "valid", "reason")

    def __init__(self, status, reason=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.valid = status == STATUS_VALID
        self.reason = reason

    def to_dict(self):
        """This validation as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result objects
        already follow (e.g. `CorrectionApplicationTargetValidation`,
        `CorrectionApplicationResult`)."""
        return {
            "status": self.status,
            "valid": self.valid,
            "reason": self.reason,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationResultValidation):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationResultValidation(%r)" % (self.to_dict(),)


def _invalid(reason):
    return CorrectionApplicationResultValidation(STATUS_INVALID, reason=reason)


def validate_applied_correction_result(request, result):
    """Check whether `result` (a `CorrectionApplicationResult`) is
    structurally consistent with `request` (the
    `CorrectionApplicationRequest` it claims to fulfill) - see the
    module docstring for the exact per-status rules. Never applies,
    retries, or modifies anything.

    Never raises: a wrong-typed `request`/`result`, or a `result` with
    an unrecognized `status`, produces an `INVALID` validation rather
    than an exception. Pure and deterministic: the same `request` and
    `result` always produce an equal validation.
    """
    if not isinstance(request, CorrectionApplicationRequest):
        return _invalid("request_not_a_correction_application_request")

    if not isinstance(result, CorrectionApplicationResult):
        return _invalid("result_not_a_correction_application_result")

    if result.status == STATUS_APPLIED:
        if result.applied is not True:
            return _invalid("applied_flag_not_true_for_applied_status")

        if result.text_before is None:
            return _invalid("text_before_missing")

        if result.text_after is None:
            return _invalid("text_after_missing")

        if result.matched_text != request.original_expression:
            return _invalid(
                "matched_text_does_not_match_requested_original_expression"
            )

        if result.replacement_text != request.corrected_expression_or_meaning:
            return _invalid(
                "replacement_text_does_not_match_requested_correction"
            )

        if not isinstance(result.match_count, int) or result.match_count <= 0:
            return _invalid("match_count_not_greater_than_zero")

        if request.original_expression not in result.text_before:
            return _invalid("original_expression_not_found_in_text_before")

        if request.corrected_expression_or_meaning not in result.text_after:
            return _invalid("corrected_expression_not_found_in_text_after")

        recomputed_text_after = result.text_before.replace(
            result.matched_text, result.replacement_text,
        )
        if recomputed_text_after != result.text_after:
            return _invalid(
                "text_after_does_not_match_exact_replacement_of_text_before"
            )

        return CorrectionApplicationResultValidation(STATUS_VALID)

    if result.status == STATUS_NOT_APPLIED:
        if result.applied is not False:
            return _invalid("applied_flag_not_false_for_not_applied_status")

        if result.text_before != result.text_after:
            return _invalid("text_before_and_text_after_differ")

        if result.match_count != 0:
            return _invalid("match_count_not_zero_for_not_applied")

        return CorrectionApplicationResultValidation(STATUS_VALID)

    if result.status == STATUS_FAILED:
        if result.applied is not False:
            return _invalid("applied_flag_not_false_for_failed_status")

        if result.match_count != 0:
            return _invalid("match_count_not_zero_for_failed")

        return CorrectionApplicationResultValidation(STATUS_VALID)

    return _invalid("unrecognized_result_status")
