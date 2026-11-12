"""
Persian conversation brain - which sentences are about the CLOUD BRAIN
======================================================================
`classify(text, norm, toks)` says which cloud-brain command (if any) one Persian sentence is: set it up, switch it on or off, ask
how it is, test it, change its model, forget the key, wipe its short memory, allow or forbid personal details, explain it.

Like `hub_intents` it is a pure, deterministic cascade over normalized tokens and small closed word lists. A sentence is a cloud-brain
command only when it NAMES the thing («مغز ابری», «مغز آنلاین», «هوش ابری», «کلید API») next to an action word - so ordinary
conversation, the local-model commands («مدل ... را دانلود کن») and the weather («هوا ابری است») are never taken over.

The answers the app keeps for offline use («جواب‌های نگه‌داشته‌شده») have their own four commands (on / off / wipe / how many); they need
the word «جواب» or «پاسخ» next to a keeping word («نگه», «ذخیره», «حافظه») AND an action word, so no other sentence is taken over.

`is_halt` / `is_resume` are the emergency words, checked before anything else (see `hub_brain.early`).
"""

import re

from . import lexicon as lx

SETUP = "setup"                 # «مغز ابری را فعال کن», «می‌خواهم کلید API بدهم»
OFF = "off"
STATUS = "status"
PROBE = "probe"
MODEL = "model"
FORGET_KEY = "forget_key"
CHANGE_KEY = "change_key"
PRIVATE_ON = "private_on"
PRIVATE_OFF = "private_off"
HISTORY_CLEAR = "history_clear"
HELP = "help"
MEM_STATUS = "mem_status"       # «چند جواب نگه داشته‌ای؟»
MEM_ON = "mem_on"               # «نگه‌داشتن جواب‌ها را روشن کن»
MEM_OFF = "mem_off"             # «جواب‌ها را نگه نداری» / «نگه‌داشتن جواب‌ها را خاموش کن»
MEM_CLEAR = "mem_clear"         # «جواب‌های نگه‌داشته‌شده را پاک کن»

KINDS = (SETUP, OFF, STATUS, PROBE, MODEL, FORGET_KEY, CHANGE_KEY, PRIVATE_ON, PRIVATE_OFF, HISTORY_CLEAR, HELP,
         MEM_STATUS, MEM_ON, MEM_OFF, MEM_CLEAR)
MAX_CHARS = 400
MAX_TOKENS = 30

_CLOUD = lx.phrases("مغز ابری", "مغز آنلاین", "مغز اینترنتی", "مغز ابر", "هوش ابری", "هوش آنلاین", "ابر مغز", "مغز دوم ابری")
_ON = lx.word_set("فعال روشن راه‌اندازی راه‌انداز راهاندازی وصل اتصال برقرار شروع نصب بساز داشته باشی بشی بشو بگیر بده بدم بدهم بیا")
_OFF = lx.word_set("خاموش غیرفعال قطع ببند نخواه متوقف")
_STATUS = lx.word_set("وضعیت چطوره چطوری چطوریه روشنه وصله کار هست هستش آماده")
_ASK_FROM = lx.word_set("بخواه بخواهی بخواهید بخوای بخواین بخوام بخواهم بپرس بپرسی بپرسید بپرسین بپرسم")
_PROBE = lx.word_set("امتحان تست آزمایش آزمون بررسی چک")
_MODEL = lx.word_set("مدل")
_DEFAULT = lx.word_set("پیش‌فرض پیشفرض")
_KEY = lx.word_set("کلید")
_API = lx.word_set("api ای‌پی‌آی")
_FORGET = lx.word_set("فراموش پاک حذف دور")
_CHANGE = lx.word_set("عوض تغییر جدید تازه عوضش")
_HISTORY = lx.word_set("تاریخچه گفتگو سابقه حافظه")
_PERSONAL = lx.word_set("شخصی خصوصی")
_SEND = lx.word_set("بفرست ارسال بفرستی بفرستید بده")
_NOSEND = lx.word_set("نفرست نفرستی نفرستید ارسال‌نکن")
_QUESTION = lx.word_set("چیست چیه چی چطور چگونه توضیح یعنی")
_MODEL_ID_RE = re.compile(r"(?<![\w.:/@+-])([A-Za-z0-9][A-Za-z0-9._:/@+-]{1,79})(?![\w.:/@+-])")
_NOT_MODEL = frozenset({"api", "ai", "http", "https", "key", "gpt-api"})
_ANSWER_NOUN = frozenset({"جواب", "پاسخ", "جوابها", "پاسخها", "جوابا", "پاسخا"})
_KEEP_WORD = frozenset({"نگه", "نگهدار", "نگهداری", "نگهداشتن", "نگهداشته", "ذخیره", "حافظه", "یادگرفته", "یادگرفتن"})
_MEM_CLEAR = frozenset({"پاک", "حذف", "فراموش", "دور", "خالی"})
_MEM_OFF = frozenset({"خاموش", "غیرفعال", "نکن", "نداری", "ندار", "نده", "نخواه", "قطع", "نگیر"})
_MEM_ON = frozenset({"روشن", "فعال", "دار", "نگهدار", "بدار"})
_MEM_STATUS = frozenset({"چند", "چندتا", "چقدر", "چنده", "وضعیت", "نشان", "لیست", "فهرست", "چیه", "چیست", "داشته", "داری", "داشتی"})
_MEM_MAX_TOKENS = 12
_HALT = frozenset({"ایست", "بایست", "توقف", "استاپ", "stop"})
_RESUME = frozenset({"ادامه", "ازسربگیر", "ازسرگیر", "ادامهبده", "ادامهکن"})


