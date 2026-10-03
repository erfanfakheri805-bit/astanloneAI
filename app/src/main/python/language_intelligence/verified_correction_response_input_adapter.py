"""
Language Intelligence - Verified Correction Response Input Adapter
========================================================================
Prompt 486. A small, deterministic adapter that converts a valid,
successfully-applied `CorrectionApplicationResult` (Prompt 474/478/479,
correction_application_result.py) into the project's EXISTING Prompt
485 `VerifiedCorrectionResponseInput`
(verified_correction_response_input.py).

This module does not apply a correction, does not perform new text
matching, and does not modify `result` or anything else. It only
performs one small, pure conversion:

    CorrectionApplicationResult
        -> build_verified_correction_response_input_from_result(...)
        -> a `VerifiedCorrectionResponseInput` - or the project's
           existing empty-result convention (`None`, the SAME value
           `convert_correction_feedback_to_learning_input()`,
           Prompt 455, already returns for an unusable input) when
           `result` does not represent a successfully applied AND
           verified correction.

Why `None`, and not a new placeholder/invalid instance
------------------------------------------------------------
`VerifiedCorrectionResponseInput` (Prompt 485) has no "empty, not
valid" placeholder state of its own - see that module's own docstring
("Represents ONLY an already-applied correction"). This adapter
therefore follows the SAME "nothing usable -> `None`" convention
`convert_correction_feedback_to_learning_input()` already uses for its
own structurally identical situation, rather than inventing a second
"empty" shape for this new type.

What must hold before a `VerifiedCorrectionResponseInput` is built
------------------------------------------------------------------------
ALL of the following, using EXACT, literal, case-sensitive
`is not None`/`==` checks only - the SAME per-field rules Prompt 484's
`is_correction_application_result_usable()` already documents for its
own, structurally identical question, applied here directly to a
`CorrectionApplicationResult` rather than through a
`ResponseGenerationContext`:

    - `result` is a `CorrectionApplicationResult` (required; `TypeError`
      otherwise, the SAME "isinstance check, then raise" posture
      `convert_correction_feedback_to_learning_input()` already uses)
    - `result.status` is exactly `STATUS_APPLIED` (`"APPLIED"`)
    - `result.applied` is exactly `True`
    - `result.match_count` is an `int` greater than zero
    - `result.text_before` is present (not `None`)
    - `result.text_after` is present (not `None`)
    - `result.matched_text` is present (not `None`)
    - `result.replacement_text` is present (not `None`)

Reusing the EXISTING validation logic, unmodified
------------------------------------------------------
This adapter additionally requires `result` to pass the EXISTING
Prompt 480 `validate_applied_correction_result()`
(correction_application_result_validation.py) - imported and called
exactly as it already exists, never re-implemented or duplicated. That
validator compares `result` against the
`CorrectionApplicationRequest` it claims to fulfill (Prompt 473); this
adapter is only ever handed a `CorrectionApplicationResult`, so it
builds the SAME kind of self-consistent, minimal request the EXISTING
`CorrectionApplicationRequest` constructor already accepts
(`is_valid=True`, `kind=REQUEST_KIND_APPLY_CORRECTION`,
`original_expression=result.matched_text`,
`corrected_expression_or_meaning=result.replacement_text`) - the
EXACT same `matched_text`/`replacement_text` `result` already carries,
never a re-derived or re-matched value. `validate_applied_correction_result()`
then checks, using its own existing, unmodified rules, that `matched_text`
occurs in `text_before`, that `replacement_text` occurs in `text_after`,
and that replacing every EXACT occurrence of `matched_text` in
`text_before` with `replacement_text` (Python's own `str.replace()`,
reused by the validator - not by this module) equals `text_after`
EXACTLY. A `result` that fails any of these is never converted, and
this module performs no fuzzy matching, semantic similarity,
embeddings, spelling correction, normalization, guessing, ranking, or
confidence-based decision anywhere in this check.

Never applies, matches, or generates anything
-------------------------------------------------
`build_verified_correction_response_input_from_result()` never applies
a correction, never performs new text matching, and never modifies
`result` or the `CorrectionApplicationResult` it was given. Converting
an already-applied, already-verified result into a
`VerifiedCorrectionResponseInput` is the entire operation.

Exact strings and metadata, never normalized
------------------------------------------------
`text_before`, `text_after`, `matched_text`, `replacement_text`, and
`match_count` are copied straight from `result` into the
`VerifiedCorrectionResponseInput` constructor - never stripped, cased,
trimmed, re-derived, or re-counted. `metadata` is likewise copied
straight through (deep-copied by `VerifiedCorrectionResponseInput.
__init__` itself, the SAME `copy.deepcopy()` convention that class
already uses for its own field of this name - not duplicated here).

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`, Response
Generation, Learning, Memory, Knowledge, Meaning Resolution,
Correction Understanding, Correction Lookup, Correction Selection,
Correction Application, the Local Model Runtime, `AgentLoop`, or
Self-Upgrade. It does not modify `CorrectionApplicationResult`,
`CorrectionApplicationRequest`, `validate_applied_correction_result()`,
or `VerifiedCorrectionResponseInput` - a thin, read-only adapter
between two structures that already exist.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED,
)
from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest,
    REQUEST_KIND_APPLY_CORRECTION,
)
from language_intelligence.correction_application_result_validation import (
    validate_applied_correction_result,
    STATUS_VALID,
)
from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
)


def _has_required_fields(result):
    """True only when every field a `VerifiedCorrectionResponseInput`
    needs is present on `result` (not `None`) - see the module
    docstring. Never mutates `result`."""
    if result.text_before is None:
        return False
    if result.text_after is None:
        return False
    if result.matched_text is None:
        return False
    if result.replacement_text is None:
        return False
    return True


def _passes_existing_validation(result):
    """True only when `result` passes the EXISTING, unmodified Prompt
    480 `validate_applied_correction_result()`, checked against a
    self-consistent `CorrectionApplicationRequest` built from
    `result`'s OWN `matched_text`/`replacement_text` - see the module
    docstring's "Reusing the EXISTING validation logic" section. Never
    mutates `result`."""
    request = CorrectionApplicationRequest(
        is_valid=True,
        kind=REQUEST_KIND_APPLY_CORRECTION,
        original_expression=result.matched_text,
        corrected_expression_or_meaning=result.replacement_text,
    )
    validation = validate_applied_correction_result(request, result)
    return validation.status == STATUS_VALID


def build_verified_correction_response_input_from_result(result):
    """Convert `result` (a `CorrectionApplicationResult` - required;
    `TypeError` otherwise, the SAME "isinstance check, then raise"
    posture `convert_correction_feedback_to_learning_input()` already
    uses) into a `VerifiedCorrectionResponseInput` (Prompt 485), ONLY
    when `result` represents a successfully applied AND verified
    correction - see the module docstring for the exact conditions.

    Returns `None` - the project's existing empty-result convention -
    when `result` does not meet every condition: no result, a
    `NOT_APPLIED`/`FAILED` status, `applied` not `True`, a
    `match_count` that is not a positive `int`, any of
    `text_before`/`text_after`/`matched_text`/`replacement_text`
    missing, or a `result` that fails the EXISTING
    `validate_applied_correction_result()` check. Never raises for any
    of these - only a wrong-typed `result` raises `TypeError`.

    Never applies a correction, never performs new text matching,
    never modifies `result`. Pure and deterministic: the same `result`
    always produces an equal `VerifiedCorrectionResponseInput` (or the
    same `None`).
    """
    if not isinstance(result, CorrectionApplicationResult):
        raise TypeError(
            "result must be a CorrectionApplicationResult "
            "(language_intelligence.correction_application_result."
            "CorrectionApplicationResult) instance"
        )

    if result.status != STATUS_APPLIED:
        return None

    if result.applied is not True:
        return None

    if not isinstance(result.match_count, int) or result.match_count <= 0:
        return None

    if not _has_required_fields(result):
        return None

    if not _passes_existing_validation(result):
        return None

    return VerifiedCorrectionResponseInput(
        text_before=result.text_before,
        text_after=result.text_after,
        matched_text=result.matched_text,
        replacement_text=result.replacement_text,
        match_count=result.match_count,
        metadata=result.metadata,
    )
