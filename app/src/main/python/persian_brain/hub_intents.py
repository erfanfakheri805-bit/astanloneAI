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

from teacher import assistants as _assistants

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
MODEL_IMPORT = "model_import"
ANDROID_STATUS = "android_status"
PERMISSIONS = "permissions"
EXT_PROMPT = "ext_prompt"
EXT_HELP = "ext_help"
REPAIR_STORE = "repair_store"
PACK_LIST = "pack_list"
PACK_HISTORY = "pack_history"
PACK_ROLLBACK = "pack_rollback"
PACK_DISABLE = "pack_disable"
PACK_ENABLE = "pack_enable"
PACK_REMOVE = "pack_remove"
PACK_STATUS = "pack_status"
PACK_SAFE_LEAVE = "pack_safe_leave"
PACK_HELP = "pack_help"
PACK_PROMPT = "pack_prompt"
TEACHER_ASK = "teacher_ask"
TEACHER_CAPTURE = "teacher_capture"
TEACHER_SCREEN = "teacher_screen"
TEACHER_STATUS = "teacher_status"
TEACHER_CANCEL = "teacher_cancel"
TEACHER_LIST = "teacher_list"
TEACHER_REVOKE = "teacher_revoke"
ACCESS_SETTINGS = "access_settings"

KINDS = (OVERVIEW, EXT_LIST, EXT_HISTORY, EXT_ROLLBACK, EXT_DISABLE, EXT_ENABLE, EXT_PERM_GRANT, EXT_PERM_REVOKE, NET_ON,
         NET_OFF, NET_STATUS, FETCH, MODELS_LIST, MODEL_DOWNLOAD, MODEL_PREPARE, MODEL_REMOVE, MODEL_LICENSE, MODEL_IMPORT,
         ANDROID_STATUS, PERMISSIONS, EXT_PROMPT, EXT_HELP, REPAIR_STORE, PACK_LIST, PACK_HISTORY, PACK_ROLLBACK, PACK_DISABLE,
         PACK_ENABLE, PACK_REMOVE, PACK_STATUS, PACK_SAFE_LEAVE, PACK_HELP, PACK_PROMPT, TEACHER_ASK, TEACHER_CAPTURE,
         TEACHER_SCREEN, TEACHER_STATUS, TEACHER_CANCEL, TEACHER_LIST, TEACHER_REVOKE, ACCESS_SETTINGS)

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
_STATUS = lx.word_set("وضعیت")                 # «وضعیت مدل‌ها» is a request to list them
_MODEL_CONTEXT = lx.word_set("محلی زبانی llm gguf onnx tflite ngram دانلود")
_BUILD_VERBS = lx.word_set("بساز بسازی بسازید ایجاد آموزش train بنویس تولید طراحی")
_MODEL_DOWNLOAD = lx.word_set("دانلود download بارگیری")
_MODEL_PREPARE = lx.word_set("آماده بررسی تست آزمون لود بارگذاری فعال")
_MODEL_REMOVE = lx.word_set("حذف پاک بردار")
_MODEL_IMPORT_VERBS = lx.word_set("وارد ایمپورت import")
_MODEL_FILE_RE = re.compile(r"(?<![\w.-])([A-Za-z0-9][A-Za-z0-9._-]{0,98}\.(?:task|gguf|json))(?![\w-])", re.IGNORECASE)
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
_PACK_NOUNS = frozenset({"بسته", "پکیج", "پک"})
_PACK_PLURAL = frozenset({"ها", "های", "هایی"})
_PACK_LANG = lx.word_set("زبان زبانی")
_PACK_DISABLE = lx.word_set("غیرفعال خاموش")
_PACK_REMOVE = lx.word_set("حذف پاک بردار")
_PACK_LEAVE = lx.word_set("تمام خاموش غیرفعال خارج بیرون ببند پایان لغو برگرد")
_PACK_SHORT_LIST = frozenset({"نصب", "شده", "نصبشده", "ها", "های", "هایی", "بسته", "پکیج", "پک", "من", "همه", "تمام"})
_PACK_BLOCK = lx.word_set("اینترنت مدل گوشی سیمکارت اپراتور همراه")
# --- the teacher (asking another assistant / letting the app look into another app) -------------------------------------
_T_PREPOSITIONS = frozenset({"از", "با", "به", "توی", "تو", "داخل", "در", "برنامه", "اپ", "اپلیکیشن", "سایت", "پیش", "نزد"})
_T_ARTICLE = frozenset({"یه", "یک", "یکی"})
_T_ASK = frozenset({"بپرس", "بپرسی", "بپرسید", "بپرسم", "بپرسین", "بخواه", "بخواهی", "بخواهید", "بخوای", "بخواین", "بخواید", "بخواهم",
                    "بخوام", "کمک", "مشورت", "سوال", "سؤال", "بنویس", "بنویسه", "بساز", "بسازه", "بفرست", "بگیر", "بگیری", "برو",
                    "حرف", "صحبت", "یادبگیر", "درخواست"})
