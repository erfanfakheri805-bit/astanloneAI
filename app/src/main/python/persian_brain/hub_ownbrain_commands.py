"""
Persian conversation brain - which sentences are about the OWN BRAIN («مغز خودکار»)  (Prompt 959, stage B)
==========================================================================================================
`classify(text, norm, toks)` says which own-brain command (if any) one Persian sentence is: get a brain for itself, say how it stands,
stop or continue the download, delete it, test it, try again, or explain it.

Like `hub_brain_commands` it is a pure, deterministic cascade over normalized tokens and small closed word lists, and a sentence is a
command only when it NAMES the thing («مغز», «هوش مصنوعیِ خودت», «مدل زبانیِ خودت») next to an action word:

* the CLOUD brain is never taken over - «مغز ابری», «مغز آنلاین», a key or an API next to the word (unless the user says «بدون کلید»);
* «از مغزت بخواه …», «از مغزت بپرس …», «از مغزت کمک بگیر» are requests TO a brain (the teacher route), never «get a brain»;
* a few short phrases have no noun («دانلود را متوقف کن», «ادامه دانلود», «دوباره امتحان کن»): they are marked `bare` and the conversation
  module only acts on them while the own brain has a download/failed state to act on - otherwise another command may have them.

`choose_word(toks)` (a choice between the two brains) and `confirm_word(toks)` (a yes/no for the consent question) serve the open question.
"""

from . import intents as I
from . import lexicon as lx

GET = "get"                    # «مغز خودت را بگیر», «خودت مغز برای خودت فراهم کن», «می‌خوام مغز داشته باشی»
STATUS = "status"              # «وضعیت مغز», «مغزت چه شد؟», «دانلود مغز چقدر مونده؟»
PAUSE = "pause"                # «دانلود مغز را متوقف کن»
RESUME = "resume"              # «ادامه دانلود مغز»
DELETE = "delete"              # «مغز را پاک کن»
TEST = "test"                  # «مغز را آزمایش کن», «مغزت کار می‌کند؟»
RETRY = "retry"                # «مغز را دوباره امتحان کن»
HELP = "help"                  # «مغز خودکار چیست؟», «مغز چقدر جا می‌گیرد؟»

KINDS = (GET, STATUS, PAUSE, RESUME, DELETE, TEST, RETRY, HELP)
MAX_CHARS = 300
MAX_TOKENS = 22


class OwnBrainCommand:
    __slots__ = ("kind", "slots")

    def __init__(self, kind, slots=None):
        self.kind = kind
        self.slots = dict(slots or {})

    def __repr__(self):
        return "OwnBrainCommand(%s, %r)" % (self.kind, self.slots)


# ---------------------------------------------------------------------------------------------------- word lists
_SUFFIX = frozenset({"م", "ت", "ش", "مان", "تان", "شان", "مون", "تون", "شون", "مو", "تو", "شو", "ام", "ات", "اش", "ی", "ه", "ها", "های"})
_SELF = lx.word_set("خودت خودتو خودتون خودش خودشو")
_AI = lx.phrases("هوش مصنوعی", "هوش مصنوعی خودت", "مدل زبانی", "مدل زبان", "مغز زبانی")
_CLOUDISH = lx.word_set("ابری ابر آنلاین اینترنتی")
_KEYISH = lx.word_set("کلید api key توکن")
_WITHOUT = lx.word_set("بدون بی نیازی نیاز")
_ASK_FROM = lx.word_set("بخواه بخواهی بخواهید بخوای بخواین بخوام بخواهم بپرس بپرسی بپرسید بپرسین بپرسم کمک کمکم")
_WANT = lx.word_set("میخوام میخواهم میخواستم میخوایم خوام خواهم خواستم")
_GET = lx.word_set("بگیر بگیری بگیره بگیرید بگیرم بگیریم بگیرین بگیرش فراهم تهیه پیدا بیار بیاری بیاور بیارم دانلود نصب بساز بسازی بسازم بسازید "
                   "فعال روشن شروع راه‌اندازی راه‌انداز راهاندازی تامین تأمین مجهز")
