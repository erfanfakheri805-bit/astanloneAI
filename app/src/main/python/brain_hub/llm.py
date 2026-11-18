"""
brain_hub.llm - the Persian brain's own language model, on the phone
====================================================================
When a REAL language model has been prepared by `model_runtime` (its file checked against its hash, its engine really loaded, a real
smoke test passed), the Persian conversation can ask it about a sentence that nothing else in the app could answer. Nothing here is
a model: this module only builds the prompt in the model's chat format, runs one generation with a deadline, cleans the text and
remembers the last few turns (in memory only; they are gone when the app is closed).

What a model's answer is - and is not:
* it is TEXT shown to the user; it is never run, never installed, never fed back as if the user had said it, and it carries no tools;
* it can be wrong - the system prompt asks the model to say «نمی‌دانم» instead of guessing, and the first answer carries a one-time note;
* the model is told what it cannot do (it has done nothing on the phone; it cannot draw pictures or read the live web) and to point the user
  to «از ChatGPT بخواه …» for those, which is the teacher (`persian_brain.hub_teacher`).

Only `model_runtime` engines that are real language models count (`LLM_FORMATS`); the always-available n-gram model is NOT one.

The phone's own brain (`ownbrain`, a `.litertlm` model) is a chat engine: it is given the instruction, the last few turns and the new
message SEPARATELY (the engine applies the model's own chat template), it may need a minute for the first answer (the model is loaded then),
so it gets a longer deadline, and an answer that overruns it is cancelled in the engine instead of being left to run for ever.
"""

import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

__all__ = ["LlmBrain", "LlmReply", "get_llm", "LLM_FORMATS", "CHAT_FORMATS", "CHAT_DEADLINE_SECONDS", "SYSTEM_FA", "build_prompt", "family_of", "clean_answer"]

LLM_FORMATS = ("task", "gguf", "litertlm")
CHAT_FORMATS = ("litertlm",)           # engines that take the instruction / turns / message as separate parts
DEADLINE_SECONDS = 100.0
CHAT_DEADLINE_SECONDS = 170.0          # a 1-3 GB model is loaded at the first answer after the app started
MAX_TOKENS = 256
MEMORY_TURNS = 3
MAX_TURN_CHARS = 400
MAX_ANSWER_CHARS = 1800
MAX_QUESTION_CHARS = 1200

SYSTEM_FA = (
    "تو «دستیار هوشمند» هستی؛ دستیار فارسی‌زبانِ داخل گوشی. همیشه به فارسیِ ساده و روان، کوتاه و مستقیم جواب بده. "
    "اگر جواب را نمی‌دانی یا مطمئن نیستی، صریح بگو «نمی‌دانم»؛ هرگز حدس را به‌جای واقعیت نگو. "
    "تو فقط متن می‌نویسی و هیچ کاری روی گوشی انجام نداده‌ای؛ نگو «انجام دادم». "
    "اگر کاربر چیزی خواست که از تو برنمی‌آید (ساخت عکس، اطلاعات زندهٔ اینترنت، کاری روی گوشی)، بگو نمی‌توانی و پیشنهاد بده بگوید: «از ChatGPT بخواه …»."
)

# The chat format is inferred from the model's NAME (whole words only: "dolphin" is not "phi"). A name that is not recognised gets the plain
# format. DeepSeek-R1 distills use a format of their own that is not built here, so they are "plain" too. UNVERIFIED on real model files.
_FAMILY_WORDS = (("gemma", "gemma"), ("qwen", "chatml"), ("smollm", "chatml"), ("llama", "llama3"), ("phi", "phi3"))
_STRAY_TOKENS = re.compile(r"<\|?/?(?:start_of_turn|end_of_turn|im_start|im_end|eot_id|start_header_id|end_header_id|begin_of_text|endoftext|end|"
                           r"system|user|assistant|model)\|?>|<bos>|<eos>|</s>|<s>", re.I)
_ROLE_OPEN = re.compile(r"<\|?(?:start_of_turn|im_start|start_header_id)\|?>\s*(?:model|assistant|user|system)\s*(?:<\|?end_header_id\|?>)?\s*", re.I)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.S | re.I)           # a thought that never closed (the answer ran out of tokens while thinking)
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")      # control characters and bidi overrides / isolates
_NEWLINES = re.compile(r"\n{3,}")


def family_of(model_id, title=""):
    """The chat format a model expects, from its name (`gemma`, `chatml`, `llama3`, `phi3`, else `plain`)."""
    words = re.split(r"[^a-z0-9]+", ("%s %s" % (model_id, title)).lower())
    for family_word, family in _FAMILY_WORDS:
        if any(w == family_word or (w.startswith(family_word) and w[len(family_word):].isdigit()) for w in words):
            return family
    return "plain"