_T_OUTSIDE = (("آموزگار",), ("هوش", "مصنوعی", "دیگه"), ("هوش", "مصنوعی", "دیگر"), ("دستیار", "دیگه"), ("دستیار", "دیگر"),
              ("دستیار", "بیرونی"), ("دستیارهای", "بیرونی"))
_T_ANSWER = lx.word_set("جواب پاسخ جوابش پاسخش جواباش")
_T_CAME = lx.word_set("آمد اومد رسید رسیده اومده آمده آماده حاضر شد کپی کردم گرفتم فرستادم اشتراک")
_T_READ = lx.word_set("بخوان بخون بگیر بردار بیار بیاور")
_T_SELF = lx.word_set("خودت")
# «می‌تونی … ؟» asks whether the app CAN; it is a question to answer (see hub_self), not a command to carry out. «می‌شه …» stays a polite request.
_T_ABILITY = lx.phrases("می تونی", "میتونی", "می توانی", "میتوانی", "می تونید", "میتونید", "می توانید", "میتوانید", "بلدی", "بلدید", "قادری",
                        "از دستت بر میاد", "از دستت برمیاد", "امکانش هست")
_T_DO = lx.word_set("انجام تایپ بپرس بفرست بنویس بخوان بخون جلو برو حرف وارد بزن کن")
_T_MISSION = lx.word_set("ماموریت مأموریت ماموریتش")
_T_STATUS = lx.word_set("وضعیت چی چه کجا")
_T_CANCEL = lx.word_set("لغو کنسل بیخیال متوقف توقف بسه")
_T_EXTERNAL = lx.word_set("بیرونی خارجی دیگر دیگه")
_T_ASSISTANT_NOUN = lx.word_set("دستیار دستیارها دستیارهای")
_T_OPEN = lx.word_set("باز نشان نشون برو ببر بیار بیاور")
_T_ACCESS_PAGE = lx.word_set("تنظیمات settings صفحه سرویس service")
_T_LANG_Q = lx.phrases("پرسش و پاسخ", "سوال و جواب", "سؤال و جواب", "پرسش پاسخ")
_T_CAPABILITY = lx.word_set("قابلیت قابلیتی توانایی امکان امکانات بسته افزونه پلاگین ابزار موتور زیرساخت")
_T_QUESTION = lx.word_set("چیه چیست چطور چطوره چرا فرق تفاوت کجاست کیست چند چه")
_T_LEAD_RE = re.compile(r"^.*?(?:بپرس(?:ی|ید|م|ین)?|بخواه(?:ی|ید|م)?|بخوا(?:ی|ین|ید|م)|بگیر(?:ی)?|بنویس(?:ه)?|بساز(?:ه)?|بفرست)(?![\w])", re.S)


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
def classify(raw, norm, toks, named_extension=False, named_pack=False, teacher_open=False):
    """`HubCommand` or None. `raw` is the typed text, `norm` its normalization, `toks` the tokens of `norm`;
    `named_pack` says the sentence names an installed pack (see `pack_system`); `teacher_open` says a mission with another
    assistant is open (so «جواب آمد» or «خودت انجام بده» mean something)."""
    if not toks or len(raw or "") > MAX_COMMAND_CHARS or len(toks) > 120:
        return None
    tset = set(toks)
    stems = _stems(toks)
    has_ext = bool(tset & _EXT) or "افزونه" in norm

    def teacher(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
        return _teacher(raw, norm, toks, tset, stems, has_ext, teacher_open)

    for rule in (_fetch, _repair, _pack_prompt, _prompt, teacher, _model_import, _models, _network, _extensions, _packs, _android, _permissions_rule,
                 _overview):
        found = rule(raw, norm, toks, tset, stems, has_ext, named_extension, named_pack)
        if found is not None:
            return found
    return None


def _teacher_wish(raw):
    """What the user wants from the other assistant: the words after the first asking verb ("از ChatGPT بخواه ⟨…⟩")."""
    found = _T_LEAD_RE.match(raw or "")
    if not found:
        return ""
    rest = (raw or "")[found.end():]
    rest = re.sub(r"^[\s،,:;؛.!؟?-]+", "", rest)
    rest = re.sub(r"^که\s+", "", rest)
    rest = rest.strip(" ?؟.!،")
    return rest[:600] if sum(ch.isalpha() for ch in rest) >= 4 else ""


def _teacher_kind(tset, toks, norm):
    if lx.any_phrase(toks, _T_LANG_Q) or ("زبان" in tset and (tset & {"بسته", "داده", "داده‌ها"})):
        return "lang"
    asking = norm.rstrip().endswith("?") or bool(tset & _T_QUESTION)
    if asking and not tset & _T_CAPABILITY and not (tset & {"بساز", "بسازه", "درست", "اضافه", "یادبگیر"} or "یاد" in tset):
        return "ask"
    return "code"


def _mentions_outside_assistant(toks):
    """`(assistant id or '', mention end)` when the sentence names an assistant (after «از/با/توی …») or "another assistant"."""
    found = _assistants.find_in_tokens(toks)
    if found is not None:
        assistant_id, start, end = found
        if start > 0 and toks[start - 1] in _T_PREPOSITIONS:
            return assistant_id, end
        if start > 1 and toks[start - 2] in _T_PREPOSITIONS and toks[start - 1] in ("برنامه", "اپ", "اپلیکیشن", "ی", "گوگل", "مایکروسافت"):
            return assistant_id, end
        return None
    for phrase in _T_OUTSIDE:
        n = len(phrase)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i:i + n]) != phrase:
                continue
            before = toks[i - 1] if i > 0 else ""
            if before in _T_ARTICLE and i > 1:
                before = toks[i - 2]
            if before in _T_PREPOSITIONS or phrase == ("آموزگار",):
                return "", i + n
    return None


