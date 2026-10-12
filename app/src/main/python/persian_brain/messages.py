"""
Persian conversation brain - message templates
==============================================
Every Persian sentence the brain says is built here from what is actually
true at that moment (the stored user name, the capability registry, a build
result, the dialogue state). There is no table of "message -> answer": these
are fixed sentence frames with slots, chosen by the handler that already
knows the facts.

Tone: friendly, short, second person singular ("تو"), honest about what the
brain can and cannot do.
"""

import re
import zlib

from self_builder import fa_text, policy, textops

fa = fa_text.fa_number
_DIGIT_DOT = re.compile(r"(?<=[0-9])\.(?=[0-9])")
_DIGIT_TABLE = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
LRI, PDI = "\u2066", "\u2069"   # bidi isolate: keeps an ASCII expression in order inside Persian text


def digits(text):
    """Persian digits and decimal separator for the numbers inside a stored text."""
    return _DIGIT_DOT.sub("٫", str(text)).translate(_DIGIT_TABLE)


def ltr(text):
    return f"{LRI}{text}{PDI}"

KIND_LABEL = {
    policy.ARCHETYPE_UNIT_CONVERSION: "تبدیل واحد",
    policy.ARCHETYPE_FORMULA: "فرمول",
    policy.ARCHETYPE_TEXT_TOOL: "ابزار متنی",
}

STAGE_LABEL = {
    "request": "دریافت درخواست", "analyze": "تحلیل درخواست", "spec": "تنظیم مشخصات",
    "check_capabilities": "بررسی قابلیت‌های موجود", "identify_gap": "شناسایی کمبود", "plan": "طرح تغییر",
    "generate": "تولید فایل‌ها", "validate": "اعتبارسنجی امنیتی", "test": "آزمون", "analyze_failure": "تحلیل خطا",
    "repair": "اصلاح امن", "retest": "آزمون دوباره", "checkpoint": "نقطهٔ بازگشت", "apply": "اعمال",
    "persist": "ذخیره‌سازی", "register": "ثبت در فهرست قابلیت‌ها", "version": "نسخه‌گذاری", "audit": "ثبت ممیزی",
}

_BUILTIN_ABILITIES = (
    "گفت‌وگوی فارسی؛ سلام، پرسش و درخواست",
    "یاد گرفتن چیزهایی که بهم می‌گویی («یاد بگیر که …») و جواب دادن به آن‌ها",
    "به‌خاطر سپردن نام و علایقت",
    "ساختن قابلیت تازه برای خودم، آزمودنش، ثبت و نسخه‌گذاری‌اش (تبدیل واحد، فرمول، ابزار متنی)",
)

SUPPORTED_KINDS_TEXT = ("تبدیل واحد (مثل «کیلومتر به مایل»)، فرمول (مثل «مساحت دایره = pi * r ** 2») "
                        "و ابزار متنی (مثل شمارش کلمات)")

_CALL_ERRORS = {
    "bad_input": "ورودی معتبر نبود",
    "division_by_zero": "تقسیم بر صفر پیش آمد",
    "domain": "این مقدار در دامنهٔ فرمول نیست (مثلاً ریشهٔ دوم عدد منفی)",
    "overflow": "نتیجه بیش‌ازحد بزرگ شد",
    "bad_power": "توان خیلی بزرگ است",
    "timeout": "محاسبه بیش‌ازحد طول کشید",
    "exception": "در اجرای قابلیت خطایی رخ داد",
    "bad_output": "خروجی قابلیت معتبر نبود",
}


def variant(text, n):
    """A deterministic pick 0..n-1 from the text (no randomness, no clock)."""
    return zlib.crc32((text or "").encode("utf-8")) % n


def ver(n):
    return f"نسخه‌ی {fa(n)}"


def quoted(title):
    return f"«{title}»"


def bullets(lines):
    return "\n".join("• " + line for line in lines)


def numbered(lines):
    return "\n".join(f"{fa(i)}. {line}" for i, line in enumerate(lines, 1))


def _who(name):
    return f" {name}" if name else ""


# ------------------------------------------------------------------ social --

_DAYPART = {"morning": "صبح", "noon": "ظهر", "afternoon": "عصر", "evening": "شب", "day": "روز"}


def hello(name=None, flavor=None, text=""):
    if flavor in _DAYPART:
        return f"{_DAYPART[flavor]} تو هم بخیر{_who(name)}! چه کاری از دستم برمی‌آید؟"
    options = (f"سلام{_who(name)}! خوشحالم که اینجایی. چه کاری از دستم برمی‌آید؟",
               f"سلام{_who(name)}! بگو چطور می‌توانم کمکت کنم.")
    return options[variant(text, len(options))]


