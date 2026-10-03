"""
Language Intelligence - Apply Correction Request, Guarded by Validation
========================================================================
Prompt 477. A small, deterministic operation that adds the EXISTING
Prompt 476 `validate_correction_application_target()` readiness guard
in front of the EXISTING Prompt 475 `apply_correction_request()`. It
adds no new rules of its own - the validator remains the single
source of truth for whether a `CorrectionApplicationRequest` may be
applied to a target text.

    validate_correction_application_target(request, target_text)  (Prompt 476, unchanged)
        -> CorrectionApplicationTargetValidation
    apply_correction_request(request, target_text)                 (Prompt 475, unchanged)
        -> CorrectionApplicationResult
    apply_correction_request_with_validation(request, target_text)  (THIS module)
        -> CorrectionApplicationResult

Behavior - deterministic on the validator's status
------------------------------------------------------
    READY       the validator confirms `apply_correction_request()`
                would find an exact match. This function then calls
                the EXISTING `apply_correction_request()` unchanged
                and returns its result verbatim (`APPLIED`,
                `original_text` preserved, `corrected_text` set).
    NOT_READY   `target_text` is not modified; a `CorrectionApplicationResult`
                with `status=NOT_APPLIED` (`applied=False`) is
                returned, `original_text` set to `target_text` and
                `corrected_text` set to `target_text` unchanged (the
                SAME "return target text unmodified as both
                original_text and corrected_text" shape Prompt 475's
                own `NOT_APPLIED` outcome already uses), carrying the
                validator's own `reason` through verbatim.
    INVALID     `target_text` is not modified; a `CorrectionApplicationResult`
                with `status=FAILED` (`applied=False`) is returned,
                `original_text` set to `target_text` when it is at
                least a string (else `None`, the SAME rule Prompt
                475's own `FAILED` outcome already uses) and
                `corrected_text` left `None`, carrying the
                validator's own `reason` through verbatim.

Prompt 482 addendum - verify the result before returning it as APPLIED
------------------------------------------------------------------------
When validation returns `READY` and `apply_correction_request()`
produces a `STATUS_APPLIED` result, that result is no longer returned
as-is. It is first checked with the EXISTING Prompt 482
`verify_correction_application_result()` operation (which itself
delegates to the EXISTING Prompt 480
`validate_applied_correction_result()` structural check) against the
SAME `request`:

    VALID     the `APPLIED` result is returned exactly as
              `apply_correction_request()` produced it - unchanged.
    INVALID   the `APPLIED` result is discarded (never returned, and
              never "repaired") and a deterministic `FAILED` result is
              returned instead: `applied=False`, `match_count=0`,
              `original_text` set to the produced result's own
              `original_text` when it is safely available as a string
              (else `None` - the SAME rule every other `FAILED`
              outcome in this module already uses), `corrected_text`
              left `None`, and `reason` carrying the verification
              operation's own reason through verbatim - never an
              invented explanation.

No correction is ever retried or re-attempted: `apply_correction_request()`
is called at most once per invocation, exactly as before Prompt 482.
`NOT_READY` and `INVALID` (validation) outcomes are unaffected - since
nothing was applied in those cases, there is nothing to verify, and
this function's behavior for them is unchanged from Prompt 477.

The verification operation - and, through it, Prompt 480's validator -
remains the single source of truth for whether a produced `APPLIED`
result may be returned as such. This module never re-derives,
re-implements, or duplicates any of those rules itself.

Single source of truth for readiness
----------------------------------------
This module never re-derives, re-implements, or duplicates any of the
validator's rules (structural validity of `request`, presence of
`original_expression`/`corrected_expression_or_meaning`, or the exact
`in` containment check). It calls
`validate_correction_application_target()` exactly once per
invocation and branches only on its `status` - it never inspects
`request` or `target_text` directly to make that decision itself.

Never applies anything beyond this one operation
----------------------------------------------------
`apply_correction_request_with_validation()` performs exactly one
guarded exact-match substring replacement (via the existing,
unmodified `apply_correction_request()`) and returns the result - it
never modifies the user's message, generated response text, or any
stored learning record, never writes to storage, never touches
Memory, Knowledge, the Learning algorithms, Response Generation,
`ResponseGenerationContext`, `AgentLoop`, Self-Upgrade, or the Local
Model Runtime, and is not connected to the normal conversation/
response pipeline. It never mutates `request` or `target_text`.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed. `apply_correction_request()`
(Prompt 475) and `validate_correction_application_target()` (Prompt
476) are both reused exactly as they already exist. Prompt 482's
`verify_correction_application_result()` is reused exactly as it
already exists too - this module adds no verification rules of its
own.
"""

from language_intelligence.correction_application import (
    apply_correction_request,
)
from language_intelligence.correction_application_target_validation import (
    validate_correction_application_target,
    STATUS_READY, STATUS_NOT_READY, STATUS_INVALID,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_application_verification import (
    verify_correction_application_result,
)
from language_intelligence.correction_application_verification_result import (
    STATUS_VALID as VERIFICATION_STATUS_VALID,
)


def apply_correction_request_with_validation(request, target_text):
    """Apply `request` (a `CorrectionApplicationRequest`, Prompt 473)
    to `target_text` (EXACT matching only), but only after the
    EXISTING Prompt 476 `validate_correction_application_target()`
    guard reports the target as `READY` - see the module docstring
    for the exact READY / NOT_READY / INVALID behavior. When a
    `READY` target produces an `APPLIED` result, that result is also
    checked with the EXISTING Prompt 482
    `verify_correction_application_result()` operation before being
    returned - see the module docstring's Prompt 482 addendum for the
    exact VALID / INVALID behavior.

    Never raises: whatever `validate_correction_application_target()`,
    `apply_correction_request()`, and
    `verify_correction_application_result()` already guarantee not to
    raise on, this function does not raise on either. Pure and
    deterministic: the same `request` and `target_text` always
    produce an equal result, because every operation this delegates
    to is itself pure and deterministic. No correction is ever
    retried: `apply_correction_request()` is called at most once per
    invocation.
    """
    validation = validate_correction_application_target(request, target_text)

    if validation.status == STATUS_READY:
        result = apply_correction_request(request, target_text)

        if result.status != STATUS_APPLIED:
            return result

        verification = verify_correction_application_result(request, result)
        if verification.status == VERIFICATION_STATUS_VALID:
            return result

        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=(
                result.original_text
                if isinstance(result.original_text, str) else None
            ),
            reason=verification.reason,
        )

    if validation.status == STATUS_NOT_READY:
        return CorrectionApplicationResult(
            STATUS_NOT_APPLIED,
            original_text=target_text,
            corrected_text=target_text,
            reason=validation.reason,
        )

    # STATUS_INVALID
    return CorrectionApplicationResult(
        STATUS_FAILED,
        original_text=target_text if isinstance(target_text, str) else None,
        reason=validation.reason,
    )
