"""
Language Intelligence - Local Model Request/Result Mapping
==============================================================
Prompt 399. The ONE place where the language-intelligence layer and the
local-model runtime layer are translated into each other. Keeping the
mapping here (pure functions, no state, no I/O) means:

  * the runtime only ever receives an `inference.InferenceRequest` - the
    text to respond to, an optional system prompt, a few recent turns,
    optional generation parameters and (Prompt 401) the message's
    LanguageContext. It never sees a
    `LanguageUnderstandingResult`, a `ConversationContext`, or anything
    else from the application;
  * the rest of the application only ever receives a
    `response_generation.ResponseGenerationResult` - it never sees an
    `InferenceResult`, a runtime exception, or an engine detail.

    LanguageUnderstandingResult + ConversationContext
        -> build_inference_request(...)    -> InferenceRequest
        -> LocalModelRuntime.generate(...) -> InferenceResult
        -> map_inference_result(...)       -> ResponseGenerationResult

Status mapping (inference status -> response status):

    success              -> generated               (the ONLY path to text)
    model_not_configured -> model_not_configured
    model_unavailable    -> model_unavailable
    model_load_failed    -> model_unavailable
    inference_failed     -> model_failed
    invalid_request      -> model_failed
    resource_limit       -> model_failed
    timeout              -> model_failed
    cancelled            -> model_failed
    anything else        -> model_failed            (never guessed as success)

The original `inference_status` and `error_code` are always preserved on
the result, so a caller can still tell a timeout from a resource limit.

Nothing here can invent output: `response_text` is set only when the
runtime reported STATUS_SUCCESS with a real, non-empty string.

Safe error information: failure `reason` strings come from the runtime's
own translated messages. When the runtime itself misbehaves (raises, or
returns something that is not an InferenceResult), only the exception's
TYPE NAME is reported - never its message, arguments or traceback.

Prompt 404 - inference request size control:
`build_inference_request` now ties the conversation slice it selects to
the MODEL'S OWN configured `context_length` / `max_output_tokens`
(`local_model_config.py`, Prompts 398/401) instead of only the fixed
Prompt-403 ceiling. The two optional `context_length`/`max_output_tokens`
parameters are the SAME numbers `LocalModelRuntime.generate()` already
enforces (see local_model_runtime.py step 3) - callers (in practice
`LocalLanguageModelBackend.generate_response`, via the selected
provider's existing `resource_status()`) pass them straight through;
nothing here re-declares or re-validates a model configuration.

What changes when the budget is tight, in this exact order (never any
other order):
  1. `user_input` - never touched, never dropped, always sent complete.
  2. `system_prompt` / `language_context` - always sent complete; their
     size is *counted* against the budget but they are never trimmed or
     removed here (this module invents no "drop the instructions"
     policy - a caller that wants that decides it upstream).
  3. the most relevant selected turns (`context/relevance.py`'s own
     ranking - shared terms/names, message-final references) are kept
     first, using the SAME `select_bounded_context` narrowing Prompt
     403 introduced.
  4. a turn kept for an active-topic/reference match is exactly a
     highly-ranked turn from #3 above - see
     `context/relevance.py:select_bounded_context`'s own docstring.
  5. the oldest / least-relevant turns are dropped first when the
     budget still will not fit everything.

Prompt 405 - compact conversation state:
when the understanding carries a `conversation_state`
(context/conversation_state.py - earlier topics, explicit preferences,
unresolved references), only the part relevant to THIS message
(`select_relevant_state`) is rendered as one short system message placed
before the turns. It is tier 2b of the order above - after
`user_input`/`system_prompt`/`language_context`, before the turns - and
is charged against the SAME budget: it may use at most half of it, and
what it uses is deducted from what the turns may use. With no room, no
state is sent; with no state, nothing here changes. It reuses the
Prompt-403 selection module and the Prompt-404 budget - there is no
separate selection pipeline or size limit for it.

If steps 2-5 still leave no room at all for prior turns, the
conversation is simply empty (`max_turns=0`-equivalent) - construction
NEVER shrinks, rewrites or drops `user_input` to make room. When even
`user_input` alone will not fit the model's context window, this
function still builds the (honest, unmodified) request; it is
`LocalModelRuntime.generate()` - already checking this before any model
load - that reports it as the structured `STATUS_RESOURCE_LIMIT` /
`ERROR_CONTEXT_LENGTH_EXCEEDED` failure. No new failure path, no crash,
no fabricated text, and no repeated retry-with-random-truncation is
introduced here.
"""

