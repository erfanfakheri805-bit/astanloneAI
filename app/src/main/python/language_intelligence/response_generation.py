"""
Language Intelligence - Structured Response-Generation Result
==================================================================
`ResponseGenerationResult` is the structured object every
`LanguageIntelligenceBackend.generate_response()` call returns (see
backend.py). It exists so the *interface* for "turn an understanding
into a reply" is already fixed and stable before any backend actually
implements real generation - see this package's own module docstring.

Today, exactly one backend exists
(deterministic_fallback_backend.DeterministicFallbackBackend), and it
deliberately does NOT generate reply text itself. Actual reply text
for a conversational turn continues to be produced exactly where it
already is - Core._handle_conversation's own sequence of skills /
learning / reasoning / knowledge-lookup / fallback-construction steps
(core/core.py) - because duplicating that already-working, already-
tested logic inside this new package would be exactly the "second,
disagreeing system" this project's own conventions forbid, and exactly
the kind of "fake intelligence" Prompt 397 explicitly warns against.

So `generate_response()` on the deterministic backend always returns a
result whose `status` is STATUS_DEFERRED: an honest, structured way of
saying "this backend does not generate text; the caller's own existing
pipeline already does." A future local-model backend is the first
backend expected to ever return STATUS_GENERATED with a real
`response_text` - seeing STATUS_DEFERRED anywhere is not an error, it
is the correct, honest answer for every backend that exists today.
"""

from .corrected_response_target_selection import select_corrected_response_target
from .response_generation_context import build_generation_context
from .response_generation_request import generation_request_from_understanding

STATUS_DEFERRED = "deferred_to_existing_pipeline"
STATUS_GENERATED = "generated"
STATUS_NOT_IMPLEMENTED = "not_implemented"

# Added in Prompt 398 (additive - the three statuses above are
# unchanged). Reported ONLY by LocalLanguageModelBackend, and only when
# it could not get real text out of a local model:
#   STATUS_MODEL_NOT_CONFIGURED - no valid, enabled model configuration
#   STATUS_MODEL_UNAVAILABLE    - configured, but no runtime engine is
#                                 available / the model could not be loaded
#   STATUS_MODEL_FAILED         - inference was attempted and failed
#                                 (failure, timeout, cancellation, limit,
#                                 invalid request); see `inference_status`
#                                 / `error_code` for exactly which
# None of these carries `response_text`. They are never substituted with
# deterministic-fallback output.
STATUS_MODEL_NOT_CONFIGURED = "model_not_configured"
STATUS_MODEL_UNAVAILABLE = "model_unavailable"
STATUS_MODEL_FAILED = "model_failed"

ALL_STATUSES = (
    STATUS_DEFERRED, STATUS_GENERATED, STATUS_NOT_IMPLEMENTED,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)

# Prompt 406: the statuses that mean "a local model could not produce the
# reply" (as opposed to DEFERRED / GENERATED / NOT_IMPLEMENTED). The finer
# distinction - not configured / unavailable / load failed / inference
# failed / timeout / cancelled / resource limit / invalid request - is the
# result's `inference_status` (inference.py STATUS_*) plus `error_code`;
# nothing here duplicates it.
MODEL_FAILURE_STATUSES = (
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)


