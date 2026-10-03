"""
Language Intelligence - Validate Correction Application Target
========================================================================
Prompt 476. A small, deterministic, READ-ONLY validation operation
that checks whether an EXISTING Prompt 473
`CorrectionApplicationRequest` can be safely applied to a specific
target text - using the SAME EXACT-matching rule the EXISTING Prompt
475 `apply_correction_request()` (correction_application.py) already
uses, reused here (`_is_usable_text()`, imported, never
reimplemented), never re-derived. This module adds no new matching
rule of its own.

    build_correction_application_request(...)          (Prompt 473, unchanged)
        -> CorrectionApplicationRequest
    apply_correction_request(request, target_text)      (Prompt 475, unchanged)
        -> CorrectionApplicationResult
    validate_correction_application_target(request, target_text)  (THIS module)
        -> CorrectionApplicationTargetValidation

This module never applies the correction and never modifies
`target_text` - it only answers whether `apply_correction_request()`
would find an exact match to apply, without actually calling it or
duplicating its replacement logic.

Matching rule - EXACT ONLY
------------------------------
`request.original_expression` is checked against `target_text` with a
plain, literal, case-sensitive substring containment test (Python's
own `in` operator) - nothing else. No fuzzy matching, semantic
similarity, embeddings, spelling correction, automatic normalization,
case-insensitive matching (the existing request never specifies one -
`CorrectionApplicationRequest`, Prompt 473, carries no case-
sensitivity field), guessing, ranking, or confidence-based decisions
are ever performed.

Statuses
---------
    READY       `request` is a structurally valid, ready
                `CorrectionApplicationRequest` (`is_valid is True`,
                with usable `original_expression` and
                `corrected_expression_or_meaning` text), `target_text`
                is a string, and `original_expression` occurs at least
                once in `target_text` (exact match) - everything
                `apply_correction_request()` needs is present and the
                match exists.
    NOT_READY   `request` and `target_text` are both structurally
                usable (as above), but `original_expression` does not
                occur anywhere in `target_text` - nothing is
                structurally wrong, the correction simply does not
                apply to this text yet.
    INVALID     `request` is not a `CorrectionApplicationRequest`, or
                `request.is_valid` is not `True`, or
                `original_expression`/`corrected_expression_or_meaning`
                is missing, blank, or not text, or `target_text` is
                not a string - the operation cannot be safely
                performed at all.

Fields (only these three; nothing else is carried)
----------------------------------------------------
    status    one of `ALL_STATUSES` (`READY` / `NOT_READY` /
              `INVALID`) - required; `ValueError` for anything else,
              the SAME "status not in ALL_STATUSES -> raise" posture
              `CorrectionLearningHandoffResult`
              (correction_learning_handoff_result.py, Prompt 458)
              already uses.
    ready     bool; always `status == STATUS_READY`, never set
              independently of `status` - the SAME "derived, never
              independent" posture that module's own `accepted` field
              already uses.
    reason    an EXISTING, already-known explanation for `NOT_READY`
              or `INVALID`, reused verbatim; `None` for `READY`. Never
              an invented explanation.

Never applies anything
-------------------------
`validate_correction_application_target()` never applies the
correction, never modifies `target_text`, `request`, or any stored
learning record, never writes to storage, never touches Memory,
Knowledge, the Learning algorithms, Response Generation,
`ResponseGenerationContext`, `AgentLoop`, Self-Upgrade, or the Local
Model Runtime, and is not connected to the normal conversation/
response pipeline. It never calls `apply_correction_request()` itself
- checking readiness and performing the application remain two
separate, explicitly scoped operations.

Read-only and non-mutating
-----------------------------
This function only reads `request`'s existing fields and performs a
single, non-mutating `in` containment check against `target_text` -
`str` is already immutable, and nothing on `request` is ever set. The
same `request` and `target_text` always produce an equal validation
result.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest,
)
from language_intelligence.correction_application import _is_usable_text

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT_READY"
STATUS_INVALID = "INVALID"
ALL_STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID)


class CorrectionApplicationTargetValidation:
    """The minimum useful fields describing whether a
    `CorrectionApplicationRequest` can be safely applied to a specific
    target text - nothing more. See the module docstring for the
    exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`. Never applies anything and never
    modifies the target text - see the module docstring.
    """

    __slots__ = ("status", "ready", "reason")

    def __init__(self, status, reason=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.ready = status == STATUS_READY
        self.reason = reason

    def to_dict(self):
        """This validation as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result objects
        already follow (e.g. `CorrectionLearningHandoffResult`,
        `CorrectionApplicationResult`)."""
        return {
            "status": self.status,
            "ready": self.ready,
            "reason": self.reason,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationTargetValidation):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationTargetValidation(%r)" % (self.to_dict(),)


def validate_correction_application_target(request, target_text):
    """Check whether `request` (a `CorrectionApplicationRequest`,
    Prompt 473) could be safely applied to `target_text` by Prompt
    475's `apply_correction_request()`, using EXACT matching only -
    see the module docstring for the exact READY / NOT_READY / INVALID
    rules. Never applies the correction and never modifies
    `target_text`.

    Never raises: a structurally invalid `request` or a non-string
    `target_text` produces an `INVALID` result rather than an
    exception. Pure and deterministic: the same `request` and
    `target_text` always produce an equal validation result.
    """
    if not isinstance(request, CorrectionApplicationRequest):
        return CorrectionApplicationTargetValidation(
            STATUS_INVALID,
            reason="request_not_a_correction_application_request",
        )

    if not isinstance(target_text, str):
        return CorrectionApplicationTargetValidation(
            STATUS_INVALID, reason="target_text_not_a_string",
        )

    if request.is_valid is not True:
        return CorrectionApplicationTargetValidation(
            STATUS_INVALID, reason="request_not_valid",
        )

    if not _is_usable_text(request.original_expression):
        return CorrectionApplicationTargetValidation(
            STATUS_INVALID,
            reason="original_expression_missing_or_not_text",
        )

    if not _is_usable_text(request.corrected_expression_or_meaning):
        return CorrectionApplicationTargetValidation(
            STATUS_INVALID,
            reason="corrected_expression_or_meaning_missing_or_not_text",
        )

    if request.original_expression not in target_text:
        return CorrectionApplicationTargetValidation(
            STATUS_NOT_READY,
            reason="original_expression_not_found_in_target_text",
        )

    return CorrectionApplicationTargetValidation(STATUS_READY)
