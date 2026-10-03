"""
Language Intelligence - Learned Response Decision
=================================================
Prompt 437. One small, deterministic decision point that runs BEFORE
normal backend response generation:

    understanding -> ... -> Pattern Rendering (Prompt 436)
      -> ResponseGenerationRequest.generation_request
         (`response_pattern_selection` / `_binding` / `_rendering`)
      -> decide_learned_response()               (this module)
           used     -> a `ResponseGenerationResult` (STATUS_GENERATED)
                       carrying the rendered text; the backend is not called
           not used -> None; the existing routing (backend selection, local
                       model, deterministic fallback) runs UNCHANGED

A learned response is an ADDITIONAL deterministic response source, never a
replacement for the local model or the fallback. It is used only when
every step already succeeded for THIS request:

    selection RESOLVED   exactly one pattern was selected (Prompt 434)
    binding   RESOLVED   every required variable was bound (Prompt 435)
    rendering RESOLVED   the template was rendered to non-blank text (436)
    validation VALID     the resulting `ResponseGenerationResult` passes
                         the existing Prompt 430 validation

Any other state - AMBIGUOUS / NOT_FOUND selection, UNRESOLVED binding or
rendering, a failed render, a failed validation, no plan at all - is "not
used", with the first failing step named in `LearnedResponseDecision.reason`.
Nothing is rendered, repaired, retried or guessed here; this module only
reads what Prompts 434-436 produced (as copies) and never mutates the
understanding, the request, learned records or any shared state.

Prompt 576 addendum - correction_application_result_usable
------------------------------------------------------------
`LearnedResponseDecision` also carries
`correction_application_result_usable`, forwarded straight from the SAME
`ResponsePlan.correction_application_result_usable` (Prompt 574, already
propagated onto `ResponseGenerationContext` by Prompt 575) this decision
is made from - never recomputed, never re-derived from a correction
application result. It is set on EVERY returned decision, used or not,
so the fact "a verified correction application result is available" is
now visible through this existing decision structure without a second
lookup. `False` by default (no plan, a legacy plan built before Prompt
574, or the plan itself says False) - `used` / `reason` / `pattern_id`
and every existing decision, ordinary or correction-related, are
completely unaffected by it.

No second status system
-----------------------
The produced value is an ordinary `ResponseGenerationResult`: status
STATUS_GENERATED, `response_text` = the rendered text exactly,
`backend_kind` = `BACKEND_KIND_LEARNED_RESPONSE` ("learned_response", a new
VALUE of the existing field - the source of the text), `selected_backend_kind`
the same, and small `metadata` (`response_source`, `pattern_id`,
`bound_variables`, `language`, `locale`, `original_message`, the pattern's
`confidence` / `source`). Prompt 428/430/431 therefore derive the usual
SUCCESS outcome, VALID validation and NORMAL `ConversationResponse` from it,
and the source stays distinguishable from a local model (`local_model`), a
deterministic fallback (FALLBACK status / `deterministic_fallback`), a
failure (FAILED) and an unresolved response (UNRESOLVED).
"""

import copy

from .response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_GENERATED,
)
from .response_generation_validation import validate_response_generation_result, VALIDATION_VALID
from .learned_response_pattern_selection import STATUS_RESOLVED as SELECTION_RESOLVED
from .learned_response_pattern_binding import STATUS_RESOLVED as BINDING_RESOLVED
from .learned_response_pattern_rendering import STATUS_RESOLVED as RENDERING_RESOLVED

# The `backend_kind` / `selected_backend_kind` of a result whose text is a
# rendered learned response. (Not a backend: it is deliberately NOT in
# backend.ALL_BACKEND_KINDS, and backend selection never chooses it.)
BACKEND_KIND_LEARNED_RESPONSE = "learned_response"
RESPONSE_SOURCE_LEARNED_RESPONSE = "learned_response"

REASON_USED = "learned_response_used"
REASON_NO_REQUEST = "no_generation_request"
REASON_SELECTION_NOT_RESOLVED = "selection_not_resolved"
REASON_BINDING_NOT_RESOLVED = "binding_not_resolved"
REASON_RENDERING_NOT_RESOLVED = "rendering_not_resolved"
REASON_NO_RENDERED_TEXT = "no_rendered_text"
REASON_PATTERN_MISMATCH = "pattern_mismatch"
REASON_VALIDATION_FAILED = "validation_failed"