class BrainCommand:
    __slots__ = ("kind", "slots")

    def __init__(self, kind, slots=None):
        self.kind = kind
        self.slots = dict(slots or {})

    def __repr__(self):
        return "BrainCommand(%s, %r)" % (self.kind, self.slots)


def _squash(toks):
    return "".join(toks)


def is_halt(toks):
    """The emergency word on its own («ایست», «بایست», «توقف کن»): one or two tokens, never inside a longer sentence."""
    if not toks or len(toks) > 2:
        return False
    return toks[0] in _HALT and (len(toks) == 1 or toks[1] in {"کن", "کنید", "همه", "شو"})


def is_resume(toks):
    """«ادامه» / «ادامه بده» / «از سر بگیر» - the answer to an emergency stop (only honoured while the app is halted)."""
    if not toks or len(toks) > 3:
        return False
    return _squash(toks) in _RESUME or toks[0] == "ادامه" and len(toks) <= 2


def model_id(text):
    """The model name written in a sentence («gemini-3.8-flash», «gpt-5.4-mini», «openrouter/auto»), or ''."""
    for match in _MODEL_ID_RE.finditer(text or ""):
        word = match.group(1)
        if word.lower() in _NOT_MODEL or word.lower().startswith(("http", "www")):
            continue
        if any(c.isdigit() for c in word) or any(c in word for c in "-./:") or len(word) >= 5:
            return word
    return ""


def _is_cloud(toks):
    return lx.any_phrase(toks, _CLOUD)


def _memory_command(toks):
    """The command about the kept answers, or None. Needs: an answer noun, a keeping word within four words of it, and an action word."""
    if len(toks) > _MEM_MAX_TOKENS:
        return None
    near = False
    for i, tok in enumerate(toks):
        if tok in _ANSWER_NOUN:
            window = toks[max(0, i - 4):i] + toks[i + 1:i + 6]
            if any(w in _KEEP_WORD for w in window):
                near = True
                break
    if not near:
        return None
    tset = set(toks)
    if tset & _MEM_CLEAR:
        return BrainCommand(MEM_CLEAR)
    if tset & _MEM_OFF:
        return BrainCommand(MEM_OFF)
    if tset & _MEM_ON:
        return BrainCommand(MEM_ON)
    if tset & _MEM_STATUS or len(toks) <= 4:
        return BrainCommand(MEM_STATUS)
    return None


def classify(text, norm, toks):
    """A `BrainCommand` or None."""
    if not toks or len(toks) > MAX_TOKENS or len(text or "") > MAX_CHARS:
        return None
    tset = set(toks)
    cloud = _is_cloud(toks)
    if cloud and tset & _ASK_FROM:      # «از مغز ابری‌ات بخواه … بسازد»: a request TO the brain (the teacher route), not a command about it
        return None
    key_noun = bool(tset & _KEY)
    api = bool(tset & _API)
    if cloud or (key_noun and api):
        if tset & _FORGET and key_noun:
            return BrainCommand(FORGET_KEY)
        if tset & _HISTORY and tset & _FORGET:
            return BrainCommand(HISTORY_CLEAR)
        if key_noun and tset & _CHANGE:
            return BrainCommand(CHANGE_KEY)
        if tset & _MODEL:
            mid = model_id(text)
            if mid:
                return BrainCommand(MODEL, {"model": mid})
            if tset & _DEFAULT:
                return BrainCommand(MODEL, {"model": ""})
            return BrainCommand(MODEL, {"missing": True})
        if tset & _PERSONAL:
            if tset & _NOSEND:
                return BrainCommand(PRIVATE_OFF)
            if tset & _SEND:
                return BrainCommand(PRIVATE_ON)
        if tset & _OFF and not tset & _ON:
            return BrainCommand(OFF)
        if tset & _PROBE:
            return BrainCommand(PROBE)
        if tset & _ON or (key_noun and api):
            return BrainCommand(SETUP)
        if tset & _STATUS:
            return BrainCommand(STATUS)
        if tset & _QUESTION:
            return BrainCommand(HELP)
        return BrainCommand(STATUS) if len(toks) <= 3 else None
    if key_noun and tset & _FORGET and len(toks) <= 6:           # «کلید را فراموش کن» (the key is the cloud brain's only key)
        return BrainCommand(FORGET_KEY)
    if key_noun and tset & _CHANGE and len(toks) <= 6 and not tset & _MODEL:
        return BrainCommand(CHANGE_KEY)
    if tset & _PERSONAL and tset & {"ابر", "ابری"} and tset & (_NOSEND | _SEND):
        return BrainCommand(PRIVATE_OFF if tset & _NOSEND else PRIVATE_ON)
    return _memory_command(toks)


__all__ = ["BrainCommand", "classify", "is_halt", "is_resume", "model_id", "KINDS", "SETUP", "OFF", "STATUS", "PROBE", "MODEL",
           "FORGET_KEY", "CHANGE_KEY", "PRIVATE_ON", "PRIVATE_OFF", "HISTORY_CLEAR", "HELP", "MEM_STATUS", "MEM_ON", "MEM_OFF", "MEM_CLEAR"]