import math

from .inference import (
    InferenceRequest, InferenceResult, ConversationMessage, ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM,
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
    STATUS_MODEL_LOAD_FAILED, STATUS_INFERENCE_FAILED,
    ERROR_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT,
    standardize_inference_result, inference_failure_from_exception,
)
from context.relevance import (
    select_bounded_context, DEFAULT_FOCUSED_MAX_TURNS, DEFAULT_FOCUSED_MAX_CHARS,
)
from context.conversation_state import (
    select_relevant_state, format_state_text, DEFAULT_STATE_MAX_CHARS,
)
from .local_model_config import DEFAULT_CONTEXT_LENGTH, DEFAULT_MAX_OUTPUT_TOKENS
from .local_model_runtime import _CHARS_PER_TOKEN_ESTIMATE, _PER_MESSAGE_OVERHEAD_TOKENS
from .response_generation import (
    ResponseGenerationResult, STATUS_GENERATED,
    STATUS_MODEL_NOT_CONFIGURED as RESPONSE_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as RESPONSE_UNAVAILABLE,
    STATUS_MODEL_FAILED as RESPONSE_FAILED,
)


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def resolve_request_size_limits(context_length=None, max_output_tokens=None):
    """Resolve the two runtime-configured limits request construction
    needs in order to size the conversation slice sensibly: the
    model's `context_length` and `max_output_tokens`
    (local_model_config.py, Prompts 398/401 - the SAME fields
    LocalModelRuntime.generate() itself enforces).

    Never raises and never invents a large number: an unknown/invalid
    value (None, or anything that is not a positive int) falls back to
    local_model_config.py's own conservative, phone-class defaults
    (`DEFAULT_CONTEXT_LENGTH`, `DEFAULT_MAX_OUTPUT_TOKENS`) - the exact
    numbers a `LocalModelConfig` itself defaults to, not a new ceiling
    invented here. If the two values would leave no room for a prompt
    at all (`max_output_tokens >= context_length` - the same invariant
    `LocalModelConfig.validate()` requires), `max_output_tokens` is
    clamped down just far enough to leave at least one token of
    prompt room for the *sizing calculation* below; the real values are
    still sent to the runtime unchanged and it is the runtime's own
    check that has the final say."""
    resolved_context_length = (
        context_length if _is_positive_int(context_length) else DEFAULT_CONTEXT_LENGTH
    )
    resolved_max_output_tokens = (
        max_output_tokens if _is_positive_int(max_output_tokens) else DEFAULT_MAX_OUTPUT_TOKENS
    )
    if resolved_max_output_tokens >= resolved_context_length:
        resolved_max_output_tokens = max(0, resolved_context_length - 1)
    return resolved_context_length, resolved_max_output_tokens


def conversation_char_budget(user_input, system_prompt, context_length,
                             max_output_tokens, max_turns):
    """How many characters of PRIOR conversation (context-priority
    tiers 3-5 - see this module's docstring) may still be added on top
    of the current user message and system/language instructions
    (tiers 1-2, always sent in full) without the ESTIMATED prompt size,
    plus the reserved output budget, exceeding `context_length`.

    Uses the exact same rough char-per-token estimate
    `LocalModelRuntime._estimate_prompt_tokens` uses (imported, not
    duplicated - see local_model_runtime.py's own module docstring for
    why a real tokenizer is out of scope here), so a request bounded to
    fit this budget agrees with what the runtime will independently
    re-check before it loads any model. Deliberately conservative
    (reserves per-message overhead for every turn that MIGHT still be
    added, before any are chosen) - never negative; 0 means no room is
    left for any prior turn at all, which is a normal, valid outcome,
    not an error."""
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        return 0
    fixed_messages = 1 + (1 if system_prompt else 0)  # user message + optional system prompt
    fixed_chars = len(user_input or "") + len(system_prompt or "")
    fixed_tokens = (
        math.ceil(fixed_chars / _CHARS_PER_TOKEN_ESTIMATE)
        + fixed_messages * _PER_MESSAGE_OVERHEAD_TOKENS
    )
    available_for_prompt = context_length - max_output_tokens
    # Reserve the per-message overhead of every turn (user + assistant)
    # that might still be selected, up front, before any text budget.
    reserved_turn_overhead = max_turns * 2 * _PER_MESSAGE_OVERHEAD_TOKENS
    remaining_tokens = available_for_prompt - fixed_tokens - reserved_turn_overhead
    if remaining_tokens <= 0:
        return 0
    return remaining_tokens * _CHARS_PER_TOKEN_ESTIMATE

