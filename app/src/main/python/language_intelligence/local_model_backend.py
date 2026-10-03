"""
Language Intelligence - Local Language Model Backend
========================================================
Prompt 397 introduced `LocalLanguageModelBackend` as an inert
placeholder. Prompt 398 connects it to a real runtime boundary:

    LanguageIntelligenceCore
      -> LocalLanguageModelBackend                (this module)
        -> LocalModelRuntime                       (local_model_runtime.py)
          -> a concrete runtime's engine hooks     (none installed yet)
            -> the local model                     (none present yet)

With no model configured (the default - `LocalLanguageModelBackend()`
builds an `UnavailableLocalModelRuntime`), the backend reports an
EXPLICIT `STATUS_MODEL_NOT_CONFIGURED`; with a valid configuration but
no engine it reports `STATUS_MODEL_UNAVAILABLE`. It NEVER falls back to
deterministic output and never labels anything it did not get from a
model as model output. The deterministic fallback stays a separate
backend (`DeterministicFallbackBackend`) chosen by whoever constructs
the `LanguageIntelligenceCore` - this class never calls it.

Prompt 400 - provider layer: the backend no longer talks to a runtime
directly. It talks to a `LocalModelProvider` (local_model_provider.py):

    LocalLanguageModelBackend -> LocalModelProvider -> LocalModelRuntime

Passing a `runtime` (the Prompt 398/399 way) still works - it is wrapped in
a `RuntimeBackedProvider`. Passing `provider=` (or building from a
`ProviderRegistry` with `from_registry`) lets a different local model
implementation be swapped in without touching anything above this class.

What is real today (Prompt 398):
  * `generate_response()` builds a real `InferenceRequest` from the
    `LanguageUnderstandingResult` (its `original_input`, optional system
    prompt, and the last few turns of the caller's ConversationContext),
    calls `runtime.generate()`, and maps the `InferenceResult` to a
    `ResponseGenerationResult`: STATUS_GENERATED only for a genuinely
    successful inference; otherwise STATUS_MODEL_NOT_CONFIGURED /
    STATUS_MODEL_UNAVAILABLE / STATUS_MODEL_FAILED with the underlying
    `inference_status` and `error_code` preserved.

Prompt 399 - real backend -> runtime integration:
  * The request/result translation now lives in ONE explicit module,
    `local_model_mapping.py` (build_inference_request /
    map_inference_result). The runtime receives only an InferenceRequest;
    the rest of the application receives only a ResponseGenerationResult
    (now with small, safe `metadata`: model id, runtime name, timing,
    reported token counts).
  * `check_availability()` returns a structured `ModelAvailability`
    (configured / enabled / runtime_available / loadable / loaded /
    can_infer + error code) without loading the model or running anything.
  * `generate_response()` never raises for a runtime problem: a runtime
    that breaks its own contract (raises, or returns a non-result) is
    reported as STATUS_MODEL_FAILED with only the exception TYPE named.
  * Loading stays lazy: constructing the backend, checking availability
    and calling `understand()` never load a model; the first successful
    `generate_response()` does. Nothing is downloaded, no network is used.

What is deliberately NOT implemented yet:
  * `understand()`. Turning a model's output into a
    `LanguageUnderstandingResult` (intent, entities, references,
    confidence) needs a prompt design and a validated structured-output
    mapping - a later stage, once a real model exists to develop it
    against. Until then `understand()` raises:
      - `LocalModelBackendError` when the model cannot be used at all
        (not configured / runtime unavailable / load failed) - carrying
        the same explicit status as above; or
      - `NotImplementedError` when a model IS usable but this mapping
        does not exist yet.
    It never returns a fabricated `LanguageUnderstandingResult`.

Prompt 404 - inference request size control:
  * `generate_response()` now reads the selected provider's OWN
    configured `context_length` / `max_output_tokens` (via the
    provider's existing `resource_status()`) and hands them to
    `build_inference_request`, so the conversation slice it selects is
    sized to what THIS model can actually use, not just a fixed
    ceiling. Nothing is re-declared: with no provider/config yet, the
    same conservative `local_model_config.py` defaults apply that
    `LocalModelRuntime` itself would use.

Prompt 409 - pre-inference readiness guard:
  * `generate_response()` first asks the provider's existing availability
    (the same observation `check_readiness()` summarises). If the answer
    is MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE / MODEL_LOAD_FAILED, the
    provider (and so the runtime) is NOT called: no request is built, no
    load and no inference is attempted, and the block is reported through
    the SAME structured path a runtime failure takes - an
    `InferenceResult` failure with the matching inference status and the
    availability's own error code/message, mapped by
    `map_inference_result` - so Prompt 406's fallback handling applies
    unchanged. MODEL_READY continues to the existing inference path
    exactly as before. If the provider cannot report availability at all
    the guard does not block: the existing path (which already reports a
    provider that breaks its contract) decides. Nothing is retried.

Prompt 410 - local inference resource guard:
  * After the readiness check (which keeps priority) and once the request
    is built, `generate_response()` asks the provider whether the request
    is within the model's configured limits (max output tokens, timeout,
    context length - the runtime's existing checks, now reachable through
    `check_request_limits()` instead of being re-implemented). If a limit
    is exceeded, the provider's `generate()` is NOT called: the existing
    structured `STATUS_RESOURCE_LIMIT` failure is mapped by
    `map_inference_result` exactly like a runtime failure, so Prompt 406's
    fallback applies unchanged. Within limits, the request continues to the
    existing inference path. A provider that cannot answer the question
    does not block; `generate()` still enforces its own limits. Nothing is
    retried, resized or invented.

Prompt 411 - timeout and cancellation:
  * The runtime already enforces the configured (or lower per-request)
    timeout and honours a `CancellationToken` - cooperatively, discarding
    late output - and reports STATUS_TIMEOUT / STATUS_CANCELLED. What was
    missing was a way for a caller to reach it: `generate_response()`
    now takes an optional `cancellation_token` and hands it to the
    provider's `generate()` for the ONE inference of the request. The
    outcome maps like every other runtime failure (`model_failed` with
    inference_status `timeout` / `cancelled`, never text), so Prompt 406's
    fallback applies unchanged. No thread, timer or retry is added here:
    one request = at most one inference.

Prompt 412 - standardized inference result:
  * `inference.InferenceResult` is the one result of every inference attempt
    (nine statuses, error code/message, model/runtime ids, timing, token
    counts, details). Whatever produces the outcome here - the runtime via
    the provider, the readiness guard, the resource guard, or a provider
    that raised / returned a malformed value - `generate_response()` maps a
    valid `InferenceResult` with the one `map_inference_result`, so the
    `ResponseGenerationResult` a caller (and Prompt 406's fallback) sees is
    built the same way on every path, with the failure's error code, message
    and safe scalar details preserved in `metadata`.

Prompt 426 - response generation context:
  * `generate_response()` now also builds the bounded, read-only
    `ResponseGenerationContext` (response_generation_context.py) from
    whatever `ResponsePlan` (Prompt 425) is already attached to
    `understanding`, and hands it to `build_inference_request()`, which
    forwards it unmodified as `InferenceRequest.generation_context` -
    additional structured input next to the existing prompt
    construction. Nothing about model loading, readiness, resource
    guards, timeout/cancellation or fallback selection changes; with no
    plan attached (a caller/test that built the understanding directly)
    this is None and the request is built exactly as before.

Prompt 427 - structured backend generation request:
  * `generate_response()` additionally builds the bounded, read-only
    `BackendGenerationRequest` (response_generation_request.py) -
    exactly `generation_context` above PLUS `understanding.
    learned_sentence_structure` (Prompt 422) - and hands it to
    `build_inference_request()`, which forwards it unmodified as
    `InferenceRequest.generation_request`, alongside the still-present
    `InferenceRequest.generation_context` (Prompt 426, unchanged).
    Nothing about model loading, readiness, resource guards, timeout/
    cancellation or fallback selection changes; with no plan attached
    this is None, same as `generation_context`.

Nothing in Core constructs this backend; Core still uses
`DeterministicFallbackBackend`. Swapping is a one-line construction
change at the call site, not a change to Core/Memory/Context/Planning.
"""

