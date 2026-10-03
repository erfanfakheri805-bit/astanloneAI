"""
Language Intelligence - Correction Application Result Usability
========================================================================
Prompt 484. A small, deterministic usability check over the EXISTING
Prompt 483 `ResponseGenerationContext.correction_application_result`
(a `CorrectionApplicationResult`, Prompt 474/478/479, when a caller
explicitly supplied one - see response_generation_context.py's own
module docstring). This module answers exactly one question - "is the
correction result this context is carrying safe to treat as an
actually applied correction?" - and nothing else. It does not apply a
correction, does not modify `ResponseGenerationContext`, does not
modify the stored `CorrectionApplicationResult`, and does not connect
this answer to anything downstream.

    build_generation_context(...)                  (Prompt 467/471/483, unchanged)
        -> ResponseGenerationContext
    is_correction_application_result_usable(...)     (THIS module)
        -> True / False

Same reasoning Prompt 468's `correction_lookup_usability.py` and
Prompt 456's `correction_learning_input_eligibility.py` already
document for their own, structurally identical question: this is a
single, small, deterministic fact about an already-built object, not a
new structure with a status and an issues list to maintain.
`is_correction_application_result_usable()` is the entire answer this
stage needs.

What "usable" means
---------------------
`context.correction_application_result` (a `CorrectionApplicationResult`,
required to already be one - see "Not a validator, not a re-verifier"
below) is usable only when ALL of the following hold, using EXACT,
literal, case-sensitive `is not None`/`==` checks only - the SAME
"only structural, deterministic facts" posture
`correction_application_result_validation.py` (Prompt 480) already
uses for its own `APPLIED` checks:

    - a correction result exists (`context.correction_application_result`
      is not `None`, and is a `CorrectionApplicationResult` instance)
    - `result.status` is exactly `STATUS_APPLIED` (`"APPLIED"`) -
      `NOT_APPLIED` and `FAILED` are never usable, regardless of what
      else the result carries
    - `result.applied` is exactly `True`
    - `result.match_count` is an `int` greater than zero
    - `result.text_before` is available (not `None`)
    - `result.text_after` is available (not `None`)
    - `result.matched_text` is available (not `None`)
    - `result.replacement_text` is available (not `None`)

Missing or structurally incomplete correction information (no result
at all, or any one of the fields above missing/blank in the sense of
being `None`) makes the result not usable - the SAME "every required
piece must be present" posture `correction_lookup_usability.py`
already uses for its own required-field pair.

Not a validator, not a re-verifier
-------------------------------------
This module does not call, duplicate, or replace
`validate_applied_correction_result()` (Prompt 480) or
`verify_correction_application_result()` (Prompt 482) - it only reads
the EXISTING fields already present on an EXISTING
`CorrectionApplicationResult` that a caller already attached to a
`ResponseGenerationContext`. It performs no cross-checking against any
`CorrectionApplicationRequest`, no fuzzy matching, no semantic
similarity, no embeddings, no spelling correction, no normalization,
no guessing, no ranking, no confidence-based decision, and no
automatic correction.

Pure, deterministic, non-mutating
------------------------------------
`is_correction_application_result_usable()` only reads
`context.correction_application_result` and that result's own
`status` / `applied` / `match_count` / `text_before` / `text_after` /
`matched_text` / `replacement_text` attributes - it never sets,
appends, or otherwise mutates `context`, the stored
`CorrectionApplicationResult`, or anything else. The same
`ResponseGenerationContext` always produces the same boolean.

Not yet connected
--------------------
This module does not perform any correction, does not change normal
response-generation behavior, does not make the local model consume
or interpret the correction result, and does not automatically invoke
correction application. It does not modify Correction Understanding,
Correction Lookup, Correction Selection, Correction Application,
Correction Application Validation, Correction Application
Verification, Learning, Memory, Knowledge, Meaning Resolution, the
Local Model Runtime, `AgentLoop`, or Self-Upgrade - a thin, read-only
check over an object that already exists, exactly like
`correction_lookup_usability.py` is for `CorrectionLookupContext`.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
`ResponseGenerationContext` (Prompt 426/467/471/483) and
`CorrectionApplicationResult` (Prompt 474/478/479) are both reused
exactly as they already exist.
"""

from language_intelligence.response_generation_context import (
    ResponseGenerationContext,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED,
)


def is_correction_application_result_usable(context):
    """True only when `context` (a `ResponseGenerationContext` -
    required; `TypeError` otherwise, the SAME "isinstance check, then
    raise" posture `is_correction_lookup_context_usable()` already
    uses) carries a `correction_application_result` that is itself a
    `CorrectionApplicationResult` with `status == STATUS_APPLIED`,
    `applied is True`, a `match_count` greater than zero, and all of
    `text_before` / `text_after` / `matched_text` / `replacement_text`
    available (not `None`) - see the module docstring for exactly what
    each of these means.

    No correction result at all, a `NOT_APPLIED` result, a `FAILED`
    result, an `applied=False` result, a zero (or otherwise not a
    positive `int`) `match_count`, or any one of the four text fields
    missing all make this False - never guessed, never treated as
    "close enough".

    Pure and deterministic; never mutates `context` or the stored
    `CorrectionApplicationResult`; never applies, verifies, re-checks,
    or generates anything - purely informational, exactly like Prompt
    483's own `correction_application_result` field on
    `ResponseGenerationContext`.
    """
    if not isinstance(context, ResponseGenerationContext):
        raise TypeError(
            "context must be a ResponseGenerationContext "
            "(language_intelligence.response_generation_context."
            "ResponseGenerationContext) instance"
        )

    result = context.correction_application_result
    if not isinstance(result, CorrectionApplicationResult):
        return False

    if result.status != STATUS_APPLIED:
        return False

    if result.applied is not True:
        return False

    if not isinstance(result.match_count, int) or result.match_count <= 0:
        return False

    if result.text_before is None:
        return False

    if result.text_after is None:
        return False

    if result.matched_text is None:
        return False

    if result.replacement_text is None:
        return False

    return True
