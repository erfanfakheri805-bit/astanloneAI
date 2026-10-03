"""
Language Intelligence - Build Verified Correction Response Instruction
========================================================================
Prompt 491. A small, deterministic operation that converts an
already-validated and usable `VerifiedCorrectionResponseInput`
(Prompt 485) into a `VerifiedCorrectionResponseInstruction`
(Prompt 490). This module adds ONLY the conversion itself - no
response text is modified, no new text matching (fuzzy, semantic, or
otherwise) happens here, and this instruction is not connected to the
normal response-generation flow.

    VerifiedCorrectionResponseInput                    (Prompt 485, unchanged)
    is_verified_correction_response_input_usable(...)   (Prompt 488, unchanged)
    VerifiedCorrectionResponseInstruction              (Prompt 490, unchanged)
    build_verified_correction_response_instruction_from_input(...)   (THIS module)
        -> VerifiedCorrectionResponseInstruction, or None

Same shape as Prompt 486's existing converter
------------------------------------------------------------
This module follows the SAME "convert one already-known, already-
verified structure into another, returning the project's existing
`None` empty-result convention when the input is missing or not
usable" posture that
`build_verified_correction_response_input_from_result()`
(verified_correction_response_input_adapter.py, Prompt 486) already
uses for its own, structurally identical conversion
(`CorrectionApplicationResult` -> `VerifiedCorrectionResponseInput`).
Nothing about that existing converter, or about Prompt 488's own
usability rules, is modified here.

Reuses the existing usability rules, never re-derives them
------------------------------------------------------------------
Prompt 488's `is_verified_correction_response_input_usable()` answers
this same "is this verified correction response input structurally
usable?" question, but for a `VerifiedCorrectionResponseInput`
already attached to a `ResponseGenerationContext`
(response_generation_context.py). This module receives the
`VerifiedCorrectionResponseInput` directly rather than wrapped in a
context, so it applies the EXACT SAME rule set that module's own
docstring documents - existence and type, then non-blank
`text_before` / `text_after` / `matched_text` / `replacement_text`
and a positive `int` `match_count`, using the SAME `_is_blank()`
(correction_understanding.py, imported, never re-implemented) - the
SAME "adapt the existing rule set to a differently-shaped input,
never loosen or re-derive it" posture
`verified_correction_response_input_adapter.py` (Prompt 486) already
uses when it applies Prompt 480's existing validation rules to a
`CorrectionApplicationResult` rather than to a
`ResponseGenerationContext`.

Only prepares the instruction - never modifies response text
------------------------------------------------------------------
This module performs no correction application, no text replacement,
no matching of any kind (fuzzy, semantic, embeddings, spelling-
correction, normalization, guessing, ranking, or confidence-based),
no response generation, and no response text modification. It also
never modifies correction storage, correction application, learning
behavior, or the normal response-generation flow. Building one
`VerifiedCorrectionResponseInstruction` from one already-usable
`VerifiedCorrectionResponseInput` is the entire operation.

Field mapping - exact values, never normalized
----------------------------------------------------
    source_text        <- verified_input.text_before
    corrected_text      <- verified_input.text_after
    matched_text        <- verified_input.matched_text
    replacement_text    <- verified_input.replacement_text
    match_count         <- verified_input.match_count
    instruction_type     <- always
                          `INSTRUCTION_TYPE_USE_CORRECTED_TEXT`
                          (`"USE_CORRECTED_TEXT"`)

Every value is taken EXACTLY as stored on `verified_input` - never
stripped, cased, trimmed, reinterpreted, or otherwise transformed.
`VerifiedCorrectionResponseInstruction.__init__` (Prompt 490,
unchanged) performs its own construction-time validation of these
same values; this module adds no additional transformation on top of
it.

What "missing or unusable" means -> `None`
------------------------------------------------
`VerifiedCorrectionResponseInstruction` (Prompt 490) has no "empty,
not valid" placeholder state of its own - see that module's own
docstring. This module therefore follows the SAME "nothing usable ->
`None`" convention `verified_correction_response_input_extraction.py`
(Prompt 489) and `verified_correction_response_input_adapter.py`
(Prompt 486) already use for their own, structurally identical
situations, rather than inventing a second empty-result convention.
`None` is returned when:

    - `verified_input` is `None`
    - `verified_input` is present but is not itself a
      `VerifiedCorrectionResponseInput` instance (e.g. a plain dict)
    - `verified_input` is a `VerifiedCorrectionResponseInput` that
      fails the usability rules above (any one of `text_before` /
      `text_after` / `matched_text` / `replacement_text` missing or
      blank, or a `match_count` that is not a positive `int`)

Never raises for any of these - `None` is the project's existing
empty-result convention for this situation, exactly as Prompt 486's
own converter already uses it.

Not yet connected
--------------------
This module does not modify `VerifiedCorrectionResponseInput`
(verified_correction_response_input.py),
`is_verified_correction_response_input_usable()`
(verified_correction_response_input_usability.py),
`extract_usable_verified_correction_response_input()`
(verified_correction_response_input_extraction.py),
`VerifiedCorrectionResponseInstruction`
(verified_correction_response_instruction.py), or
`ResponseGenerationContext` (response_generation_context.py), and is
not wired into the normal response-generation pipeline. It does not
touch Learning, Memory, Knowledge, Meaning Resolution, Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction
Application Verification, `CorrectionApplicationResult`, the Local
Model Runtime, `AgentLoop`, or Self-Upgrade - deciding when/how a
`VerifiedCorrectionResponseInstruction` built here is actually used
by response generation is a separate, future, explicitly scoped step.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

from language_intelligence.correction_understanding import _is_blank
from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
)
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
    INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
)


def _is_usable_verified_correction_response_input(verified_input):
    """The exact same structural rules Prompt 488's
    `is_verified_correction_response_input_usable()` documents for a
    `VerifiedCorrectionResponseInput` - existence and type, then
    non-blank `text_before` / `text_after` / `matched_text` /
    `replacement_text` and a positive `int` `match_count` - applied
    directly to `verified_input` rather than to a
    `ResponseGenerationContext` that carries one. See this module's
    own docstring ("Reuses the existing usability rules, never
    re-derives them") for why this module checks the input directly
    instead of calling that context-shaped function.
    """
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


def build_verified_correction_response_instruction_from_input(verified_input):
    """Convert `verified_input` (expected to be a
    `VerifiedCorrectionResponseInput`, Prompt 485) into a
    `VerifiedCorrectionResponseInstruction` (Prompt 490), ONLY when
    `verified_input` is usable per the rules in this module's own
    docstring.

    Returns `None` - the project's existing empty-result convention -
    when `verified_input` is `None`, is not itself a
    `VerifiedCorrectionResponseInput` instance, or fails the
    usability rules (any one of `text_before` / `text_after` /
    `matched_text` / `replacement_text` missing or blank, or a
    `match_count` that is not a positive `int`). Never raises for any
    of these.

    When usable, returns a new `VerifiedCorrectionResponseInstruction`
    built from `verified_input`'s own values exactly as stored - see
    this module's own docstring's "Field mapping" section for the
    exact field correspondence - with
    `instruction_type=INSTRUCTION_TYPE_USE_CORRECTED_TEXT`. No
    normalization, rewriting, inference, or reinterpretation of any
    value happens here.

    Pure and deterministic; never mutates `verified_input`; never
    applies a correction, performs text replacement, performs
    matching, or generates/modifies any response text - purely a
    conversion, exactly like Prompt 486's
    `build_verified_correction_response_input_from_result()` is for
    its own, structurally identical conversion.
    """
    if not _is_usable_verified_correction_response_input(verified_input):
        return None

    return VerifiedCorrectionResponseInstruction(
        source_text=verified_input.text_before,
        corrected_text=verified_input.text_after,
        matched_text=verified_input.matched_text,
        replacement_text=verified_input.replacement_text,
        match_count=verified_input.match_count,
        instruction_type=INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
    )