from .backend import LanguageIntelligenceBackend, BACKEND_KIND_LOCAL_MODEL
from .response_generation import (
    ResponseGenerationRequest, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
)
from .local_model_mapping import (
    build_inference_request, map_inference_result, map_runtime_exception,
)
from .response_generation_context import generation_context_from_understanding
from .response_generation_request import (
    build_generation_request, generation_request_from_understanding,
)
from .local_model_runtime import (
    ModelAvailability, STATE_NOT_CONFIGURED, STATE_RUNTIME_UNAVAILABLE, STATE_LOAD_FAILED,
    model_readiness,
)
from .inference import (
    ERROR_INFERENCE_FAILED, InferenceResult, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_RESOURCE_LIMIT as INF_RESOURCE_LIMIT, ERROR_MODEL_FILE_NOT_FOUND,
    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT,
    READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED, READINESS_MODEL_LOAD_FAILED,
)
from .local_model_provider import (
    LocalModelProvider, RuntimeBackedProvider, ModelInfo,
)
from .unavailable_runtime import UnavailableLocalModelRuntime

DEFAULT_MAX_CONTEXT_TURNS = 4

# Prompt 409: two MODEL_UNAVAILABLE causes keep the inference status the
# runtime's own load preflight has always reported for them (a model file
# that is missing = a failed load; one over the declared memory budget = a
# resource limit), so blocking early changes nothing a caller can observe
# except that the runtime is no longer called.
_BLOCK_STATUS_BY_ERROR_CODE = {
    ERROR_MODEL_FILE_NOT_FOUND: INF_LOAD_FAILED,
    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT: INF_RESOURCE_LIMIT,
}