_GET_PHRASES = lx.phrases("راه بیانداز", "راه بنداز", "راه بندازی", "داشته باشی", "داشته باشه", "برای خودت", "به دست بیار")
_PROVIDE = lx.word_set("فراهم تهیه تامین تأمین")
_NEED = lx.word_set("لازم نداری نداره نیاز کمبود نیازه")
_INDEP = lx.word_set("مستقل خودکفا")
_DELETE = lx.word_set("پاک حذف نابود بردار")
_DELETE_PHRASES = lx.phrases("دور بریز", "دور بینداز", "فضا آزاد", "جا آزاد", "جا باز", "فضا باز")
_STOP = lx.word_set("متوقف توقف لغو کنسل بایست بس وایسا صبر قطع بیخیال")
_STOP_PHRASES = lx.phrases("نگه دار", "نگهدار", "دست نگه دار", "بس کن", "صبر کن", "قطعش کن")
_RESUME = lx.word_set("ادامه")
_RESUME_PHRASES = lx.phrases("از سر بگیر", "از سر گیر", "از سرگیری", "دوباره ادامه")
_TRY = lx.word_set("امتحان آزمایش آزمون تست چک بررسی")
_AGAIN = lx.word_set("دوباره مجدد مجددا باز")
_AGAIN_PHRASES = lx.phrases("از نو", "یک بار دیگه", "یه بار دیگه", "یکبار دیگه")
_RESTART = lx.word_set("راه‌اندازی راه‌انداز راهاندازی بارگذاری لود تلاش")
_WORKS_PHRASES = lx.phrases("کار می کنه", "کار میکنه", "کار می کند", "کار میکند", "سالمه", "درسته", "جواب می ده", "جواب میده", "جواب می‌دهد")
_HELP = lx.word_set("چیه چیست توضیح فایده حجم فضا هزینه پول قیمت امنه امن خطر ریسک باتری رم کندی گیگ گیگابایت سایز مصرف چرا مضر "
                    "ارزونه گرونه")
_HELP_PHRASES = lx.phrases("چی هست", "یعنی چی", "یعنی چه", "چطور کار", "چجوری کار", "چگونه کار", "چه فرقی", "چه جوری کار", "چه طوری کار",
                           "چقدر جا", "چقدر فضا", "چقدر حجم", "چقدر رم")
_STATUS = lx.word_set("وضعیت پیشرفت درصد آماده تموم تمام مونده مانده رسید رسیده")
_STATUS_PHRASES = lx.phrases("چه شد", "چی شد", "چطور شد", "چی شده", "چه خبر", "چطوره", "تموم شد", "تمام شد", "آماده شد", "آماده شده", "آماده است",
                             "چقدر شد", "چقدر مونده", "چقدر مانده", "چقدر باقی مانده", "کی آماده", "کی تموم", "کی تمام")
_DOWNLOAD = lx.word_set("دانلود دانلودش")
_OWN_MARK = lx.word_set("خودت خودتو خودتون خودش خودکار آفلاین محلی مستقل داخلی گوشی گوشیم دانلود نصب بدون "
                        "بگیر بگیرم بگیری بگیره بگیرید بگیرش فراهم تهیه")     # «مغز بگیرم»: nobody «gets» a human brain
_FREE = lx.word_set("رایگان مجانی")                                       # «مغز رایگان بگیر» is an order; «رایگانه؟» (a question) is not
_QUESTION = lx.word_set("آیا چیه چیست چقدر چرا چطور چجوری چگونه مگه دارد داره هست")
_ATTRIBUTE_OF = lx.word_set("بدون بی")                                    # «بدون هزینه», «بی‌پول»: the next word is a property, not the topic
_FREEUP_NOUN = lx.word_set("جا جای فضا فضای حجم")
_FREEUP_VERB = lx.word_set("آزاد باز خالی")
_FILLER_BARE = lx.word_set("لطفا کن کنی بکن را رو دیگه هم لطفاً")
_BARE_AGAIN_OK = _AGAIN | lx.word_set("امتحان تلاش کن بکن کنی لطفا یکبار یه بار دیگه از نو مجدد مجددا") | _FILLER_BARE

_LIGHT = lx.word_set("سبک سبکتر کوچک کوچکتر ریز کم‌حجم کمحجم کیوین qwen")
_STRONG = lx.word_set("قوی قویتر سنگین سنگینتر بزرگ بزرگتر بهتر gemma جما گما جمنای")
_CHOOSE_FILLER = lx.word_set("نسخه ی را رو همون همین اون اونو بگیر بگیرش بده بزن میخوام خوام می نه مغز مغزی لطفا همونو بیار بیاور بکن کن "
                             "بله آره باشه ولی پس خب فعلا تر")                     # «قوی‌تر» is two tokens: قوی + تر