def wellbeing(name=None, flavor=None, text=""):
    return f"{hello(name, flavor, text).split('!')[0]}! من خوبم، ممنون که پرسیدی. تو چطوری؟"


def thanks(name=None):
    return f"خواهش می‌کنم{_who(name)}! هر وقت خواستی، در خدمتم."


def farewell(name=None):
    return f"خداحافظ{_who(name)}! هر وقت خواستی برگرد؛ چیزهایی که یاد گرفته‌ام و قابلیت‌هایی که ساخته‌ام می‌مانند."


def intro_name(name, flavor=None):
    greeting = f"{_DAYPART[flavor]} تو هم بخیر" if flavor in _DAYPART else "سلام"
    return f"{greeting} {name}! خوشحالم از آشنایی. اسمت را یاد گرفتم."


def hello_short(name=None, flavor=None):
    """The opening of a compound message: «سلام عرفان!» before the real answer."""
    greeting = f"{_DAYPART[flavor]} تو هم بخیر" if flavor in _DAYPART else "سلام"
    return f"{greeting}{_who(name)}!"


# ------------------------------------------------------------- capabilities --

def _kind(kind):
    return KIND_LABEL.get(kind, kind)


def capability_list(records, with_help=True):
    lines = ["من این کارها را بلدم:", bullets(_BUILTIN_ABILITIES)]
    active = [r for r in records if r.get("status") == "active" and r.get("version") is not None]
    disabled = [r for r in records if r not in active]
    if active:
        lines.append("")
        lines.append(f"قابلیت‌هایی که خودم ساخته‌ام ({fa(len(active))}):")
        lines.append(numbered(f"{quoted(r['title'])} — {_kind(r['kind'])}، {ver(r['version'])}" for r in active))
        if with_help:
            lines.append("برای دیدن جزئیات یکی بگو: «جزئیات " + active[0]["title"] + "».")
    else:
        lines.append("")
        lines.append("هنوز قابلیتی برای خودم نساخته‌ام. مثلاً بگو: «یک مبدل کیلومتر به مایل بساز».")
    if disabled:
        lines.append("غیرفعال: " + "، ".join(quoted(r["title"]) for r in disabled))
    return "\n".join(lines)


def capability_list_unavailable(code):
    """The built-in abilities are still true; what I built myself cannot be listed right now."""
    return "\n".join(["من این کارها را بلدم:", bullets(_BUILTIN_ABILITIES), "", registry_unavailable(code)])


def usage_hint(rec):
    """How to call a capability, built from its own spec."""
    spec = rec.get("spec") or {}
    kind = rec.get("kind")
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        return f"مثلاً بپرس: «۱۰ {spec['from']['name']} چند {spec['to']['name']} است؟»"
    if kind == policy.ARCHETYPE_FORMULA:
        sample = "، ".join(f"{v.get('label') or v['name']}=۳" for v in spec.get("variables", []))
        return f"مثلاً بگو: «{rec['title']} را با {sample} حساب کن»"
    ops = spec.get("ops") or []
    phrase = textops.OPS[ops[0]][3][0] if ops and ops[0] in textops.OPS else rec["title"]
    return f"مثلاً بگو: «{phrase}: سلام دنیا»"


def capability_detail(rec):
    state = "فعال" if rec.get("status") == "active" and rec.get("version") is not None else "غیرفعال"
    shown_version = rec.get("version") if rec.get("version") is not None else rec.get("latest_version")
    lines = [f"{quoted(rec['title'])} — {_kind(rec['kind'])}، {ver(shown_version)} ({state})"]
    if rec.get("kind") == policy.ARCHETYPE_FORMULA and (rec.get("spec") or {}).get("expression"):
        lines.append(f"محاسبهٔ {quoted(rec['title'])} با فرمول {ltr(rec['spec']['expression'])}")
    elif rec.get("description"):
        lines.append(digits(rec["description"]))
    if rec.get("inputs"):
        lines.append("ورودی: " + "، ".join(i.get("label") or i.get("name") for i in rec["inputs"]))
    if rec.get("outputs"):
        lines.append("خروجی: " + "، ".join(o.get("label") or o.get("name") for o in rec["outputs"]))
    tests = rec.get("tests") or {}
    if tests.get("total") is not None:
        lines.append(f"آزمون‌ها: {fa(tests['passed'])} از {fa(tests['total'])} موفق")
    rb = rec.get("rollback") or {}
    if rb.get("restorable"):
        lines.append(f"می‌توانم به {ver(rb['previous_version'])} برگردم.")
    elif rec.get("status") == "active":
        lines.append("نسخهٔ قبلی‌ای برای بازگشت ندارد.")
    usage = rec.get("usage") or {}
    if usage.get("calls"):
        lines.append(f"تا حالا {fa(usage['calls'])} بار استفاده شده.")
    versions = rec.get("versions") or []
    if len(versions) > 1:
        names = {"active": "فعال", "superseded": "جایگزین‌شده", "rolled_back": "برگردانده‌شده", "broken": "خراب"}
        lines.append("همهٔ نسخه‌ها: " + "، ".join(f"{fa(v['version'])} ({names.get(v['status'], v['status'])})"
                                                   for v in versions))
    if state == "فعال":
        lines.append(usage_hint(rec))
    return "\n".join(lines)


