"""
Language Intelligence - Extract Usable Verified Correction Response Input
========================================================================
Prompt 489. A small, deterministic operation that reads the EXISTING
Prompt 487 `ResponseGenerationContext.verified_correction_response_input`
(a `VerifiedCorrectionResponseInput`, Prompt 485, when a caller
explicitly supplied one) and returns it - as a safe copy, never the
stored instance itself - ONLY when Prompt 488's
`is_verified_correction_response_input_usable()` says it is usable.
This module performs no correction application, no text replacement,
no matching of any kind, and no response generation - it only decides
"is there a usable verified correction response input here, and if
so, hand back an independent copy of it".

    build_generation_context(...)                       (Prompt 426/467/471/483/487, unchanged)
        -> ResponseGenerationContext
    is_verified_correction_response_input_usable(...)     (Prompt 488, unchanged)
        -> True / False
    extract_usable_verified_correction_response_input(...)   (THIS module)
        -> VerifiedCorrectionResponseInput copy, or None

Reuses the existing usability check, never re-implements it
------------------------------------------------------------------
This module does not duplicate, loosen, or re-derive Prompt 488's
"what usable means" logic (existing input, non-blank `text_before` /
`text_after` / `matched_text` / `replacement_text`, positive int
`match_count` - see verified_correction_response_input_usability.py's
own module docstring for the exact rule). It calls
`is_verified_correction_response_input_usable(context)` and branches
on that single boolean alone - the SAME "call the existing check,
never re-derive it" posture this package already follows wherever one
module's output feeds another's decision.

What "the project's appropriate empty/None result" means
-------------------------------------------------------------
`VerifiedCorrectionResponseInput` (Prompt 485) has no "empty, not
valid" placeholder state of its own - see that module's own docstring
("Represents ONLY an already-applied correction"). This module
therefore follows the SAME "nothing usable -> `None`" convention
`verified_correction_response_input_adapter.py` (Prompt 486) already
uses for its own, structurally identical situation, rather than
inventing a second empty-state convention. `None` is returned when:

    - `context.verified_correction_response_input` is `None`
    - `context.verified_correction_response_input` is present but is
      not itself a `VerifiedCorrectionResponseInput` (e.g. a plain
      dict) - the SAME case the usability check already treats as not
      usable
    - `context.verified_correction_response_input` is a
      `VerifiedCorrectionResponseInput` that fails the usability
      check (any one of its required fields missing/blank/non-positive)

Safe copy, never the stored instance
-----------------------------------------
When the input is usable, this module returns
`context.verified_correction_response_input.copy()` -
`VerifiedCorrectionResponseInput.copy()` (Prompt 485) already returns
a new, independent instance with every field preserved exactly and
`metadata` deep-copied, the SAME "return an independent copy, never
hand back shared mutable state" convention this package's `to_dict()`/
`copy()` methods already use throughout. A caller that mutates the
returned copy can never reach back into `context` or the stored
`VerifiedCorrectionResponseInput`.

Never applies, matches, or generates anything
-------------------------------------------------
This module never performs correction application, never performs
text replacement, never performs matching (fuzzy, semantic,
embeddings, spelling-correction, normalization, guessing, ranking, or
confidence-based), never modifies `ResponseGenerationContext`, never
modifies the stored `VerifiedCorrectionResponseInput`, and never
generates or modifies any response text. Extracting an already-usable
copy is the entire operation.

Not yet connected
--------------------
This module is not wired into the normal response-generation
execution path, does not make the local model consume this input, and
does not modify Correction Understanding, Correction Lookup,
Correction Selection, Correction Application, Correction Application
Validation, Correction Application Verification,
`CorrectionApplicationResult`, Learning, Memory, Knowledge, Meaning
Resolution, Response Generation, the Local Model Runtime, `AgentLoop`,
or Self-Upgrade - deciding when/how an extracted
`VerifiedCorrectionResponseInput` is actually used is a separate,
future, explicitly scoped step.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed. `ResponseGenerationContext`
(Prompt 426/467/471/483/487), `VerifiedCorrectionResponseInput`
(Prompt 485), and `is_verified_correction_response_input_usable()`
(Prompt 488) are all reused exactly as they already exist.
"""

from language_intelligence.response_generation_context import (
    ResponseGenerationContext,
)
from language_intelligence.verified_correction_response_input_usability import (
    is_verified_correction_response_input_usable,
)


def extract_usable_verified_correction_response_input(context):
    """The `context.verified_correction_response_input`
    (`ResponseGenerationContext`, Prompt 426/467/471/483/487 -
    required; `TypeError` otherwise, the SAME "isinstance check, then
    raise" posture `is_verified_correction_response_input_usable()`
    already uses) as an independent copy, ONLY when
    `is_verified_correction_response_input_usable(context)` is `True`
    - `None` otherwise (no input at all, an input stored as something
    other than a `VerifiedCorrectionResponseInput`, or one that fails
    the usability check). See the module docstring for exactly what
    "usable" means and why `None` is the empty result.

    The returned value, when not `None`, is
    `context.verified_correction_response_input.copy()` - a fresh,
    independent `VerifiedCorrectionResponseInput` with every field
    (`text_before`, `text_after`, `matched_text`, `replacement_text`,
    `match_count`) and `metadata` preserved exactly. Mutating it can
    never reach back into `context` or the stored input.

    Pure and deterministic; never mutates `context` or the stored
    `VerifiedCorrectionResponseInput`; never applies a correction,
    performs text replacement, performs matching, or generates/modifies
    any response text - purely an extraction, exactly like Prompt
    486's `build_verified_correction_response_input_from_result()` is
    for its own, structurally identical conversion.
    """
    if not isinstance(context, ResponseGenerationContext):
        raise TypeError(
            "context must be a ResponseGenerationContext "
            "(language_intelligence.response_generation_context."
            "ResponseGenerationContext) instance"
        )

    if not is_verified_correction_response_input_usable(context):
        return None

    return context.verified_correction_response_input.copy()
