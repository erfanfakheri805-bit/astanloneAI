"""
Persian conversation brain - hub commands
=========================================
`classify(raw, norm, toks, named_extension)` says which HUB command (if any) one Persian sentence is: the capability
map, the installed extensions (list / history / roll back / switch off or on / permissions), the internet switch,
reading a web page, local models, Android status, the extension prompt, and repairing a damaged extension store.

Like `intents.py` it is a pure, deterministic cascade over normalized tokens and small closed word lists - there is no
table of whole sentences and no call to any service. A sentence is a hub command only when it carries one of the hub's
own nouns (افزونه, اینترنت, مدل, نقشه, پرامپت, a web address ...) next to an action word, so ordinary conversation, the
Self-Builder commands («لیست قابلیت‌ها», «برگردان») and personal facts are never taken over.
"""

import re

from self_builder import fa_text

from . import lexicon as lx

OVERVIEW = "overview"
EXT_LIST = "ext_list"
EXT_HISTORY = "ext_history"
EXT_ROLLBACK = "ext_rollback"
EXT_DISABLE = "ext_disable"
EXT_ENABLE = "ext_enable"
EXT_PERM_GRANT = "ext_perm_grant"
EXT_PERM_REVOKE = "ext_perm_revoke"
NET_ON = "net_on"
NET_OFF = "net_off"
NET_STATUS = "net_status"
FETCH = "fetch"
MODELS_LIST = "models_list"
MODEL_DOWNLOAD = "model_download"
MODEL_PREPARE = "model_prepare"
MODEL_REMOVE = "model_remove"
MODEL_LICENSE = "model_license"
ANDROID_STATUS = "android_status"
PERMISSIONS = "permissions"
EXT_PROMPT = "ext_prompt"
EXT_HELP = "ext_help"
REPAIR_STORE = "repair_store"

KINDS = (OVERVIEW, EXT_LIST, EXT_HISTORY, EXT_ROLLBACK, EXT_DISABLE, EXT_ENABLE, EXT_PERM_GRANT, EXT_PERM_REVOKE, NET_ON,
         NET_OFF, NET_STATUS, FETCH, MODELS_LIST, MODEL_DOWNLOAD, MODEL_PREPARE, MODEL_REMOVE, MODEL_LICENSE,
         ANDROID_STATUS, PERMISSIONS, EXT_PROMPT, EXT_HELP, REPAIR_STORE)

MAX_COMMAND_CHARS = 700
_URL_RE = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)
_URL_TAIL = ".,;:!?)]}،؛؟»"
_MODEL_ID_RE = re.compile(r"(?<![\w.-])[A-Za-z0-9][A-Za-z0-9._-]{1,63}(?![\w.-])")
_NOT_MODEL_IDS = frozenset({"gguf", "onnx", "tflite", "llm", "ngram", "json", "ai", "ext", "https", "http"})
_OBJECT_CLITICS = ("شون", "شو", "ش")


class HubCommand:
    """One classification result (plain data)."""

    __slots__ = ("kind", "slots")

    def __init__(self, kind, slots=None):
        self.kind = kind
        self.slots = dict(slots or {})

    def __repr__(self):
        return "HubCommand(%s, %r)" % (self.kind, self.slots)


# ------------------------------------------------------------------ word lists
_EXT = lx.word_set("افزونه پلاگین اکستنشن")
_LIST = lx.word_set("لیست فهرست نشان نشون بده بگو ببینم نمایش داری دارید چه کدام کدوم چی")
_INSTALLED = lx.phrases("نصب شده", "نصب شده ها", "نصب شدهها")
_INSTALL_VERBS = lx.word_set("نصب بساز اضافه دانلود")
_HISTORY = lx.HISTORY_WORDS
_ROLLBACK = lx.ROLLBACK_WORDS
_ROLLBACK_WORDS_EXTRA = lx.word_set("قبلی پیشین")
_DISABLE = lx.word_set("غیرفعال خاموش حذف پاک")
_ENABLE = lx.word_set("فعال روشن")
_GRANT = lx.word_set("بده بدهید بدین اجازه مجاز")
_REVOKE = lx.word_set("بگیر بگیرید لغو سلب بردار پس قطع")
_PERMISSION_NOUNS = ("مجوز", "دسترسی", "اجازه")
_PERM_WORDS = {"network": lx.word_set("اینترنت شبکه network"),
               "clock": lx.word_set("ساعت زمان clock"),
               "storage": lx.word_set("حافظه ذخیره storage")}