# Explicit inference-status -> response-status table (see docstring).
# Any status not listed maps to RESPONSE_FAILED.
INFERENCE_TO_RESPONSE_STATUS = {
    STATUS_MODEL_NOT_CONFIGURED: RESPONSE_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE: RESPONSE_UNAVAILABLE,
    STATUS_MODEL_LOAD_FAILED: RESPONSE_UNAVAILABLE,
}


def build_inference_request(understanding, context=None, system_prompt=None,
                            max_context_turns=0, generation_parameters=None,
                            timeout_seconds=None, max_context_chars=DEFAULT_FOCUSED_MAX_CHARS,
                            context_length=None, max_output_tokens=None,
                            generation_context=None, generation_request=None,
                            response_target=None):
    """Build the `InferenceRequest` the runtime needs for one response.

    Only these things cross the boundary: the understanding's
    `original_input` (verbatim - never the normalized text, and never
    altered by context selection below), the optional `system_prompt`,
    a small, focused slice of prior conversation (see
    `focused_conversation_from_context` below), the optional generation
    parameters, an optional per-request timeout, and (Prompt 401) the
    understanding's `language_context`, forwarded untouched as a
    separate field. The mapping neither builds language instructions
    into the prompt nor alters the text according to the language; a
    understanding without a language context yields a request without
    one. A bad `understanding` (None, no text) does not
    raise here - it yields a request the runtime rejects as
    STATUS_INVALID_REQUEST, so the failure is reported in the normal
    structured way.

    `max_context_chars` (Prompt 403) is the fixed, small CEILING on the
    conversation slice - it never grows. `context_length` /
    `max_output_tokens` (Prompt 404, both optional) are the model's own
    configured limits (the same ones `LocalModelRuntime.generate()`
    enforces - see `resolve_request_size_limits`); when given, the
    conversation slice is bounded further, to whichever of the fixed
    ceiling or the model's real remaining room is SMALLER
    (`conversation_char_budget`) - so a small-context model gets a
    correspondingly smaller slice instead of one sized for a ceiling it
    can never actually fit. Limits are only ever narrowed here, never
    invented or enlarged. See this module's own docstring for the exact
    context-priority order this narrowing follows, and
    context/relevance.py:select_bounded_context /
    `focused_conversation_from_context` below for what it does and why
    a plain character count (no tokenizer) is enough here.

    `generation_context` (Prompt 426, optional) is an already-built
    `response_generation_context.ResponseGenerationContext` - typically
    `response_generation_context.generation_context_from_understanding
    (understanding)`, built from the `ResponsePlan` (Prompt 425)
    already attached to `understanding` - forwarded to the resulting
    `InferenceRequest.generation_context` unmodified. It is additional
    structured input next to the prompt this function already builds;
    nothing about the sizing/selection above changes because of it, and
    it is never counted against the character budget (it is not text).

    `generation_request` (Prompt 427, optional) is an already-built
    `response_generation_request.BackendGenerationRequest` - typically
    `response_generation_request.generation_request_from_understanding
    (understanding)`, which is exactly `generation_context` above plus
    `understanding.learned_sentence_structure` (Prompt 422) - forwarded
    to `InferenceRequest.generation_request` unmodified. Same rules as
    `generation_context`: additional structured input, never counted
    against the character budget, never required.

    `response_target` (Prompt 500, optional) is the verified corrected
    response target (`ResponseGenerationRequest.selected_response_target`)
    a caller already selected. When it is not None it is the text the
    request responds to (`InferenceRequest.user_input`), used EXACTLY as
    given - never normalized, rewritten or corrected again - in place of
    the understanding's `original_input`, and the sizing below is done
    for that text. When None (the default) the request is built exactly
    as before."""
    user_input = (response_target if response_target is not None
                  else getattr(understanding, "original_input", None))
    resolved_context_length, resolved_max_output_tokens = resolve_request_size_limits(
        context_length, max_output_tokens)
    budget_chars = conversation_char_budget(
        user_input, system_prompt, resolved_context_length, resolved_max_output_tokens,
        max_context_turns)
    effective_max_chars = (
        min(max_context_chars, budget_chars)
        if isinstance(max_context_chars, (int, float)) and not isinstance(max_context_chars, bool)
        else budget_chars
    )
    state_messages, turn_max_turns, turn_max_chars = _fit_conversation_state(
        understanding, user_input, effective_max_chars, max_context_turns)
    if effective_max_chars <= 0:
        # No room at all (see module docstring, Prompt 404): no prior turns.
        # select_bounded_context reads a 0-character limit as "no limit", so
        # the empty conversation is requested explicitly.
        turn_max_turns = 0
    return InferenceRequest(
        user_input=user_input,
        system_prompt=system_prompt,
        conversation=state_messages + focused_conversation_from_context(
            understanding, context, turn_max_turns, turn_max_chars),
        parameters=generation_parameters,
        timeout_seconds=timeout_seconds,
        language_context=getattr(understanding, "language_context", None),
        generation_context=generation_context,
        generation_request=generation_request,
    )


