"""
Persian conversation brain - the commands of the BODY  (Prompt 959, stage B)
============================================================================
`classify(raw, norm, toks)` says which BODY command (if any) one Persian sentence is:

    selftest         «گزارش آزمایشی» (with «کپی کن»: also put it on the clipboard)
    access           «چک‌لیست دسترسی‌ها» / «چرا دانلود قطع می‌شود؟» / «تنظیمات گوشی برای کار در پس‌زمینه»
    open             «صفحهٔ باتری را باز کن» / «تنظیمات برنامه را باز کن» / «تنظیمات اعلان را باز کن»
    sms              «کد پیامک را بخوان» (the newest one-time code of an SMS, on his order only)
    sms_permission   «مجوز پیامک را بده» (Android's own dialog; he taps «اجازه» himself)

Like the other command classifiers it is a pure, deterministic cascade over normalized tokens and small closed word lists - no table of
whole sentences, no service. A sentence is a body command only when it carries one of the body's own nouns next to an action word, so
a QUESTION («کد تأیید چیه؟» - what is such a code), a general sentence («رمز وای‌فای را بگو») and the commands of the other parts
(«تنظیمات دسترسی‌پذیری», «یک برنامه بساز», «دانلود مغز را متوقف کن») are never taken over.
"""

from . import lexicon as lx

SELFTEST = "selftest"
ACCESS = "access"
OPEN = "open"
SMS = "sms"
SMS_PERMISSION = "sms_permission"
KINDS = (SELFTEST, ACCESS, OPEN, SMS, SMS_PERMISSION)

MAX_TOKENS = 16
MAX_CHARS = 220
DEFAULT_MINUTES = 15
MAX_MINUTES = 120

_REPORT = lx.word_set("گزارش")
_REPORT_KIND = lx.word_set("آزمایشی آزمایش فنی سلامت خطا خطاها")
_SELF_PHRASES = lx.phrases("خود آزمایی", "خود آزمون", "تست سلامت", "آزمایش سلامت", "بررسی سلامت", "چک سلامت", "وضعیت فنی",
                           "وضعیت فنی برنامه")
_SELF_WORDS = lx.word_set("خودآزمایی خودآزمون")
_COPY = lx.word_set("کپی کلیپ بورد")

_SMS_NOUN = lx.word_set("پیامک sms اسمس پیامکی")
_SMS_PHRASES = lx.phrases("اس ام اس", "پیام کوتاه")
_CODE_NOUN = lx.word_set("کد کدی رمز")
_QUALIFIER = lx.word_set("تایید تاییدیه یکبارمصرف پویا ورود فعالسازی احراز")
_QUALIFIER_PHRASES = lx.phrases("یک بار مصرف", "رمز دوم", "کد ورود", "کد فعال سازی")
_READ = lx.word_set("بخوان بخون بخونی بخوانی بخونید بخوانید بخونم بخوانم")
_SHOW = lx.word_set("بگو بده بدی بدید ببینم نشان نشون بیار")
_DEIXIS = lx.word_set("اومد آمد رسید رسیده اومده آمده الان آخرین اخرین تازه جدید جدیدترین برام برایم")
_ARRIVED = lx.word_set("اومد آمد رسید رسیده اومده آمده")      # «کدی که برام اومد»: a code that ARRIVED - from an SMS, even when the word is not said
_QUESTION = lx.word_set("چیه چیست چنده چی")
_PERMISSION_NOUN = lx.word_set("مجوز اجازه دسترسی")
_GIVE = lx.word_set("بده بدم بدی بدهم فعال روشن بگیر بخواه بپرس بخوای")
_MINUTE = lx.word_set("دقیقه دقیقهی")
_HOUR = lx.word_set("ساعت")

_PHONE_BACKGROUND = lx.phrases("پس زمینه", "پشت صحنه")
_CHECKLIST = lx.phrases("چک لیست")
_CHECKLIST_NOUN = lx.word_set("دسترسی اجازه مجوز تنظیمات تنظیم گوشی برنامه")
_ACCESS_MATTER = lx.word_set("تنظیمات تنظیم دسترسی اجازه چرا چطور چجوری چگونه کار اجرا نگه بسته قطع متوقف نمیمونی میپره")
_WHY = lx.word_set("چرا")
_THING = lx.word_set("دانلود برنامه اپ اپلیکیشن مغز")
_DIES = lx.word_set("قطع بسته متوقف کیل میپره میبنده خاموش")
_DIES_PHRASES = lx.phrases("می شود", "میشه", "می شه")