_UNDERSTAND_NOT_IMPLEMENTED_MESSAGE = (
    "Model-driven language understanding is not implemented yet: a local model "
    "is usable, but the mapping from model output to LanguageUnderstandingResult "
    "belongs to a later stage. Use the deterministic fallback backend's "
    "understand() for structured understanding today."
)


class LocalModelBackendError(Exception):
    """Raised by `understand()` when the local model cannot be used at
    all. `status` is a response_generation STATUS_MODEL_* constant;
    `error_code` the runtime's machine-readable code."""

    def __init__(self, status, error_code, message):
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message


class LocalLanguageModelBackend(LanguageIntelligenceBackend):
    def __init__(self, runtime=None, system_prompt=None,
                 max_context_turns=DEFAULT_MAX_CONTEXT_TURNS, generation_parameters=None,
                 timeout_seconds=None, provider=None):
        """`runtime` - a LocalModelRuntime, wrapped in a
        RuntimeBackedProvider. `provider` - a LocalModelProvider used
        as-is. Give at most one; with neither, an unconfigured
        UnavailableLocalModelRuntime is used (=> explicit
        MODEL_NOT_CONFIGURED). `system_prompt` - optional instructions
        sent with every request (None = none; this class invents no
        persona). `max_context_turns` - how many recent
        {"user","assistant"} turns of the caller's context to include
        (0 = none). `generation_parameters` - optional
        GenerationParameters applied to every request. `timeout_seconds`
        - optional per-request time limit; it can only be LOWER than the
        model configuration's own (the runtime enforces that). None =
        use the configured limit."""
        if provider is not None and runtime is not None:
            raise ValueError("give either `runtime` or `provider`, not both")
        if provider is not None:
            if not isinstance(provider, LocalModelProvider):
                raise TypeError("provider must be a LocalModelProvider")
            self._provider = provider
        else:
            self._provider = RuntimeBackedProvider(
                runtime if runtime is not None else UnavailableLocalModelRuntime())
        self._system_prompt = system_prompt
        self._max_context_turns = max_context_turns
        self._generation_parameters = generation_parameters
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_registry(cls, registry, provider_id=None, **kwargs):
        """Build a backend on the provider `registry` selects (the default
        provider when `provider_id` is None). An unknown id raises
        UnknownProviderError; nothing is silently substituted."""
        return cls(provider=registry.select(provider_id), **kwargs)

    @property
    def provider(self):
        return self._provider

    @property
    def runtime(self):
        """The wrapped LocalModelRuntime when the provider is
        runtime-backed, else None (a provider need not have one)."""
        return getattr(self._provider, "runtime", None)

    @property
    def backend_kind(self):
        return BACKEND_KIND_LOCAL_MODEL

    # ------------------------------------------------------------------
    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        availability = self.check_availability()
        state, error_code, message = (availability.state, availability.error_code,
                                      availability.message)
        if state == STATE_NOT_CONFIGURED:
            raise LocalModelBackendError(STATUS_MODEL_NOT_CONFIGURED, error_code, message)
        if state in (STATE_RUNTIME_UNAVAILABLE, STATE_LOAD_FAILED):
            raise LocalModelBackendError(STATUS_MODEL_UNAVAILABLE, error_code, message)
        raise NotImplementedError(_UNDERSTAND_NOT_IMPLEMENTED_MESSAGE)

    def check_availability(self):
        """Structured `ModelAvailability` of the selected provider.
        Read-only: never loads the model, never runs inference. If the
        provider itself breaks its contract the result is an explicit
        "cannot infer" availability, never an exception."""
        try:
            return self._provider.availability()
        except Exception as exc:  # noqa: BLE001 - report, never leak
            return ModelAvailability(
                configured=False, enabled=False, runtime_available=False,
                loadable=False, loaded=False, can_infer=False,
                state=STATE_RUNTIME_UNAVAILABLE, error_code=ERROR_INFERENCE_FAILED,
                message=f"the local model provider could not report availability "
                        f"({type(exc).__name__})")

    def check_readiness(self):
        """Prompt 407: `ModelReadiness` (inference.py) -
        MODEL_READY / MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE /
        MODEL_LOAD_FAILED - summarising `check_availability()`. Cheap,
        read-only and safe to call before every request: it never loads
        the model, never runs inference, never raises."""
        return model_readiness(self.check_availability())

    def model_info(self):
        """`ModelInfo` of the selected provider's model (unknown fields
        stay None). A provider that breaks its contract yields an
        all-unknown ModelInfo, never an exception."""
        try:
            return self._provider.model_info()
        except Exception:  # noqa: BLE001 - report, never leak
            return ModelInfo(provider_id=_safe_provider_id(self._provider))

    def generate_response(self, understanding, context=None, cancellation_token=None,
                          verified_correction_instruction=None):
        # Prompt 500: `verified_correction_instruction` (optional - a
        # VerifiedCorrectionResponseInstruction, Prompt 490). When it
        # yields a selected corrected response target through the
        # existing ResponseGenerationRequest preparation (Prompts
        # 492-497), that target - exactly as selected - is the text the
        # model responds to; no second lookup, matching or correction
        # happens here. Otherwise (absent, unusable, no plan) the request
        # is built exactly as before.
        blocked = self._readiness_block()
        if blocked is not None:
            return blocked
        context_length, max_output_tokens = self._resolved_size_limits()
        # Prompt 426: the bounded, read-only bridge from whatever
        # ResponsePlan LanguageIntelligenceCore already attached to
        # `understanding` (see response_generation_context.py). None
        # when no plan is attached - the request is built exactly as
        # before Prompt 426.
        generation_context = generation_context_from_understanding(understanding)
        # Prompt 427: generation_context above PLUS
        # understanding.learned_sentence_structure - the structured
        # request the model receives instead of needing to know about
        # ResponsePlan/ConversationContext internals itself (see
        # response_generation_request.py). None under the same
        # condition as generation_context above.
        generation_request = generation_request_from_understanding(understanding)
        response_target = None
        if verified_correction_instruction is not None:
            prepared = ResponseGenerationRequest(
                understanding, context=context,
                verified_correction_instruction=verified_correction_instruction)
            response_target = prepared.selected_response_target
            if response_target is not None:
                # the same BackendGenerationRequest, carrying the corrected
                # target as `original_message` and used_verified_correction
                # True (Prompts 497/498)
                generation_request = build_generation_request(prepared.generation_request)
        request = build_inference_request(
            understanding, context, system_prompt=self._system_prompt,
            max_context_turns=self._max_context_turns,
            generation_parameters=self._generation_parameters,
            timeout_seconds=self._timeout_seconds,
            context_length=context_length, max_output_tokens=max_output_tokens,
            generation_context=generation_context, generation_request=generation_request,
            response_target=response_target)
        limited = self._resource_block(request)
        if limited is not None:
            return limited
        # Prompt 500: the corrected target counts as used only once the
        # request carrying it is actually handed to the provider.
        used_correction = response_target is not None
        try:
            if cancellation_token is None:
                result = self._provider.generate(request)
            else:
                result = self._provider.generate(request, cancellation_token)
        except Exception as exc:  # noqa: BLE001 - provider contract is "never raises"
            failure = map_runtime_exception(exc, self.backend_kind)
            failure.used_verified_correction = used_correction
            return failure
        response = map_inference_result(result, self.backend_kind)
        if response.metadata is not None:
            response.metadata["provider_id"] = _safe_provider_id(self._provider)
        response.used_verified_correction = used_correction
        return response

    def not_ready_response(self):
        """Prompt 414: the structured failure `ResponseGenerationResult` for
        a model that is clearly not ready (the Prompt 409 readiness guard's
        own result), or None when inference may proceed. Read-only: never
        loads, never infers, never calls the provider's generate()."""
        return self._readiness_block()

    def _readiness_block(self):
        """Prompt 409: None when inference may proceed; otherwise the
        structured failure `ResponseGenerationResult` for a model that is
        clearly not ready (see the module docstring). Cheap, read-only:
        never loads the model, never calls the provider's generate()."""
        try:
            availability = self._provider.availability()
        except Exception:  # noqa: BLE001 - unknown readiness never blocks
            return None
        readiness = model_readiness(availability)
        if readiness.status == READINESS_MODEL_READY:
            return None
        if readiness.status == READINESS_MODEL_NOT_CONFIGURED:
            status = INF_NOT_CONFIGURED
        elif readiness.status == READINESS_MODEL_LOAD_FAILED:
            status = INF_LOAD_FAILED
        else:
            status = _BLOCK_STATUS_BY_ERROR_CODE.get(readiness.error_code, INF_UNAVAILABLE)
        result = InferenceResult.failure(
            status, readiness.error_code or ERROR_INFERENCE_FAILED,
            readiness.message or readiness.status,
            runtime_name=readiness.runtime_name, model_id=readiness.model_id)
        response = map_inference_result(result, self.backend_kind)
        if response.metadata is not None:
            response.metadata["provider_id"] = _safe_provider_id(self._provider)
        return response

    def _resource_block(self, request):
        """Prompt 410: None when `request` is within the configured limits;
        otherwise the structured RESOURCE_LIMIT failure
        `ResponseGenerationResult`. Read-only: never loads, never infers.
        A provider that cannot answer never blocks."""
        try:
            failure = self._provider.check_request_limits(request)
        except Exception:  # noqa: BLE001 - unknown limits never block
            return None
        if not isinstance(failure, InferenceResult) or failure.ok:
            return None
        response = map_inference_result(failure, self.backend_kind)
        if response.metadata is not None:
            response.metadata["provider_id"] = _safe_provider_id(self._provider)
        return response

    def _resolved_size_limits(self):
        """Prompt 404: the selected provider's OWN configured
        `context_length` / `max_output_tokens` (read once per request
        from the provider's existing `resource_status()` - see
        local_model_provider.py; nothing is re-declared or duplicated
        here), so `build_inference_request` can size the conversation
        slice to what this model can actually use. Read-only and never
        raises: a provider with no config yet, or one that breaks its
        `resource_status()` contract, yields `(None, None)` -
        `build_inference_request` then falls back to
        `local_model_config.py`'s own conservative defaults, exactly as
        the runtime itself would for an unconfigured model."""
        try:
            limits = self._provider.resource_status().get("limits") or {}
        except Exception:  # noqa: BLE001 - a sizing hint only, never fatal
            return None, None
        return limits.get("context_length"), limits.get("max_output_tokens")


def _safe_provider_id(provider):
    try:
        return provider.provider_id
    except Exception:  # noqa: BLE001
        return None
