"""
model_runtime.litertlm_runtime - the phone's OWN language model (LiteRT-LM, `.litertlm` files)
==============================================================================================
`LiteRtLmRuntime` runs a `.litertlm` model (Gemma 4, Qwen 3.5 ... as packaged by Google's `litert-community`) with Google's LiteRT-LM engine
(`com.google.ai.edge.litertlm:litertlm-android`, Apache-2.0). That library is native code that has to be BUILT INTO the APK; it cannot be added from
inside a running app. The Java side is one small class, `LiteRtLmBridge` (reflection, no hard dependency), so this runtime reports itself available
only when

* Python really runs inside the Android app (Chaquopy), AND
* `LiteRtLmBridge` is in the APK AND it says the engine's classes are in the APK too (the build was made with the engine).

Otherwise it says exactly which is missing; nothing is faked. The answer is plain TEXT: the engine is given no tools, and nothing it writes is ever run.

Structured chat: unlike the other engines this one is given the instruction, the last few turns and the new message SEPARATELY (the engine applies the
model's own chat template), so no chat format is guessed from a file name. `generate()` (a bare prompt) still works and is one user message.

Crash guard: loading a model of 1-3 GB is the one moment the phone can kill the app (the system's memory killer, or a native fault Java cannot catch).
Before the engine is loaded a marker file `<model>.loading` is written; it is removed only after the first real answer (the smoke test). A marker that is
still there at the next start means the last attempt never finished, so the model is NOT loaded again by itself (`crashed_before`); the user decides
with «مغز را دوباره امتحان کن» (`reset_crash_guard`) or chooses the lighter brain.

UNVERIFIED ON A DEVICE: this delivery could only exercise the Python side against a fake bridge and the Java side against a stand-in engine.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional, Sequence, Tuple

from .card import ModelCard
from .mediapipe_runtime import _cut
from .runtimes import (InferenceRuntime, LoadedModel, RuntimeAvailability, RuntimeGenerateError, RuntimeLoadError, SmokeReport)

__all__ = ["LiteRtLmRuntime", "BRIDGE_CLASS", "REQUIRES", "ENGINE_CONTEXT_TOKENS", "MARKER_SUFFIX", "reset_crash_guard", "crash_guard_active",
           "parse_result", "encode_history"]

BRIDGE_CLASS = "com.erfan.standaloneai.LiteRtLmBridge"
REQUIRES = ("com.google.ai.edge.litertlm:litertlm-android (an APK built with the on-device brain engine)",)
ENGINE_CONTEXT_TOKENS = 2048          # input + output tokens the engine's KV-cache is sized for (a phone-friendly window)
MARKER_SUFFIX = ".loading"
TURN_SEP = "\x1e"
FIELD_SEP = "\x1f"
MAX_HISTORY_TURNS = 6
MAX_FIELD_CHARS = 4000
_BAD_CHARS = dict.fromkeys(list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127], None)   # control characters (incl. the two separators)


def _clean(text: object, limit: int = MAX_FIELD_CHARS) -> str:
    return str(text or "").translate(_BAD_CHARS).replace("\r", "").strip()[:limit]


def encode_history(turns: Sequence[Tuple[str, str]]) -> str:
    """`[(user, assistant), ...]` -> the single string the Java side parses (the last few turns only; empty turns are dropped)."""
    records = []
    for pair in list(turns or ())[-MAX_HISTORY_TURNS:]:
        try:
            user, answer = _clean(pair[0]), _clean(pair[1])
        except (TypeError, IndexError):
            continue
        if user and answer:
            records.append(user + FIELD_SEP + answer)
    return TURN_SEP.join(records)


def parse_result(raw: object) -> Tuple[str, str, str]:
    """The bridge's answer -> ("OK", text, "") or ("ERR", code, detail). Anything else is an engine error `bad_bridge_answer`."""
    text = "" if raw is None else str(raw)
    if text.startswith("OK\n") or text == "OK":
        return "OK", text[3:], ""
    if text.startswith("ERR\n"):
        parts = text[4:].split("\n", 1)
        code = (parts[0] or "engine_error").strip()[:40]
        return "ERR", code, (parts[1] if len(parts) > 1 else "").strip()[:160]
    return "ERR", "bad_bridge_answer", ""