_NET = lx.word_set("اینترنت")
_NET_ON = lx.word_set("روشن فعال وصل باز اجازه")
_NET_OFF = lx.word_set("خاموش قطع غیرفعال ببند بسته")
_NET_STATUS = lx.word_set("وضعیت آنلاین آفلاین")
_NET_STATE_WORDS = lx.word_set("وصل وصله قطع قطعه روشن روشنه خاموش خاموشه فعال فعاله هست است چطوره")
_WANT = lx.word_set("کن بکن بکنید کنید شو بشو بشه شه شود بشود میخوام میخواهم میخوایم بزن بزنید بده بدید")
_SEARCH_WORDS = lx.word_set("جستجو سرچ بگرد search گوگل")
_READ = lx.word_set("بخوان بخون بخوانید بخونید بیاور ببین ببینید بررسی باز مطالعه محتوا محتوای متن خلاصه واکشی دریافت fetch read")
_MODEL = lx.word_set("مدل")
_MODEL_CONTEXT = lx.word_set("محلی زبانی llm gguf onnx tflite ngram دانلود")
_BUILD_VERBS = lx.word_set("بساز بسازی بسازید ایجاد آموزش train بنویس تولید طراحی")
_MODEL_DOWNLOAD = lx.word_set("دانلود download بارگیری")
_MODEL_PREPARE = lx.word_set("آماده بررسی تست آزمون لود بارگذاری فعال")
_MODEL_REMOVE = lx.word_set("حذف پاک بردار")
_LICENSE = lx.word_set("مجوز لایسنس license شرایط")
_ACCEPT = lx.word_set("میپذیرم پذیرم پذیرفتم قبول موافقم تایید")
_ANDROID = lx.word_set("اندروید گوشی موبایل دستگاه")
_ANDROID_TOPIC = lx.word_set("وضعیت امکانات قابلیت")
_PROMPT = lx.word_set("پرامپت prompt")
_HOW = lx.word_set("چطور چطوری چگونه چجوری")
_ADD = lx.word_set("اضافه نصب بسازم درست بسازیم اضافهکنم بدهم یادت")
_NEW = lx.word_set("جدید تازه")
_REPAIR = lx.word_set("ترمیم تعمیر بازسازی درست")
_STORE = lx.word_set("حافظه پایگاه دیتابیس ذخیره")
_MAP = lx.word_set("نقشه")
_CAP_STEMS = ("قابلیت", "توانایی", "امکانات")
_CANT = lx.word_set("نداری نمیتونی نمیتوانی نمیدونی ناتوانی")
_CANT_PHRASES = lx.phrases("بلد نیستی", "نمی تونی", "نمی توانی", "نمی دونی", "از دستت برنمیاد", "از دستت بر نمیاد")
_ASSISTANTS = frozenset({"chatgpt", "gpt", "claude", "gemini", "copilot", "دستیار", "هوش"})
_WHICH = lx.word_set("چه چی کدام کدوم چیزهایی چیزایی کارهایی کارایی هنوز")


def _stems(toks):
    out = set(toks)
    for t in toks:
        for clitic in _OBJECT_CLITICS:
            if t.endswith(clitic) and len(t) - len(clitic) >= 3:
                out.add(t[:-len(clitic)])
                break
    return out


def _starts(toks, stems):
    return any(t.startswith(s) for t in toks for s in stems)


def _url(raw):
    m = _URL_RE.search(raw or "")
    if not m:
        return None
    url = m.group(0).rstrip(_URL_TAIL)
    return url if len(url) > 8 else None


def _model_id(raw):
    for m in _MODEL_ID_RE.finditer(raw or ""):
        word = m.group(0).lower()
        if word not in _NOT_MODEL_IDS and re.search(r"[a-z]", word):
            return word
    return None


def _version(toks):
    for i, t in enumerate(toks[:-1]):
        if t in ("نسخه", "ورژن", "نسخهی"):
            n = fa_text.parse_number(toks[i + 1])
            if isinstance(n, (int, float)) and not isinstance(n, bool) and n == int(n) and 0 < n < 10 ** 6:
                return int(n)
    return None


def _permissions(toks):
    tset = set(toks)
    return [name for name, words in _PERM_WORDS.items() if tset & words]


def _wish(norm, toks):
    """The user's own wish inside «پرامپت افزونه برای …»: the words after the first «برای» that follows the prompt word
    (and, when that part starts with the name of an assistant, the words after its «که»)."""
    words = norm.split()
    for i, w in enumerate(words):
        if w.lower() in _PROMPT:
            for j in range(i + 1, len(words) - 1):
                if words[j] == "برای":
                    rest = words[j + 1:]
                    if "که" in rest[:-1] and any(x.lower() in _ASSISTANTS for x in rest[:rest.index("که")]):
                        rest = rest[rest.index("که") + 1:]
                    return " ".join(rest).strip(" ?؟.!،")[:600]
            break
    return ""


# ------------------------------------------------------------------ the cascade
def classify(raw, norm, toks, named_extension=False):
    """`HubCommand` or None. `raw` is the typed text, `norm` its normalization, `toks` the tokens of `norm`."""
    if not toks or len(raw or "") > MAX_COMMAND_CHARS or len(toks) > 120:
        return None
    tset = set(toks)
    stems = _stems(toks)
    has_ext = bool(tset & _EXT) or "افزونه" in norm
    for rule in (_fetch, _repair, _prompt, _models, _network, _extensions, _android, _permissions_rule, _overview):
        found = rule(raw, norm, toks, tset, stems, has_ext, named_extension)
        if found is not None:
            return found
    return None


def _fetch(raw, norm, toks, tset, stems, has_ext, named):
    url = _url(raw)
    if url and stems & _READ:
        return HubCommand(FETCH, {"url": url})
    return None


