"""
brain_hub.pack_prompt - the request a user hands to ANY assistant to get a `code.v1` / `lang.v1` pack
======================================================================================================
Like `templates.build_prompt` (for `ext.v1` extensions) this never calls an AI: it builds text the user pastes into the
assistant of their choice (ChatGPT, Claude, Gemini, a friend ...) and the assistant's answer is pasted back into this
app's chat, where `pack_system` validates, scans and shows it and installs it only after the user's explicit yes.

Every number, list and name below is read from the live `pack_system` constants and from `PackAPI` itself, so the text
cannot drift from what the validator enforces, and the two example packs are REAL packs that the real manager accepts
(a test installs them).
"""

import re

from pack_system import limits, scan
from pack_system.api import PackAPI

__all__ = ["build_prompt", "example_code_pack_text", "example_lang_pack_text", "prompt_facts", "MAX_REQUEST_CHARS", "API_DOC"]

MAX_REQUEST_CHARS = 700
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")

# (call, permission, what it does) - one row per public member of PackAPI; a test keeps this table complete
API_DOC = (
    ("api.register_chat(name, matcher, handler, stage='fallback', priority=50)", "",
     "matcher(ctx)->bool و handler(ctx)->str. stage='early' یعنی پیش از مغز فارسی، 'fallback' یعنی وقتی هیچ‌چیز دیگر جواب نداد. عدد priority کوچک‌تر زودتر."),
    ("api.register_tool(tool_id, title_fa, fn, summary_fa='', params=None)", "", "یک ابزار نام‌دار در نقشهٔ قابلیت‌ها ثبت می‌کند (pack.<id>.<tool_id>)."),
    ("api.register_android_action(feature_id, action, fn)", "android", "یک عمل تازه برای یکی از درگاه‌های اندروید."),
    ("api.register_runtime(runtime)", "model", "یک موتور مدل زبانی تازه (شیئی با name، availability، load، generate، smoke_test)."),
    ("api.register_recipe(recipe_id, recipe)", "teacher", "یک دستور (recipe) برای پرسیدن از یک دستیار بیرونی."),
    ("api.make_context(text, norm, toks, brain)", "", "فقط برای آزمایش: یک ctx می‌سازد."),
    ("api.read_pack_file(rel)", "", "متن یکی از فایل‌های خود بسته را می‌خواند (مثلاً داده‌ای که کنار کد گذاشته‌ای)."),
    ("api.read_text(rel, default=None) / api.write_text(rel, text)", "", "خواندن/نوشتن یک فایل متنی در پوشهٔ داده‌ی خود بسته (حداکثر ۱ مگابایت برای هر نوشتن، ۲۰ مگابایت کل)."),
    ("api.read_json(rel, default=None) / api.write_json(rel, obj)", "", "همان، برای JSON."),
    ("api.list_data() / api.delete_data(rel)", "", "فهرست و حذف فایل‌های پوشهٔ داده‌ی خود بسته."),
    ("api.log(message)", "", "یک خط به گزارش خود بسته اضافه می‌کند."),
    ("api.inbox_list() / api.inbox_read(name) / api.inbox_take(name, rel)", "", "فایل‌هایی که کاربر با «انتخاب فایل» یا «اشتراک‌گذاری» به برنامه داده؛ take فایل را به پوشهٔ داده‌ی بسته منتقل می‌کند."),
    ("api.net_fetch(url)", "network", "متن یک صفحهٔ وب (فقط GET، از دروازهٔ اینترنت برنامه؛ اگر کاربر اینترنت را خاموش کرده باشد خطا می‌دهد). خروجی: dict."),
    ("api.ask_model(prompt, max_tokens=160)", "model", "از مدل زبانی روی گوشی (اگر نصب باشد) متن می‌گیرد؛ وگرنه None."),
    ("api.android", "android", "درگاه‌های گوشی (شیء)."),
    ("api.teacher", "teacher", "پرسیدن از دستیارهای بیرونی با اجازهٔ کاربر (شیء)."),
)


def _clean_request(text):
    text = _CONTROL_RE.sub(" ", str(text or "")).strip()
    return re.sub(r"\s+", " ", text)[:MAX_REQUEST_CHARS]