def how_computed(rec):
    """How a capability gets its result - read from its own spec, not invented."""
    spec = rec.get("spec") or {}
    kind = rec.get("kind")
    title = quoted(rec["title"])
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        text = (f"{title} این‌طور حساب می‌کند: نتیجه = مقدار × {fa(spec['scale'], 9)}"
                + (f" + {fa(spec['shift'], 9)}" if spec.get("shift") else "") + ".")
        if spec.get("standard"):
            text += " این ضریب همان ضریب استانداردِ جدول واحدهای من است."
        else:
            text += " این ضریب را خودت گفته‌ای، نه جدول استاندارد."
        return text
    if kind == policy.ARCHETYPE_FORMULA:
        return f"{title} با این فرمول حساب می‌کند: {ltr(spec.get('expression'))}"
    ops = spec.get("ops") or []
    labels = [textops.op_label(o) for o in ops if o in textops.OPS]
    return f"{title} این کارها را به‌ترتیب روی متن انجام می‌دهد: " + " ← ".join(labels) + "."


def capability_exists(rec):
    return (f"بله، {quoted(rec['title'])} را دارم ({ver(rec['version'])}، {_kind(rec['kind'])}). "
            + usage_hint(rec))


def history(rows, titles):
    if not rows:
        return "هنوز هیچ تغییری ثبت نشده؛ چیزی نساخته‌ام."
    kind_fa = {"build": "ساخت", "rollback": "بازگشت", "disable": "غیرفعال‌سازی"}
    result_fa = {"applied": "انجام شد", "failed": "ناموفق", "needs_confirmation": "منتظر تأیید", "noop": "تغییری لازم نبود",
                 "started": "ناتمام ماند"}
    lines = []
    for r in rows:
        title = titles.get(r.get("capability_id")) or r.get("capability_id") or "—"
        text = f"{kind_fa.get(r['kind'], r['kind'])} {quoted(title)} — {result_fa.get(r['result'], r['result'])}"
        if r.get("version") is not None and r["result"] == "applied":
            text += f" ({ver(r['version'])})"
        if r["result"] == "failed" and r.get("error_code"):
            text += f" [{r['error_code']}]"
        lines.append(text)
    return "آخرین تغییرات (تازه‌ترین اول):\n" + numbered(lines)


def status_report(status, check):
    if not status.get("exists"):
        return ("هنوز چیزی نساخته‌ام؛ ثبت قابلیت‌هایم وقتی اولین قابلیت را بسازم ایجاد می‌شود. "
                "سیاست امنیتی فعال است و فقط سه نوع قابلیت را می‌سازم.")
    if status.get("open_error"):
        return "ثبت قابلیت‌هایم الان در دسترس نیست (" + str(status["open_error"].get("code")) + ")."
    chain = status.get("audit_chain") or {}
    lines = [f"من {fa(status.get('capabilities', 0))} قابلیت دارم که {fa(status.get('active', 0))} تای آن‌ها فعال است."]
    if chain.get("ok"):
        lines.append(f"زنجیرهٔ ممیزی سالم است ({fa(chain.get('entries', 0))} رکورد).")
    else:
        lines.append("هشدار: زنجیرهٔ ممیزی ناسالم است (رکورد شمارهٔ " + fa(chain.get("first_bad_seq") or 0) + ").")
    startup = status.get("startup") or {}
    if startup.get("fallbacks") or startup.get("disabled") or startup.get("quarantined"):
        lines.append("در آخرین راه‌اندازی مشکل‌هایی را خودم برطرف کردم و موارد خراب را کنار گذاشتم.")
    if check is not None:
        bad = [c for c in check.get("checked", []) if not c["ok"]]
        if bad:
            lines.append("بررسی زنده: مشکل در " + "، ".join(c["capability_id"] for c in bad))
        elif check.get("checked"):
            lines.append("بررسی زنده: همهٔ نسخه‌های فعال راستی‌آزمایی شدند و آزمون‌هایشان دوباره موفق بود.")
    return "\n".join(lines)


