"""
Language Intelligence - Attach Corrected Response Target to Context
========================================================================
Prompt 494. A small, deterministic operation that attaches the
already-prepared corrected response target (Prompt 493's
`prepare_corrected_response_target()`, corrected_response_target.py)
onto an existing `ResponseGenerationContext`
(response_generation_context.py, Prompt 494's new
`corrected_response_target` field). This module only carries the
prepared value into the context - it performs no correction lookup,
no matching, no learning, and it never modifies the actual generated
response text.

    ResponseGenerationRequest(..., verified_correction_instruction=...)   (Prompt 492, unchanged)
    prepare_corrected_response_target(...)                               (Prompt 493, unchanged)
        -> corrected target text (str), or None
    ResponseGenerationContext(..., corrected_response_target=...)        (Prompt 494, additive field)
    with_corrected_response_target(...)                                  (THIS module)
        -> a NEW ResponseGenerationContext

Follows the project's existing "always return a fresh instance"
convention
------------------------------------------------------------------------
`ResponseGenerationContext` (response_generation_context.py) has no
setters and no `copy()` method of its own - it is a plain, read-only
bridge object built once by `build_generation_context()` and never
mutated afterward (see that module's own docstring, "a value holder
with `to_dict()`, never anything that validates by raising"). Rather
than introduce a new context architecture, mutation path, or
`copy()`/`with_*` convention onto `ResponseGenerationContext` itself,
this module follows the SAME "read every existing field, construct a
brand-new instance with the same values (plus the one field being
set)" posture this package's other read-only structures already use
for their own `copy()` methods (e.g.
`VerifiedCorrectionResponseInput.copy()`,
`VerifiedCorrectionResponseInstruction.copy()`) - `with_corrected_
response_target()` is that same pattern, applied once, for this one
additional field.

Reuses `prepare_corrected_response_target()`, never re-derives it
------------------------------------------------------------------------
This module does not duplicate, loosen, or re-derive Prompt 493's own
"is there a usable corrected target, and if so what is it" logic. It
calls `prepare_corrected_response_target(request)` and uses that
single result directly - the SAME "call the existing operation, never
re-derive it" posture this package already follows wherever one
module's output feeds directly into another's field.

What gets carried, and what does not
------------------------------------------
Every OTHER field already on `context` (`original_message`, `status`,
`response_action`, `meaning`, `meaning_candidates`, `matched_pattern`,
`variables`, `active_topic`, `references`, `context`, `language`,
`locale`, `unresolved_requirements`, `language_guidance`,
`response_pattern_selection`, `response_pattern_binding`,
`response_pattern_rendering`, `correction_lookup_context`,
`correction_application_candidate`, `correction_application_result`,
`verified_correction_response_input`) is copied onto the returned
context BY REFERENCE, exactly as `context` already holds it - never
recomputed, never re-validated, never transformed. Only
`corrected_response_target` is newly set, from
`prepare_corrected_response_target(request)`'s own return value,
preserved EXACTLY - never stripped, cased, trimmed, or otherwise
transformed.

"Leave the context unchanged when no corrected target exists"
--------------------------------------------------------------------
When `prepare_corrected_response_target(request)` returns `None` (no
`verified_correction_instruction` on `request`, or one that is not
usable - see corrected_response_target.py's own module docstring),
the returned context's `corrected_response_target` is `None` too -
the SAME value `ResponseGenerationContext.__init__`'s own default
already produces for any context nobody has attached one to. Every
other field is still copied through unchanged; nothing about the
context's meaning, plan-derived data, or existing correction fields
is altered by calling this operation with an unusable instruction.

Never applies, matches, looks up, or learns anything
------------------------------------------------------------
This module performs no correction lookup, no fuzzy matching, no
semantic matching, no learning, no storage, and no correction
application. It never modifies the actual generated response text,
never changes normal response-generation behavior, and never mutates
`context`, `request`, or anything either of them was built from -
`context.to_dict()` before and after calling this operation differs
only in the `corrected_response_target` key.

Not yet connected
--------------------
This module does not change how `generate_response()` or any backend
consumes a `ResponseGenerationContext`, does not modify Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction
Application Verification, `CorrectionApplicationResult`, Learning,
Memory, Knowledge, Meaning Resolution, the Local Model Runtime,
`AgentLoop`, or Self-Upgrade - deciding when/how a context carrying a
`corrected_response_target` is actually used to change generated
response text is a separate, future, explicitly scoped step.

Backward compatible
-----------------------
This is a new, additive module. `ResponseGenerationContext`'s new
`corrected_response_target` field (Prompt 494) defaults to `None`, so
every existing caller of `build_generation_context()` /
`ResponseGenerationContext.__init__` that does not know about this
field is completely unaffected. No existing file, class, function, or
constant is modified beyond that one additive field and its
`to_dict()` entry.
"""

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_context import ResponseGenerationContext
from language_intelligence.corrected_response_target import (
    prepare_corrected_response_target,
)


def with_corrected_response_target(context, request):
    """A NEW `ResponseGenerationContext`, identical to `context`
    (`ResponseGenerationContext` - required; `TypeError` otherwise)
    except its `corrected_response_target` field is set from
    `prepare_corrected_response_target(request)` (`request` must be a
    `ResponseGenerationRequest` - required; `TypeError` otherwise,
    the SAME "isinstance check, then raise" posture
    `prepare_corrected_response_target()` itself already uses).

    Every other field already on `context` is carried through exactly
    as it already holds it - see the module docstring's "What gets
    carried, and what does not" section. When
    `prepare_corrected_response_target(request)` returns `None` (no
    usable verified correction instruction on `request`), the
    returned context's `corrected_response_target` is `None` too -
    every other field is still unchanged.

    Pure and deterministic; never mutates `context` or `request`
    (`ResponseGenerationContext` has no setters of its own, so this
    was never possible in the first place, but this function also
    never reads or writes any private/internal state beyond the
    documented public attributes). Never applies a correction,
    performs text replacement, performs matching, or generates/
    modifies any response text - purely an attachment, exactly like
    Prompt 493's `prepare_corrected_response_target()` is for its own,
    structurally identical situation.
    """
    if not isinstance(context, ResponseGenerationContext):
        raise TypeError(
            "context must be a ResponseGenerationContext "
            "(language_intelligence.response_generation_context."
            "ResponseGenerationContext) instance"
        )
    if not isinstance(request, ResponseGenerationRequest):
        raise TypeError(
            "request must be a ResponseGenerationRequest "
            "(language_intelligence.response_generation."
            "ResponseGenerationRequest) instance"
        )

    corrected_target = prepare_corrected_response_target(request)

    return ResponseGenerationContext(
        original_message=context.original_message,
        status=context.status,
        response_action=context.response_action,
        meaning=context.meaning,
        meaning_candidates=context.meaning_candidates,
        matched_pattern=context.matched_pattern,
        variables=context.variables,
        active_topic=context.active_topic,
        references=context.references,
        context=context.context,
        language=context.language,
        locale=context.locale,
        unresolved_requirements=context.unresolved_requirements,
        language_guidance=context.language_guidance,
        response_pattern_selection=context.response_pattern_selection,
        response_pattern_binding=context.response_pattern_binding,
        response_pattern_rendering=context.response_pattern_rendering,
        correction_lookup_context=context.correction_lookup_context,
        correction_application_candidate=context.correction_application_candidate,
        correction_application_result=context.correction_application_result,
        verified_correction_response_input=context.verified_correction_response_input,
        corrected_response_target=corrected_target,
        learned_knowledge_context=context.learned_knowledge_context,
    )