_OWN_YES = lx.word_set("شروع بگیر بگیرش دانلود بیار بیاور بزن برو بکن کن مغز خودت را رو")
_OWN_YES_CORE = lx.word_set("شروع بگیر بگیرش دانلود بیار بیاور بزن برو")


# ---------------------------------------------------------------------------------------------------- helpers
def _brain_at(toks, i):
    """Does the token at `i` name «مغز» (also with a pronoun suffix: مغزت, مغزش, مغزم …)?"""
    t = toks[i]
    return t == "مغز" or (t.startswith("مغز") and t[3:] in _SUFFIX)


def _noun_index(toks, tset):
    """Index of the word that names the own brain, or -1. «مغز» always counts; «هوش مصنوعی» / «مدل زبانی» only next to «خودت»."""
    for i in range(len(toks)):
        if _brain_at(toks, i):
            return i
    if tset & _SELF:
        for ph in _AI:
            n = len(ph)
            for i in range(len(toks) - n + 1):
                if tuple(toks[i:i + n]) == ph:
                    return i
    return -1


def _is_question(text, tset):
    return "؟" in text or "?" in text or bool(tset & _QUESTION)


def _helping(text, toks, tset):
    """Is the sentence asking ABOUT the own brain (what it is, what it costs, how much room it takes ...)? A cost word after «بدون» is an attribute
    of an order («مغز بدون هزینه بگیر»), not a question; «رایگان» only makes a question when the sentence is one."""
    attribute = {toks[i + 1] for i in range(len(toks) - 1) if toks[i] in _ATTRIBUTE_OF}
    words = (tset & _HELP) - attribute
    if tset & _FREE and _is_question(text, tset):
        words = words | (tset & _FREE)
    return bool(words) or lx.any_phrase(toks, _HELP_PHRASES)


def _wants(toks):
    tset = set(toks)
    return bool(tset & _WANT) or lx.any_phrase(toks, lx.phrases("می خوام", "می خواهم", "دوست دارم", "ای کاش", "کاش"))


def _from_before_noun(toks, i):
    """«از مغزت …»: the brain is the one being asked (or used), not the one to get."""
    return i > 0 and toks[i - 1] == "از"


def _is_cloud(tset):
    if tset & _CLOUDISH:
        return True
    return bool(tset & _KEYISH) and not tset & _WITHOUT


def _self_provision(toks, tset):
    """«خودش کارای لازم رو برای چیزی که نداره فراهم کنه», «خودت مستقل شو»: the user's own words for the same wish - no noun needed."""
    if not tset & _SELF:
        return False
    needs = bool(tset & _NEED) or any(tok.startswith("لازم") for tok in toks)      # «لازم», but also «لازمت», «لازمه», «لازمش»
    if tset & _PROVIDE and (needs or "برای" in tset):
        return True
    return bool(tset & _INDEP) and bool(tset & lx.word_set("کن بشو بشی شو بشه کنه"))


def _bare(toks, tset):
    """The short phrases that have no noun; the caller acts on them only while the own brain has something they could mean."""
    if tset & _DOWNLOAD:
        if (tset & _STOP or lx.any_phrase(toks, _STOP_PHRASES)) and not tset & _RESUME:
            return OwnBrainCommand(PAUSE, {"bare": True})
        if tset & _RESUME or lx.any_phrase(toks, _RESUME_PHRASES):
            return OwnBrainCommand(RESUME, {"bare": True})
        if tset & _STATUS or lx.any_phrase(toks, _STATUS_PHRASES):
            return OwnBrainCommand(STATUS, {"bare": True})
    if len(toks) <= 5 and (tset & _AGAIN or lx.any_phrase(toks, _AGAIN_PHRASES)) and tset & lx.word_set("امتحان تلاش") and tset <= _BARE_AGAIN_OK:
        return OwnBrainCommand(RETRY, {"bare": True})
    if tuple(toks) in lx.phrases("چقدر مونده", "چقدر مانده", "چقدر باقی مانده", "چقدر مونده؟"):
        return OwnBrainCommand(STATUS, {"bare": True})
    return None