def help_text():
    return ("می‌توانی این‌ها را بگویی:\n" + bullets([
        "«یک مبدل کیلومتر به مایل بساز»",
        "«فرمول مساحت دایره را یاد بگیر: pi * r ** 2»",
        "«ابزاری بساز که تعداد کلمات متن را بشمارد»",
        "«۱۰ کیلومتر چند مایل است؟» — بعد از ساخت، خودم جواب می‌دهم",
        "«چه کارهایی بلدی؟» / «جزئیات تبدیل کیلومتر به مایل» / «تاریخچهٔ ساخت»",
        "«به نسخهٔ قبلی برگرد» / «قابلیت … را غیرفعال کن»",
        "«یاد بگیر که پایتون یک زبان برنامه‌نویسی است» و بعد «پایتون چیست؟»",
    ]))


# --------------------------------------------------------- build: questions --

def ask_kind():
    return ("چه نوع قابلیتی لازم داری؟ این سه نوع را می‌توانم خودم بسازم:\n"
            + bullets(["تبدیل واحد — مثلاً «تبدیل کیلومتر به مایل»",
                       "فرمول — مثلاً «مساحت دایره = pi * r ** 2»",
                       "ابزار متنی — مثلاً «شمارش کلمات» یا «معکوس کردن متن»"])
            + "\nکدام را می‌خواهی؟ (برای انصراف بگو «لغو»)")


def clarify(request, missing_note=None):
    """The question that fits what a build request is missing."""
    kind = request.kind
    missing = list(request.missing)
    slots = request.slots or {}
    if "kind" in missing:
        return ask_kind()
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        if "direction" in missing:
            from self_builder import units
            names = [units.UNITS[u].display for u in slots.get("candidate_units", []) if u in units.UNITS]
            if len(names) == 2:
                return (f"منظورت تبدیل {names[0]} به {names[1]} است یا برعکس؟ "
                        f"بنویس «از {names[0]} به {names[1]}» یا «از {names[1]} به {names[0]}».")
        if request.note == "same_unit" or ("to_unit" in missing and "from_unit" in slots):
            from self_builder import units
            u = units.UNITS.get(slots.get("from_unit"))
            name = u.display if u else "این واحد"
            if request.note == "same_unit":
                return f"مبدأ و مقصد یکی شد ({name}). به چه واحد دیگری تبدیل کنم؟"
            return f"{name} را به چه واحدی تبدیل کنم؟ (مثلاً «به مایل»)"
        if "from_unit" in missing and "to_unit" in slots:
            from self_builder import units
            u = units.UNITS.get(slots.get("to_unit"))
            return f"از چه واحدی به {u.display if u else 'آن'} تبدیل کنم؟"
        return ("کدام واحد را به کدام واحد تبدیل کنم؟ مثلاً «کیلومتر به مایل». "
                "اگر واحدها را نمی‌شناسم، یک رابطه بگو، مثل «هر ۱ فوت برابر ۳۰٫۴۸ سانتی‌متر است».")
    if kind == policy.ARCHETYPE_FORMULA:
        if "title" in missing and "expression" in missing:
            return "فرمول را چطور بنویسم؟ مثلاً «مساحت دایره = pi * r ** 2» (نام و عبارت ریاضی)."
        if "expression" in missing:
            return (f"عبارت ریاضیِ «{slots.get('title', 'فرمول')}» چیست؟ مثلاً «pi * r ** 2». "
                    "از + - * / ** ، پرانتز، pi و تابع‌هایی مثل sqrt می‌توانی استفاده کنی.")
        return "این فرمول را چه نام بگذارم؟ (مثلاً «مساحت دایره»)"
    # text tool
    labels = [textops.op_label(o) for o in textops.op_ids()]
    if "ops_order" in missing:
        return "شمارش فقط می‌تواند آخرین مرحله باشد. ترتیب کارها را اصلاح کن."
    if "ops_count" in missing:
        return f"حداکثر {fa(textops.MAX_CHAIN)} کار پشت‌سرهم روی متن ممکن است. کمترش کن."
    return "ابزار متنی چه کاری روی متن بکند؟ مثلاً: " + "، ".join(labels) + "."


def pending_retry(request):
    return "هنوز مطمئن نیستم منظورت چیست. " + clarify(request)


def gave_up():
    return "نتوانستم منظورت را بفهمم، پس این درخواست را کنار گذاشتم. هر وقت خواستی دوباره بگو."


def cancelled():
    return "باشه، لغو شد."


def declined():
    return "باشه، انجام نمی‌دهم."


def no_pending():
    return "الان سؤال بازی ندارم که جوابش را بدهی؛ بگو چه کاری می‌خواهی."


# ----------------------------------------------------------- build: results --

def _repair_lines(repairs):
    notes = [r.get("note") for r in repairs if r.get("note")]
    return notes[:4]