class ResponseGenerationRequest:
    """What a caller hands to `generate_response()` - just the two
    already-existing things it needs: the `LanguageUnderstandingResult`
    to respond to, and the same conversational context object
    (context.conversation_context.ConversationContext) understand()
    calls already accept. A plain holder, not a new subsystem."""

    def __init__(self, understanding, context=None, verified_correction_instruction=None):
        self.understanding = understanding
        self.context = context
        # Prompt 492: the VerifiedCorrectionResponseInstruction (Prompt
        # 490), when a caller explicitly supplies one, or None. Additive
        # and optional - existing callers that omit it are unaffected.
        # Carried through EXACTLY as given: never transformed, normalized,
        # copied into a different structure, or applied to response text
        # here. Deciding when/how this instruction is actually used by
        # response generation is a separate, future, explicitly scoped
        # step.
        self.verified_correction_instruction = verified_correction_instruction

    @property
    def response_plan(self):
        """Prompt 425: the structured `ResponsePlan.to_dict()`
        (response_planning.py) `LanguageIntelligenceCore` attached to
        `understanding`, or None. Read-only: the plan describes what a
        response must contain; it is not response text, and reading it
        changes nothing about how a backend generates."""
        return getattr(self.understanding, "response_plan", None)

    @property
    def generation_context(self):
        """Prompt 426: the structured, bounded
        `ResponseGenerationContext.to_dict()`
        (response_generation_context.py) built from the SAME
        `response_plan` above - read-only input a backend's generation
        path can use, never response text itself. None exactly when
        `response_plan` is None. Building this reads only the plan (plus,
        Prompt 433, `understanding.learned_sentence_structure` when
        present, forwarded into the plan's own `language_guidance` -
        language_guidance.py); it never mutates `understanding`, the
        plan, or anything else, and the same plan always yields an
        independent copy, never a shared mutable reference to the plan
        or understanding.

        Prompt 496: when this request carries a usable
        `verified_correction_instruction`, the returned dict's existing
        `corrected_response_target` key holds its corrected text (see
        `selected_response_target` below); otherwise the dict is
        exactly what it was before.

        Prompt 568: the returned dict's existing
        `correction_application_candidate` key now also reflects
        whatever `understanding.correction_application_candidate`
        (Prompt 470/564, populated on the real conversation path since
        Prompt 567) carries - previously this property always reported
        None for that key even when `understanding` carried a real
        candidate, because this method built the context without
        forwarding it. Still purely informational: it does not apply
        the candidate, does not change `response_action` / guidance /
        selection / binding / rendering, and remains None whenever
        `understanding` carries no candidate.

        Prompt 571: the returned dict's existing
        `correction_application_result` key now also reflects whatever
        `understanding.correction_application_result` (Prompt 474,
        produced by Prompt 570's application operation) carries -
        previously this property always reported None for that key
        even when `understanding` carried a real result, because this
        method built the context without forwarding it. Still purely
        informational: it does not apply the result, does not change
        `response_action` / guidance / selection / binding / rendering,
        and remains None whenever `understanding` carries no result."""
        context = self._generation_context_object()
        if context is None:
            return None
        return context.to_dict()

    @property
    def selected_response_target(self):
        """Prompt 496: the corrected response target text (`str`) the
        response-generation layer should treat as the selected target,
        or None. Read straight off the SAME `ResponseGenerationContext`
        `generation_context` above is built from, through the one
        existing selection operation,
        `select_corrected_response_target()`
        (corrected_response_target_selection.py, Prompt 495) - no second
        selection system. None when there is no plan (so no
        `generation_context`), when `verified_correction_instruction`
        is absent or unusable, or when the target is blank. When
        selected, the text is exactly what the verified instruction
        already carries - never stripped, cased, rewritten, or
        otherwise transformed. Never generates or rewrites response
        text; never mutates the request, `understanding`, or the
        instruction."""
        context = self._generation_context_object()
        if context is None:
            return None
        return select_corrected_response_target(context)

    def _generation_context_object(self):
        """Prompt 496: the `ResponseGenerationContext` (object, not
        dict) `generation_context` and `selected_response_target` are
        both built from - None exactly when `response_plan` is None.
        Built exactly as before (`build_generation_context`); the ONLY
        addition is that, when this request carries a usable verified
        correction instruction, the existing
        `with_corrected_response_target()`
        (corrected_response_target_context.py, Prompt 494) attaches its
        corrected target. "Usable" is decided by the existing
        `select_corrected_response_target()` (Prompt 495) on the
        candidate context: when it selects nothing (no instruction, a
        non-instruction value, or a blank target), the ORIGINAL context
        is returned untouched, so the result is exactly what it was
        before this stage."""
        plan = self.response_plan
        if plan is None:
            return None
        sentence_structure = getattr(self.understanding, "learned_sentence_structure", None)
        # Prompt 568: the existing CorrectionApplicationCandidate (Prompt
        # 470/564/565/567) already attached to `understanding` by Core,
        # when present - carried through unchanged, exactly the same
        # "forward an already-built value, never compute it here" rule
        # `learned_knowledge_context` just below already follows. This is
        # the one field `build_generation_context()` (response_generation_
        # context.py, Prompt 471) already accepts and
        # `generation_context_from_understanding()` already forwards, but
        # that this method itself did not - the smallest missing
        # connection Prompt 568's own audit found. None whenever
        # `understanding` carries no candidate (the common case, and
        # every case before Prompt 567's own wiring existed), so nothing
        # changes for any existing caller. Purely informational: this
        # method still never applies, selects, or decides anything about
        # the candidate.
        # Prompt 501: the learned knowledge Core attached to the
        # understanding (only ever when exactly one entry was directly
        # relevant), carried through unchanged; None otherwise.
        # Prompt 571: the existing CorrectionApplicationResult (Prompt
        # 474/570) already attached to `understanding` by Core, when
        # present - carried through unchanged, the SAME "forward an
        # already-built value, never compute it here" rule
        # `correction_application_candidate` just above already follows.
        # This is the one field `build_generation_context()` already
        # accepts and `generation_context_from_understanding()` already
        # forwards, but that this method itself did not. None whenever
        # `understanding` carries no result, so nothing changes for any
        # existing caller. Purely informational: this method still never
        # applies, selects, or decides anything about the result.
        context = build_generation_context(
            plan, sentence_structure=sentence_structure,
            correction_application_candidate=getattr(
                self.understanding, "correction_application_candidate", None),
            correction_application_result=getattr(
                self.understanding, "correction_application_result", None),
            learned_knowledge_context=getattr(
                self.understanding, "learned_knowledge_context", None))
        if self.verified_correction_instruction is None:
            return context
        # Imported here, not at module top: corrected_response_target_
        # context.py itself imports this module (ResponseGenerationRequest).
        from .corrected_response_target_context import with_corrected_response_target
        candidate = with_corrected_response_target(context, self)
        if select_corrected_response_target(candidate) is None:
            return context
        return candidate

    @property
    def generation_request(self):
        """Prompt 427: the structured, bounded
        `BackendGenerationRequest.to_dict()`
        (response_generation_request.py) - `generation_context` above
        PLUS `understanding.learned_sentence_structure` (Prompt 422),
        the one field `ResponseGenerationContext` does not carry (see
        response_generation_request.py's own module docstring for
        why). None exactly when `response_plan` is None. Available for
        any backend, the deterministic fallback one included -
        reading it never mutates `understanding` or anything it was
        built from, and never requires a backend to use it.

        Prompt 497: when `selected_response_target` is not None, the
        returned dict's existing `original_message` holds that
        corrected target exactly as selected (the uncorrected text
        stays on `understanding` and in `generation_context`'s own
        `original_message`) and `used_verified_correction` is True
        (Prompt 498, observability only); every other key is unchanged.
        Without a selected target `used_verified_correction` is False
        and the rest is exactly what it was before."""
        request = generation_request_from_understanding(self.understanding)
        if request is None:
            return None
        # Prompt 497: when a verified corrected response target is
        # selected (`selected_response_target`, Prompt 496), it is the
        # text this request supplies to response generation - it takes
        # the place of the request's EXISTING `original_message` field
        # (no new input field). Used exactly as selected: never
        # stripped, cased, rewritten, or corrected again. `request` is
        # a freshly built object owned by this call, so nothing the
        # caller holds is mutated. With no selected target the request
        # is exactly what it was before this stage.
        target = self.selected_response_target
        if target is not None:
            request.original_message = target
            # Prompt 498: record that the corrected target was actually
            # used as the input (observability only - no text changes).
            request.used_verified_correction = True
        return request.to_dict()

    def __repr__(self):
        return f"ResponseGenerationRequest(understanding={self.understanding!r})"