def example_code_pack_text():
    """A small, complete, valid code pack in the text form (used verbatim inside the prompt)."""
    return '''=== PACK code.v1 ===
id: daily_quote
version: 1
title: جملهٔ روز
description: وقتی بگویی «یک جمله انگیزشی بگو» یکی از جمله‌های ذخیره‌شده را می‌دهد؛ با «جمله انگیزشی اضافه کن: …» جملهٔ تازه یاد می‌گیرد.
permissions:
entry: daily_quote.main
=== FILE daily_quote/__init__.py ===

=== FILE daily_quote/main.py ===
import random

DEFAULT = ["هر روز یک قدم کوچک، یک سال بعد یک مسیر بزرگ است.", "اشتباه کردن یعنی دارم امتحان می‌کنم."]


def _quotes(api):
    return api.read_json("quotes.json", None) or list(DEFAULT)


def register(api):
    def want_one(ctx):
        return "جمله انگیزشی" in ctx.norm and "اضافه" not in ctx.norm

    def give_one(ctx):
        return random.choice(_quotes(ctx.api))

    def want_add(ctx):
        return "جمله انگیزشی اضافه کن" in ctx.norm and ":" in ctx.text

    def add_one(ctx):
        sentence = ctx.text.split(":", 1)[1].strip()
        if not sentence:
            return "بعد از «:» جمله را بنویس."
        quotes = _quotes(ctx.api)
        quotes.append(sentence[:200])
        ctx.api.write_json("quotes.json", quotes[-200:])
        return "یاد گرفتم؛ حالا %d جمله دارم." % len(quotes)

    api.register_chat("quote_add", want_add, add_one, stage="early", priority=40)
    api.register_chat("quote_get", want_one, give_one, stage="early", priority=50)


def selftest(api):
    return len(_quotes(api)) >= 2
=== END PACK ===
'''


def example_lang_pack_text():
    return '''=== PACK lang.v1 ===
id: fa_basics_demo
version: 1
title: پرسش‌وپاسخ‌های نمونه
description: چند پرسش‌وپاسخ عمومی؛ هر پاسخ چند شکل پرسیدن دارد.
=== QA ===
q: پایتخت ایران کجاست | پایتخت ایران چیست | مرکز ایران کجاست | تهران پایتخت ایران است
a: پایتخت ایران تهران است.
q: بلندترین قلهٔ ایران کدام است | بلندترین کوه ایران چیست | دماوند چند متر است
a: بلندترین قلهٔ ایران دماوند است؛ ارتفاعش حدود ۵٬۶۰۹ متر است.
=== END PACK ===
'''


def prompt_facts():
    """The live numbers the prompt states (for tests and documentation)."""
    return {
        "max_files": limits.MAX_FILES, "max_file_bytes": limits.MAX_FILE_BYTES, "max_total_bytes": limits.MAX_TOTAL_BYTES,
        "max_qa": limits.MAX_QA, "max_questions_per_entry": limits.MAX_QUESTIONS_PER_ENTRY,
        "max_question_chars": limits.MAX_QUESTION_CHARS, "max_answer_chars": limits.MAX_ANSWER_CHARS,
        "permissions": list(limits.PERMISSIONS), "risky_permissions": sorted(limits.RISKY_PERMISSIONS),
        "blocked_modules": sorted(m for m in scan.BLOCKED_MODULES if "." not in m),
        "blocked_calls": sorted(scan.BLOCKED_CALLS), "handler_seconds": limits.HANDLER_SECONDS,
        "selftest_seconds": limits.SELFTEST_SECONDS, "platform_level": limits.PLATFORM_LEVEL,
        "protected_prefixes": list(limits.PROTECTED_PREFIXES),
    }


def _api_lines():
    return ["• %s%s — %s" % (call, "  [مجوز: %s]" % perm if perm else "", doc) for call, perm, doc in API_DOC]


