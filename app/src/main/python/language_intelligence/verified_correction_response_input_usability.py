"""
Language Intelligence - Verified Correction Response Input Usability
========================================================================
Prompt 488. A small, deterministic usability check over the EXISTING
Prompt 487 `ResponseGenerationContext.verified_correction_response_input`
(a `VerifiedCorrectionResponseInput`, Prompt 485, when a caller
explicitly supplied one - see response_generation_context.py's own
module docstring). This module answers exactly one question - "is the
verified correction response input this context is carrying
structurally usable?" - and nothing else. It does not apply a
correction, does not modify `ResponseGenerationContext`, does not
modify the stored `VerifiedCorrectionResponseInput`, and does not
connect this answer to anything downstream.

    build_generation_context(...)                  (Prompt 426/467/471/483/487, unchanged)
        -> ResponseGenerationContext
    is_verified_correction_response_input_usable(...)   (THIS module)
        -> True / False

Same reasoning Prompt 468's `correction_lookup_usability.py` and
Prompt 484's `correction_application_result_usability.py` already
document for their own, structurally identical question: this is a
single, small, deterministic fact about an already-built object, not a
new structure with a status and an issues list to maintain.
`is_verified_correction_response_input_usable()` is the entire answer
this stage needs.

What "usable" means
---------------------
`context.verified_correction_response_input` (required to already be
a `VerifiedCorrectionResponseInput` instance - see "Not a validator,
not a re-verifier" below) is usable only when ALL of the following
hold, using EXACT, literal, case-sensitive checks only - the SAME
"only structural, deterministic facts" posture
`correction_application_result_usability.py` (Prompt 484) already uses
for its own, structurally identical question:

    - the input exists (`context.verified_correction_response_input`
      is not `None`, and is a `VerifiedCorrectionResponseInput`
      instance)
    - `text_before` is non-blank (`correction_understanding._is_blank()`,
      imported, never re-implemented - the SAME "nothing supplied"
      rule `correction_lookup_usability.py` and
      `VerifiedCorrectionResponseInput.__init__` itself already apply
      to these same four text fields)
    - `text_after` is non-blank
    - `matched_text` is non-blank
    - `replacement_text` is non-blank
    - `match_count` is an `int` greater than zero

Missing or structurally incomplete correction information (no input
at all, or any one of the fields above missing/blank/non-positive)
makes the input not usable - the SAME "every required piece must be
present" posture `correction_application_result_usability.py` already
uses for its own required-field set.

Not a validator, not a re-verifier
-------------------------------------
This module does not call, duplicate, or replace
`VerifiedCorrectionResponseInput.__init__`'s own construction-time
validation, and does not call, duplicate, or replace
`build_verified_correction_response_input_from_result()` (Prompt 486)
- it only reads the EXISTING fields already present on an EXISTING
`VerifiedCorrectionResponseInput` that a caller already attached to a
`ResponseGenerationContext`. It performs no fuzzy matching, no
semantic similarity, no embeddings, no spelling correction, no
normalization, no guessing, no ranking, no confidence-based decision,
and no automatic correction. Every string field is read and compared
EXACTLY as stored - never cased, trimmed, or otherwise transformed
beyond the blank/not-blank check itself.

Pure, deterministic, non-mutating
------------------------------------
`is_verified_correction_response_input_usable()` only reads
`context.verified_correction_response_input` and that input's own
`text_before` / `text_after` / `matched_text` / `replacement_text` /
`match_count` attributes - it never sets, appends, or otherwise
mutates `context`, the stored `VerifiedCorrectionResponseInput`, or
anything else. The same `ResponseGenerationContext` always produces
the same boolean.

Not yet connected
--------------------
This module does not perform any correction, does not change normal
response-generation behavior, does not make the local model consume
or interpret the verified correction response input, and does not
automatically invoke correction application or response generation.
It does not modify Correction Understanding, Correction Lookup,
Correction Selection, Correction Application, Correction Application
Validation, Correction Application Verification,
`CorrectionApplicationResult`, Learning, Memory, Knowledge, Meaning
Resolution, Response Generation, the Local Model Runtime, `AgentLoop`,
or Self-Upgrade - a thin, read-only check over an object that already
exists, exactly like `correction_application_result_usability.py` is
for `CorrectionApplicationResult`.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
`ResponseGenerationContext` (Prompt 426/467/471/483/487) and
`VerifiedCorrectionResponseInput` (Prompt 485) are both reused exactly
as they already exist.
"""

from language_intelligence.response_generation_context import (
    ResponseGenerationContext,
)
from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
)
from language_intelligence.correction_understanding import _is_blank


def is_verified_correction_response_input_usable(context):
    """True only when `context` (a `ResponseGenerationContext` -
    required; `TypeError` otherwise, the SAME "isinstance check, then
    raise" posture `is_correction_application_result_usable()` already
    uses) carries a `verified_correction_response_input` that is
    itself a `VerifiedCorrectionResponseInput` with `text_before`,
    `text_after`, `matched_text`, and `replacement_text` all non-blank,
    and a `match_count` that is an `int` greater than zero - see the
    module docstring for exactly what each of these means.

    No verified correction response input at all, an input stored as
    a plain dict rather than a `VerifiedCorrectionResponseInput`
    instance, any one of the four text fields missing/blank, or a
    zero/negative/non-`int` `match_count` all make this False - never
    guessed, never treated as "close enough".

    Pure and deterministic; never mutates `context` or the stored
    `VerifiedCorrectionResponseInput`; never applies, matches, or
    generates anything - purely informational, exactly like Prompt
    487's own `verified_correction_response_input` field on
    `ResponseGenerationContext`.
    """
    if not isinstance(context, ResponseGenerationContext):
        raise TypeError(
            "context must be a ResponseGenerationContext "
            "(language_intelligence.response_generation_context."
            "ResponseGenerationContext) instance"
        )

    verified_input = context.verified_correction_response_input
    if not isinstance(verified_input, VerifiedCorrectionResponseInput):
        return False

    if _is_blank(verified_input.text_before):
        return False

    if _is_blank(verified_input.text_after):
        return False

    if _is_blank(verified_input.matched_text):
        return False

    if _is_blank(verified_input.replacement_text):
        return False

    if not isinstance(verified_input.match_count, int) or verified_input.match_count <= 0:
        return False

    return True
