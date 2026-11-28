"""
Persian conversation brain - the words of the BODY  (Prompt 959, stage B)
==========================================================================
What the assistant says about its own body: the self-test report the user copies after trying the app on his phone, the access checklist
(what only HE can switch on - Android and HyperOS close a background app hard), the settings pages it opens, the one-time code it reads
from an SMS when he orders it, and the extra line of the emergency stop.

Every line is written from facts the doors report (`brain_hub.selftest`, `native_bridge`): "ok" is said only when the phone said so, and
what could not be read is said so. Nothing here reads, opens or changes anything - `hub_body` does that, and only on the user's order.
"""

from self_builder import fa_text

from .hub_messages_ownbrain import size

fa = fa_text.fa_number

SELFTEST_ASK = "گزارش آزمایشی"                            # the sentences the replies tell the user to say (each one is understood; a test proves it)
SELFTEST_COPY = "گزارش آزمایشی را کپی کن"
ACCESS_ASK = "چک‌لیست دسترسی‌ها"
OPEN_BATTERY = "صفحهٔ باتری را باز کن"
OPEN_APP = "تنظیمات برنامه را باز کن"
OPEN_NOTIFICATIONS = "تنظیمات اعلان را باز کن"
SMS_ASK = "کد پیامک را بخوان"
SMS_PERMISSION = "مجوز پیامک را بده"
CODE_PREFIX = "🔑 کدی که پیدا کردم: "                      # what the reply with a one-time code starts with; the stored copy is masked after it (hub_body)
CODE_MASK = "••••••"
SENDER_PREFIX = "(فرستنده: "                              # the line under the code: who sent the SMS (masked in the history together with the code)
SENDER_MASK = "•••)"

_PHASES = {"idle": "شروع نشده", "asking": "منتظرِ پاسخِ تو", "downloading": "در حال دانلود", "installing": "در حال نصب", "ready": "آماده",
           "paused": "متوقف", "failed": "ناموفق"}
_FEATURE_STATES = {"ready": "آماده ✅", "permission_required": "مجوز داده نشده", "permission_not_declared": "در این APK اعلام نشده",
                   "unavailable_platform": "خارج از اندروید", "native_bridge_missing": "بخشِ بومی در APK نیست",
                   "not_supported_on_this_android": "نسخهٔ اندروید کافی نیست", "special_permission_required": "مجوزِ ویژه لازم است",
                   "limited_by_android_policy": "محدودِ اندروید"}
_SETTINGS_TITLES = {"battery": "تنظیمات باتری (فهرستِ بهینه‌سازیِ اندروید)", "app": "صفحهٔ این برنامه در تنظیمات", "notifications": "تنظیمات اعلانِ این برنامه"}