def build_prompt(request_text="", kind="code"):
    """The Persian request to paste into any assistant. `kind` is 'code' (a code.v1 pack) or 'lang' (a lang.v1 pack)."""
    facts = prompt_facts()
    wish = _clean_request(request_text) or "(اینجا بنویس چه قابلیتی می‌خواهی)"
    if kind == "lang":
        return _lang_prompt(wish, facts)
    lines = [
        "تو یک «بستهٔ کد» (code.v1) برای یک دستیار فارسیِ آفلاین روی گوشی اندروید می‌نویسی. برنامه با پایتون ۳٫۱۲ (فقط کتابخانهٔ استاندارد) اجرا می‌شود.",
        "فقط و فقط خودِ بسته را، در «قالب متنی» پایین، بده (از «=== PACK code.v1 ===» تا «=== END PACK ===»). هیچ JSON، توضیح یا متن دیگری ننویس.",
        "کاربر جوابت را در چت برنامه می‌چسباند؛ برنامه آن را می‌خواند، بررسی امنیتی می‌کند و فقط با «بله»ی او نصب می‌کند.",
        "",
        "درخواست من: " + wish,
        "",
        "قالب (دقیقاً همین‌طور، هر نشانه در یک سطر جدا):",
        "=== PACK code.v1 ===",
        "id: <حرف کوچک انگلیسی/رقم/_ ، با حرف شروع شود، ۳ تا ۴۰ نویسه؛ مثلاً daily_quote>",
        "version: <عدد صحیح؛ برای هر نسخهٔ تازه یکی بالاتر>",
        "title: <عنوان فارسی کوتاه>",
        "description: <یک یا دو جمله به فارسی: بسته چه می‌کند>",
        "permissions: <فهرست جداشده با ویرگول از: %s — اگر هیچ‌کدام لازم نیست خالی بگذار>" % "، ".join(facts["permissions"]),
        "entry: <id>.main",
        "=== FILE <id>/__init__.py ===",
        "(خالی)",
        "=== FILE <id>/main.py ===",
        "(کد پایتون؛ تابع register(api) الزامی است)",
        "=== END PACK ===",
        "",
        "قواعد ساختار:",
        "• همهٔ فایل‌های پایتون داخل پوشهٔ <id>/ باشند. حداکثر %d فایل، هر فایل حداکثر %d بایت، مجموع حداکثر %d بایت. پسوند فایل: py، json، txt یا md." % (
            facts["max_files"], facts["max_file_bytes"], facts["max_total_bytes"]),
        "• در main.py تابع register(api) را بنویس؛ آنجا با api.register_chat و api.register_tool کارهای بسته را ثبت کن. اختیاری: تابع selftest(api) که True برگرداند؛ برنامه پس از نصب آن را اجرا می‌کند و اگر False یا خطا بدهد، نسخهٔ قبلی را برمی‌گرداند.",
        "• فقط از کتابخانهٔ استاندارد پایتون استفاده کن (json، re، math، time، random، datetime، collections، itertools، functools، textwrap، unicodedata، base64، hashlib، html، string، statistics …).",
        "• ctx (ورودی matcher/handler) این‌ها را دارد: ctx.text (جملهٔ کاربر)، ctx.norm (نرمال‌شده)، ctx.toks (کلمه‌ها)، ctx.api (api همین بسته)، ctx.brain، ctx.memory، ctx.hub.",
        "• handler باید یک رشتهٔ فارسی برگرداند (یا None اگر جواب نمی‌دهد). همهٔ متن‌هایی که کاربر می‌بیند فارسی باشد.",
        "• هر handler حداکثر %d ثانیه وقت دارد؛ کار سنگین یا بی‌پایان نکن." % int(facts["handler_seconds"]),
        "",
        "چیزهایی که ممنوع است (بررسی‌کنندهٔ خودکار رد می‌کند و بسته نصب نمی‌شود):",
        "• import این ماژول‌ها: " + ", ".join(facts["blocked_modules"]) + " (و هر چیز مربوط به شبکهٔ خام، فایل، پردازه و کد بومی).",
        "• فراخوانی این‌ها: " + ", ".join(facts["blocked_calls"]) + " ؛ همین‌طور __import__، __globals__، __subclasses__ و مانند آن.",
        "• import نسبی (from . import …) و نام‌های غیر ASCII در کد (نام تابع و متغیر انگلیسی باشد؛ متن فارسی فقط داخل رشته‌ها).",
        "• برای فایل از open() استفاده نکن؛ فقط از api.read_text/write_text/read_json/write_json (پوشهٔ داده‌ی خود بسته). برای وب فقط api.net_fetch.",
        "• بسته نمی‌تواند این بخش‌های برنامه را عوض کند: " + ", ".join(facts["protected_prefixes"]) + ". اگر لازم است ماژولی غیر از این‌ها را عوض کنی، فیلد replaces را بنویس (کاربر دو بار تأیید می‌کند و باید برنامه را ببندد و باز کند)؛ بهتر است اصلاً لازم نباشد.",
        "",
        "دستیار شما (api) این‌ها را دارد:",
    ] + _api_lines() + [
        "• اگر از یکی از چیزهای دارای [مجوز: …] استفاده می‌کنی، همان مجوز را در permissions بنویس؛ وگرنه در اجرا خطا می‌دهد. مجوزهای پرخطر (%s) را فقط اگر واقعاً لازم است بخواه." % "، ".join(facts["risky_permissions"]),
        "",
        "پیش از جواب‌دادن بررسی کن: ۱) هر نشانهٔ === در سطر جدا و بدون فاصلهٔ اضافه است؛ ۲) id در همهٔ مسیرها یکی است؛ ۳) register(api) هست؛ ۴) هیچ import یا فراخوانی ممنوعی نیست؛",
        "۵) تورفتگی کد با ۴ فاصله است و در متن خراب نشده؛ ۶) اگر نسخهٔ تازهٔ بستهٔ قبلی است، version بالاتر از قبلی است.",
        "",
        "نمونهٔ کامل و معتبر (همین قالب را رعایت کن):",
        example_code_pack_text().rstrip(),
        "",
        "اگر درخواست من فقط داده‌ی پرسش‌وپاسخ فارسی است، به‌جای بستهٔ کد، بستهٔ زبان (lang.v1) بنویس: از من بخواه یا بگو «پرامپت بستهٔ زبان».",
    ]
    return "\n".join(lines)


