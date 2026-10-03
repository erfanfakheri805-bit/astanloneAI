"""
Language Intelligence - Verify Correction Application Result
========================================================================
Prompt 482. The correction-application verification OPERATION: it
wraps the EXISTING Prompt 480 `validate_applied_correction_result()`
STRUCTURAL check and reports the outcome as an EXISTING Prompt 481
`CorrectionApplicationVerificationResult` - the SAME "wrap the value,
report an outcome, never mutate" posture that model already defines.

    validate_applied_correction_result(request, result)   (Prompt 480, unchanged)
        -> CorrectionApplicationResultValidation
    verify_correction_application_result(request, result)  (THIS module)
        -> CorrectionApplicationVerificationResult

This module performs no validation rules of its own - it calls
`validate_applied_correction_result()` exactly once per invocation and
carries its `status` and `reason` through verbatim into a
`CorrectionApplicationVerificationResult`. Prompt 480's validator
remains the single source of truth for whether a
`CorrectionApplicationResult` is structurally consistent with the
`CorrectionApplicationRequest` it claims to fulfill - this module never
re-derives, re-implements, or duplicates any of those rules, and never
inspects `request` or `result` directly to make that decision itself.

Never applies, retries, or modifies anything
-------------------------------------------------
`verify_correction_application_result()` never applies a correction,
never retries one, and never modifies `request` or `result` - the SAME
non-mutating posture `validate_applied_correction_result()` (Prompt
480) already has. It does not touch Memory, Knowledge, the Learning
algorithms, Response Generation, `ResponseGenerationContext`,
`AgentLoop`, Self-Upgrade, or the Local Model Runtime, and is not
connected to the normal conversation/response pipeline.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
`validate_applied_correction_result()` (Prompt 480) and
`CorrectionApplicationVerificationResult` (Prompt 481) are both reused
exactly as they already exist.
"""

from language_intelligence.correction_application_result_validation import (
    validate_applied_correction_result,
    STATUS_VALID as VALIDATION_STATUS_VALID,
)
from language_intelligence.correction_application_verification_result import (
    CorrectionApplicationVerificationResult,
    STATUS_VALID, STATUS_INVALID,
)


def verify_correction_application_result(request, result):
    """Verify `result` (a `CorrectionApplicationResult`) against
    `request` (the `CorrectionApplicationRequest` it claims to
    fulfill) by delegating to the EXISTING Prompt 480
    `validate_applied_correction_result()`, and report the outcome as
    a `CorrectionApplicationVerificationResult` (Prompt 481).

    Never raises: whatever `validate_applied_correction_result()`
    already guarantees not to raise on, this function does not raise
    on either. Pure and deterministic: the same `request` and `result`
    always produce an equal verification result, because the
    validator this delegates to is itself pure and deterministic.
    """
    validation = validate_applied_correction_result(request, result)

    status = (
        STATUS_VALID
        if validation.status == VALIDATION_STATUS_VALID
        else STATUS_INVALID
    )
    return CorrectionApplicationVerificationResult(
        status, reason=validation.reason,
    )