_OWN_BRAIN_WORD = frozenset({"مغزت", "مغزتو", "مغزتان", "مغزتون"})
_OWN_BRAIN_NOUN = frozenset({"مغز", "هوش"})
_OWN_BRAIN_ADJ = ("ابری", "آنلاین", "اینترنتی")
_OWN_BRAIN_SUFFIX = frozenset({"م", "ت", "ش", "مان", "تان", "شان", "مون", "تون", "شون"})     # «ابری‌ام», «ابریت», «ابریتون»


def _own_brain_len(toks, i):
    """How many words a mention of the user's OWN cloud brain takes at position `i` («مغزت», «مغز ابری», «مغز ابریم», «مغز خودت»); 0 if none."""
    tok = toks[i]
    if tok in _OWN_BRAIN_WORD:
        return 1
    nxt = toks[i + 1] if i + 1 < len(toks) else ""
    if tok in _OWN_BRAIN_NOUN and nxt:
        if nxt in ("خودت", "خودتان", "خودتون"):
            return 2 if tok == "مغز" else 0
        for adj in _OWN_BRAIN_ADJ:
            if nxt == adj or (nxt.startswith(adj) and nxt[len(adj):] in _OWN_BRAIN_SUFFIX):
                return 2
        if tok == "مغز" and nxt == "ابر":
            return 2
    if tok == "ابر" and nxt == "مغز":
        return 2
    return 0


def _mentions_own_brain(toks):
    """The user's OWN cloud brain named after a preposition («از مغزت بخواه …», «از مغز ابری‌ات بپرس …»): the index after the name, else None."""
    for i in range(1, len(toks)):
        if toks[i - 1] in _T_PREPOSITIONS:
            n = _own_brain_len(toks, i)
            if n:
                return i + n
    return None


def _own_brain_ask(raw, norm, toks, tset, stems):
    """«از مغزت بخواه برایم X بسازد» / «از مغز ابری‌ات بپرس X»: a request TO the user's own cloud brain (never the commands ABOUT it)."""
    if _mentions_own_brain(toks) is None or not (tset & _T_ASK or stems & _T_ASK):
        return None
    wish = _teacher_wish(raw)
    if not wish and lx.any_phrase(toks, _T_ABILITY):       # «می‌تونی از مغزت کمک بگیری؟» is a question about the app (hub_self), not a request
        return None
    return HubCommand(TEACHER_ASK, {"assistant": "brain", "wish": wish, "kind": _teacher_kind(tset, toks, norm), "auto": False})