def _stage_line(result):
    seen = []
    for st in result.get("stages", []):
        label = STAGE_LABEL.get(st["stage"])
        if label and label not in seen:
            seen.append(label)
    return " ← ".join(seen)


def build_applied(result, record=None, with_stages=True):
    title = result["title"]
    tests = result.get("tests") or {}
    if result.get("action") == "improve":
        head = (f"قابلیت {quoted(title)} را ارتقا دادم؛ حالا {ver(result['version'])} فعال است "
                f"و {ver(result.get('previous_version'))} برای بازگشت نگه داشته شد.")
    else:
        head = f"ساختم! قابلیت {quoted(title)} ({_kind(result['kind'])}) آماده و فعال شد."
    lines = [head]
    if tests.get("total"):
        lines.append(f"آزمون‌های خودکار: {fa(tests['passed'])} از {fa(tests['total'])} موفق.")
    repairs = result.get("repairs") or []
    if repairs:
        lines.append(f"در ساخت {fa(len(repairs))} مورد پیدا شد که خودم به‌صورت امن اصلاح کردم و دوباره آزمودم:")
        lines.extend("  – " + n for n in _repair_lines(repairs))
    lines.append("در حافظهٔ ماندگار ثبت شد؛ بعد از بستن و دوباره باز کردن برنامه هم می‌ماند.")
    if with_stages:
        stage_line = _stage_line(result)
        if stage_line:
            lines.append("مراحل: " + stage_line)
    if record is not None:
        lines.append(usage_hint(record))
    return "\n".join(lines)


def build_noop(result, record=None):
    text = (f"این قابلیت را همین حالا دارم: {quoted(result['title'])} ({ver(result['version'])}) "
            "با همین مشخصات؛ لازم نبود چیزی ساخته شود.")
    if record is not None:
        text += " " + usage_hint(record)
    return text


def build_confirmation(result):
    conf = result.get("confirmation") or {}
    reason = conf.get("reason")
    details = conf.get("details") or {}
    title = quoted(result.get("title") or "")
    if reason == "factor_deviation":
        return (f"ضریبی که گفتی با ضریب استاندارد من فرق دارد: ضریب تو {fa(details.get('user_scale'), 9)} "
                f"و ضریب استاندارد {fa(details.get('table_scale'), 9)} است. "
                f"{title} را با ضریب خودت بسازم؟ (بله / نه)")
    if reason == "guess_repair":
        reps = details.get("repairs") or []
        notes = [f"{r.get('before')} ← {r.get('after')}" for r in reps if r.get("before") != r.get("after")][:3]
        text = "عبارت را برای ساخت کمی اصلاح کردم و مطمئن نیستم درست فهمیده باشم"
        if notes:
            text += ": " + "؛ ".join(notes)
        if details.get("interpretation"):
            text += f". برداشت من: {details['interpretation']}"
        return text + f". {title} را با همین برداشت بسازم؟ (بله / نه)"
    return f"برای ساختن {title} تأیید تو لازم است. بسازم؟ (بله / نه)"


_ERROR_TEXT = {
    "E_BUILD_NOT_READY": "درخواست کامل نبود.",
    "E_SPEC_FACTOR_REQUIRED": "برای این واحدها ضریب تبدیل لازم است؛ بگو مثلاً «هر ۱ فوت برابر ۳۰٫۴۸ سانتی‌متر است».",
    "E_SPEC_FACTOR": "ضریب تبدیل خارج از محدودهٔ مجاز است.",
    "E_SPEC_SAME_UNIT": "مبدأ و مقصد یکی هستند.",
    "E_SPEC_DIMENSION": "این دو واحد هم‌جنس نیستند (مثلاً طول و جرم)؛ بدون ضریب نمی‌توانم تبدیلشان کنم.",
    "E_SPEC_TITLE": "نام قابلیت معتبر نیست.",
    "E_SPEC_NO_VARIABLES": "فرمول باید دست‌کم یک متغیر داشته باشد.",
    "E_SPEC_TOO_MANY_VARIABLES": "متغیرهای فرمول بیش‌ازحد زیاد است.",
    "E_SPEC_VARIABLES": "متغیرهای فرمول با عبارت نمی‌خواند.",
    "E_SPEC_EXAMPLE": "مثالی که دادی قابل استفاده نبود.",
    "E_SPEC_OPS": "ترکیب کارهای متنی مجاز نیست.",
    "E_BUILD_VALIDATION": "اعتبارسنجی امنیتیِ قابلیت تولیدشده رد شد.",
    "E_BUILD_LIMIT_CAPABILITIES": "به سقف تعداد قابلیت‌ها رسیده‌ام.",
    "E_BUILD_LIMIT_VERSIONS": "این قابلیت به سقف تعداد نسخه‌هایش رسیده است.",
    "E_BUILD_APPLY_VERIFY": "راستی‌آزمایی فایل‌های اعمال‌شده ناموفق بود؛ همه‌چیز به حالت قبل برگردانده شد.",
    "E_BUILD_INTERNAL": "در مرحلهٔ اعمال خطای غیرمنتظره‌ای پیش آمد؛ همه‌چیز به حالت قبل برگردانده شد.",
}


