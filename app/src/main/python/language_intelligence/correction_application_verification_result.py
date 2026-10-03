"""
Language Intelligence - Correction Application Verification Result
========================================================================
Prompt 481. A small, deterministic DATA MODEL - not an operation - that
represents whether an EXISTING `CorrectionApplicationResult` (Prompt
474/478/479) passed deterministic validation, such as the EXISTING
Prompt 480 `validate_applied_correction_result()`. The same "wrap the
value, report an outcome, never mutate" posture already used for
`CorrectionApplicationResultValidation`
(correction_application_result_validation.py, Prompt 480), combined
with the same `metadata` convention `CorrectionApplicationResult`
(correction_application_result.py, Prompt 474/478/479) already uses
for its own small, optional, JSON-shaped extra-detail field.

This module defines ONLY the result shape. It contains no validation
logic of its own, calls nothing from Prompt 480 or any other
correction-application module, and never applies, retries, or
modifies a `CorrectionApplicationResult` or any other value - building
one of these is purely recording an already-determined outcome.

Fields (only these four; nothing else is carried)
----------------------------------------------------
    status     one of `ALL_STATUSES` (`VALID` / `INVALID`) - required;
               `ValueError` for anything else, the SAME "status not in
               ALL_STATUSES -> raise" posture
               `CorrectionApplicationResultValidation` (Prompt 480)
               and `CorrectionApplicationResult` (Prompt 474) already
               use.
    valid      bool; always `status == STATUS_VALID`, never set
               independently of `status` - the SAME "derived, never
               independent" posture `CorrectionApplicationResultValidation.
               valid` and `CorrectionApplicationResult.applied` already
               use.
    reason     an existing explanation for `INVALID` (or, less often,
               additional context for `VALID`), reused verbatim when
               one is already available; `None` otherwise. Never an
               invented explanation - the SAME rule
               `CorrectionApplicationResultValidation.reason` already
               follows.
    metadata   a small, optional, JSON-shaped dict of additional
               detail about the outcome; `{}` when not supplied.
               Deep-copied at construction time and again by
               `to_dict()`, the SAME `copy.deepcopy()` convention
               `CorrectionApplicationResult.metadata` (Prompt 474)
               already uses for its own mutable, caller-shaped field -
               mutating the dict passed in, or the dict `to_dict()`
               returns, never reaches back into this result.

Statuses
---------
    VALID     the wrapped `CorrectionApplicationResult` was verified
               successfully.
    INVALID   the wrapped `CorrectionApplicationResult` failed
               verification.
These two outcomes are always kept distinct: `valid` mirrors `status`
exactly and is never set independently of it.

Never performs validation, never applies anything, never mutates
----------------------------------------------------------------------
`CorrectionApplicationVerificationResult` has no method or function in
this module that inspects, validates, applies, retries, or modifies a
`CorrectionApplicationResult`, a `CorrectionApplicationRequest`, or any
target text. It only stores `status`, `reason`, and `metadata` that
the caller already determined elsewhere (e.g. by calling Prompt 480's
`validate_applied_correction_result()` first) and reports them back
unchanged. It does not touch Memory, Knowledge, the Learning
algorithms, Response Generation, `ResponseGenerationContext`,
`AgentLoop`, Self-Upgrade, or the Local Model Runtime, and is not
connected to the normal conversation/response pipeline.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

import copy

STATUS_VALID = "VALID"
STATUS_INVALID = "INVALID"
ALL_STATUSES = (STATUS_VALID, STATUS_INVALID)


class CorrectionApplicationVerificationResult:
    """The minimum useful fields describing whether an existing
    `CorrectionApplicationResult` passed deterministic verification -
    nothing more. See the module docstring for the exact meaning of
    each field.

    Pure data: this class performs no validation, no correction
    application, and no mutation of anything passed to it - it only
    records an outcome already determined elsewhere.
    """

    __slots__ = ("status", "valid", "reason", "metadata")

    def __init__(self, status, reason=None, metadata=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.valid = status == STATUS_VALID
        self.reason = reason
        self.metadata = copy.deepcopy(metadata) if metadata else {}

    def to_dict(self):
        """This result as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result objects
        already follow (e.g. `CorrectionApplicationResult`,
        `CorrectionApplicationResultValidation`). `metadata` is
        deep-copied again here, so mutating the returned dict never
        reaches back into this result."""
        return {
            "status": self.status,
            "valid": self.valid,
            "reason": self.reason,
            "metadata": copy.deepcopy(self.metadata),
        }

    def copy(self):
        """An independent copy of this result - mutating the copy's
        `metadata` never reaches back into this one, and vice versa.
        The same `copy()` convention `CorrectionApplicationCandidate`
        (Prompt 470) already provides for its own result shape."""
        return CorrectionApplicationVerificationResult(
            self.status, reason=self.reason, metadata=self.metadata,
        )

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationVerificationResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationVerificationResult(%r)" % (
            self.to_dict(),
        )
