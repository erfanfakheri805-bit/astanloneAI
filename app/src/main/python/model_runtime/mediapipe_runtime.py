"""
model_runtime.mediapipe_runtime - a real language model on the phone (MediaPipe LLM Inference, `.task` files)
==============================================================================================================
`MediaPipeLlmRuntime` runs a `.task` model (Gemma and the like) through Google's MediaPipe LLM Inference Java API
(`com.google.mediapipe:tasks-genai`). That library is native code that has to be BUILT INTO the APK; it cannot be added from inside
a running app. So the runtime reports itself available only when

* Python really runs inside the Android app (Chaquopy), AND
* the class `com.google.mediapipe.tasks.genai.llminference.LlmInference` is really in the APK (the build was made with the engine).

Otherwise it says exactly which of the two is missing; nothing is faked. Output is plain TEXT: the engine never gets tools, and nothing
it writes is ever run.

Facts taken from Google's documentation (Android guide, `tasks-genai:0.10.27`): `LlmInference.LlmInferenceOptions.builder()` with
`setModelPath`, `setMaxTokens`, `setMaxTopK`; `LlmInference.createFromOptions(context, options)`; `generateResponse(prompt)`. Google marks
this API "maintenance only" and points to LiteRT-LM; the engine can be replaced later by a platform build without changing anything above
this class. UNVERIFIED ON DEVICE: this delivery could only exercise the adapter against a hand-written fake of those classes.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from .card import ModelCard
from .runtimes import (InferenceRuntime, LoadedModel, RuntimeAvailability, RuntimeGenerateError, RuntimeLoadError, SmokeReport)

__all__ = ["MediaPipeLlmRuntime", "LLM_CLASS", "OPTIONS_CLASS", "REQUIRES", "ENGINE_CONTEXT_TOKENS", "CHARS_PER_TOKEN"]

LLM_CLASS = "com.google.mediapipe.tasks.genai.llminference.LlmInference"
OPTIONS_CLASS = LLM_CLASS + "$LlmInferenceOptions"
REQUIRES = ("com.google.mediapipe:tasks-genai:0.10.27 (an APK built with the language-model engine)",)
ENGINE_CONTEXT_TOKENS = 1024          # input + output tokens the engine is created for (a small, phone-friendly window)
TOP_K = 40
CHARS_PER_TOKEN = 5                   # a coarse ceiling when cutting an answer to `max_tokens` (Persian is ~3-4 chars per token)


def _cut(text: str, max_tokens: int) -> str:
    limit = max(1, int(max_tokens)) * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(" "), cut.rfind("\n"), cut.rfind("."), cut.rfind("؟"), cut.rfind("!"))
    return (cut[:boundary] if boundary > limit // 2 else cut).rstrip()


class MediaPipeLlmRuntime(InferenceRuntime):
    name = "mediapipe_llm"
    formats = ("task",)
    description_fa = ("اجرای مدل زبانیِ «.task» (مثل Gemma) روی خودِ گوشی با موتور MediaPipe؛ فقط در نسخه‌ای از برنامه کار می‌کند که با این موتور ساخته شده. "
                      "خروجی فقط متن است و هرگز اجرا نمی‌شود.")
    description_en = ("Runs a '.task' language model (e.g. Gemma) on the phone with the MediaPipe engine; only in an APK built with that engine. "
                      "The output is text only and is never executed.")

    def __init__(self, jvm_provider: Optional[Callable[[], object]] = None, context_tokens: int = ENGINE_CONTEXT_TOKENS) -> None:
        self._jvm_provider = jvm_provider
        self._context_tokens = int(context_tokens)

    # ---- plumbing ---------------------------------------------------------------------------------------------
    def _jvm(self):
        if self._jvm_provider is not None:
            return self._jvm_provider()
        from native_bridge import facade                      # imported lazily: nothing here needs Android until a model is used
        return facade.get_jvm()

    def availability(self) -> RuntimeAvailability:
        try:
            jvm = self._jvm()
            if jvm is None or not jvm.available():
                return RuntimeAvailability(False, "unavailable_platform", "موتور مدل فقط داخل برنامهٔ اندروید کار می‌کند، نه روی این دستگاه.",
                                           "The model engine only runs inside the Android app, not on this machine.", REQUIRES)
            jvm.jclass(LLM_CLASS)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code in ("class_missing", "bad_class_name") or type(exc).__name__ == "NativeUnavailable":
                return RuntimeAvailability(False, "dependency_missing",
                                           "این نسخهٔ برنامه موتور مدل زبانی (MediaPipe) را در خودش ندارد؛ باید نسخه‌ای نصب شود که با آن ساخته شده.",
                                           "This build of the app does not contain the language-model engine (MediaPipe).", REQUIRES)
            return RuntimeAvailability(False, "engine_error", "موتور مدل زبانی در دسترس نیست.", "The language-model engine is not available.", REQUIRES)
        return RuntimeAvailability(True, "ok", "موتور MediaPipe در برنامه هست.", "The MediaPipe engine is in the app.")

    # ---- load / generate -----------------------------------------------------------------------------------------
    def load(self, path: str, card: ModelCard) -> LoadedModel:
        if not self.availability().available:
            raise RuntimeLoadError("dependency_missing", "mediapipe tasks-genai")
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeLoadError("model_file_invalid", "not_a_regular_file")
        except OSError:
            raise RuntimeLoadError("model_file_unreadable") from None
        try:
            jvm = self._jvm()
            engine_cls = jvm.jclass(LLM_CLASS)
            options_cls = jvm.jclass(OPTIONS_CLASS)
            builder = options_cls.builder()
            builder = builder.setModelPath(str(path))
            builder = builder.setMaxTokens(self._context_tokens)
            builder = builder.setMaxTopK(TOP_K)
            engine = engine_cls.createFromOptions(jvm.context(), builder.build())
        except RuntimeLoadError:
            raise
        except Exception as exc:                              # engine errors are reported by type only (never the model's text)
            raise RuntimeLoadError("engine_load_failed", type(exc).__name__) from None
        if engine is None:
            raise RuntimeLoadError("engine_load_failed", "no_engine")
        return LoadedModel(card.model_id, self.name, engine, path)

    def generate(self, loaded: LoadedModel, prompt: str, *, max_tokens: int, seed: int) -> str:
        engine = loaded.handle
        if engine is None:
            raise RuntimeGenerateError("not_loaded")
        try:
            raw = engine.generateResponse(str(prompt))
        except Exception as exc:
            raise RuntimeGenerateError("engine_generate_failed", type(exc).__name__) from None
        if raw is None:
            raise RuntimeGenerateError("engine_bad_output", "none")
        return _cut(str(raw), max_tokens)

    def smoke_test(self, loaded: LoadedModel) -> SmokeReport:
        text = self.generate(loaded, "سلام", max_tokens=16, seed=0)
        if not text.strip():
            return SmokeReport(False, "empty_output", "")
        return SmokeReport(True, "non_empty_completion", text[:80])

    def unload(self, loaded: LoadedModel) -> None:
        engine, loaded.handle = loaded.handle, None
        try:
            if engine is not None and hasattr(engine, "close"):
                engine.close()
        except Exception:
            pass