def _teacher(raw, norm, toks, tset, stems, has_ext, teacher_open):
    """Asking another assistant, and what follows: the answer arrived, let the app do it itself, status, cancel, list, revoke."""
    if has_ext:                                            # a sentence about extensions belongs to the extension commands - except a plain request TO the cloud brain
        return _own_brain_ask(raw, norm, toks, tset, stems) if _mentions_outside_assistant(toks) is None else None
    # the accessibility settings page (the user switches the service on himself - the app can only open the page)
    access_word = ("دسترس" in tset or "دسترسی" in tset) and "پذیری" in tset or "accessibility" in tset     # Android's Persian label drops the «ی»; people type both
    if access_word and tset & _T_ACCESS_PAGE and (tset & _T_OPEN or len(toks) <= 5):
        return HubCommand(ACCESS_SETTINGS)
    # take back the permission to look into other apps
    if (_starts(toks, ("اجازه", "دسترس")) and "برنامه" in tset and stems & _REVOKE) or (
            "سر" in tset and "نزن" in tset and "برنامه" in tset):
        return HubCommand(TEACHER_REVOKE)
    # which outside assistants are there
    if tset & _T_ASSISTANT_NOUN and tset & _T_EXTERNAL and (stems & _LIST or "نصب" in tset) and "پرامپت" not in tset:
        return HubCommand(TEACHER_LIST)
    mission = bool(tset & _T_MISSION)
    if mission and tset & _T_CANCEL:                       # the word «ماموریت» itself makes these two unambiguous
        return HubCommand(TEACHER_CANCEL)
    if mission and tset & _T_STATUS:
        return HubCommand(TEACHER_STATUS)
    if teacher_open:
        if tset & _T_ANSWER and tset & _T_CAME and len(toks) <= 12:
            return HubCommand(TEACHER_CAPTURE)
        if "کلیپ" in tset and "بورد" in tset and stems & _T_READ:
            return HubCommand(TEACHER_CAPTURE)
        if tset & _T_SELF and tset & _T_DO and len(toks) <= 12:
            return HubCommand(TEACHER_SCREEN)
        if tset & _T_CANCEL and _assistants.find_in_tokens(toks) is not None and len(toks) <= 9:
            return HubCommand(TEACHER_CANCEL)
    mention = _mentions_outside_assistant(toks)
    if mention is None:
        own = _own_brain_ask(raw, norm, toks, tset, stems)
        if own is not None:
            return own
    if mention is not None and (tset & _T_ASK or "یاد" in tset and ("بگیر" in tset or "بده" in tset) or stems & _T_ASK):
        assistant_id, _end = mention
        wish = _teacher_wish(raw)
        if not wish and lx.any_phrase(toks, _T_ABILITY):   # «می‌تونی از کلود کمک بگیری؟»: a question about the app, answered by hub_self - it never
            return None                                    # picks up an old wish and prepares a request nobody asked for
        return HubCommand(TEACHER_ASK, {"assistant": assistant_id, "wish": wish, "kind": _teacher_kind(tset, toks, norm),
                                        "auto": bool(tset & _T_SELF or "خودکار" in tset)})
    return None


