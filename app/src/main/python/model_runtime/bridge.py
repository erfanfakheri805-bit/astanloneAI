"""
model_runtime.bridge - the managed model behind the EXISTING local-model contract
=================================================================================
`ManagedModelRuntime` is a `language_intelligence.local_model_runtime.LocalModelRuntime`
whose model is owned by a `ModelManager`. It therefore plugs into the existing
chain unchanged:

    LocalLanguageModelBackend -> RuntimeBackedProvider -> ManagedModelRuntime -> ModelManager

* While the model is not `usable` (not downloaded, not verified, no engine, a
  failed smoke test, a changed file ...) the runtime reports the existing
  "not configured" / "runtime unavailable" states and generates NOTHING. It
  never substitutes an answer.
* Once the manager says `usable`, `generate()` returns exactly what the engine
  produced for the request's `user_input`. A statistical n-gram model ignores
  instructions, temperature and the conversation; it only continues text.

This module is the ONLY place in `model_runtime` that imports `language_intelligence`.
"""

from __future__ import annotations

from typing import Optional

from language_intelligence.inference import ERROR_RUNTIME_DEPENDENCY_MISSING
from language_intelligence.local_model_config import MODEL_FORMAT_GGUF, MODEL_FORMAT_OTHER, LocalModelConfig
from language_intelligence.local_model_provider import RuntimeBackedProvider
from language_intelligence.local_model_runtime import (InferenceExecutionError, LocalModelRuntime, ModelLoadError,
                                                       RuntimeOutput)

from .manager import ModelManager
from .ngram import tokenize

__all__ = ["ManagedModelRuntime", "build_provider", "RUNTIME_NAME_MANAGED"]

RUNTIME_NAME_MANAGED = "managed-model"
_DEFAULT_MAX_TOKENS = 64


class ManagedModelRuntime(LocalModelRuntime):
    def __init__(self, manager: ModelManager, model_id: str, clock=None) -> None:
        super().__init__(config=None, clock=clock)
        self._manager = manager
        self._model_id = model_id
        self.refresh()

    # ---- configuration follows the manager's truth ------------------------------

    def refresh(self) -> bool:
        """Re-read the manager: configure the runtime when the model is usable, otherwise leave it unconfigured."""
        status = self._manager.status(self._model_id)
        if not status.usable or not status.card:
            self.configure(None)
            return False
        card = status.card
        config = LocalModelConfig(
            model_id=card["model_id"], model_path=self._manager.model_path(self._model_id),
            model_format=MODEL_FORMAT_GGUF if card["format"] == "gguf" else MODEL_FORMAT_OTHER,
            context_length=2048, max_output_tokens=256, timeout_seconds=30.0,
            supported_languages=list(card["languages"]) or None)
        self.configure(config)
        return True

    @property
    def runtime_name(self) -> str:
        return RUNTIME_NAME_MANAGED

    def dependency_status(self):
        if self._manager.is_usable(self._model_id):
            return True, ""
        status = self._manager.status(self._model_id)
        return False, ("model %r is not usable (state: %s); it has to pass hash verification, compatibility, loading and a real "
                       "inference test first" % (self._model_id, status.state))

    # ---- hooks of the template-method contract -----------------------------------

    def _load_model(self, config) -> None:
        if not self._manager.is_usable(self._model_id):
            raise ModelLoadError("the managed model is not usable", ERROR_RUNTIME_DEPENDENCY_MISSING)

    def _run_inference(self, request, params, config, control) -> RuntimeOutput:
        control.check()
        limit = params.max_output_tokens or _DEFAULT_MAX_TOKENS
        result = self._manager.generate(self._model_id, request.user_input, max_tokens=max(1, min(int(limit), 512)),
                                        seed=params.seed if isinstance(params.seed, int) else 0)
        if not result.ok:
            raise InferenceExecutionError("managed model refused: %s" % result.code)
        control.check()
        words = len(tokenize(result.text))
        return RuntimeOutput(result.text, finish_reason="length" if words >= limit else "stop", output_tokens=words)


def build_provider(manager: ModelManager, model_id: str, provider_id: Optional[str] = None) -> RuntimeBackedProvider:
    """The provider object the existing provider layer expects, backed by the managed runtime."""
    return RuntimeBackedProvider(ManagedModelRuntime(manager, model_id), provider_id=provider_id or "managed:%s" % model_id)