def _clip(text, limit):
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def build_prompt(family, system, turns, user):
    """The full prompt in the model's chat format. `turns` is `[(user, assistant), ...]` (oldest first)."""
    user = _clip(user, MAX_QUESTION_CHARS)
    history = [(_clip(u, MAX_TURN_CHARS), _clip(a, MAX_TURN_CHARS)) for u, a in turns]
    if family == "gemma":                                   # Gemma has no system role: the instructions open the first user turn
        out = []
        first = True
        for u, a in history:
            out.append("<start_of_turn>user\n%s%s<end_of_turn>\n<start_of_turn>model\n%s<end_of_turn>\n" % (system + "\n\n" if first else "", u, a))
            first = False
        out.append("<start_of_turn>user\n%s%s<end_of_turn>\n<start_of_turn>model\n" % (system + "\n\n" if first else "", user))
        return "".join(out)
    if family == "chatml":
        out = ["<|im_start|>system\n%s<|im_end|>\n" % system]
        for u, a in history:
            out.append("<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s<|im_end|>\n" % (u, a))
        out.append("<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n" % user)
        return "".join(out)
    if family == "llama3":
        out = ["<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n%s<|eot_id|>" % system]
        for u, a in history:
            out.append("<|start_header_id|>user<|end_header_id|>\n\n%s<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n%s<|eot_id|>" % (u, a))
        out.append("<|start_header_id|>user<|end_header_id|>\n\n%s<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n" % user)
        return "".join(out)
    if family == "phi3":
        out = ["<|system|>\n%s<|end|>\n" % system]
        for u, a in history:
            out.append("<|user|>\n%s<|end|>\n<|assistant|>\n%s<|end|>\n" % (u, a))
        out.append("<|user|>\n%s<|end|>\n<|assistant|>\n" % user)
        return "".join(out)
    out = [system + "\n\n"]
    for u, a in history:
        out.append("کاربر: %s\nدستیار: %s\n" % (u, a))
    out.append("کاربر: %s\nدستیار:" % user)
    return "".join(out)


