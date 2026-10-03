"""
Language Intelligence - Backend Interface
=============================================
`LanguageIntelligenceBackend` is the one, small interface every
language-intelligence backend implements - today's deterministic
fallback (deterministic_fallback_backend.py) and, later, a real
on-device/local language model (local_model_backend.py - a stub only,
see that module's own docstring). `LanguageIntelligenceCore`
(language_intelligence_core.py) holds exactly one backend instance and
never calls anything on it beyond the two methods declared here - this
is the whole boundary a future local-model integration needs to fill
in.

    understand(raw_text, context, relevant_context, resolved_reference,
               active_topic, requested_language=None)
               -> LanguageUnderstandingResult

    generate_response(understanding, context) -> ResponseGenerationResult

No cloud provider, API key, network call, or model download is
referenced anywhere in this module - it is a plain Python interface,
nothing more. `backend_kind` is a fixed, small string label (see the
BACKEND_KIND_* constants below) so a caller can tell, from a produced
result's `source_backend` / `backend_kind` field, which backend
actually ran - never inferred from behavior.
"""

BACKEND_KIND_DETERMINISTIC_FALLBACK = "deterministic_fallback"
BACKEND_KIND_LOCAL_MODEL = "local_model"

ALL_BACKEND_KINDS = (BACKEND_KIND_DETERMINISTIC_FALLBACK, BACKEND_KIND_LOCAL_MODEL)


class LanguageIntelligenceBackend:
    """Base interface. Not instantiated directly - both
    DeterministicFallbackBackend and LocalLanguageModelBackend extend
    this and override every method below. Left as plain
    NotImplementedError methods (rather than the `abc` module) to
    match this project's existing convention of small, dependency-free
    base classes.

    `backend_kind` is a read-only property every subclass must
    override with one of the BACKEND_KIND_* constants above - used
    only for labeling produced results, never for branching logic
    inside LanguageIntelligenceCore itself (a caller that wants
    backend-specific behavior should hold a reference to that backend
    directly, not inspect `backend_kind` to decide what to do)."""

    @property
    def backend_kind(self):
        raise NotImplementedError

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        """Return a `LanguageUnderstandingResult`
        (language_understanding_result.py) for `raw_text`.

        `requested_language` (Prompt 401, optional) is a language the
        caller says the reply must be in (a UI setting, an upstream
        parser) - the highest-priority input to the result's
        `language_context.response_language` (see language_context.py).
        `LanguageIntelligenceCore` only passes it when it is not None,
        so a backend written before Prompt 401 keeps working unchanged.

        `context` is a context.conversation_context.ConversationContext
        (or None). `relevant_context` is an already-computed
        context.relevance.RelevantContextResult (or None).
        `resolved_reference` is an already-computed
        context.message_reference_resolution.ResolvedReference (or
        None). `active_topic` is an already-computed
        context.active_topic.ActiveTopicResult (or None). Every one of
        these is accepted, never recomputed a second, competing way -
        see LanguageIntelligenceCore.understand's own docstring for
        why a caller supplies them instead of this method deriving
        them itself."""
        raise NotImplementedError

    def generate_response(self, understanding, context=None, cancellation_token=None,
                          verified_correction_instruction=None):
        """Return a `ResponseGenerationResult`
        (response_generation.py) for an already-produced
        `LanguageUnderstandingResult`. `context` is the same
        ConversationContext `understand()` above accepts.

        `cancellation_token` (Prompt 411, optional) is the existing
        `local_model_runtime.CancellationToken`: a caller that cancels it
        asks a backend that runs a model to stop. A backend that runs no
        inference ignores it. `LanguageIntelligenceCore` only passes it
        when it is not None.

        `verified_correction_instruction` (Prompt 500, optional - a
        `VerifiedCorrectionResponseInstruction`) is likewise only passed
        when a caller supplied one. A backend that responds to text may
        use the corrected target it yields (see
        `LocalLanguageModelBackend`) and reports that through the
        result's `used_verified_correction`; a backend that does not
        simply omits the parameter or ignores it."""
        raise NotImplementedError