_EXPR_TEXT = {
    "E_EXPR_EMPTY": "عبارت خالی است",
    "E_EXPR_TOO_LONG": "عبارت بیش‌ازحد طولانی است",
    "E_EXPR_NON_ASCII_NAME": "نام متغیر باید با حروف لاتین نوشته شود",
    "E_EXPR_TOKEN": "در عبارت نویسهٔ غیرمجاز هست",
    "E_EXPR_TOO_COMPLEX": "عبارت بیش‌ازحد پیچیده است",
    "E_EXPR_PAREN_CLOSE": "یک پرانتز بسته جفت ندارد",
    "E_EXPR_PAREN_OPEN": "یک پرانتز باز بسته نشده است",
    "E_EXPR_SYNTAX": "ساختار عبارت درست نیست",
    "E_EXPR_SYNTAX_END": "عبارت ناتمام مانده است",
    "E_EXPR_ADJACENT": "بین دو مقدار عملگر نیست (مثلاً ضرب با *)",
    "E_EXPR_NUMBER": "یک عدد معتبر نیست",
    "E_EXPR_UNKNOWN_FUNC": "تابعی با این نام را نمی‌شناسم",
    "E_EXPR_RESERVED_NAME": "نام یک تابع را نمی‌شود نام متغیر گذاشت",
    "E_EXPR_ARITY": "تعداد آرگومان‌های یک تابع درست نیست",
}


def _expr_reason(code, info):
    reason = _EXPR_TEXT.get(code, "عبارت قابل خواندن نیست")
    char = (info or {}).get("char")
    if code == "E_EXPR_TOKEN" and isinstance(char, str) and len(char) == 1:
        reason += f" ({ltr(char)})"
    name = (info or {}).get("name")
    if code in ("E_EXPR_UNKNOWN_FUNC", "E_EXPR_RESERVED_NAME", "E_EXPR_ARITY") and isinstance(name, str):
        reason += f" ({ltr(name)})"
        if code == "E_EXPR_UNKNOWN_FUNC" and name.lower() in _LOG_NAMES:
            reason += "؛ برای لگاریتم از ln (طبیعی) یا log10 (مبنای ۱۰) استفاده کن"
    return reason


_LOG_NAMES = frozenset({"log", "log2", "lg", "logn", "loge"})


def build_failed(result):
    err = result.get("error") or {}
    code = err.get("code") or "E_BUILD"
    info = err.get("info") or {}
    if code == "E_BUILD_TESTS_FAILED":
        cls = info.get("failure_class")
        why = {"example_mismatch": "نتیجه با مثالی که دادی نمی‌خواند",
               "reference_mismatch": "نتیجهٔ کد با محاسبهٔ مرجع نمی‌خواند",
               "sandbox_fault": "اجرای امن کد خطا داد",
               "exhausted": "چند اصلاح امن را امتحان کردم ولی کافی نبود"}.get(cls, "آزمون‌های خودکار موفق نبود")
        text = f"ساخت ناموفق بود: {why}، پس چیزی فعال نشد."
        failed = info.get("cases") or []
        if failed:
            text += " (مورد: " + str(failed[0].get("name")) + ")"
    elif code.startswith("E_EXPR"):
        text = ("نتوانستم عبارت ریاضی را بخوانم: " + _expr_reason(code, info) + ". "
                "فقط + - * / ** ، پرانتز، pi و تابع‌هایی مثل sqrt، sin، cos، abs، min، max را می‌فهمم.")
    elif code.startswith("E_STORE") or code.startswith("E_POLICY"):
        text = "ثبت قابلیت‌هایم الان در دسترس نیست یا سیاست امنیتی اجازه نداد؛ چیزی تغییر نکرد."
    else:
        generic = ("مشخصات قابلیت معتبر نبود." if code.startswith("E_SPEC") else
                   "اعتبارسنجی یا اجرای امنِ قابلیت تولیدشده موفق نبود." if code.startswith(("E_VALIDATION", "E_SANDBOX"))
                   else "خطایی پیش آمد.")
        text = "ساخت ناموفق بود: " + _ERROR_TEXT.get(code, generic)
    kept = result.get("active_version")
    tail = (f" نسخهٔ فعلی ({ver(kept)}) دست‌نخورده ماند." if kept else " هیچ نسخهٔ ناقصی فعال نشد.")
    return f"{text}{tail} (کد: {code})"


