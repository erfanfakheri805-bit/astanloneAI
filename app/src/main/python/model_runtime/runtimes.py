"""
model_runtime.runtimes - the engines that can really load and run a model file
==============================================================================
An `InferenceRuntime` turns a verified model file into generated text. Two
exist today:

* `NgramRuntime` ("ngram-json") - the pure-Python statistical n-gram model in
  `ngram.py`. It really loads and generates, always available, but it is a
  counting model, NOT a large language model.
* `LlamaCppRuntime` ("gguf") - a thin adapter over the `llama_cpp` Python
  package. It reports itself available ONLY when that package can really be
  found; on a stock Chaquopy build it cannot, and it says exactly that.

Formats without a runtime here ("onnx", "tflite") stay unsupported; the
manager reports `no_runtime_for_format` instead of pretending.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple

from .card import ModelCard
from .ngram import MAX_MODEL_BYTES, NgramModel, NgramModelError, load_ngram_model, tokenize

GGUF_MAGIC = b"GGUF"

__all__ = ["RuntimeAvailability", "LoadedModel", "SmokeReport", "RuntimeLoadError", "RuntimeGenerateError",
           "InferenceRuntime", "NgramRuntime", "LlamaCppRuntime", "default_runtimes"]


class RuntimeLoadError(Exception):
    """The runtime could not load the model file; `code` is stable, `detail` a short diagnostic."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__("%s: %s" % (code, detail) if detail else code)
        self.code, self.detail = code, detail