def clean_answer(text):
    """A model's raw output -> text safe to show: no chat-format tokens, no control or bidi-override characters, bounded."""
    text = str(text or "")
    if "</think>" in text.lower() and "<think>" not in text.lower():             # the chat template already opened the thought: only the end shows
        text = re.split(r"</think>", text, flags=re.I)[-1]
    text = _THINK_OPEN.sub("", _THINK_BLOCK.sub("", text))
    text = _STRAY_TOKENS.sub("", _ROLE_OPEN.sub("", text))
    text = _CONTROL.sub("", text).replace("\r", "")
    text = _NEWLINES.sub("\n\n", text).strip()
    if len(text) > MAX_ANSWER_CHARS:
        cut = text[:MAX_ANSWER_CHARS]
        boundary = max(cut.rfind("."), cut.rfind("؟"), cut.rfind("!"), cut.rfind("\n"))
        text = (cut[:boundary + 1] if boundary > MAX_ANSWER_CHARS // 2 else cut).rstrip() + "…"
    return text


@dataclass(frozen=True)
class LlmReply:
    ok: bool
    text: str = ""
    code: str = ""
    model_id: str = ""
    seconds: float = 0.0
    cancelled: bool = False        # a timed-out answer that the engine was told to stop


class LlmBrain:
    def __init__(self, hub, *, deadline_seconds=DEADLINE_SECONDS, max_tokens=MAX_TOKENS, monotonic=time.monotonic):
        self._hub = hub
        self._deadline, self._max_tokens, self._monotonic = float(deadline_seconds), int(max_tokens), monotonic
        self._lock = threading.RLock()
        self._busy = threading.Event()
        self._turns = []
        self._model_id = ""
        self._cached = None
        self._used = 0

    # ---- which model ---------------------------------------------------------------------------------------------------
    def models(self):
        """The usable models that are real language models (never the n-gram model), newest registration last."""
        try:
            rows = self._hub.list_models()
        except Exception:
            return []
        return [m for m in rows if m.usable and (m.card or {}).get("format") in LLM_FORMATS]

    def current(self):
        """The model that would answer (the last one used while it is still usable, else the newest usable one), or None.
        While an answer is being made the model manager is locked, so the last known model is returned without asking it."""
        if self._busy.is_set() and self._cached is not None:
            return self._cached
        found = self.models()
        if not found:
            self._cached = None
            return None
        chosen = next((m for m in found if m.model_id == self._model_id), found[-1])
        self._cached = chosen
        return chosen

    def status(self):
        """`{state, model_id, title, reason_fa}`; state is `ready`, `busy`, `no_model` or `no_engine`."""
        model = self.current()
        if model is not None:
            return {"state": "busy" if self._busy.is_set() else "ready", "model_id": model.model_id,
                    "title": (model.card or {}).get("title") or model.model_id, "reason_fa": ""}
        try:
            engines = [r for r in self._hub.model_runtimes_info() if set(r.get("formats") or ()) & set(LLM_FORMATS)]
        except Exception:
            engines = []
        if engines and not any(r.get("available") for r in engines):
            reason = next((r.get("reason_fa") for r in engines if r.get("reason_fa")), "")
            return {"state": "no_engine", "model_id": "", "title": "", "reason_fa": reason}
        return {"state": "no_model", "model_id": "", "title": "", "reason_fa": ""}

    # ---- one answer -------------------------------------------------------------------------------------------------------
    def _named(self, model_id):
        return next((m for m in self.models() if m.model_id == model_id), None)

    def reply(self, text, *, model_id=None, remember=True):
        """One answer: `LlmReply(ok=True, text=...)`, or `ok=False` with a stable code (`no_model`, `bad_question`, `busy`, `timeout`,
        `empty`, or the model manager's own code such as `model_not_usable`). Blocks at most the deadline; never raises.
        `model_id` asks one particular usable model (the test of the own brain); `remember=False` keeps the exchange out of the short memory."""
        if self._busy.is_set():                               # an earlier answer is still being made (a timed-out one keeps running)
            return LlmReply(False, code="busy", model_id=self._model_id)
        model = self.current() if model_id is None else self._named(model_id)
        if model is None:
            return LlmReply(False, code="no_model")
        text = str(text or "").strip()
        if not text or len(text) > MAX_QUESTION_CHARS:
            return LlmReply(False, code="bad_question", model_id=model.model_id)
        with self._lock:
            if self._busy.is_set():
                return LlmReply(False, code="busy", model_id=model.model_id)
            self._busy.set()
            if model.model_id != self._model_id and remember:
                self._model_id, self._turns = model.model_id, []
            turns = list(self._turns) if remember else []
        card = model.card or {}
        chat_engine = card.get("format") in CHAT_FORMATS
        if chat_engine:                                        # the engine applies the model's own chat template to the three parts
            prompt = text
            kwargs = {"max_tokens": self._max_tokens, "chat": {"system": SYSTEM_FA, "turns": [(_clip(u, MAX_TURN_CHARS), _clip(a, MAX_TURN_CHARS))
                                                                                                   for u, a in turns], "user": text}}
            deadline = max(self._deadline, CHAT_DEADLINE_SECONDS)
        else:
            prompt = build_prompt(family_of(model.model_id, card.get("title", "")), SYSTEM_FA, turns, text)
            kwargs = {"max_tokens": self._max_tokens}
            deadline = self._deadline
        box = {}

        def work():
            try:
                box["result"] = self._hub.ask_model(model.model_id, prompt, **kwargs)
            except Exception as exc:                          # a model can never take the conversation down
                box["error"] = type(exc).__name__
            finally:
                self._busy.clear()

        started = self._monotonic()
        worker = threading.Thread(target=work, name="llm-answer", daemon=True)
        try:
            worker.start()
        except RuntimeError:                                   # no thread could be started: never stay "busy" for ever
            self._busy.clear()
            return LlmReply(False, code="no_thread", model_id=model.model_id)
        worker.join(deadline)
        seconds = round(self._monotonic() - started, 2)
        if worker.is_alive():                                  # still running: a chat engine is told to stop, the others keep running (`busy` says so)
            stopped = False
            if chat_engine:
                try:
                    stopped = bool(self._hub.cancel_model_generation())
                except Exception:
                    stopped = False
            return LlmReply(False, code="timeout", model_id=model.model_id, seconds=seconds, cancelled=stopped)
        result = box.get("result")
        if result is None or not getattr(result, "ok", False):
            return LlmReply(False, code=str(getattr(result, "code", "") or box.get("error") or "failed")[:40], model_id=model.model_id, seconds=seconds)
        answer = clean_answer(result.text)
        if not answer:
            return LlmReply(False, code="empty", model_id=model.model_id, seconds=seconds)
        if remember:
            with self._lock:
                self._turns = (self._turns + [(text, answer)])[-MEMORY_TURNS:]
                self._used += 1
        self._after_answer(model.model_id, chat_engine)
        return LlmReply(True, text=answer, model_id=model.model_id, seconds=seconds)

    def _after_answer(self, model_id, chat_engine):
        try:
            self._hub.note_served("llm.local")
        except Exception:
            pass
        if chat_engine:                                        # the own brain was used: its idle timer (which gives the memory back) restarts
            try:
                own = getattr(self._hub, "_own_brain", None)
                if own is not None and own.model_id() == model_id:
                    own.touch()
            except Exception:
                pass

    def used_count(self):
        return self._used

    def forget(self):
        with self._lock:
            self._turns = []


_LOCK = threading.Lock()


def get_llm(hub):
    """The one `LlmBrain` of this hub object (created on first use; nothing is touched on disk), or None for something that is not a hub."""
    if hub is None or not hasattr(hub, "list_models"):
        return None
    brain = getattr(hub, "_llm_brain", None)
    if isinstance(brain, LlmBrain):
        return brain
    with _LOCK:
        brain = getattr(hub, "_llm_brain", None)
        if not isinstance(brain, LlmBrain):
            brain = LlmBrain(hub)
            try:
                hub._llm_brain = brain
            except Exception:
                return brain
        return brain