# ---------------------------------------------------------------------------------------------------- the classifier
def classify(text, norm, toks):
    """An `OwnBrainCommand` or None."""
    if not toks or len(toks) > MAX_TOKENS or len(text or "") > MAX_CHARS:
        return None
    tset = set(toks)
    if _is_cloud(tset):
        return None                                   # the cloud brain has its own commands (and is asked first)
    at = _noun_index(toks, tset)
    if at < 0:
        if _self_provision(toks, tset):
            return OwnBrainCommand(GET, {"how": False})
        return _bare(toks, tset)
    if tset & _ASK_FROM or _from_before_noun(toks, at):
        return None                                   # «از مغزت بخواه …», «از مغزت کمک بگیر»: a request TO a brain
    # «مغز» alone is also the human brain («مغز انسان چطور کار می‌کند؟»): a sentence is about THIS one only when it says so (خودت, خودکار, گوشی,
    # «مغزت», «می‌خوام … داشته باشی» …) or is a short command; an explanation / a how-is-it question always needs the plain marker.
    marked = bool(tset & _OWN_MARK) or toks[at] != "مغز" or _wants(toks)
    short = len(toks) <= 6
    helping = _helping(text, toks, tset)
    if not (marked or short) or (helping and not marked):
        return None                                   # «مغز انسان چطور کار می‌کند؟», «تست مغز چیست؟»: general questions are not ours
    if tset & _DELETE or lx.any_phrase(toks, _DELETE_PHRASES) or (tset & _FREEUP_NOUN and tset & _FREEUP_VERB):
        return OwnBrainCommand(DELETE)
    resume = bool(tset & _RESUME) or lx.any_phrase(toks, _RESUME_PHRASES)
    stop = bool(tset & _STOP) or (lx.any_phrase(toks, _STOP_PHRASES) and bool(tset & _DOWNLOAD))
    if stop and not resume:
        return OwnBrainCommand(PAUSE)
    if resume:
        return OwnBrainCommand(RESUME)
    again = bool(tset & _AGAIN) or lx.any_phrase(toks, _AGAIN_PHRASES)
    if tset & _TRY:
        return OwnBrainCommand(RETRY if again else TEST)
    if again and tset & _RESTART:
        return OwnBrainCommand(RETRY)
    get = bool(tset & _GET) or lx.any_phrase(toks, _GET_PHRASES) or (_wants(toks) and "داشته" in tset)
    if helping and marked:
        return OwnBrainCommand(HELP)                  # «مغز بگیرم هزینه دارد؟», «مغزت چطور کار می‌کند؟»: the answer is the explanation, nothing starts
    if marked and lx.any_phrase(toks, _WORKS_PHRASES):
        return OwnBrainCommand(TEST, {"soft": True})
    if tset & _STATUS or lx.any_phrase(toks, _STATUS_PHRASES):
        if get and not tset & lx.word_set("دانلود"):
            return OwnBrainCommand(GET, {"how": False})
        if marked or len(toks) <= 4:
            return OwnBrainCommand(STATUS)
    if get:
        return OwnBrainCommand(GET, {"how": bool(tset & lx.word_set("چجوری چطور چگونه چطوری"))})
    if lx.contains(toks, ("مغز", "خودکار")) and len(toks) <= 4:
        return OwnBrainCommand(HELP)                  # just «مغز خودکار»
    return None


# ---------------------------------------------------------------------------------------------------- for the open question
def choose_word(toks):
    """«سبک» / «قوی» (the user picks one of the two brains while the consent question is open), or None."""
    if not toks or len(toks) > 6:
        return None
    tset = set(toks)
    light, strong = bool(tset & _LIGHT), bool(tset & _STRONG)
    if light == strong or not tset <= (_LIGHT | _STRONG | _CHOOSE_FILLER):
        return None
    return "light" if light else "strong"


def confirm_word(toks):
    """'confirm' | 'deny' | 'cancel' | None for the answer to the consent question: the usual yes / no words, and also «بله شروع کن», «آره بگیرش»."""
    word = I.answer_word(toks)
    if word is not None:
        return word
    if not toks or len(toks) > 6:
        return None
    tset = set(toks)
    if tset & (lx.DENY_WORDS | lx.CANCEL_WORDS | lx.NEGATIVE_FILLER - lx.word_set("ممنون مرسی لطفا")):
        return None
    if tset <= (lx.CONFIRM_WORDS | lx.CONFIRM_TAIL | _OWN_YES) and tset & (lx.CONFIRM_WORDS | _OWN_YES_CORE) \
            and (tset & lx.CONFIRM_WORDS or len(toks) <= 3):
        return "confirm"
    return None


__all__ = ["OwnBrainCommand", "classify", "choose_word", "confirm_word", "KINDS", "GET", "STATUS", "PAUSE", "RESUME", "DELETE", "TEST", "RETRY",
           "HELP", "MAX_CHARS", "MAX_TOKENS"]