def unsupported_build():
    return ("این را به‌صورت خودکار نمی‌توانم بسازم. فعلاً فقط این سه نوع قابلیت را خودم می‌سازم: "
            + SUPPORTED_KINDS_TEXT + ". قابلیت‌های دیگر هنوز به برنامه‌نویس نیاز دارند.")


# ------------------------------------------------------------------ gaps --

def offer_build_unit(from_name, to_name):
    return (f"قابلیت «تبدیل {from_name} به {to_name}» را هنوز ندارم. ولی از نوعی است که می‌توانم خودم بسازم، "
            "آزمایش کنم و ثبت کنم. بسازمش؟ (بله / نه)")


def offer_build_text(labels):
    return (f"ابزار «{' و '.join(labels)}» را هنوز ندارم. ولی می‌توانم خودم بسازمش، بیازمایمش و ثبتش کنم. "
            "بسازمش؟ (بله / نه)")


def capability_missing(kind_text):
    return f"نه، {kind_text} را هنوز ندارم."


# --------------------------------------------------------------- invocation --

def invoke_ok(rec, inputs, out):
    spec = rec.get("spec") or {}
    kind = rec.get("kind")
    value = out["value"]
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        return f"{fa(inputs['value'])} {spec['from']['name']} = {fa(value)} {spec['to']['name']}"
    if kind == policy.ARCHETYPE_FORMULA:
        shown = "، ".join(f"{v.get('label') or v['name']} = {fa(inputs[v['name']])}" for v in spec["variables"])
        return f"{spec.get('result_label') or rec['title']} ({shown}) = {fa(value)}"
    if isinstance(value, str):
        return f"نتیجه: «{value}»"
    return f"{rec['title']}: {fa(value)}"


def invoke_failed(rec, out):
    reason = _CALL_ERRORS.get(out.get("error"), "خطایی رخ داد")
    return f"نتوانستم {quoted(rec['title'])} را حساب کنم: {reason}."


def fallback_note(fallback):
    if not fallback:
        return ""
    if fallback.get("restored_version"):
        return (f"\nتوجه: فایل {ver(fallback['broken_version'])} این قابلیت سالم نبود (تغییر کرده بود)؛ آن را کنار گذاشتم "
                f"و با {ver(fallback['restored_version'])} ادامه دادم.")
    if fallback.get("disabled"):
        return (f"\nتوجه: فایل {ver(fallback['broken_version'])} این قابلیت سالم نبود و نسخهٔ سالم دیگری نداشتم؛ "
                "قابلیت را غیرفعال کردم. می‌توانی دوباره بسازیش.")
    return ""


def unavailable(rec_title):
    return f"{quoted(rec_title)} الان فعال نیست."


def needs_inputs(rec, missing_labels, have):
    got = ""
    if have:
        got = " (دارم: " + "، ".join(f"{k} = {fa(v)}" for k, v in have.items()) + ")"
    return (f"برای {quoted(rec['title'])} به این مقدارها هم نیاز دارم{got}: " + "، ".join(missing_labels)
            + ". مثلاً بگو «" + "، ".join(f"{n}=۳" for n in [m for m in missing_labels]) + "».")


def needs_text(rec):
    return f"کدام متن را پردازش کنم؟ آن را داخل « » یا بعد از «:» بنویس. (برای {quoted(rec['title'])})"


def reference_missing():
    return "منظورت از «همان» را نمی‌دانم؛ هنوز چیزی را با هم محاسبه نکرده‌ایم."


def reference_inputs_mismatch(rec):
    return f"برای {quoted(rec['title'])} مقدار(های) لازم را کامل بگو؛ مثلاً: «{usage_hint(rec).split('«', 1)[-1].rstrip('»')}»."


# -------------------------------------------------- rollback / disable ----

def rollback_done(result):
    return (f"برگشتم: {quoted(result['title'])} از {ver(result['from_version'])} به {ver(result['version'])} "
            "برگشت. نسخهٔ برگردانده‌شده پیش از فعال شدن دوباره راستی‌آزمایی و آزمون شد و در ثبت ماندگار ذخیره شد.")


def rollback_failed(result):
    err = result.get("error") or {}
    code = err.get("code")
    text = {"E_ROLLBACK_UNKNOWN": "چنین قابلیتی نمی‌شناسم.",
            "E_ROLLBACK_NOT_ACTIVE": "این قابلیت الان فعال نیست.",
            "E_ROLLBACK_BAD_TARGET": "آن نسخه قابل بازگردانی نیست.",
            "E_ROLLBACK_NO_TARGET": "نسخهٔ سالمِ قبلی‌ای برای بازگشت ندارم.",
            "E_ROLLBACK_NO_REGISTRY": "هنوز قابلیتی نساخته‌ام که بخواهم برگردانم."}.get(code, "بازگشت انجام نشد.")
    return f"{text} (کد: {code}) چیزی تغییر نکرد."