_OPEN_WORDS = lx.word_set("باز بازکن ببر برو")
_SHOW_PAGE = lx.word_set("نشان نشون")
_PAGE = lx.word_set("تنظیمات تنظیم صفحه")
_BATTERY = lx.word_set("باتری")
_NOTIFICATION = lx.word_set("اعلان نوتیفیکیشن نوتیف اعلانات")
_APP = lx.word_set("برنامه اپ اپلیکیشن")
_ELSEWHERE = lx.word_set("پذیری accessibility")           # «تنظیمات دسترسی‌پذیری»: the hub's own accessibility command


class BodyCommand:
    """One classification result (plain data)."""

    __slots__ = ("kind", "slots")

    def __init__(self, kind, slots=None):
        self.kind, self.slots = kind, dict(slots or {})

    def __repr__(self):
        return "BodyCommand(%r, %r)" % (self.kind, self.slots)


def _number_before(toks, index):
    if index > 0 and toks[index - 1].isdigit():
        return int(toks[index - 1])
    return None


def _minutes(toks):
    """How far back the user wants to look: «۲۰ دقیقه» -> 20, «یک ساعت» -> 60, nothing said -> 15; never more than two hours."""
    for i, tok in enumerate(toks):
        if tok in _MINUTE:
            n = _number_before(toks, i)
            if n:
                return max(1, min(MAX_MINUTES, n))
        if tok in _HOUR:
            n = _number_before(toks, i)
            return max(1, min(MAX_MINUTES, (n or 1) * 60))
    return DEFAULT_MINUTES


# ------------------------------------------------------------------ the rules
def _selftest(toks, tset):
    if (tset & _REPORT and tset & _REPORT_KIND) or tset & _SELF_WORDS or lx.any_phrase(toks, _SELF_PHRASES):
        return BodyCommand(SELFTEST, {"copy": bool(tset & _COPY)})
    return None


def _sms_context(toks, tset):
    return bool(tset & _SMS_NOUN) or lx.any_phrase(toks, _SMS_PHRASES)


def _sms(toks, tset):
    sms = _sms_context(toks, tset)
    if tset & _PERMISSION_NOUN and sms and tset & _GIVE and not tset & _CODE_NOUN:
        return BodyCommand(SMS_PERMISSION)
    if not tset & _CODE_NOUN:
        return None
    qualified = bool(tset & _QUALIFIER) or lx.any_phrase(toks, _QUALIFIER_PHRASES)
    if not (sms or qualified or tset & _ARRIVED):
        return None
    if tset & _READ or (tset & _SHOW and (sms or tset & _DEIXIS)) or (tset & _QUESTION and tset & _DEIXIS):
        return BodyCommand(SMS, {"minutes": _minutes(toks)})
    return None


def _open(toks, tset):
    if tset & _ELSEWHERE:
        return None
    wants_open = bool(tset & _OPEN_WORDS) or (tset & _SHOW_PAGE and "بده" in tset)
    if not wants_open or not tset & _PAGE:
        return None
    if tset & _BATTERY:
        return BodyCommand(OPEN, {"target": "battery"})
    if tset & _NOTIFICATION:
        return BodyCommand(OPEN, {"target": "notifications"})
    if "تنظیمات" in tset and tset & _APP:
        return BodyCommand(OPEN, {"target": "app"})
    return None


def _access(toks, tset):
    if lx.any_phrase(toks, _CHECKLIST) and tset & _CHECKLIST_NOUN:
        return BodyCommand(ACCESS)
    if lx.any_phrase(toks, _PHONE_BACKGROUND) and tset & _ACCESS_MATTER:
        return BodyCommand(ACCESS)
    if tset & _WHY and tset & _THING and (tset & _DIES or lx.any_phrase(toks, _DIES_PHRASES)) and len(toks) <= 8:
        # «چرا دانلود قطع می‌شود؟» / «چرا برنامه خودش بسته می‌شود؟»: a question about the app dying in the background, not a command to stop
        return BodyCommand(ACCESS)
    return None


def classify(raw, norm, toks):
    """The `BodyCommand` of this sentence, or None. `toks`: the normalized tokens of the sentence."""
    if not toks or len(toks) > MAX_TOKENS or len(raw or "") > MAX_CHARS:
        return None
    tset = set(toks)
    for rule in (_selftest, _sms, _open, _access):
        command = rule(toks, tset)
        if command is not None:
            return command
    return None