def _lang_prompt(wish, facts):
    return "\n".join([
        "تو یک «بستهٔ زبان» (lang.v1) برای یک دستیار فارسیِ آفلاین روی گوشی می‌نویسی: داده‌هایی از «پرسش ← پاسخ» که دستیار با آن‌ها فارسی را بهتر می‌فهمد.",
        "فقط خودِ بسته را در قالب متنی پایین بده (از «=== PACK lang.v1 ===» تا «=== END PACK ===») و هیچ توضیح دیگری ننویس.",
        "",
        "درخواست من: " + wish,
        "",
        "قالب:",
        "=== PACK lang.v1 ===",
        "id: <حرف کوچک انگلیسی/رقم/_ ، با حرف شروع شود، ۳ تا ۴۰ نویسه>",
        "version: <عدد صحیح؛ هر نسخهٔ تازه یکی بالاتر>",
        "title: <عنوان فارسی کوتاه>",
        "description: <یک جمله>",
        "=== QA ===",
        "q: <شکل اول پرسش> | <شکل دوم> | <شکل سوم> …",
        "a: <پاسخ>",
        "q: …",
        "a: …",
        "=== END PACK ===",
        "",
        "قواعد:",
        "• حداکثر %d ورودی (q/a)؛ هر ورودی حداکثر %d شکل پرسیدن (با | جدا کن)، هر پرسش حداکثر %d نویسه و هر پاسخ حداکثر %d نویسه (چند خطی هم می‌شود؛ خط بعدیِ a: ادامهٔ همان پاسخ است)." % (
            facts["max_qa"], facts["max_questions_per_entry"], facts["max_question_chars"], facts["max_answer_chars"]),
        "• برای هر پاسخ ۴ تا ۱۰ شکل واقعاً متفاوتِ پرسیدن بنویس: رسمی و محاوره‌ای، کوتاه و بلند، با «چیست/چیه/چی میشه/…»، با مترادف‌ها.",
        "• فقط چیزهایی را بنویس که درستی‌شان را مطمئنی؛ جواب نادرست بدتر از بی‌جواب بودن است. حدس نزن، آمار یا تاریخ ساختگی نده.",
        "• پاسخ‌ها به فارسی روان و کوتاه باشند. دو پرسشِ مشابه نباید دو پاسخ متفاوت داشته باشند (برنامه در این حالت ساکت می‌ماند).",
        "• برنامه فقط وقتی جواب می‌دهد که پرسش کاربر به یکی از شکل‌های نوشته‌شده خیلی نزدیک باشد؛ پس تنوع شکل‌ها مهم‌تر از تعداد ورودی‌هاست.",
        "",
        "نمونهٔ کامل و معتبر:",
        example_lang_pack_text().rstrip(),
    ])
