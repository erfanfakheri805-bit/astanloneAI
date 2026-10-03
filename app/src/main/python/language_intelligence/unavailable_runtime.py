"""
Language Intelligence - Unavailable Local Model Runtime
===========================================================
Prompt 398. `UnavailableLocalModelRuntime` is the ONLY concrete
`LocalModelRuntime` (local_model_runtime.py) this project contains
today, and it exists to be honest: no on-device inference engine
(llama.cpp binding, ONNX Runtime, TFLite, ...) is installed, so no
model can be loaded or run.

  * With no/invalid/disabled configuration, generate() reports
    STATUS_MODEL_NOT_CONFIGURED.
  * With a valid, enabled configuration, generate() reports
    STATUS_MODEL_UNAVAILABLE / ERROR_RUNTIME_DEPENDENCY_MISSING, with a
    message stating exactly what is missing.

It never produces text. Its hooks `_load_model` / `_run_inference` are
unreachable (the base class stops at the dependency check) and raise if
ever called, rather than returning anything that could be mistaken for
model output.

This is not a second runtime implementation and not a fake model: it
is the explicit "unavailable" state Prompt 398 asks for. A real
runtime is added later as a sibling subclass of LocalModelRuntime -
see docs/local_model_runtime.md.
"""

from .local_model_runtime import LocalModelRuntime, ModelLoadError, InferenceExecutionError

RUNTIME_NAME_UNAVAILABLE = "unavailable"

MISSING_DEPENDENCY_MESSAGE = (
    "No on-device language-model inference engine is installed in this project. "
    "A concrete LocalModelRuntime backed by a local engine (for example a "
    "llama.cpp Python binding for GGUF models, built for Android/Chaquopy ABIs "
    "arm64-v8a and armeabi-v7a) plus a local model file is required. "
    "See docs/local_model_runtime.md."
)


class UnavailableLocalModelRuntime(LocalModelRuntime):
    @property
    def runtime_name(self):
        return RUNTIME_NAME_UNAVAILABLE

    def dependency_status(self):
        return False, MISSING_DEPENDENCY_MESSAGE

    def _load_model(self, config):
        raise ModelLoadError("UnavailableLocalModelRuntime cannot load models")

    def _run_inference(self, request, params, config, control):
        raise InferenceExecutionError("UnavailableLocalModelRuntime cannot run inference")
