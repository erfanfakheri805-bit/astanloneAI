"""
Language Intelligence - Select Corrected Response Target
========================================================================
Prompt 495. A small, deterministic operation that selects the
appropriate response target from an existing
`ResponseGenerationContext` (response_generation_context.py): when a
verified corrected response target is available (Prompt 494's
`corrected_response_target` field, itself Prompt 493's `prepare_
corrected_response_target()` output, attached via `with_corrected_
response_target()`), that target is selected; otherwise `None`. This
stage only SELECTS the target - it generates no final response,
rewrites no user text, performs no new correction lookup or
application, and does not change the normal response-generation flow.

    ResponseGenerationContext(..., corrected_response_target=...)   (Prompt 494, unchanged)
    select_corrected_response_target(...)                          (THIS module)
        -> the corrected response target text (str), or None

No competing selection abstraction
------------------------------------------
This is the first response-target-selection operation in this
package - there is no existing "response target selection"
abstraction to integrate with, so this module does not introduce a
new architecture; it reads the ONE field Prompt 494 already exposes
for exactly this purpose and nothing else.

Reuses the existing "blank means nothing supplied" convention, never
re-derives it
------------------------------------------------------------------------
`corrected_response_target` (Prompt 494) is a plain attribute on
`ResponseGenerationContext` with no `__init__`-time validation of its
own (`ResponseGenerationContext` "never anything that validates by
raising" - see that module's own docstring), so a value that is
present but not actually a usable target (blank text, or some other
empty shape) must still be treated as "nothing selected". Rather than
inventing a new validity rule, this module reuses the SAME
`_is_blank()` (correction_understanding.py, Prompt 440s) every other
usability/validation check in this package already reuses for this
same "nothing supplied" question - `is_verified_correction_response_
input_usable()` (Prompt 488), `verified_correction_response_
instruction_adapter.py` (Prompt 491) and `VerifiedCorrectionResponse
Instruction.__init__` (Prompt 490) itself all rest on it. `None` and
a blank/whitespace-only string are the ONLY "nothing usable" shapes
`corrected_response_target` can actually take (it is always either
`None`, or `prepare_corrected_response_target()`'s output - a
`VerifiedCorrectionResponseInstruction.corrected_text`, which that
class's own `__init__` already guarantees is non-blank); this module
still checks explicitly, the SAME defensive "never assume, always
check" posture the rest of this package already uses, rather than
relying on that upstream guarantee alone.

Selects only - never generates, rewrites, applies, or matches
anything
------------------------------------------------------------------
This module performs no response generation, no rewriting of the
user's text, no new or repeated correction application, no fuzzy
matching, no semantic matching, no new correction lookup, and no
learning or storage. It does not call, use, or depend on any LLM or
external AI service. Reading one already-known field off an
already-built context, through the one existing validity check this
package already reuses, is the entire operation.

Preserves the value exactly
--------------------------------
When selected, the returned value is `context.corrected_response_
target` EXACTLY as stored - never stripped, cased, trimmed,
reinterpreted, or otherwise transformed. Nothing here reconstructs,
guesses, or re-derives it.

Pure, deterministic, non-mutating
------------------------------------
`select_corrected_response_target()` only reads
`context.corrected_response_target` - it never sets, appends, or
otherwise mutates `context` or anything it was built from. The same
`ResponseGenerationContext` always produces the same result.

Not yet connected
--------------------
This module does not change how `generate_response()` or any backend
actually produces a final response, does not modify Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction
Application Verification, `CorrectionApplicationResult`, Learning,
Memory, Knowledge, Meaning Resolution, the Local Model Runtime,
`AgentLoop`, or Self-Upgrade - deciding when/how a selected corrected
response target is actually used to produce generated response text
is a separate, future, explicitly scoped step.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
`ResponseGenerationContext` (Prompt 494) is reused exactly as it
already exists.
"""

from language_intelligence.correction_understanding import _is_blank
from language_intelligence.response_generation_context import ResponseGenerationContext


def select_corrected_response_target(context):
    """The corrected response target text (`str`) already carried by
    `context.corrected_response_target`
    (`ResponseGenerationContext`, Prompt 494 - required; `TypeError`
    otherwise, the SAME "isinstance check, then raise" posture
    `prepare_corrected_response_target()` (Prompt 493) and `with_
    corrected_response_target()` (Prompt 494) already use), or `None`
    when there is nothing usable to select.

    `None` is returned when `context.corrected_response_target` is
    `None`, or is blank per the SAME `_is_blank()`
    (correction_understanding.py) every other usability check in this
    package already reuses - see the module docstring for exactly why
    this second check is defensive rather than strictly necessary.

    When selected, the value is returned EXACTLY as stored - never
    stripped, cased, trimmed, or otherwise transformed.

    Pure and deterministic; never mutates `context`; never applies a
    correction, performs text replacement, performs matching, or
    generates/rewrites any response text - purely a selection, exactly
    like Prompt 493's `prepare_corrected_response_target()` is for its
    own, structurally identical situation.
    """
    if not isinstance(context, ResponseGenerationContext):
        raise TypeError(
            "context must be a ResponseGenerationContext "
            "(language_intelligence.response_generation_context."
            "ResponseGenerationContext) instance"
        )

    target = context.corrected_response_target

    if _is_blank(target):
        return None

    return target
