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
# Prompt 959 (corrective): people say «مغز ابریت», «مغز ابری‌ات», «مغز ابریمو», «هوش مصنوعیِ ابری» - the exact phrases above miss them
_CLOUD_NOUN = frozenset({"مغز", "هوش"})
_CLOUD_ADJ = ("ابری", "آنلاین", "اینترنتی")
_CLOUD_SUFFIX = frozenset({"م", "ت", "ش", "مان", "تان", "شان", "مون", "تون", "شون", "مو", "تو", "شو", "ام", "ات", "اش"})
_ON = lx.word_set("فعال روشن راه‌اندازی راه‌انداز راهاندازی وصل اتصال برقرار شروع نصب بساز داشته باشی بشی بشو بگیر بده بدم بدهم بیا "
                  "بنداز بندازیم بندازی بندازم بندازید استفاده")
_OFF = lx.word_set("خاموش غیرفعال قطع ببند نخواه متوقف")
_STATUS = lx.word_set("وضعیت چطوره چطوری چطوریه روشنه وصله کار هست هستش آماده")
_NOT_DO = lx.word_set("نکن نکنی نکنید نکنین نشو نشه نباشه")              # «مغز ابری را خاموش نکن»: the opposite of a switch-off
_WANT = lx.word_set("میخوام میخواهم میخواستم میخوایم خوام خواهم")
_NOT_WANT = lx.word_set("نمیخوام نمیخواهم نخوام نخواهم نمیخوایم")
_HOW = lx.word_set("چجوری چطوری چطور چگونه چیکار چکار چجور")
_HOW_PHRASES = lx.phrases("چه کار", "چی کار", "چه جوری", "چه طوری", "به چه شکل")
_PRIVACY_Q = lx.word_set("امن امنه ایمن ایمنه خطرناک خطرناکه میره میفرستی")
_BUILD_WORDS = lx.word_set("بنویس بنویسه بنویسد بنویسی بسازه بسازد بسازی قابلیت بسته پک پیشنویس افزونه")   # a wish for the teacher route, not a switch-on
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
_QUESTION = lx.word_set("چیست چیه چی چطور چگونه توضیح یعنی چرا فایده دردی")
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


_CLARIFY_FILLER = frozenset({"آخه", "خب", "پس", "ولی", "اصلا", "لطفا", "ببخشید", "هان", "اوه", "وای"})
_CLARIFY = lx.phrases(
    "چرا", "برای چی", "واسه چی", "برای چه", "چه فایده", "فایده اش چیه", "فایده ش چیه", "یعنی چی", "یعنی چه", "چی هست", "چیه", "چیست",
    "این چیه", "این چیست", "چی بنویسم", "چی بگم", "چی بدم", "چی بفرستم", "چیکار کنم", "چکار کنم", "چه کار کنم", "چی کار کنم", "چه کنم",
    "چطوری", "چجوری", "چطور", "چگونه", "از کجا", "کجا", "کجا بگیرم", "کجا میگیرم", "کمک", "کمکم کن", "کمک کن", "راهنمایی", "راهنما",
    "توضیح بده", "توضیح بیشتر", "بیشتر توضیح بده", "بیشتر بگو", "نمی فهمم", "نمیفهمم", "نفهمیدم", "متوجه نشدم", "نمی دونم", "نمیدونم",
    "نمی دانم", "کدوم", "کدام", "کدوم بهتره", "کدام بهتر است", "فرقشون چیه", "فرقشان چیست", "همه چیه", "اینا چیه")


_CLARIFY_START = lx.phrases("چرا", "برای چی", "واسه چی", "برای چه", "چه فایده", "یعنی چی", "یعنی چه")           # may be followed by a few more words
_CLARIFY_ANY = lx.phrases("از کجا", "کجا بگیرم", "کجا میگیرم", "چی بنویسم", "چی بگم", "چی بدم", "چی بفرستم", "چیکار کنم", "چکار کنم",
                          "چه کار کنم", "چی کار کنم", "چه کنم", "نمی فهمم", "نمیفهمم", "نفهمیدم", "متوجه نشدم", "نمی دونم", "نمیدونم",
                          "نمی دانم", "یعنی چی", "یعنی چه", "کدوم بهتره", "کدام بهتر است", "فرقشون چیه", "فرقشان چیست")     # anywhere in a short sentence


_CLARIFY_TOPIC = lx.word_set("باید کلید کلیدمو کلیدم میپرسی میخوای میخواهی لازم لازمه نیاز اجازه سرویس مغز ابری api اینو این اینجا")


