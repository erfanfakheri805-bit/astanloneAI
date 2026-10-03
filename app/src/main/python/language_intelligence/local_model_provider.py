"""
Language Intelligence - Local Model Provider (adapter layer)
=================================================================
Prompt 400. `LocalModelProvider` is the small, replaceable seam between
the language layer and whatever local model implementation is behind it:

    LanguageIntelligenceCore
      -> LocalLanguageModelBackend        (local_model_backend.py)
        -> LocalModelProvider             (THIS module - replaceable)
          -> LocalModelRuntime            (local_model_runtime.py)
            -> the actual local model     (none installed yet)

Adding a second/specialized/lightweight local model later means writing
one more provider (usually just a `RuntimeBackedProvider` around another
`LocalModelRuntime`) and registering it in a `ProviderRegistry`. Nothing
above the backend - LanguageIntelligenceCore, Memory, Context, Knowledge,
Reasoning, Planning, Execution, the Agent Loop - changes.

Result contract (deliberately NOT duplicated here): a provider returns
the runtime layer's existing structured types, which already
distinguish every state the language layer needs -

    availability()  -> local_model_runtime.ModelAvailability
    load()          -> local_model_runtime.ModelLoadResult
    generate()      -> inference.InferenceResult, whose `status` is one of
                       success / model_not_configured / model_unavailable /
                       model_load_failed / inference_failed / timeout /
                       cancelled / resource_limit / invalid_request, with a
                       machine-readable `error_code`

`ModelInfo` (below) is the one new data shape: honest metadata about the
model behind a provider. Anything not actually known is `None`
(unknown) - never guessed - and a provider with no configured model
reports `model_id=None`.

Prompt 401 adds the language capability fields to ModelInfo
(supported_languages, supported_scripts, multilingual, default_language).
They are declared by the model's configuration (LocalModelConfig) or by a
custom provider; unless declared they stay None, and
`ModelInfo.supports_language()` reports None (unknown) rather than True.

`RuntimeBackedProvider` is a pure delegate to a `LocalModelRuntime`: it
adds no limits, no state and no text of its own. There is no fake model,
cloud call, or download anywhere in this module.
"""

from .language_context import canonical_language
from .local_model_runtime import ModelAvailability, ModelLoadResult
from .inference import standardize_inference_result, inference_failure_from_exception


class ProviderRegistryError(Exception):
    """Registration/selection problem (duplicate id, nothing to select)."""


class UnknownProviderError(ProviderRegistryError, LookupError):
    """`provider_id` is not registered."""

    def __init__(self, provider_id, known_ids=()):
        super().__init__(f"unknown local model provider {provider_id!r}; "
                         f"registered: {list(known_ids)}")
        self.provider_id = provider_id


class ModelInfo:
    """What is known about the model behind a provider. `None` means
    UNKNOWN (or, for `model_id`, "no model configured").

        provider_id         which provider reports this
        model_id            configured model label, else None
        model_format        configured format label, else None
        supported_languages tuple of language codes/names the provider
                            DECLARES the model supports, else None
                            (unknown). Never guessed or inferred here.
        supported_scripts   tuple of scripts ("arabic", "latin", ...) the
                            provider declares, else None (unknown)
        multilingual        True / False if the provider declares it,
                            else None (unknown). Says nothing about any
                            particular language.
        default_language    the model's declared preferred language, else
                            None (unknown)
        context_length      configured token window, else None
        max_output_tokens   configured output cap, else None
        is_local            True: this provider runs on-device only
                            (remote/cloud providers are not supported)
        loaded              the model is loaded right now
        runtime_name        the engine label behind the provider, if any

    Language capabilities are DECLARATIONS made by whoever configures the
    model or writes the provider (Prompt 401); this project never infers
    or verifies them. `supports_language()` therefore answers True only
    for a declared language and None (unknown) when nothing was declared -
    a model is never reported as supporting Persian unless its
    provider/configuration says so.
    """

    def __init__(self, provider_id, model_id=None, model_format=None,
                 supported_languages=None, context_length=None,
                 max_output_tokens=None, is_local=True, loaded=False, runtime_name=None,
                 supported_scripts=None, multilingual=None, default_language=None):
        self.provider_id = provider_id
        self.model_id = model_id
        self.model_format = model_format
        self.supported_languages = (tuple(supported_languages)
                                    if supported_languages is not None else None)
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens
        self.is_local = is_local
        self.loaded = loaded
        self.runtime_name = runtime_name
        self.supported_scripts = (tuple(supported_scripts)
                                  if supported_scripts is not None else None)
        self.multilingual = multilingual
        self.default_language = default_language

    def supports_language(self, language):
        """True if `language` is among the DECLARED supported languages
        (codes and names compare equal: "fa" == "persian"), False if a
        list was declared and it does not include it, None (unknown) if
        no list was declared or `language` names no language."""
        wanted = canonical_language(language)
        if wanted is None or self.supported_languages is None:
            return None
        return wanted in {canonical_language(item) for item in self.supported_languages}

    def supports_script(self, script):
        """Like `supports_language`, for a script name ("arabic", "latin")."""
        if not isinstance(script, str) or not script.strip() or self.supported_scripts is None:
            return None
        return script.strip().lower() in {str(item).strip().lower()
                                          for item in self.supported_scripts}

    def __repr__(self):
        return (f"ModelInfo(provider_id={self.provider_id!r}, model_id={self.model_id!r}, "
                f"loaded={self.loaded!r})")

    def to_dict(self):
        return {
            "provider_id": self.provider_id, "model_id": self.model_id,
            "model_format": self.model_format,
            "supported_languages": list(self.supported_languages)
            if self.supported_languages is not None else None,
            "context_length": self.context_length,
            "max_output_tokens": self.max_output_tokens,
            "is_local": self.is_local, "loaded": self.loaded,
            "runtime_name": self.runtime_name,
            "supported_scripts": list(self.supported_scripts)
            if self.supported_scripts is not None else None,
            "multilingual": self.multilingual,
            "default_language": self.default_language,
        }