_STATE_MESSAGE_OVERHEAD_CHARS = _PER_MESSAGE_OVERHEAD_TOKENS * _CHARS_PER_TOKEN_ESTIMATE


def _fit_conversation_state(understanding, user_input, max_chars, max_turns):
    """Prompt 405: `(state_messages, turns_max_turns, turns_max_chars)`.

    Renders the part of `understanding.conversation_state` relevant to
    `user_input` (context/conversation_state.py) as at most one system
    message, inside `max_chars` - the SAME character ceiling (Prompt
    403 ceiling narrowed by Prompt 404's budget) the turns are bound
    by. The state may use at most half of it (its per-message overhead
    included) and whatever it uses is deducted from what the turns may
    use, so the total never exceeds the ceiling. If the state leaves no
    room for turns, none are selected. Without a state, with nothing
    relevant in it, or with no room, this returns `([], max_turns,
    max_chars)` - the request is exactly what it was before Prompt
    405. Pure; never raises."""
    state = getattr(understanding, "conversation_state", None)
    if not state or not isinstance(max_chars, (int, float)) or isinstance(max_chars, bool):
        return [], max_turns, max_chars
    ceiling = min(DEFAULT_STATE_MAX_CHARS, (max_chars // 2) - _STATE_MESSAGE_OVERHEAD_CHARS)
    text = format_state_text(select_relevant_state(state, user_input), ceiling)
    if not text:
        return [], max_turns, max_chars
    remaining = max_chars - len(text) - _STATE_MESSAGE_OVERHEAD_CHARS
    if remaining <= 0:
        return [ConversationMessage(ROLE_SYSTEM, text)], 0, 0
    return [ConversationMessage(ROLE_SYSTEM, text)], max_turns, remaining


def focused_conversation_from_context(understanding, context, max_turns,
                                      max_chars=DEFAULT_FOCUSED_MAX_CHARS):
    """Prompt 403: the actual conversation history sent to the model
    for one request - the most relevant recent turns for THIS message,
    never blindly the whole conversation.

    When `understanding` already carries a relevance-selected
    `conversation_context` (populated by the real Core conversation
    path - see core/core.py's `_handle_conversation` step "1c", which
    passes it through context/relevance.py's existing
    `select_relevant_turns`, reused here unchanged), this narrows that
    exact selection with context/relevance.py's `select_bounded_context`
    - no second relevance computation, no new memory system. Falls back
    to the previous, blind "last `max_turns` turns" window
    (`conversation_from_context`, unchanged below) only when no such
    relevance-selected context is available (e.g. a caller/test that
    built a `LanguageUnderstandingResult` directly, without going
    through Core's real conversation path) - so every existing caller
    of this function keeps working exactly as before Prompt 403.

    Never touches `understanding.original_input` - this only ever
    selects SUPPORTING prior turns, never the current message itself."""
    relevant = getattr(understanding, "conversation_context", None)
    if not relevant:
        return conversation_from_context(context, max_turns)
    focused_turns = select_bounded_context(relevant, max_turns=max_turns, max_chars=max_chars)
    messages = []
    for turn in focused_turns:
        messages.append(ConversationMessage(ROLE_USER, turn["user"]))
        messages.append(ConversationMessage(ROLE_ASSISTANT, turn["assistant"]))
    return messages


def conversation_from_context(context, max_turns):
    """Recent turns of a ConversationContext as ConversationMessages,
    blind to relevance - the pre-Prompt-403 behavior, kept unchanged
    and still used as the fallback in `focused_conversation_from_context`
    above when no relevance-selected context is available. Read-only:
    never writes to `context`. Malformed turns are skipped."""
    getter = getattr(context, "get_recent_turns", None)
    if getter is None or not isinstance(max_turns, int) or isinstance(max_turns, bool) \
            or max_turns < 1:
        return []
    messages = []
    for turn in getter(max_turns):
        if not isinstance(turn, dict):
            continue
        user_text, assistant_text = turn.get("user"), turn.get("assistant")
        if isinstance(user_text, str) and isinstance(assistant_text, str):
            messages.append(ConversationMessage(ROLE_USER, user_text))
            messages.append(ConversationMessage(ROLE_ASSISTANT, assistant_text))
    return messages


def result_metadata(result):
    """Small, safe metadata dict from an InferenceResult: identifiers,
    timing and token counts the runtime really reported (None stays
    None - never invented). No raw details, no prompt/response text."""
    return {
        "model_id": getattr(result, "model_id", None),
        "runtime_name": getattr(result, "runtime_name", None),
        "request_id": getattr(result, "request_id", None),
        "elapsed_seconds": round(getattr(result, "elapsed_seconds", 0.0) or 0.0, 4),
        "prompt_tokens": getattr(result, "prompt_tokens", None),
        "output_tokens": getattr(result, "output_tokens", None),
        "finish_reason": getattr(result, "finish_reason", None),
    }


_MAX_DETAIL_TEXT = 200
_UNSAFE_DETAIL_KEYS = ("output_preview",)


def failure_details(result):
    """Prompt 412: the scalar entries of a failed `InferenceResult.details`
    (e.g. `requested` / `limit` / `context_length` of a resource-limit
    failure) - useful error information the fallback decision or a log can
    use. Lists, nested values and model output (`output_preview`) are left
    out; long strings are cut. Empty dict when there is nothing to keep."""
    details = getattr(result, "details", None)
    if not isinstance(details, dict):
        return {}
    kept = {}
    for key, value in details.items():
        if not isinstance(key, str) or key in _UNSAFE_DETAIL_KEYS:
            continue
        if isinstance(value, str):
            kept[key] = value[:_MAX_DETAIL_TEXT]
        elif isinstance(value, (int, float, bool)):
            kept[key] = value
    return kept


def map_inference_result(result, backend_kind):
    """Convert a runtime `InferenceResult` into a `ResponseGenerationResult`.
    Prompt 412: the value is first standardized (inference.py
    `standardize_inference_result`), so a bad runtime value - wrong type,
    unknown status, success without text - is one structured
    STATUS_INFERENCE_FAILED / ERROR_INVALID_RUNTIME_OUTPUT failure, and
    everything below only ever sees a valid `InferenceResult`."""
    result = standardize_inference_result(result)

    if result.status == STATUS_SUCCESS:
        return ResponseGenerationResult(
            status=STATUS_GENERATED, response_text=result.text,
            reason=f"generated by local model {result.model_id!r} "
                   f"via runtime {result.runtime_name!r}",
            backend_kind=backend_kind, inference_status=result.status,
            metadata=result_metadata(result),
        )

    metadata = result_metadata(result)
    details = failure_details(result)
    if details:
        metadata["details"] = details
    return ResponseGenerationResult(
        status=INFERENCE_TO_RESPONSE_STATUS.get(result.status, RESPONSE_FAILED),
        response_text=None,
        reason=result.error_message or str(result.status),
        backend_kind=backend_kind, inference_status=result.status,
        error_code=result.error_code, metadata=metadata,
    )


def map_runtime_misbehavior(backend_kind, error_code, reason, inference_status=None,
                            metadata=None):
    """A failure of the runtime CONTRACT itself (it raised, or returned
    the wrong type) - always a model failure, never text."""
    return ResponseGenerationResult(
        status=RESPONSE_FAILED, response_text=None, reason=reason,
        backend_kind=backend_kind,
        inference_status=inference_status or STATUS_INFERENCE_FAILED,
        error_code=error_code, metadata=metadata,
    )


def map_runtime_exception(exc, backend_kind):
    """`LocalModelRuntime.generate()` is contractually non-raising; if a
    runtime raises anyway, report only the exception type name (as the
    same structured failure `inference_failure_from_exception` builds)."""
    return map_inference_result(inference_failure_from_exception(exc), backend_kind)
