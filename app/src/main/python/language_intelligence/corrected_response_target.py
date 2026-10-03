"""
Language Intelligence - Prepare Corrected Response Target
========================================================================
Prompt 493. A small, deterministic operation that reads the EXISTING
`ResponseGenerationRequest.verified_correction_instruction`
(a `VerifiedCorrectionResponseInstruction`, Prompt 490, when a caller
explicitly supplied one - see Prompt 492's
`ResponseGenerationRequest.__init__`) and returns ONLY the corrected
target text it already carries. This module performs no correction
application, no text replacement, no matching of any kind, no
response generation, and no change to the normal response-generation
flow - it only decides "is there a usable verified correction
instruction here, and if so, what is its corrected target text".

    ResponseGenerationRequest(..., verified_correction_instruction=...)   (Prompt 492, unchanged)
    VerifiedCorrectionResponseInstruction                                (Prompt 490, unchanged)
    prepare_corrected_response_target(...)                               (THIS module)
        -> corrected target text (str), or None

Reuses the instruction's own construction-time validation, never
re-derives it
------------------------------------------------------------------------
`VerifiedCorrectionResponseInstruction.__init__` (Prompt 490,
unchanged) is itself the gate: constructing one raises `ValueError`
unless `source_text`, `corrected_text`, `matched_text`, and
`replacement_text` are all non-blank, `match_count` is a positive
`int`, and `instruction_type` is one of the supported values (see
that module's own docstring, "Represents ONLY a deterministic
instruction to use a corrected form"). Consequently, any object that
IS a `VerifiedCorrectionResponseInstruction` instance is already
valid and usable by construction - there is no separate,
already-existing validation function to call, and this module does
not invent one. What this module checks is exactly the ONE thing
Prompt 490 does not guarantee on its own: whether
`request.verified_correction_instruction` is actually present and is
actually a `VerifiedCorrectionResponseInstruction` instance, rather
than `None` or something else entirely - the SAME "existence and
type, then trust the structure's own construction-time guarantees"
posture `verified_correction_response_input_usability.py` (Prompt
488) and `verified_correction_response_instruction_adapter.py`
(Prompt 491) already use for their own, structurally identical
questions.

What "the corrected target text represented by the instruction" means
----------------------------------------------------------------------
`VerifiedCorrectionResponseInstruction.corrected_text` (Prompt 490)
IS the corrected target text - "the exact text after the correction
is used" per that module's own docstring. This module returns that
value EXACTLY as stored - never stripped, cased, trimmed,
reinterpreted, or otherwise transformed, and never recomputed from
`matched_text` / `replacement_text` / `source_text`. The returned
value comes directly from the existing verified instruction; nothing
here reconstructs, guesses, or re-derives it.

Only prepares the target - never generates or applies anything
------------------------------------------------------------------
This module performs no fuzzy matching, no semantic matching, no new
correction lookup, no new correction application, no learning, no
storage, no inference, and no response generation. It does not
change the normal response-generation flow, does not modify
`ResponseGenerationContext` (response_generation_context.py), and
does not modify correction learning, correction storage, or
correction application. Reading one already-known field off an
already-verified instruction is the entire operation.

What `None` means
----------------------
`None` is returned when:

    - `request.verified_correction_instruction` is `None` (the
      default - see Prompt 492)
    - `request.verified_correction_instruction` is present but is
      not itself a `VerifiedCorrectionResponseInstruction` instance
      (e.g. a plain dict) - treated as unusable, the SAME "wrong
      shape -> not usable" posture
      `verified_correction_response_input_usability.py` (Prompt 488)
      already uses for its own, structurally identical field

Never raises for either of these; `None` is the project's existing
empty-result convention for this situation, exactly as Prompt 489's
`extract_usable_verified_correction_response_input()` and Prompt
491's `build_verified_correction_response_instruction_from_input()`
already use it.

Pure, deterministic, non-mutating
------------------------------------
`prepare_corrected_response_target()` only reads
`request.verified_correction_instruction` and, when present and
valid, that instruction's own `corrected_text` attribute - it never
sets, appends, or otherwise mutates `request`, the stored
`VerifiedCorrectionResponseInstruction`, or anything else. The same
`ResponseGenerationRequest` always produces the same result.

Not yet connected
--------------------
This module does not change the normal conversation flow, does not
modify `ResponseGenerationContext`, does not modify Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction
Application Verification, `CorrectionApplicationResult`, Learning,
Memory, Knowledge, Meaning Resolution, the Local Model Runtime,
`AgentLoop`, or Self-Upgrade - deciding when/how a prepared corrected
target is actually used by response generation is a separate,
future, explicitly scoped step.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
`ResponseGenerationRequest` (Prompt 492) and
`VerifiedCorrectionResponseInstruction` (Prompt 490) are both reused
exactly as they already exist.
"""

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)


def prepare_corrected_response_target(request):
    """The corrected target text (`str`) already carried by
    `request.verified_correction_instruction`
    (`ResponseGenerationRequest`, Prompt 492 - required; `TypeError`
    otherwise, the SAME "isinstance check, then raise" posture
    `is_verified_correction_response_input_usable()` (Prompt 488)
    already uses), or `None` when there is nothing usable to prepare.

    `None` is returned when `request.verified_correction_instruction`
    is `None`, or is present but is not itself a
    `VerifiedCorrectionResponseInstruction` instance. See the module
    docstring for exactly why any actual
    `VerifiedCorrectionResponseInstruction` instance is already
    considered valid (its own `__init__` guarantees this at
    construction time) and for what `corrected_text` means.

    Pure and deterministic; never mutates `request` or the stored
    instruction; never applies a correction, performs text
    replacement, performs matching, or generates/modifies any
    response text - purely a read of one already-known field, exactly
    like Prompt 489's `extract_usable_verified_correction_response_input()`
    is for its own, structurally identical situation.
    """
    if not isinstance(request, ResponseGenerationRequest):
        raise TypeError(
            "request must be a ResponseGenerationRequest "
            "(language_intelligence.response_generation."
            "ResponseGenerationRequest) instance"
        )

    instruction = request.verified_correction_instruction

    if not isinstance(instruction, VerifiedCorrectionResponseInstruction):
        return None

    return instruction.corrected_text