class LearnedResponseDecision:
    """Plain, read-only record of one decision: `used`, `reason`,
    `pattern_id` and, when used, the `response`.

    Prompt 576: also carries `correction_application_result_usable` -
    `True` only when the SAME `ResponsePlan` this decision was made
    from already says a verified correction application result is
    usable (`ResponsePlan.correction_application_result_usable`,
    Prompt 574, already forwarded onto `ResponseGenerationContext` by
    Prompt 575). `False` by default (missing plan, legacy plan built
    before Prompt 574, or the plan itself says False) - the exact same
    default `ResponsePlan` and `ResponseGenerationContext` already use.
    This field is purely observational: it never changes `used`,
    `reason` or `pattern_id`, and reading it never applies, re-applies,
    looks up, retrieves or re-selects a correction - the value is read
    directly off the already-computed plan field, never recomputed."""

    def __init__(self, used, reason, response=None, pattern_id=None,
                 correction_application_result_usable=False):
        self.used = bool(used)
        self.reason = reason
        self.response = response
        self.pattern_id = pattern_id
        self.correction_application_result_usable = bool(
            correction_application_result_usable)

    def __repr__(self):
        return (f"LearnedResponseDecision(used={self.used!r}, reason={self.reason!r}, "
                f"pattern_id={self.pattern_id!r}, "
                f"correction_application_result_usable="
                f"{self.correction_application_result_usable!r})")


def _status(section):
    return section.get("status") if isinstance(section, dict) else None


def _correction_application_result_usable_from_plan(response_plan):
    """Prompt 576: reads the ALREADY-COMPUTED
    `correction_application_result_usable` straight off `response_plan`
    (a `ResponsePlan` or its `to_dict()` - the same two shapes every
    other reader in this package already accepts), exactly as it already
    reads on the plan (Prompt 574) - never recomputed, never re-derived
    from a correction application result. `False` for `None`, a legacy
    plan/dict with no such key, or any other shape."""
    if isinstance(response_plan, dict):
        return bool(response_plan.get("correction_application_result_usable"))
    return bool(getattr(response_plan, "correction_application_result_usable", False))


def decide_learned_response(understanding, context=None):
    """The `LearnedResponseDecision` for `understanding`. Pure and
    deterministic: the same input always gives the same decision. Never
    raises for a missing plan / missing sections; never mutates anything.

    Prompt 576: the returned decision's
    `correction_application_result_usable` reflects the SAME
    `response_plan` this decision is made from (see
    `_correction_application_result_usable_from_plan`) on every return
    path, used or not - an existing, already-scoped fact simply exposed
    through this existing decision structure. It does not affect `used`,
    `reason`, `pattern_id` or the response itself; ordinary messages and
    plans built before Prompt 574 behave exactly as before (the field is
    just False)."""
    generation_request = ResponseGenerationRequest(understanding, context=context)
    request = generation_request.generation_request
    correction_usable = _correction_application_result_usable_from_plan(
        generation_request.response_plan)
    if not isinstance(request, dict):
        return LearnedResponseDecision(
            False, REASON_NO_REQUEST,
            correction_application_result_usable=correction_usable)

    selection = request.get("response_pattern_selection")
    binding = request.get("response_pattern_binding")
    rendering = request.get("response_pattern_rendering")
    pattern_id = rendering.get("pattern_id") if isinstance(rendering, dict) else None

    def no(reason):
        return LearnedResponseDecision(
            False, reason, pattern_id=pattern_id,
            correction_application_result_usable=correction_usable)

    if _status(selection) != SELECTION_RESOLVED:
        return no(REASON_SELECTION_NOT_RESOLVED)
    if _status(binding) != BINDING_RESOLVED:
        return no(REASON_BINDING_NOT_RESOLVED)
    if _status(rendering) != RENDERING_RESOLVED:
        return no(REASON_RENDERING_NOT_RESOLVED)
    text = rendering.get("rendered_text")
    if not isinstance(text, str) or not text.strip():
        return no(REASON_NO_RENDERED_TEXT)
    selected = selection.get("selected_pattern")
    if not (pattern_id and pattern_id == binding.get("pattern_id")
            and isinstance(selected, dict) and pattern_id == selected.get("pattern_id")):
        return no(REASON_PATTERN_MISMATCH)

    response = ResponseGenerationResult(
        status=STATUS_GENERATED, response_text=text,
        reason=f"rendered from learned response pattern {pattern_id!r}",
        backend_kind=BACKEND_KIND_LEARNED_RESPONSE,
        selected_backend_kind=BACKEND_KIND_LEARNED_RESPONSE,
        metadata={
            "response_source": RESPONSE_SOURCE_LEARNED_RESPONSE,
            "pattern_id": pattern_id,
            "bound_variables": copy.deepcopy(rendering.get("bound_variables")),
            "language": rendering.get("language"),
            "locale": rendering.get("locale"),
            "original_message": rendering.get("original_message"),
            "pattern_confidence": copy.deepcopy(rendering.get("confidence")),
            "pattern_source": copy.deepcopy(rendering.get("source")),
        })
    validation = validate_response_generation_result(response)
    if validation.status != VALIDATION_VALID:
        return no(REASON_VALIDATION_FAILED)
    return LearnedResponseDecision(
        True, REASON_USED, response=response, pattern_id=pattern_id,
        correction_application_result_usable=correction_usable)
