"""
Persian conversation brain - messages of the teacher (asking another assistant, letting the app look into another app)
=====================================================================================================================
Like the other `hub_messages_*` modules, every sentence is built from the RESULT of a real call (`teacher.service`): nothing says
"sent", "read" or "typed" unless the result says so, a failure always says what did NOT happen, and every question names exactly
what will leave the app or what the app will be allowed to look at.

Honesty rules kept here:
* handing a text to the Android share sheet is NOT the same as the other app having received it - the wording is conditional;
* the typing recipe is called experimental, because it depends on the other app's screen (UNVERIFIED on a real device);
* the deny-list of the screen door is described exactly as it is (system apps), not as a general promise about "sensitive apps".
"""

from self_builder import fa_text

from . import messages as M

fa = fa_text.fa_number

KIND_TEXT = {"code": "یک بستهٔ کد (قابلیت تازه برای خود همین برنامه)", "lang": "یک بستهٔ زبان (داده‌های پرسش و پاسخ فارسی)",
             "ask": "یک پاسخ متنی"}
STATE_LABEL = {"drafted": "پیش‌نویس (هنوز چیزی فرستاده نشده)", "sent": "فرستاده شد؛ منتظر جواب", "running": "برنامه دارد خودش کار می‌کند",
               "captured": "جواب خوانده شد", "proposed": "جواب بررسی شد؛ نصبش به تصمیم تو مانده", "done": "تمام شد",
               "failed": "ناموفق بود", "cancelled": "لغو شد"}
ROUTE_TEXT = {"share": "اشتراک‌گذاری اندروید به برنامهٔ دستیار", "copy_open": "کپی و بازکردن برنامهٔ دستیار", "site": "کپی و بازکردن سایت دستیار",
              "screen": "خودکار با سرویس دسترس‌پذیری", "none": "هنوز نفرستاده‌ام"}
SKIP_REASON = {"empty": "خالی بود", "is_the_request": "هنوز همان درخواستِ خودِ ما بود (جواب را کپی نکرده بودی)",
               "no_pack": "متنی بود، ولی بستهٔ کامل (code.v1 یا lang.v1) نبود"}
SOURCE_LABEL = {"screen": "از صفحهٔ برنامهٔ دستیار", "shared": "از متنی که به این برنامه اشتراک‌گذاری کردی", "clipboard": "از کلیپ‌بورد"}
MAX_ANSWER_SHOWN = 3200