def _repair(raw, norm, toks, tset, stems, has_ext, named):
    if has_ext and stems & _REPAIR and tset & _STORE:
        return HubCommand(REPAIR_STORE)
    return None


def _prompt(raw, norm, toks, tset, stems, has_ext, named):
    if tset & _PROMPT:
        return HubCommand(EXT_PROMPT, {"wish": _wish(norm, toks)})
    if (has_ext or (_starts(toks, ("قابلیت",)) and tset & _NEW)) and tset & _HOW and stems & _ADD:
        return HubCommand(EXT_HELP)
    if has_ext and ("چیست" in tset or "چیه" in tset or lx.any_phrase(toks, lx.phrases("یعنی چی", "یعنی چه"))):
        return HubCommand(EXT_HELP)
    return None


def _models(raw, norm, toks, tset, stems, has_ext, named):
    if not tset & _MODEL or has_ext or stems & _BUILD_VERBS:
        return None
    plural = "ها" in toks or "های" in toks
    mid = _model_id(raw)
    accepts = bool(tset & _LICENSE and tset & _ACCEPT)
    download, remove, prepare = bool(stems & _MODEL_DOWNLOAD), bool(stems & _MODEL_REMOVE), bool(stems & _MODEL_PREPARE)
    context = bool(tset & _MODEL_CONTEXT or (plural and tset & _LIST))
    if not (context or (mid and (accepts or download or remove or prepare))):
        return None
    if accepts:
        return HubCommand(MODEL_LICENSE, {"model_id": mid})
    if download:
        return HubCommand(MODEL_DOWNLOAD, {"model_id": mid})
    if remove:
        return HubCommand(MODEL_REMOVE, {"model_id": mid})
    if prepare and (mid or not tset & _LIST):
        return HubCommand(MODEL_PREPARE, {"model_id": mid})
    return HubCommand(MODELS_LIST, {"model_id": mid})


def _network(raw, norm, toks, tset, stems, has_ext, named):
    if not tset & _NET or stems & _SEARCH_WORDS or has_ext:
        return None
    ask = norm.rstrip().endswith("?") or "آیا" in tset
    wants = bool(stems & _WANT) or "می خوام" in norm
    if wants and not ask and stems & _NET_OFF:
        return HubCommand(NET_OFF)
    if wants and not ask and stems & _NET_ON:
        return HubCommand(NET_ON)
    if len(toks) <= 7 and (tset & _NET_STATUS or (ask and tset & _NET_STATE_WORDS)):
        return HubCommand(NET_STATUS)
    return None


def _extensions(raw, norm, toks, tset, stems, has_ext, named):
    if not (has_ext or named):
        return None
    if stems & _HISTORY:
        return HubCommand(EXT_HISTORY)
    if stems & _ROLLBACK or (tset & _ROLLBACK_WORDS_EXTRA and "نسخه" in tset):
        return HubCommand(EXT_ROLLBACK, {"version": _version(toks)})
    perm_noun = _starts(toks, _PERMISSION_NOUNS)
    if perm_noun and stems & _REVOKE:
        return HubCommand(EXT_PERM_REVOKE, {"permissions": _permissions(toks)})
    if perm_noun and stems & _GRANT:
        return HubCommand(EXT_PERM_GRANT, {"permissions": _permissions(toks)})
    if stems & _DISABLE:
        return HubCommand(EXT_DISABLE)
    if stems & _ENABLE and (tset & _WANT or len(toks) <= 5):
        return HubCommand(EXT_ENABLE)
    if has_ext and not named:
        listing = bool(stems & _LIST) or lx.any_phrase(toks, _INSTALLED)
        if listing or (len(toks) <= 3 and not stems & _INSTALL_VERBS):
            return HubCommand(EXT_LIST)
    return None


def _android(raw, norm, toks, tset, stems, has_ext, named):
    if tset & _ANDROID and (tset & _ANDROID_TOPIC or _starts(toks, _PERMISSION_NOUNS[:2])) and not has_ext:
        return HubCommand(ANDROID_STATUS)
    return None


def _permissions_rule(raw, norm, toks, tset, stems, has_ext, named):
    if _starts(toks, _PERMISSION_NOUNS) and (stems & _LIST or tset & _NET_STATUS) and not has_ext and not tset & _MODEL:
        return HubCommand(PERMISSIONS)
    return None


def _overview(raw, norm, toks, tset, stems, has_ext, named):
    if tset & _MAP and _starts(toks, _CAP_STEMS):
        return HubCommand(OVERVIEW)
    if lx.any_phrase(toks, lx.phrases("وضعیت کامل", "نقشه کامل")):
        return HubCommand(OVERVIEW)
    if (tset & _CANT or lx.any_phrase(toks, _CANT_PHRASES)) and tset & _WHICH and not has_ext:
        return HubCommand(OVERVIEW, {"missing": True})
    return None


__all__ = ["HubCommand", "classify", "KINDS", "MAX_COMMAND_CHARS"] + [k.upper() for k in KINDS]