def ask_rollback(rec):
    rb = rec.get("rollback") or {}
    return (f"می‌خواهی {quoted(rec['title'])} را از {ver(rec['version'])} به {ver(rb.get('previous_version'))} "
            "برگردانم؟ (بله / نه)")


def ask_disable(rec):
    return (f"می‌خواهی {quoted(rec['title'])} را غیرفعال کنم؟ فایل‌ها و نسخه‌هایش حفظ می‌شوند. (بله / نه)")


def disable_done(result):
    return (f"{quoted(result['title'])} غیرفعال شد. فایل‌ها و نسخه‌هایش حفظ شده‌اند؛ "
            "اگر دوباره بسازیش، دوباره فعال می‌شود.")


def disable_failed(result):
    code = (result.get("error") or {}).get("code")
    return f"غیرفعال‌سازی انجام نشد. (کد: {code})"


def which_capability(action):
    return f"کدام قابلیت را {action}؟ نامش را بگو (مثلاً «تبدیل کیلومتر به مایل»)."


def no_registry():
    return "هنوز قابلیتی نساخته‌ام."


def registry_unavailable(code):
    """The registry is on the device but cannot be opened: neither «I have it» nor «I do not» can be said."""
    return ("ثبت قابلیت‌هایم روی دستگاه هست ولی الان باز نمی‌شود (کد: " + str(code) + ")؛ برای همین نمی‌توانم بگویم "
            "این قابلیت را دارم یا نه، و چیزی نمی‌سازم یا تغییر نمی‌دهم. «وضعیت قابلیت‌ها را بررسی کن» جزئیات را نشان می‌دهد.")


# -------------------------------------------------------- knowledge / memory --

def knowledge_answer(sentence):
    return f"طبق چیزی که بهم یاد داده‌ای: {sentence}"


def definition_answer(name, description):
    return f"{name} {description}" + ("" if description.rstrip().endswith((".", "؟", "!")) else ".")


def likes_answer(likes, dislikes):
    parts = []
    if likes:
        parts.append("دوست داری: " + "، ".join(likes))
    if dislikes:
        parts.append("دوست نداری: " + "، ".join(dislikes))
    if not parts:
        return "هنوز چیزی دربارهٔ علایقت نمی‌دانم. بگو «من پیتزا را دوست دارم» تا یاد بگیرم."
    return "تا اینجا یاد گرفته‌ام که " + "؛ ".join(parts) + "."


def teach_ok(sentence, updated=False):
    return ("باشه، اصلاحش کردم: " if updated else "باشه، یاد گرفتم: ") + sentence


def teach_incomplete():
    return "چه چیزی را یاد بگیرم؟ جمله‌ی کامل بگو، مثلاً «یاد بگیر که پایتون یک زبان برنامه‌نویسی است»."


def statement_ack(sentence):
    return (f"متوجه شدم: «{sentence}». می‌خواهی این را برای همیشه یاد بگیرم تا بعداً بتوانم جواب بدهم؟ (بله / نه)")


def statement_declined():
    return "باشه، یادداشت نکردم."


# ------------------------------------------------------------ continuation --

def nothing_to_continue():
    return "چیزی برای ادامه دادن ندارم؛ سؤالت را بپرس یا بگو «راهنما»."


def more_about(rec):
    lines = [f"{quoted(rec['title'])} — جزئیات بیشتر:", capability_detail(rec)]
    return "\n".join(lines)


def more_knowledge(name):
    return f"دربارهٔ «{name}» بیشتر از همین چیزی که یادم داده‌ای نمی‌دانم."


def more_build(rec):
    return capability_detail(rec)


# ---------------------------------------------------------------- feedback --

def feedback_positive(recorded):
    return "ممنون! خوشحالم که درست بود." + (" بازخوردت را برای همین نسخه ثبت کردم." if recorded else "")


def feedback_negative(recorded, can_rollback):
    text = "متأسفم که درست نبود."
    if recorded:
        text += " بازخوردت را برای همین نسخه ثبت کردم."
    if not can_rollback:
        text += " بگو دقیقاً چه چیزی اشتباه بود تا بهتر شود."
    return text


def unexpected_error():
    return "در پردازش این پیام خطای غیرمنتظره‌ای پیش آمد؛ چیزی نیمه‌کاره فعال نشد. لطفاً دوباره امتحان کن."


__all__ = [n for n in dir() if not n.startswith("_")]