def _fetch(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    url = _url(raw)
    if url and stems & _READ:
        return HubCommand(FETCH, {"url": url})
    return None


def _repair(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if has_ext and stems & _REPAIR and tset & _STORE:
        return HubCommand(REPAIR_STORE)
    return None


def _prompt(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if tset & _PROMPT:
        return HubCommand(EXT_PROMPT, {"wish": _wish(norm, toks)})
    if (has_ext or (_starts(toks, ("قابلیت",)) and tset & _NEW)) and tset & _HOW and stems & _ADD:
        return HubCommand(EXT_HELP)
    if has_ext and ("چیست" in tset or "چیه" in tset or lx.any_phrase(toks, lx.phrases("یعنی چی", "یعنی چه"))):
        return HubCommand(EXT_HELP)
    return None


def _model_import(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    """«مدل را از فایل وارد کن» / «مدل gemma.task را وارد کن»: import a model file the user picked himself (it waits in the app's inbox).
    The file name, when the sentence has one, is read from the typed text (the normalized words split a name at every dot and dash)."""
    if has_ext or named_pack or not stems & _MODEL_IMPORT_VERBS or tset & _NET or stems & _BUILD_VERBS:
        return None
    about_model = bool(tset & _MODEL)
    named_file = _MODEL_FILE_RE.search(raw or "")
    if named_file:
        name = named_file.group(1)
        if name.lower().endswith(".json") and not about_model:          # a plain .json is far more likely a pack than a model
            return None
        return HubCommand(MODEL_IMPORT, {"file": name})
    return HubCommand(MODEL_IMPORT, {"file": None}) if about_model else None


def _models(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if not tset & _MODEL or has_ext or stems & _BUILD_VERBS:
        return None
    plural = "ها" in toks or "های" in toks
    mid = _model_id(raw)
    accepts = bool(tset & _LICENSE and tset & _ACCEPT)
    download, remove, prepare = bool(stems & _MODEL_DOWNLOAD), bool(stems & _MODEL_REMOVE), bool(stems & _MODEL_PREPARE)
    context = bool(tset & _MODEL_CONTEXT or (plural and tset & _LIST) or (tset & _STATUS and len(toks) <= 4) or (plural and len(toks) == 2))
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


def _network(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
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


def _extensions(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
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


def _android(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if tset & _ANDROID and (tset & _ANDROID_TOPIC or _starts(toks, _PERMISSION_NOUNS[:2])) and not has_ext:
        return HubCommand(ANDROID_STATUS)
    return None


def _permissions_rule(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if _starts(toks, _PERMISSION_NOUNS) and (stems & _LIST or tset & _NET_STATUS) and not has_ext and not tset & _MODEL:
        return HubCommand(PERMISSIONS)
    return None


def _overview(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    if tset & _MAP and _starts(toks, _CAP_STEMS):
        return HubCommand(OVERVIEW)
    if lx.any_phrase(toks, lx.phrases("وضعیت کامل", "نقشه کامل")):
        return HubCommand(OVERVIEW)
    if (tset & _CANT or lx.any_phrase(toks, _CANT_PHRASES)) and tset & _WHICH and not has_ext:
        return HubCommand(OVERVIEW, {"missing": True})
    return None


def _pack_prompt(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    """«پرامپت بسته …»: the request to hand to an assistant that writes a code pack (or, with «زبان», a language pack)."""
    if has_ext or not tset & _PROMPT or not tset & _PACK_NOUNS:
        return None
    return HubCommand(PACK_PROMPT, {"wish": _wish(norm, toks), "kind": "lang" if tset & _PACK_LANG else "code"})


def _packs(raw, norm, toks, tset, stems, has_ext, named, named_pack=False):
    """The pack system's own commands: list / history / status / roll back / switch off or on / remove / safe mode / help."""
    if has_ext:
        return None                                        # «افزونه» sentences belong to the extension rules
    if "حالت" in tset and "امن" in tset:
        if stems & _PACK_LEAVE:
            return HubCommand(PACK_SAFE_LEAVE)
        return HubCommand(PACK_STATUS, {"safe": True})
    has_noun = bool(tset & _PACK_NOUNS)
    if not (has_noun or named_pack) or tset & _PACK_BLOCK:
        return None
    if stems & _HISTORY:
        return HubCommand(PACK_HISTORY)
    if stems & _ROLLBACK or (tset & _ROLLBACK_WORDS_EXTRA and "نسخه" in tset):
        return HubCommand(PACK_ROLLBACK, {"version": _version(toks)})
    if stems & _PACK_REMOVE:
        return HubCommand(PACK_REMOVE)
    if stems & _PACK_DISABLE:
        return HubCommand(PACK_DISABLE)
    if stems & _ENABLE and (tset & _WANT or len(toks) <= 6):
        return HubCommand(PACK_ENABLE)
    if "وضعیت" in tset:
        return HubCommand(PACK_STATUS)
    if not has_noun:
        return None
    if tset & _HOW and (stems & _ADD or stems & _INSTALL_VERBS):
        return HubCommand(PACK_HELP)
    if "چیست" in tset or "چیه" in tset or lx.any_phrase(toks, lx.phrases("یعنی چی", "یعنی چه")):
        return HubCommand(PACK_HELP)
    if stems & _LIST or lx.any_phrase(toks, _INSTALLED) or (tset & _PACK_PLURAL and tset <= _PACK_SHORT_LIST):
        return HubCommand(PACK_LIST)
    return None


__all__ = ["HubCommand", "classify", "KINDS", "MAX_COMMAND_CHARS"] + [k.upper() for k in KINDS]