def _name(title):
    return "«%s»" % M.ltr(title)


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _minutes(seconds):
    minutes = max(1, int(seconds) // 60)
    return "%s دقیقه" % fa(minutes)


# ================================================================== asking
def need_wish(title=None):
    who = _name(title) if title else "آن دستیار"
    return ("چه چیزی را از %s بخواهم؟ مثلاً بنویس:\n"
            "• «از ChatGPT بخواه قابلیت ساخت عکس برایم بسازد»\n"
            "• «از Claude بپرس تفاوت HTTP و HTTPS چیست»\n"
            "• «از ChatGPT بخواه یک بستهٔ زبان دربارهٔ تاریخ ایران بنویسد»" % who)


def route_hint(title, installed, site):
    if installed:
        return ("برنامهٔ %s روی گوشی دیده می‌شود؛ متن را به آن می‌فرستم (برگهٔ «اشتراک‌گذاری» اندروید) و برای محکم‌کاری در کلیپ‌بورد هم می‌گذارم."
                % _name(title))
    return ("برنامهٔ %s روی گوشی دیده نمی‌شود؛ متن را در کلیپ‌بورد می‌گذارم و سایتش (%s) را باز می‌کنم تا خودت «جای‌گذاری» کنی."
            % (_name(title), M.ltr(site.replace("https://", "").rstrip("/"))))


def ask_send(title, wish, kind, chars, installed, site, *, from_memory=False, superseded=False):
    lines = [("درخواست قبلی‌ات را برمی‌دارم و از %s می‌خواهم:" if from_memory else "می‌خواهی از %s بخواهم:") % _name(title), "«%s»" % _clip(wish, 300)]
    lines.append("• جوابی که می‌خواهم: %s." % KIND_TEXT.get(kind, KIND_TEXT["ask"]))
    lines.append("• چه چیزی بیرون می‌رود: فقط یک متن %s نویسه‌ای که خودِ برنامه می‌سازد (شرح کار + قالبی که بتوانم جوابش را بخوانم). "
                 "از فایل‌ها، گفتگوهای دیگر یا رمزهایت چیزی نمی‌رود." % fa(chars))
    lines.append("• چطور: " + route_hint(title, installed, site))
    lines.append("• بعدش: وقتی جواب آمد، کاملش را کپی کن (یا در آن برنامه «اشتراک‌گذاری» را بزن و این برنامه را انتخاب کن)، برگرد اینجا و بگو «جواب آمد».")
    if kind in ("code", "lang"):
        lines.append("• اگر جواب یک «بسته» باشد، اول فقط بررسی‌اش می‌کنم (بدون اجرا) و باز هم از تو می‌پرسم؛ بدون «بله»ی تو چیزی نصب یا فعال نمی‌شود.")
    else:
        lines.append("• جواب را همان‌طور که آمده نشانت می‌دهم؛ درستی‌اش را خودم نمی‌سنجم.")
    if superseded:
        lines.append("• ماموریت بازِ قبلی با «بله» کنار گذاشته می‌شود.")
    lines.append("بفرستم؟ (بله / نه) — اگر چیز دیگری بنویسی، این درخواست کنار گذاشته می‌شود.")
    return "\n".join(lines)


def mission_gone():
    return "این ماموریت دیگر باز نیست (لغو شده یا از قبل انجام شده)؛ چیزی فرستاده نشد. اگر هنوز می‌خواهی، درخواستت را دوباره بگو."


def declined():
    return "باشه؛ چیزی فرستاده نشد و درخواست را کنار گذاشتم."


def sent(result, title):
    route = result.get("route")
    name = _name(title)
    if route == "share":
        head = ("برگهٔ «اشتراک‌گذاری» را برای برنامهٔ %s باز کردم و متن درخواست را در کلیپ‌بورد هم گذاشتم. "
                "اگر متن در کادر نوشتنِ آن برنامه آمده بود، خودت دکمهٔ ارسال را بزن؛ اگر نیامده بود، در کادر «جای‌گذاری» (Paste) کن." % name)
    elif route == "copy_open":
        head = "متن درخواست را در کلیپ‌بورد گذاشتم و برنامهٔ %s را باز کردم؛ در کادر نوشتن «جای‌گذاری» (Paste) کن و بفرست." % name
    else:
        head = "متن درخواست را در کلیپ‌بورد گذاشتم و سایت %s را باز کردم؛ در کادر نوشتن «جای‌گذاری» (Paste) کن و بفرست." % name
    tail = ("وقتی جواب آمد، کاملش را کپی کن (یا «اشتراک‌گذاری» → این برنامه)، برگرد اینجا و بگو «جواب آمد». "
            "تا نگویی، هیچ چیزِ دیگری از کلیپ‌بورد یا صفحه‌ها را نمی‌خوانم.\n"
            "اگر نمی‌خواهی خودت تایپ کنی: «خودت انجام بده» (نیاز دارد سرویس «دسترس‌پذیری» را خودت روشن کنی و اجازه بدهی؛ روشی آزمایشی است).")
    return head + "\n" + tail


def send_failed(result, title):
    code = result.get("code")
    lines = ["نتوانستم درخواست را برای %s بفرستم؛ چیزی جایی نرفت." % _name(title)]
    detail = str(result.get("detail_fa") or "").strip()
    if code == "open_failed" and result.get("copied"):
        lines = ["متن درخواست در کلیپ‌بورد است، ولی نتوانستم برنامه/سایت %s را باز کنم: %s" % (_name(title), detail or "باز نشد"),
                 "خودت آن را باز کن، متن را «جای‌گذاری» کن و بفرست؛ بعد با «جواب آمد» ادامه بده."]
        return "\n".join(lines)
    if detail:
        lines.append("دلیل: " + _clip(detail, 240))
    if code in ("unavailable_platform", "native_feature_missing"):
        lines.append("این کار فقط در برنامهٔ اندرویدیِ کامل ممکن است.")
    lines.append("راه دستی: بگو «پرامپت بستهٔ کد برای …» تا متن را همین‌جا ببینی، خودت ببرش پیش دستیار و جوابش را همین‌جا بچسبان.")
    return "\n".join(lines)


# ================================================================== the answer
def no_mission():
    return ("ماموریت بازی ندارم که جوابش را بخوانم. اگر جوابی را از دستیاری گرفته‌ای، همین‌جا بچسبانش؛ "
            "اگر بسته است (=== PACK …) بررسی‌اش می‌کنم، وگرنه می‌توانی بگویی «از ChatGPT بخواه …» تا ماموریت تازه‌ای بسازم.")


SOURCE_NAME = {"screen": "صفحهٔ برنامهٔ دستیار", "shared": "متنِ اشتراک‌گذاری‌شده به این برنامه", "clipboard": "کلیپ‌بورد"}
CLIPBOARD_CODE = {"empty": "خالی بود (یا اندروید اجازهٔ خواندنش را نداد؛ این وقتی پیش می‌آید که برنامهٔ ما روی صفحه نباشد)",
                  "permission_denied": "اندروید اجازهٔ خواندنش را نداد", "unavailable_platform": "روی این دستگاه در دسترس نیست",
                  "rate_limited": "چند بار پشت‌سرهم خوانده شد؛ کمی صبر کن"}


def capture_nothing(result, title, kind):
    skipped = {source: reason for source, reason in (result.get("skipped") or [])}
    lines = ["هنوز جوابی از %s پیدا نکردم؛ چیزی نصب یا عوض نشد. جایی که نگاه کردم:" % _name(title)]
    if "screen" in skipped:
        lines.append("• %s: %s." % (SOURCE_NAME["screen"], SKIP_REASON.get(skipped["screen"], skipped["screen"])))
    lines.append("• %s: %s." % (SOURCE_NAME["shared"], SKIP_REASON.get(skipped["shared"], skipped["shared"]) if "shared" in skipped else "نبود"))
    if "clipboard" in skipped:
        lines.append("• %s: %s." % (SOURCE_NAME["clipboard"], SKIP_REASON.get(skipped["clipboard"], skipped["clipboard"])))
    else:
        code = str(result.get("clipboard_code") or "")
        lines.append("• %s: %s." % (SOURCE_NAME["clipboard"], CLIPBOARD_CODE.get(code, "خوانده نشد (%s)" % M.ltr(code[:40] or "؟"))))
    lines.append("چه کنم: جواب را کامل کپی کن%s، به این برنامه برگرد و دوباره بگو «جواب آمد»؛ یا در برنامهٔ دستیار «اشتراک‌گذاری» را بزن و این برنامه را انتخاب کن؛ یا خود جواب را همین‌جا بچسبان." % (
        " (از «=== PACK» تا «=== END PACK ===»)" if kind in ("code", "lang") else ""))
    return "\n".join(lines)


def captured_pack(source, review):
    return "جواب را %s گرفتم و فقط بررسی کردم (چیزی اجرا یا نصب نشده):\n%s" % (SOURCE_LABEL.get(source, "از جای نامعلوم"), review)


def answer(title, text, source, mission_kind="ask"):
    shown = str(text).strip()
    cut = len(shown) > MAX_ANSWER_SHOWN
    shown = shown[:MAX_ANSWER_SHOWN]
    lines = ["جواب %s (%s):" % (_name(title), SOURCE_LABEL.get(source, "")), "", shown + ("…" if cut else "")]
    lines.append("")
    lines.append("این متن فقط همان چیزی است که دستیار بیرونی نوشته؛ درستی‌اش را من نسنجیده‌ام."
                 + (" (بخش آخرِ جواب را اینجا نشان ندادم.)" if cut else ""))
    if mission_kind == "ask":
        lines.append("اگر می‌خواهی این را به‌صورت قابلیت دائمی یاد بگیرم، بگو «از %s بخواه یک بسته برایش بنویسد»." % title)
    return "\n".join(lines)


# ================================================================== status, list, cancel, revoke
def status(mission, title, running, allowed):
    lines = []
    if mission is None:
        lines.append("الان ماموریتی با دستیار بیرونی ندارم.")
    else:
        lines.append("آخرین ماموریت: «%s» از %s." % (_clip(mission.get("wish"), 120), _name(title)))
        lines.append("• نوع: %s." % KIND_TEXT.get(mission.get("kind"), "—"))
        lines.append("• وضعیت: %s%s." % (STATE_LABEL.get(mission.get("state"), "نامشخص"), "؛ همین الان در کار است" if running else ""))
        lines.append("• راه فرستادن: %s." % ROUTE_TEXT.get(mission.get("route") or "none", "—"))
        if mission.get("note"):
            lines.append("• یادداشت: " + _clip(mission["note"], 200))
    if allowed:
        lines.append("برنامه‌هایی که اجازهٔ سر زدن به آن‌ها را داده‌ای (با زمان باقی‌مانده): " + "، ".join(
            "%s (%s)" % (M.ltr(pkg), _minutes(left)) for pkg, left in allowed[:6]) + ".")
    else:
        lines.append("اجازهٔ فعالی برای سر زدن به برنامه‌های دیگر نداده‌ای.")
    return "\n".join(lines)


def cancelled(count):
    if not count:
        return "ماموریت بازی نبود که لغو کنم."
    return "ماموریت را لغو کردم%s؛ از این به بعد جوابِ آن را نمی‌خوانم." % ("" if count == 1 else " (%s ماموریت)" % fa(count))


def assistant_list(rows):
    lines = ["دستیارهای بیرونی که می‌شناسم (فقط با اجازهٔ تو و فقط وقتی بگویی سراغشان می‌روم):"]
    for row in rows:
        lines.append("• %s — %s" % (M.ltr(row["title"]), ("برنامه‌اش روی گوشی دیده می‌شود (%s)" % M.ltr(row["package"])) if row.get("installed")
                                    else "برنامه‌اش دیده نمی‌شود؛ سایتش: " + M.ltr(row["site"].replace("https://", "").rstrip("/"))))
    lines.append("بگو: «از Claude بخواه …» یا «از ChatGPT بپرس …». «دیده نمی‌شود» یعنی نصب نیست یا اندروید آن را به این برنامه نشان نمی‌دهد.")
    return "\n".join(lines)


def revoked(count):
    if not count:
        return "اجازهٔ فعالی برای سر زدن به برنامه‌های دیگر وجود نداشت؛ چیزی تغییر نکرد."
    return ("اجازهٔ سر زدن به برنامه‌های دیگر پس گرفته شد (%s مورد). سرویس «دسترس‌پذیری» اندروید هنوز در تنظیمات روشن است؛ "
            "اگر می‌خواهی کاملاً خاموش شود، خودت از «تنظیمات دسترس‌پذیری» خاموشش کن." % fa(count))


# ================================================================== the accessibility page and the typing recipe
ACCESS_STEPS = ("در صفحه‌ای که باز شد، «برنامه‌های نصب‌شده / سرویس‌های دانلودشده» را بزن، «دستیار هوشمند» را پیدا کن و روشنش کن. "
                "اندروید این کلید را فقط خودت می‌توانی بزنی؛ من نمی‌توانم. اگر کلید خاکستری و غیرقابل‌لمس بود: تنظیمات ← برنامه‌ها ← دستیار هوشمند ← "
                "منوی سه‌نقطه ← «اجازهٔ تنظیمات محدودشده» (برای برنامه‌هایی که از فروشگاه نصب نشده‌اند در اندروید ۱۳ به بعد لازم است)، بعد دوباره امتحان کن.")


def access_settings(result):
    if result.get("ok"):
        return "صفحهٔ «دسترس‌پذیری» را باز کردم.\n" + ACCESS_STEPS
    code = result.get("code")
    lines = ["نتوانستم صفحهٔ دسترس‌پذیری را باز کنم: " + _clip(result.get("detail_fa") or code or "نامعلوم", 200)]
    lines.append("خودت: تنظیمات اندروید ← دسترس‌پذیری ← برنامه‌های دانلودشده ← «دستیار هوشمند».")
    return "\n".join(lines)


def ask_screen(title, package, minutes):
    return ("برای اینکه خودم درخواست را در برنامهٔ %s (%s) تایپ کنم و جوابش را بخوانم، باید بتوانم محتوای صفحهٔ همان برنامه را ببینم و در آن تایپ و کلیک کنم.\n"
            "• فقط همین یک برنامه، و فقط %s. بعدش خودکار تمام می‌شود.\n"
            "• برنامه‌های سیستمی (تنظیمات اندروید، نصب‌کنندهٔ برنامه، مدیر مجوزها، فروشگاه) همیشه ممنوع‌اند و متنِ فیلد رمز خوانده نمی‌شود.\n"
            "• هر وقت خواستی بگو «به برنامه‌های دیگر سر نزن» تا همین الان پس گرفته شود.\n"
            "• این روش آزمایشی است و به ظاهر آن برنامه بستگی دارد؛ اگر نشد، راه دستیِ کپی و جای‌گذاری همیشه هست.\n"
            "اجازه می‌دهی؟ (بله / نه)" % (_name(title), M.ltr(package), _minutes(minutes * 60)))


def screen_blocked(state, title):
    code = state.get("code")
    name = _name(title)
    if code == "no_app":
        return "برنامهٔ %s روی گوشی دیده نمی‌شود، پس نمی‌توانم در آن تایپ کنم. راه دستی (کپی و جای‌گذاری در سایتش) را بگو اگر می‌خواهی." % name
    if code == "not_enabled":
        return ("سرویس «دسترس‌پذیری» روشن نیست، و روشن‌کردنش فقط کار خودت است. بگو «تنظیمات دسترس‌پذیری را باز کن» تا صفحه را باز کنم؛ "
                "بعد از روشن‌کردن، دوباره بگو «خودت انجام بده».")
    if code in ("unavailable_platform", "native_feature_missing"):
        return ("این نسخهٔ برنامه (یا این دستگاه) بخش «دسترس‌پذیری» را ندارد، پس نمی‌توانم خودم در برنامهٔ دیگر تایپ کنم. "
                "راه دستی (کپی و جای‌گذاری) کار می‌کند.")
    if code == "busy":
        return "یک اجرای دیگر هنوز در کار است؛ صبر کن تمام شود یا بگو «ماموریت را لغو کن»."
    if code == "no_mission":
        return no_mission()
    return "الان نمی‌توانم این کار را خودم انجام بدهم: " + _clip(state.get("detail_fa") or code or "نامعلوم", 200)


def screen_started(result, title):
    origin = "با دستورالعملی که یک بسته آورده" if result.get("recipe") == "pack" else "با دستورالعمل عمومیِ خودم"
    return ("شروع کردم: %s را %s باز می‌کنم، درخواست را تایپ می‌کنم و جوابش را می‌خوانم. تا تمام نشده، دست به صفحه نزن و برنامه را نبند.\n"
            "تمام که شد، این برنامه را دوباره جلو می‌آورم و اعلان می‌دهم؛ آن‌وقت بگو «جواب آمد». "
            "اگر وسط راه گیر کردم یا جواب را نیافتم، همین را می‌گویم و راه دستی هست. (روشی آزمایشی است.)" % (_name(title), origin))


def allowed(package, minutes):
    return "اجازه ثبت شد: فقط به %s و فقط %s." % (M.ltr(package), _minutes(minutes * 60))


__all__ = ["need_wish", "route_hint", "ask_send", "mission_gone", "declined", "sent", "send_failed", "no_mission", "capture_nothing", "captured_pack",
           "answer", "status", "cancelled", "assistant_list", "revoked", "access_settings", "ask_screen", "screen_blocked", "screen_started", "allowed",
           "KIND_TEXT", "STATE_LABEL", "ROUTE_TEXT"]