def _whole(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return default
    return int(value)


def _yes_no(value, yes, no, unknown="نامعلوم"):
    return yes if value is True else no if value is False else unknown


def _age(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 20:
        return "همین الان"
    if seconds < 90:
        return "%s ثانیه پیش" % fa(seconds)
    return "%s دقیقه پیش" % fa(int(round(seconds / 60)))


# ================================================================== the self-test report
def selftest(facts):
    """The report, as text, from `brain_hub.selftest.collect()`. No key, no chat text, no code, no number, no path is in `facts`."""
    facts = facts or {}
    app, phone, engine, brain = facts.get("app") or {}, facts.get("phone") or {}, facts.get("engine") or {}, facts.get("ownbrain") or {}
    net, perms, body = facts.get("network") or {}, facts.get("permissions") or {}, facts.get("body") or {}
    lines = ["🩺 گزارشِ آزمایشی%s" % (" — %s" % facts["time"] if facts.get("time") else ""), ""]

    if app.get("known"):
        lines.append("📱 برنامه: نسخهٔ %s (کدِ %s) · اندروید SDK %s · %s" % (
            app.get("version_name") or "؟", fa(app.get("version_code") or 0), fa(app.get("sdk") or 0), "، ".join(app.get("abis") or []) or "ABI نامعلوم"))
    else:
        lines.append("📱 برنامه: نامعلوم (بخشِ بومی جواب نداد: %s)" % (app.get("code") or "؟"))

    if phone.get("ram_total"):
        low = " — اندروید می‌گوید حافظه کم است ⚠️" if phone.get("ram_low") else ""
        lines.append("🧮 حافظهٔ رم: کل %s، آزاد %s%s" % (size(phone["ram_total"]), size(phone.get("ram_available")), low))
    else:
        lines.append("🧮 حافظهٔ رم: نامعلوم")
    lines.append("💾 جای آزادِ ذخیره‌سازی: %s" % (size(phone["free"]) if phone.get("free") else "نامعلوم"))

    if phone.get("battery_known"):
        lines.append("🔋 باتری: %s%s" % (
            "برنامه از «بهینه‌سازیِ باتریِ اندروید» معاف است ✅" if phone.get("ignoring_battery")
            else "برنامه معاف نیست ⚠️ (اندروید ممکن است در پس‌زمینه ببندَدش)",
            " · حالتِ صرفه‌جوییِ باتری روشن است ⚠️" if phone.get("power_save") else ""))
        lines.append("   (این فقط وضعیتِ استانداردِ اندروید است؛ «شروع خودکار» و «بدون محدودیت»ِ مخصوصِ HyperOS را نمی‌توانم ببینم.)")
    else:
        lines.append("🔋 باتری: نامعلوم")

    lines.append("🌐 اینترنتِ برنامه: %s · شبکهٔ گوشی: %s" % (_yes_no(net.get("app_switch"), "روشن", "خاموش"), net.get("state") or "نامعلوم"))
    lines.append("🔔 اعلان: %s · 💬 پیامک: %s · 🎙️ میکروفون: %s" % (
        _FEATURE_STATES.get((perms.get("notifications") or {}).get("state"), "نامعلوم"),
        {"granted": "مجوز داده شده ✅", "denied": "مجوز داده نشده"}.get((perms.get("sms") or {}).get("state"), "نامعلوم"),
        _FEATURE_STATES.get((perms.get("microphone") or {}).get("state"), "نامعلوم")))

    if engine.get("available"):
        lines.append("🧠 موتورِ مغز (LiteRT-LM): آماده ✅")
    else:
        lines.append("🧠 موتورِ مغز (LiteRT-LM): ❌ کد: %s%s" % (engine.get("code") or "؟", (" — %s" % engine["reason_fa"]) if engine.get("reason_fa") else ""))
        if engine.get("api"):
            lines.extend(["   فهرستِ فنیِ موتور (برای اصلاحِ برنامه):", engine["api"]])
    others = [("%s %s" % (o.get("name"), "✅" if o.get("available") else "❌ " + str(o.get("code") or ""))).strip() for o in engine.get("others") or []]
    if others:
        lines.append("   موتورهای دیگر: " + " · ".join(others))

    if brain.get("known"):
        part = [_PHASES.get(brain.get("phase"), str(brain.get("phase") or "؟"))]
        if brain.get("phase") == "downloading" and brain.get("total"):
            part.append("%s٪ (%s از %s)" % (fa(int(brain.get("percent") or 0)), size(int(brain.get("bytes") or 0)), size(int(brain["total"]))))
        if brain.get("phase") == "installing" and brain.get("install_stage"):
            part.append("مرحلهٔ %s از %s (%s) · %s٪%s · %s ثانیه از شروعِ نصب" % (
                fa(_whole(brain.get("install_step"))), fa(_whole(brain.get("install_steps"))), brain["install_stage"],
                fa(_whole(brain.get("install_percent"))), " (حدودی)" if brain.get("install_estimated") else "", fa(_whole(brain.get("install_elapsed")))))
        if brain.get("code"):
            part.append("کد: %s%s" % (brain["code"], (" / %s" % brain["detail"]) if brain.get("detail") else ""))
        lines.append("🧩 مغزِ خودکار: " + " · ".join(part))
    else:
        lines.append("🧩 مغزِ خودکار: نامعلوم")

    lines.append("⚙️ سرویسِ پس‌زمینه: بخشِ بومی در APK: %s · اکنون: %s%s%s" % (
        _yes_no(body.get("native"), "هست ✅", "نیست ❌"), _yes_no(body.get("running"), "روشن", "خاموش"),
        (" · کارها: " + "، ".join(body["jobs"])) if body.get("jobs") else "",
        (" · آخرین پاسخِ در: %s" % body["code"]) if body.get("code") and body.get("code") != "ok" else ""))

    errors = facts.get("errors") or []
    if errors:
        lines.append("⚠️ خطاهای اخیرِ برنامه (فقط نوع، بدونِ متن):")
        lines.extend("   %s: %s ×%s" % (e.get("operation") or "؟", e.get("type") or "؟", fa(e.get("count") or 1)) for e in errors)
    else:
        lines.append("✅ خطای ثبت‌شده‌ای نیست.")
    lines.append("📦 مدل‌های ثبت‌شده: %s" % fa(int(facts.get("models") or 0)))
    lines.extend(["", "این گزارش هیچ کلید، متنِ گفتگو، کدِ پیامک، شماره یا مسیرِ فایلی ندارد. اگر چیزی کار نکرد، همین متن را برای من بفرست."])
    return "\n".join(lines)


def selftest_hint():
    """The last lines of a report that was not copied: how to copy it, and where the background settings are."""
    return "برای گذاشتنِ این گزارش در کلیپ‌بورد بگو «%s»؛ برای مرورِ تنظیماتِ پس‌زمینه بگو «%s»." % (SELFTEST_COPY, ACCESS_ASK)


def copied(ok, code=""):
    if ok:
        return "گزارش را در کلیپ‌بوردِ گوشی گذاشتم؛ می‌توانی هر جا «چسباندن» بزنی."
    return "نتوانستم آن را در کلیپ‌بورد بگذارم (%s)؛ متن را با انگشت انتخاب و کپی کن." % (code or "خطا")


# ================================================================== the access checklist
def access_checklist(quick):
    """The checklist, with what the phone says about each item. `quick`: `brain_hub.selftest.quick()`."""
    quick = quick or {}
    battery = quick.get("battery") or {}
    battery_state = (_yes_no(battery.get("ignoring"), "الان معاف است ✅", "الان معاف نیست ⚠️", "الان نامعلوم")
                     + (" · صرفه‌جوییِ باتری روشن است" if battery.get("power_save") else ""))
    notif = _FEATURE_STATES.get(quick.get("notifications"), "نامعلوم")
    sms = {"granted": "داده شده ✅", "denied": "داده نشده"}.get(quick.get("sms"), "نامعلوم")
    return "\n".join([
        "🛠️ چک‌لیستِ دسترسی‌ها برای کار در پس‌زمینه (مخصوصِ HyperOS / شیائومی)",
        "",
        "اندروید و HyperOS برنامه‌ای را که روی صفحه نیست سخت می‌بندند؛ برای اینکه دانلودِ مغز (چند دقیقه تا چند ساعت) نیمه‌راه قطع نشود، این چند تنظیم را "
        "خودت یک‌بار انجام بده. برنامه هیچ‌کدام را نمی‌تواند خودش عوض کند:",
        "",
        "۱. باتری ← «بدون محدودیت»: تنظیمات ← برنامه‌ها ← مدیریتِ برنامه‌ها ← این برنامه ← «صرفه‌جوییِ باتری» ← «بدون محدودیت». (%s؛ این فقط "
        "وضعیتِ استانداردِ اندروید است و تنظیمِ ویژهٔ HyperOS را نمی‌بینم.)" % battery_state,
        "۲. شروع خودکار: همان صفحه ← «شروع خودکار» ← روشن.",
        "۳. قفل در برنامه‌های اخیر: برنامه را باز کن، دکمهٔ «اخیر» را بزن، روی کارتِ برنامه نگه دار و «قفل» را بزن.",
        "۴. اعلان‌ها: روشن باشند (الان: %s). اعلانِ «در حال گرفتنِ مغز» و دکمهٔ «ایست» از همین‌جاست." % notif,
        "۵. فقط برای خواندنِ کدِ پیامک: مجوزِ «پیامک» (الان: %s). اگر اندروید اجازه نداد: تنظیمات ← برنامه‌ها ← این برنامه ← سه‌نقطهٔ بالا ← "
        "«اجازهٔ تنظیماتِ محدودشده»." % sms,
        "",
        "برای باز شدنِ صفحه‌ها بگو: «%s»، «%s» یا «%s». بعد از دانلود هم می‌توانی «%s» بگیری تا ببینی چه چیزی هنوز لازم است." % (
            OPEN_BATTERY, OPEN_APP, OPEN_NOTIFICATIONS, SELFTEST_ASK),
    ])


def opened(kind):
    return "%s را باز کردم؛ تنظیم با خودت است، من هیچ‌چیز را عوض نمی‌کنم." % _SETTINGS_TITLES.get(kind, "صفحه")


def open_failed(code, kind=""):
    if code == "unavailable_platform":
        return "بازکردنِ صفحهٔ تنظیمات فقط داخلِ برنامهٔ اندروید ممکن است."
    if code == "rate_limited":
        return "چند بار پشت‌سرهم خواستی؛ چند دقیقه صبر کن و دوباره بگو."
    return "نتوانستم صفحه را باز کنم (%s)؛ برنامه باید روی صفحه باز باشد." % (code or "خطا")


# ================================================================== the one-time code of an SMS
def sms_privacy(scrubbed=True):
    kept = ("متنِ پیام را نخواندم و نگه نمی‌دارم؛ این کد فقط همین‌جا نشان داده می‌شود، به هیچ جایی فرستاده نمی‌شود و چند ثانیه بعد از "
            "تاریخچهٔ گفتگوی برنامه هم پاک می‌شود. کد را به هیچ‌کس نگو.")
    if scrubbed:
        return kept
    return ("متنِ پیام را نخواندم و نگه نمی‌دارم و به هیچ جایی نمی‌فرستم؛ ولی این بار نتوانستم پاک‌کردنِ خودکارِ کد از تاریخچهٔ گفتگو را برنامه‌ریزی "
            "کنم، پس بعد از استفاده خودت گفتگو را پاک کن. کد را به هیچ‌کس نگو.")


def sms_code(data, scrubbed=True):
    """The reply with the code. Two marks in it - the line that starts with `CODE_PREFIX` and the one that starts with `SENDER_PREFIX` - are what
    `hub_body.scrub_codes` finds (and masks) in the stored chat history."""
    data = data or {}
    sender = " ".join(str(data.get("sender") or "").split())[:40] or "نامشخص"
    code = "".join(str(data.get("code") or "").split())[:40]
    return "%s%s\n%s%s · %s)\n\n%s" % (CODE_PREFIX, code, SENDER_PREFIX, sender, _age(data.get("age_seconds")), sms_privacy(scrubbed))


def sms_empty(minutes):
    return ("در پیامک‌های %s دقیقهٔ اخیر کدِ یک‌بارمصرفی پیدا نکردم. اگر کد تازه رسیده چند ثانیه صبر کن و دوباره بگو «%s»؛ برای پیام‌های "
            "قدیمی‌تر بگو «کدِ پیامکِ یک ساعت اخیر را بخوان»." % (fa(minutes), SMS_ASK))


def sms_need_permission():
    return ("برای خواندنِ کدِ پیامک، اندروید باید اجازهٔ «پیامک» را بدهد و هنوز نداده. این اجازه فقط وقتی به کار می‌رود که خودت بگویی «%s»؛ "
            "متنِ پیام‌ها را نمی‌خوانم، نگه نمی‌دارم و جایی نمی‌فرستم. اگر موافقی بگو «%s» تا پنجرهٔ خودِ اندروید باز شود و تصمیم با تو باشد." % (SMS_ASK, SMS_PERMISSION))


def sms_permission_have():
    return "اجازهٔ پیامک از قبل داده شده؛ هر وقت خواستی بگو «%s»." % SMS_ASK


def sms_permission_shown():
    return ("پنجرهٔ اندروید باز شد؛ اگر «اجازه» را زدی، دوباره بگو «%s». اگر پنجره باز نشد یا «اجازه» خاکستری بود: این برنامه را بیرون از فروشگاه "
            "نصب کرده‌ای و اندروید ۱۳ به بعد برای چنین برنامه‌هایی مجوزِ پیامک را قفل می‌کند. تنظیمات ← برنامه‌ها ← این برنامه ← سه‌نقطهٔ بالا ← "
            "«اجازهٔ تنظیماتِ محدودشده»، بعد دوباره بگو «%s» (برای باز شدنِ صفحه بگو «%s»)." % (SMS_ASK, SMS_PERMISSION, OPEN_APP))


def sms_failed(code):
    if code == "permission_denied":
        return sms_need_permission()
    if code == "unavailable_platform":
        return "خواندنِ پیامک فقط داخلِ برنامهٔ اندروید ممکن است."
    if code == "rate_limited":
        return "چند بار پشت‌سرهم خواستی؛ چند دقیقه صبر کن و دوباره بگو."
    if code == "unavailable":
        return "صندوقِ پیامکِ این گوشی خوانده نشد (اندروید یا HyperOS آن را به برنامه نداد)."
    if code == "not_allowed":
        return "پنجرهٔ مجوز باز نشد؛ برنامه باید روی صفحه باز باشد."
    return "نتوانستم پیامک را بخوانم (%s)." % (code or "خطا")


# ================================================================== the emergency stop
def emergency_extra(stopped, released):
    """The lines the chat's «ایست» adds after its own: the request to a local model's engine, and the notification of the background service."""
    parts = []
    if "engine" in (stopped or ()):
        parts.append("به موتورِ مدلِ روی گوشی هم گفتم جوابی را که می‌سازد رها کند (اگر جوابی در حال ساخته‌شدن بود، چند ثانیه بعد قطع می‌شود).")
    if released:
        parts.append("اعلانِ پس‌زمینه هم برداشته شد.")
    return " ".join(parts)