class LocalModelProvider:
    """Interface every local model provider implements (plain
    NotImplementedError methods, like the project's other base classes)."""

    @property
    def provider_id(self):
        """Short, stable, unique label (the registry key)."""
        raise NotImplementedError

    def availability(self):
        """Read-only `ModelAvailability`. Must not load the model."""
        raise NotImplementedError

    def model_info(self):
        """Read-only `ModelInfo`. Must not load the model."""
        raise NotImplementedError

    def load(self):
        """Load the model now; return a `ModelLoadResult`. Never raises
        for a model problem."""
        raise NotImplementedError

    def generate(self, request, cancellation_token=None):
        """Run one inference; ALWAYS return an `inference.InferenceResult`
        (a typed failure, never an exception or substitute text)."""
        raise NotImplementedError

    def unload(self):
        """Release the model if this provider supports it. Returns True
        when it unloaded, False when unloading is unsupported."""
        return False

    def resource_status(self):
        """Read-only plain dict: {"state", "loaded", "limits"}, where
        `limits` is a dict of the configured resource limits or None if
        none are configured."""
        raise NotImplementedError

    def check_request_limits(self, request):
        """Prompt 410: None if `request` is within this provider's
        configured limits, else the `STATUS_RESOURCE_LIMIT`
        `InferenceResult` generate() would return. Read-only; never loads
        or infers. Optional: the default (None) means "no opinion" and
        leaves limit enforcement to generate(), as before."""
        return None


class RuntimeBackedProvider(LocalModelProvider):
    """Provider that delegates every operation to one `LocalModelRuntime`.
    Adds nothing of its own - limits, state, timeout and cancellation
    stay enforced once, in the runtime."""

    def __init__(self, runtime, provider_id=None):
        """`provider_id` defaults to the runtime's `runtime_name`."""
        self._runtime = runtime
        self._provider_id = provider_id

    @property
    def runtime(self):
        return self._runtime

    @property
    def provider_id(self):
        return self._provider_id or self._runtime.runtime_name

    def availability(self):
        return self._runtime.availability()

    def model_info(self):
        config = self._runtime.config
        availability = self._runtime.availability()
        return ModelInfo(
            provider_id=self.provider_id,
            model_id=config.model_id if config else None,
            model_format=config.model_format if config else None,
            # Declared by the configuration (Prompt 401); None = not declared = unknown.
            supported_languages=getattr(config, "supported_languages", None) if config else None,
            context_length=config.context_length if config else None,
            max_output_tokens=config.max_output_tokens if config else None,
            is_local=True, loaded=availability.loaded,
            runtime_name=self._runtime.runtime_name,
            supported_scripts=getattr(config, "supported_scripts", None) if config else None,
            multilingual=getattr(config, "multilingual", None) if config else None,
            default_language=getattr(config, "default_language", None) if config else None)

    def load(self):
        return self._runtime.load()

    def generate(self, request, cancellation_token=None):
        # Prompt 412: whatever the runtime does, the provider hands back
        # one valid InferenceResult (a runtime that raised or returned a
        # malformed value becomes a structured failure, never an exception).
        name = getattr(self._runtime, "runtime_name", None)
        try:
            result = self._runtime.generate(request, cancellation_token)
        except Exception as exc:  # noqa: BLE001 - runtime contract is "never raises"
            return inference_failure_from_exception(exc, runtime_name=name)
        return standardize_inference_result(result, runtime_name=name)

    def unload(self):
        self._runtime.unload()
        return True

    def check_request_limits(self, request):
        return self._runtime.check_request_limits(request)

    def resource_status(self):
        config = self._runtime.config
        state = self._runtime.availability()
        limits = None
        if config is not None:
            limits = {
                "context_length": config.context_length,
                "max_output_tokens": config.max_output_tokens,
                "timeout_seconds": config.timeout_seconds,
                "cpu_threads": config.cpu_threads,
                "max_memory_mb": config.max_memory_mb,
            }
        return {"state": state.state, "loaded": state.loaded, "limits": limits}


class ProviderRegistry:
    """Registered providers plus an optional default. This is the whole
    provider-selection mechanism: `select()` returns a provider by id (or
    the default); an unknown id is an explicit `UnknownProviderError`."""

    def __init__(self):
        self._providers = {}
        self._default_id = None

    def register(self, provider, default=False):
        if not isinstance(provider, LocalModelProvider):
            raise TypeError("provider must be a LocalModelProvider")
        provider_id = provider.provider_id
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ProviderRegistryError("provider_id must be a non-empty string")
        if provider_id in self._providers:
            raise ProviderRegistryError(f"provider {provider_id!r} is already registered")
        self._providers[provider_id] = provider
        if default or self._default_id is None:
            self._default_id = provider_id
        return provider

    def provider_ids(self):
        return list(self._providers)

    def set_default(self, provider_id):
        self.get(provider_id)
        self._default_id = provider_id

    @property
    def default_id(self):
        return self._default_id

    def get(self, provider_id):
        try:
            return self._providers[provider_id]
        except (KeyError, TypeError):
            raise UnknownProviderError(provider_id, self._providers) from None

    def select(self, provider_id=None):
        """`provider_id` None -> the default provider (the first one
        registered unless `default=True`/`set_default` chose another)."""
        if provider_id is None:
            if self._default_id is None:
                raise ProviderRegistryError("no local model provider is registered")
            return self._providers[self._default_id]
        return self.get(provider_id)