class ResponseGenerationResult:
    """`response_text` is None whenever `status` is not STATUS_GENERATED -
    same "never a value unless the status says so" rule ReasoningResult
    already applies to its own `answer` field. `reason` is a short,
    human-readable explanation of the status (never blank)."""

    def __init__(self, status, response_text=None, reason="", backend_kind=None,
                 inference_status=None, error_code=None, metadata=None,
                 fallback_backend_kind=None, selected_backend_kind=None,
                 used_verified_correction=False):
        self.status = status
        self.response_text = response_text
        self.reason = reason
        self.backend_kind = backend_kind
        # Prompt 398: the underlying inference.InferenceResult.status /
        # error_code when a local model was involved; None otherwise.
        self.inference_status = inference_status
        self.error_code = error_code
        # Prompt 399 (additive): small, safe runtime metadata when a local
        # model was involved - model_id, runtime_name, request_id,
        # elapsed_seconds, prompt_tokens, output_tokens, finish_reason
        # (see local_model_mapping.result_metadata). None otherwise; the
        # deterministic backend never sets it.
        self.metadata = dict(metadata) if metadata else None
        # Prompt 406: set by LanguageIntelligenceCore ONLY on a model
        # failure (status in MODEL_FAILURE_STATUSES) when it was given a
        # fallback backend: the `backend_kind` of the backend that handles
        # the request instead. It never turns the failure into a success -
        # `status`, `inference_status` and `error_code` still describe what
        # the local model did, `response_text` stays None, and `backend_kind`
        # still names the backend that failed. None otherwise.
        self.fallback_backend_kind = fallback_backend_kind
        # Prompt 414: set by LanguageIntelligenceCore - the BACKEND_KIND_* the
        # backend selection chose for this request (local_model when the model
        # was ready; deterministic_fallback when it was not and a fallback
        # backend is configured). None on a result no core has routed.
        self.selected_backend_kind = selected_backend_kind
        # Prompt 500: True only when the backend that produced this
        # result actually used a verified corrected response target as the
        # text it responded to (LocalLanguageModelBackend, when it handed
        # the corrected target to the model). False otherwise (default) -
        # including when a correction was supplied but not used. Never
        # changes `response_text` or any other field. Additive.
        self.used_verified_correction = bool(used_verified_correction)

    @property
    def is_generated(self):
        """Prompt 413: True only for real, usable model output - status
        STATUS_GENERATED with a non-empty `response_text`. The one test
        the conversation path uses to decide "this text is the reply"."""
        return (self.status == STATUS_GENERATED and isinstance(self.response_text, str)
                and bool(self.response_text.strip()))

    @property
    def needs_fallback(self):
        """Prompt 413: True when a local model could not produce the reply
        (status in MODEL_FAILURE_STATUSES - see `inference_status` /
        `error_code` for which failure). Distinct from STATUS_DEFERRED
        ("this backend never generates text") and from a generated reply.
        The failure itself is never changed into text; the existing
        deterministic pipeline (and Prompt 406's fallback backend) answers."""
        return self.status in MODEL_FAILURE_STATUSES

    def __repr__(self):
        return (
            f"ResponseGenerationResult(status={self.status!r}, "
            f"backend_kind={self.backend_kind!r})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "response_text": self.response_text,
            "reason": self.reason,
            "backend_kind": self.backend_kind,
            "inference_status": self.inference_status,
            "error_code": self.error_code,
            "metadata": dict(self.metadata) if self.metadata else None,
            "fallback_backend_kind": self.fallback_backend_kind,
            "selected_backend_kind": self.selected_backend_kind,
            "used_verified_correction": self.used_verified_correction,
        }