class RuntimeGenerateError(Exception):
    """The runtime failed while generating."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__("%s: %s" % (code, detail) if detail else code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class RuntimeAvailability:
    available: bool
    code: str
    reason_fa: str
    reason_en: str
    requires: Tuple[str, ...] = ()


@dataclass
class LoadedModel:
    model_id: str
    runtime: str
    handle: Any
    path: str


@dataclass(frozen=True)
class SmokeReport:
    ok: bool
    details: str
    output_excerpt: str


class InferenceRuntime(ABC):
    name: str = ""
    formats: Tuple[str, ...] = ()
    description_fa: str = ""
    description_en: str = ""

    @abstractmethod
    def availability(self) -> RuntimeAvailability: ...

    @abstractmethod
    def load(self, path: str, card: ModelCard) -> LoadedModel: ...

    @abstractmethod
    def generate(self, loaded: LoadedModel, prompt: str, *, max_tokens: int, seed: int) -> str: ...

    @abstractmethod
    def smoke_test(self, loaded: LoadedModel) -> SmokeReport: ...

    def unload(self, loaded: LoadedModel) -> None:
        loaded.handle = None


# --------------------------------------------------------------------------- n-gram

class NgramRuntime(InferenceRuntime):
    name = "ngram"
    formats = ("ngram-json",)
    description_fa = "مدل آماری n-gram؛ فقط ادامهٔ متن را از روی شمارش کلمات آموزش‌دیده می‌سازد و یک مدل زبانی بزرگ (LLM) نیست."
    description_en = "Statistical n-gram model: it only continues text from word counts it was trained on; it is NOT an LLM."

    def availability(self) -> RuntimeAvailability:
        return RuntimeAvailability(True, "ok", "آماده است (پایتون خالص).", "Available (pure Python).")

    def load(self, path: str, card: ModelCard) -> LoadedModel:
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeLoadError("model_file_invalid", "not_a_regular_file")
            if os.path.getsize(path) > MAX_MODEL_BYTES:
                raise RuntimeLoadError("model_file_invalid", "too_large")
            with open(path, "rb") as handle:
                data = handle.read(MAX_MODEL_BYTES + 1)
            return LoadedModel(card.model_id, self.name, load_ngram_model(data), path)
        except NgramModelError as err:
            raise RuntimeLoadError("model_file_invalid", err.code) from None
        except OSError:
            raise RuntimeLoadError("model_file_unreadable") from None

    def generate(self, loaded: LoadedModel, prompt: str, *, max_tokens: int, seed: int) -> str:
        model = loaded.handle
        if not isinstance(model, NgramModel):
            raise RuntimeGenerateError("not_loaded")
        try:
            return model.generate(prompt, max_tokens=max_tokens, seed=seed)
        except ValueError:
            raise RuntimeGenerateError("bad_arguments") from None

    def smoke_test(self, loaded: LoadedModel) -> SmokeReport:
        model = loaded.handle
        if not isinstance(model, NgramModel) or len(model.vocab) <= 3:
            return SmokeReport(False, "model_has_no_vocabulary", "")
        prompt = model.vocab[3]
        first = self.generate(loaded, prompt, max_tokens=12, seed=0)
        second = self.generate(loaded, prompt, max_tokens=12, seed=0)
        if first != second:
            return SmokeReport(False, "not_deterministic", first[:80])
        if not first.strip():
            return SmokeReport(False, "empty_output", "")
        allowed = model.vocabulary()
        stray = [t for t in tokenize(first) if t not in allowed]
        if stray:
            return SmokeReport(False, "output_outside_vocabulary", first[:80])
        return SmokeReport(True, "deterministic_non_empty_in_vocabulary", first[:80])


# --------------------------------------------------------------------------- llama.cpp

class LlamaCppRuntime(InferenceRuntime):
    name = "llama_cpp"
    formats = ("gguf",)
    description_fa = "اجرای مدل‌های GGUF از راه بستهٔ llama_cpp (فقط وقتی روی دستگاه واقعاً نصب باشد)."
    description_en = "Runs GGUF models through the llama_cpp package (only when it is really installed on the device)."
    REQUIRES = ("llama_cpp (llama-cpp-python) built for Android arm64",)

    def __init__(self, module_loader: Optional[Callable[[str], Any]] = None,
                 spec_finder: Optional[Callable[[str], Any]] = None) -> None:
        self._module_loader = module_loader or importlib.import_module
        self._spec_finder = spec_finder or importlib.util.find_spec

    def availability(self) -> RuntimeAvailability:
        try:
            found = self._spec_finder("llama_cpp") is not None
        except (ImportError, ValueError, AttributeError):
            found = False
        if found:
            return RuntimeAvailability(True, "ok", "بستهٔ llama_cpp پیدا شد.", "The llama_cpp package was found.")
        return RuntimeAvailability(
            False, "dependency_missing",
            "بستهٔ llama_cpp روی این دستگاه نصب نیست؛ بدون آن مدل GGUF اجرا نمی‌شود.",
            "The llama_cpp package is not installed on this device; GGUF models cannot run without it.",
            self.REQUIRES)

    def load(self, path: str, card: ModelCard) -> LoadedModel:
        if not self.availability().available:
            raise RuntimeLoadError("dependency_missing", "llama_cpp")
        try:  # a cheap format check before the native engine ever sees the file
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeLoadError("model_file_invalid", "not_a_regular_file")
            with open(path, "rb") as handle:
                magic = handle.read(len(GGUF_MAGIC))
        except OSError:
            raise RuntimeLoadError("model_file_unreadable") from None
        if magic != GGUF_MAGIC:
            raise RuntimeLoadError("model_file_invalid", "bad_gguf_magic")
        try:
            module = self._module_loader("llama_cpp")
            engine = module.Llama(model_path=str(path), n_ctx=2048, n_threads=min(4, os.cpu_count() or 1), verbose=False)
        except Exception as exc:  # engine errors are reported by type only
            raise RuntimeLoadError("engine_load_failed", type(exc).__name__) from None
        return LoadedModel(card.model_id, self.name, engine, path)

    def generate(self, loaded: LoadedModel, prompt: str, *, max_tokens: int, seed: int) -> str:
        engine = loaded.handle
        if engine is None:
            raise RuntimeGenerateError("not_loaded")
        try:
            answer = engine(prompt, max_tokens=max_tokens, temperature=0.0, seed=seed)
            text = answer["choices"][0]["text"]
        except Exception as exc:
            raise RuntimeGenerateError("engine_generate_failed", type(exc).__name__) from None
        if not isinstance(text, str):
            raise RuntimeGenerateError("engine_bad_output", type(text).__name__)
        return text

    def smoke_test(self, loaded: LoadedModel) -> SmokeReport:
        text = self.generate(loaded, "سلام", max_tokens=8, seed=0)
        if not text.strip():
            return SmokeReport(False, "empty_output", "")
        return SmokeReport(True, "non_empty_completion", text[:80])


def default_runtimes() -> Sequence[InferenceRuntime]:
    return (NgramRuntime(), LlamaCppRuntime())