def is_clarify(toks):
    """A SHORT question about the question the app just asked («چرا؟», «یعنی چی؟», «از کجا بگیرم؟», «نمی‌فهمم») - never a yes, a no or a cancel.
    Only used while a cloud-brain question is open: the answer explains that step and the same question stays open."""
    words = [t for t in toks if t not in _CLARIFY_FILLER]
    if not words or len(words) > 6 or set(words) & (lx.CONFIRM_WORDS | lx.DENY_WORDS | lx.CANCEL_WORDS):
        return False
    if any(tuple(words[:len(ph)]) == ph for ph in _CLARIFY_START):
        return len(words) <= 2 or bool(set(words) & _CLARIFY_TOPIC)      # «چرا آسمان آبی است؟» is a new question, not about this step
    if len(words) <= 5 and lx.any_phrase(words, _CLARIFY_ANY):
        return True
    return any(tuple(words[:len(ph)]) == ph and len(words) <= len(ph) + 2 for ph in _CLARIFY)


def model_id(text):
    """The model name written in a sentence («gemini-3.8-flash», «gpt-5.4-mini», «openrouter/auto»), or ''."""
    for match in _MODEL_ID_RE.finditer(text or ""):
        word = match.group(1)
        if word.lower() in _NOT_MODEL or word.lower().startswith(("http", "www")):
            continue
        if any(c.isdigit() for c in word) or any(c in word for c in "-./:") or len(word) >= 5:
            return word
    return ""


def _cloud_at(toks, i):
    """How many words a mention of the cloud brain takes at position `i` («مغز ابری», «مغز ابریت», «مغز ابریمو», «هوش مصنوعیِ ابری»); 0 if none."""
    if toks[i] not in _CLOUD_NOUN:
        return 0
    j = i + 1
    if toks[i] == "هوش" and j < len(toks) and toks[j] == "مصنوعی":
        j += 1
    if j >= len(toks):
        return 0
    nxt = toks[j]
    for adj in _CLOUD_ADJ:
        if nxt == adj or (nxt.startswith(adj) and nxt[len(adj):] in _CLOUD_SUFFIX):
            return j - i + 1
    return 0


def _is_cloud(toks):
    return lx.any_phrase(toks, _CLOUD) or any(_cloud_at(toks, i) for i in range(len(toks)))


def _wants(toks):
    """(wants, does_not_want): «می‌خوام …» / «نمی‌خوام …» - the joined «میخوام» and the split «می» + «خوام» are both read."""
    tset = set(toks)
    no = bool(tset & _NOT_WANT) or any(a == "نمی" and b in ("خوام", "خواهم", "خوایم") for a, b in zip(toks, toks[1:]))
    return (not no and bool(tset & _WANT)), no


def _asks_how(toks):
    return bool(set(toks) & _HOW) or lx.any_phrase(toks, _HOW_PHRASES)


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
    wants, not_wants = _wants(toks)
    if cloud and (tset & _ASK_FROM or (wants and tset & _BUILD_WORDS)):
        return None                     # «از مغز ابری‌ات بخواه … بسازد» / «از مغزِ ابری‌ات می‌خوام یه بسته بنویسه»: a request TO the brain (the teacher route)
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
        if not_wants:                   # «نمی‌خوام مغز ابری رو»: the safe reading of «not wanted» is «off» (if it never was on, the answer just says so)
            return BrainCommand(OFF)
        if tset & _OFF and not tset & _ON:
            return BrainCommand(STATUS if tset & _NOT_DO else OFF)      # «مغز ابری را خاموش نکن» is the opposite of a switch-off
        if tset & _PROBE:
            return BrainCommand(PROBE)
        how = _asks_how(toks)
        if tset & _ON or (key_noun and api) or wants:
            return BrainCommand(SETUP, {"how": True} if how else {})    # «چجوری مغز ابریت رو فعال کنم»: the guided setup IS the answer
        if how and "کار" in tset:                                       # «مغز ابری چطور کار می‌کند؟» asks how it works, not how it is doing
            return BrainCommand(HELP)
        if tset & _STATUS:
            return BrainCommand(STATUS)
        if tset & (_QUESTION | _PRIVACY_Q):
            return BrainCommand(HELP)
        return BrainCommand(STATUS) if len(toks) <= 3 else None
    if key_noun and tset & _FORGET and len(toks) <= 6:           # «کلید را فراموش کن» (the key is the cloud brain's only key)
        return BrainCommand(FORGET_KEY)
    if key_noun and tset & _CHANGE and len(toks) <= 6 and not tset & _MODEL:
        return BrainCommand(CHANGE_KEY)
    if tset & _PERSONAL and tset & {"ابر", "ابری"} and tset & (_NOSEND | _SEND):
        return BrainCommand(PRIVATE_OFF if tset & _NOSEND else PRIVATE_ON)
    return _memory_command(toks)


__all__ = ["BrainCommand", "classify", "is_halt", "is_resume", "is_clarify", "model_id", "KINDS", "SETUP", "OFF", "STATUS", "PROBE", "MODEL",
           "FORGET_KEY", "CHANGE_KEY", "PRIVATE_ON", "PRIVATE_OFF", "HISTORY_CLEAR", "HELP", "MEM_STATUS", "MEM_ON", "MEM_OFF", "MEM_CLEAR"]