def _marker(path: str) -> str:
    return str(path) + MARKER_SUFFIX


def crash_guard_active(model_path: str) -> bool:
    """True when an earlier load of this model never finished (see the module docstring)."""
    try:
        return os.path.lexists(_marker(model_path))
    except OSError:
        return False


def reset_crash_guard(model_path: str) -> bool:
    """The user's explicit «try again»: forget the unfinished-load marker. True when nothing of it remains."""
    try:
        if os.path.lexists(_marker(model_path)):
            os.unlink(_marker(model_path))
        return True
    except OSError:
        return False


class _Handle:
    """What the manager keeps for a loaded model: the (static) bridge and the path. The engine itself lives inside the bridge."""

    def __init__(self, bridge, path: str) -> None:
        self.bridge, self.path = bridge, path


class LiteRtLmRuntime(InferenceRuntime):
    name = "litertlm"
    formats = ("litertlm",)
    supports_chat = True
    description_fa = ("اجرای مدل زبانیِ «.litertlm» (مثل Gemma 4 یا Qwen 3.5) روی خودِ گوشی با موتور LiteRT-LM گوگل؛ فقط در نسخه‌ای از برنامه کار می‌کند که با این موتور ساخته شده. "
                      "خروجی فقط متن است و هرگز اجرا نمی‌شود.")
    description_en = ("Runs a '.litertlm' language model (e.g. Gemma 4, Qwen 3.5) on the phone with Google's LiteRT-LM engine; only in an APK built with that engine. "
                      "The output is text only and is never executed.")

    def __init__(self, jvm_provider: Optional[Callable[[], object]] = None, context_tokens: int = ENGINE_CONTEXT_TOKENS,
                 clock: Callable[[], float] = time.time) -> None:
        self._jvm_provider = jvm_provider
        self._context_tokens = int(context_tokens)
        self._clock = clock

    # ---- plumbing ---------------------------------------------------------------------------------------------
    def _jvm(self):
        if self._jvm_provider is not None:
            return self._jvm_provider()
        from native_bridge import facade                      # imported lazily: nothing here needs Android until a model is used
        return facade.get_jvm()

    def _bridge(self):
        jvm = self._jvm()
        if jvm is None or not jvm.available():
            raise _Unavailable("unavailable_platform")
        return jvm.jclass(BRIDGE_CLASS)

    def availability(self) -> RuntimeAvailability:
        try:
            bridge = self._bridge()
            present = bool(bridge.isPresent())
        except _Unavailable:
            return RuntimeAvailability(False, "unavailable_platform", "موتور مغز فقط داخل برنامهٔ اندروید کار می‌کند، نه روی این دستگاه.",
                                       "The brain engine only runs inside the Android app, not on this machine.", REQUIRES)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code in ("class_missing", "bad_class_name") or type(exc).__name__ == "NativeUnavailable":
                return RuntimeAvailability(False, "dependency_missing",
                                           "این نسخهٔ برنامه پلِ موتور مغز را در خودش ندارد؛ باید نسخهٔ تازه‌تری نصب شود که با آن ساخته شده.",
                                           "This build of the app does not contain the brain-engine bridge.", REQUIRES)
            return RuntimeAvailability(False, "engine_error", "موتور مغز در دسترس نیست.", "The brain engine is not available.", REQUIRES)
        if not present:
            return RuntimeAvailability(False, "dependency_missing",
                                       "این نسخهٔ برنامه با موتور مغز (LiteRT-LM) ساخته نشده؛ نسخه‌ای باید نصب شود که با آن ساخته شده.",
                                       "This build of the app was made without the brain engine (LiteRT-LM).", REQUIRES)
        return RuntimeAvailability(True, "ok", "موتور مغز (LiteRT-LM) در برنامه هست.", "The brain engine (LiteRT-LM) is in the app.")

    def diagnostics(self) -> str:
        """The bridge's own one-line report (which engine classes exist), or '' when it cannot be asked. Never raises."""
        try:
            return str(self._bridge().describe())[:300]
        except Exception:
            return ""

    # ---- load / generate -----------------------------------------------------------------------------------------
    def load(self, path: str, card: ModelCard) -> LoadedModel:
        if not self.availability().available:
            raise RuntimeLoadError("dependency_missing", "litertlm")
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeLoadError("model_file_invalid", "not_a_regular_file")
        except OSError:
            raise RuntimeLoadError("model_file_unreadable") from None
        if crash_guard_active(path):
            raise RuntimeLoadError("crashed_before", "unfinished_load")
        try:
            with open(_marker(path), "w", encoding="ascii") as handle:
                handle.write("loading since %d\n" % int(self._clock()))
        except OSError:
            raise RuntimeLoadError("io_error", "marker") from None
        try:
            bridge = self._bridge()
            raw = bridge.load(str(path), self._context_tokens)
        except Exception as exc:                              # Python-level error: the process survived, so the guard is lifted
            reset_crash_guard(path)
            raise RuntimeLoadError("engine_load_failed", type(exc).__name__) from None
        kind, code, detail = parse_result(raw)
        if kind != "OK":                                      # an error STRING from the bridge: the process survived too
            reset_crash_guard(path)
            raise RuntimeLoadError(code if code and code != "engine_error" else "engine_load_failed", detail[:80])
        return LoadedModel(card.model_id, self.name, _Handle(bridge, str(path)), path)

    def chat(self, loaded: LoadedModel, system: str, turns: Sequence[Tuple[str, str]], user: str, *, max_tokens: int) -> str:
        handle = loaded.handle
        if not isinstance(handle, _Handle):
            raise RuntimeGenerateError("not_loaded")
        question = _clean(user, MAX_FIELD_CHARS)
        if not question:
            raise RuntimeGenerateError("bad_arguments", "empty_question")
        try:
            raw = handle.bridge.chat(_clean(system, 2000), encode_history(turns), question, int(max_tokens))
        except Exception as exc:
            raise RuntimeGenerateError("engine_generate_failed", type(exc).__name__) from None
        kind, text, detail = parse_result(raw)
        if kind != "OK":
            raise RuntimeGenerateError(text or "engine_generate_failed", detail[:80])
        if not text.strip():
            raise RuntimeGenerateError("engine_bad_output", "empty")
        return _cut(text, max_tokens)

    def generate(self, loaded: LoadedModel, prompt: str, *, max_tokens: int, seed: int) -> str:
        return self.chat(loaded, "", (), prompt, max_tokens=max_tokens)

    def smoke_test(self, loaded: LoadedModel) -> SmokeReport:
        try:
            text = self.chat(loaded, "", (), "سلام", max_tokens=24)
        except RuntimeGenerateError as err:
            if isinstance(loaded.handle, _Handle):
                reset_crash_guard(loaded.handle.path)         # the engine answered with an error string: the process survived
            return SmokeReport(False, "%s:%s" % (err.code, err.detail) if err.detail else err.code, "")
        if isinstance(loaded.handle, _Handle):
            reset_crash_guard(loaded.handle.path)             # the first real answer came back: the load did not kill the app
        if not text.strip():
            return SmokeReport(False, "empty_output", "")
        return SmokeReport(True, "non_empty_completion", text[:80])

    def cancel(self) -> None:
        """Ask the answer in progress to stop (safe from any thread; never raises)."""
        try:
            self._bridge().cancel()
        except Exception:
            pass

    def unload(self, loaded: LoadedModel) -> None:
        handle, loaded.handle = loaded.handle, None
        try:
            if isinstance(handle, _Handle):
                handle.bridge.unload()
        except Exception:
            pass


class _Unavailable(Exception):
    pass
