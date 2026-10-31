"""
Persian conversation brain - messages of the pack system (code packs and language packs)
=========================================================================================
Like `hub_messages`, every sentence is built from the RESULT of a real call (`pack_system.manager`): nothing says
"installed", "active" or "loaded" unless the result says so, and a failure always says what did NOT happen.
"""

from self_builder import fa_text

from . import messages as M

fa = fa_text.fa_number

KIND_LABEL = {"code_v1": "بستهٔ کد", "lang_v1": "بستهٔ زبان"}
STATE_LABEL = {"active": "فعال", "disabled": "خاموش", "quarantined": "قرنطینه (سالم نبود؛ بارگذاری نشد)",
               "pending_restart": "نصب شده؛ منتظر بستن و باز کردن دوبارهٔ برنامه", "inactive": "نصب‌شده ولی فعال نیست"}
PERMISSION_LABEL = {"network": "خواندن صفحه‌های وب (با دروازهٔ اینترنت برنامه)", "android": "درگاه‌های گوشی (اشتراک‌گذاری، اعلان، گفتار …)",
                    "clipboard": "خواندن و نوشتن کلیپ‌بورد", "model": "مدل زبانی روی گوشی",
                    "teacher": "پرسیدن از دستیارهای دیگر (ChatGPT، Claude …) با اجازهٔ تو",
                    "ui": "نمایش چیزی در رابط", "replace_core": "جایگزین‌کردن بخشی از خود برنامه (پرخطر)",
                    "screen": "دیدن و کنترل صفحهٔ برنامه‌های دیگر (پرخطر؛ فقط برنامه‌هایی که خودت اجازه بدهی)",
                    "unsafe_native": "دسترسی مستقیم به Java/اندروید (پرخطر)"}
EVENT_LABEL = {
    "pack_proposed": "پیشنهاد شد", "pack_declined": "رد شد", "pack_rejected": "بسته نپذیرفته شد", "pack_installed": "نصب شد",
    "pack_activated": "فعال شد", "pack_activation_failed": "فعال‌سازی ناموفق بود و برگشت", "pack_install_failed": "نصب ناموفق بود",
    "pack_rolled_back": "به نسخهٔ قبل برگشت", "pack_disabled": "خاموش شد", "pack_enabled": "دوباره روشن شد", "pack_removed": "حذف شد",
    "pack_quarantined": "به قرنطینه رفت", "pack_auto_disabled": "خودکار خاموش شد (چند بار خطا داد)",
    "pack_boot_rollback": "بعد از یک شروع ناموفق به نسخهٔ سالم برگشت یا خاموش شد", "pack_safe_mode_entered": "حالت امن شروع شد",
    "pack_safe_mode_left": "حالت امن تمام شد", "pack_boot_failed_before": "شروع قبلی برنامه کامل نشد",
}


def kind_label(kind, default="بسته"):
    return KIND_LABEL.get(str(kind).replace(".", "_"), default)


def _ltr(text, limit=170):
    return M.ltr(" ".join(str(text).split())[:limit])


def _ver(n):
    return "نسخهٔ " + fa(n) if isinstance(n, int) and not isinstance(n, bool) else "نسخهٔ نامشخص"


def _size(n):
    n = int(n or 0)
    return "%s کیلوبایت" % fa(max(1, round(n / 1024))) if n >= 1024 else "%s بایت" % fa(n)


def perm_names(perms):
    return "، ".join(PERMISSION_LABEL.get(p, p) for p in perms)


# ------------------------------------------------------------------ proposals
def proposal(result):
    """The review the user sees BEFORE anything is installed."""
    title, pid, kind = result.get("title") or result.get("pack_id"), result.get("pack_id"), result.get("kind")
    lines = ["%s «%s» (%s) را بررسی کردم؛ هنوز چیزی نصب یا فعال نشده است:" % (kind_label(kind), title, _ltr(pid))]
    if result.get("description"):
        lines.append("• کار این بسته: " + " ".join(str(result["description"]).split())[:300])
    if kind == "lang.v1":
        lines.append("• %s پرسش‌وپاسخ با %s شکل پرسیدن (%s)." % (fa(result.get("qa_count", 0)), fa(result.get("phrasings", 0)), _size(result.get("bytes"))))
        lines.append("• این بسته فقط «داده» است و کدی ندارد. فقط وقتی پرسشت دقیقاً شبیه یکی از آن‌ها باشد با همان پاسخ جواب می‌دهم؛ اگر مطمئن نباشم ساکت می‌مانم و چیزی از خودم نمی‌سازم.")
        for sample in (result.get("samples") or [])[:2]:
            lines.append("• نمونه: «%s» ← «%s»" % (sample.get("q", ""), sample.get("a", "")))
    else:
        files = [f for f in (result.get("files") or []) if f.endswith(".py")]
        lines.append("• نوع: بستهٔ کد، یعنی قابلیت تازه برای خود برنامه — %s فایل (%s)؛ فایل‌ها: %s." % (
            fa(len(result.get("files") or [])), _size(result.get("bytes")), "، ".join(_ltr(f, 40) for f in files[:6]) or "—"))
        lines.append("• بررسی امنیتیِ خودکار (بدون اجرای کد): مشکلی پیدا نشد%s." % (
            "؛ %s هشدار هست" % fa(len(result["warnings"])) if result.get("warnings") else ""))
        for warn in (result.get("warnings") or [])[:3]:
            lines.append("   ◦ " + _ltr(warn.get("message_fa", ""), 150))
        perms = list(result.get("permissions") or [])
        lines.append("• مجوزهایی که می‌خواهد: " + (perm_names(perms) + "." if perms else "هیچ مجوز ویژه‌ای نمی‌خواهد."))
        if result.get("replaces"):
            lines.append("• این بسته بخشی از خود برنامه را جایگزین می‌کند: %s. بعد از نصب باید برنامه را کامل ببندی و دوباره باز کنی؛ اگر برنامه بعد از آن درست باز نشود، خودش به نسخهٔ سالم برمی‌گردد." % "، ".join(_ltr(r, 50) for r in result["replaces"]))
        else:
            lines.append("• بعد از نصب همین الان فعال می‌شود و کدش یک بار آزمایش خودکار می‌شود؛ اگر خطا بدهد خودش برمی‌گردد.")
        lines.append("• توجه: بررسی خودکار یک سد اولیه است، نه تضمین. کد بسته با دسترسی خود برنامه اجرا می‌شود؛ پس فقط بسته‌ای را بپذیر که از منبع مطمئنی آمده.")
    if result.get("action") == "update":
        lines.append("• این به‌روزرسانی یک بستهٔ نصب‌شده است؛ می‌شود %s و نسخهٔ فعلی نگه داشته می‌شود تا هر وقت خواستی برگردی." % _ver(result.get("planned_version")))
    else:
        lines.append("• این یک بستهٔ تازه است؛ می‌شود %s." % _ver(result.get("planned_version")))
    lines.append("نصب و فعالش کنم؟ (بله / نه) — اگر چیز دیگری بنویسی، این پیشنهاد کنار گذاشته می‌شود.")
    return "\n".join(lines)


def proposal_noop(result):
    return "این بسته با نسخهٔ نصب‌شدهٔ «%s» (%s) دقیقاً یکی است؛ چیزی تغییر نکرد.%s" % (
        result.get("title") or result.get("pack_id"), _ver(result.get("version")),
        "" if result.get("active") else " (آن نسخه الان فعال نیست؛ برای برگرداندنش بگو «نسخهٔ %s بستهٔ …».)" % fa(result.get("version") or 0))


def proposal_rejected(result):
    lines = ["بسته را نپذیرفتم؛ هیچ چیزی نصب یا فعال نشد."]
    findings = result.get("findings") or []
    if findings:
        for f in findings[:5]:
            where = "%s:%s" % (f.get("file") or "", f.get("line") or "") if f.get("file") else ""
            lines.append("• " + (_ltr(where, 60) + " — " if where else "") + str(f.get("message_fa") or f.get("code") or "")[:200])
        if len(findings) > 5:
            lines.append("… و %s مشکل دیگر." % fa(len(findings) - 5))
    else:
        lines.append("دلیل: " + str(result.get("message_fa") or result.get("code") or "نامشخص")[:300])
    lines.append("اگر بسته را از یک دستیار گرفته‌ای، همین دلیل را به او بده تا اصلاحش کند، بعد دوباره بفرستش.")
    return "\n".join(lines)


def proposal_failed(result):
    return "بسته را نتوانستم بررسی کنم و چیزی تغییر نکرد: " + str(result.get("message_fa") or result.get("code") or "خطای نامشخص")[:300]


def pack_not_found():
    return ("نشانهٔ بسته را دیدم، ولی یک بستهٔ کامل و قابل‌خواندن پیدا نکردم؛ چیزی نصب نشد. "
            "بستهٔ کامل را، از «=== PACK …» تا «=== END PACK ===»، دوباره بفرست.")


def other_schema(name):
    return ("این بسته با قالب «%s» نوشته شده، ولی این برنامه فقط code.v1 و lang.v1 را (برای بسته‌ها) می‌شناسد؛ چیزی نصب یا فعال نشد. "
            "بگو «پرامپت بسته» تا دستور درست را برای دستیارت بگیری." % _ltr(name, 20))


def ask_risky(result):
    lines = ["این بسته چیزی می‌خواهد که ریسک بیشتری دارد:"]
    for p in result.get("permissions") or []:
        lines.append("• " + PERMISSION_LABEL.get(p, p))
    if result.get("replaces"):
        lines.append("• جایگزین‌شدن این بخش‌های برنامه: " + "، ".join(_ltr(r, 50) for r in result["replaces"]))
    lines.append("اگر منبعش را می‌شناسی و واقعاً می‌خواهی، بنویس «بله، مطمئنم». هر چیز دیگری یعنی نصب نشود.")
    return "\n".join(lines)


def risky_needs_word():
    return "برای این بسته «بله» کافی نیست؛ اگر مطمئنی بنویس «بله، مطمئنم»، وگرنه «نه». تا آن موقع چیزی نصب نشده است."


# ------------------------------------------------------------------ approval results
def approved(result):
    title, kind = result.get("title") or result.get("pack_id"), result.get("kind")
    if not result.get("hot"):
        lines = ["«%s» نصب شد (%s)، ولی چون بخشی از خود برنامه را عوض می‌کند، فقط بعد از اینکه برنامه را کامل ببندی و دوباره باز کنی کار می‌کند." % (title, _ver(result.get("version"))),
                 "اگر بعد از باز شدن چیزی خراب بود، برنامه خودش به نسخهٔ سالم برمی‌گردد؛ یا بگو «حالت امن»."]
    elif kind == "lang.v1":
        lines = ["«%s» نصب و فعال شد (%s)؛ از همین پیام به بعد از آن استفاده می‌کنم." % (title, _ver(result.get("version")))]
    else:
        lines = ["«%s» نصب و فعال شد (%s)." % (title, _ver(result.get("version"))),
                 "کدش بارگذاری و آزمایش شد و فایل‌هایش با اثر انگشتشان تطبیق دارند؛ از همین الان کار می‌کند."]
    prev = result.get("previous_version")
    if prev:
        lines.append("نسخهٔ قبلی (%s) نگه داشته شد؛ با «بستهٔ %s را برگردان» می‌توانی به آن برگردی." % (fa(prev), title))
    return "\n".join(lines)


def approve_failed(result):
    status, code = result.get("status"), result.get("code")
    if code == "E_PACK_NO_PROPOSAL":
        return "این پیشنهاد دیگر باز نیست (منقضی شده یا قبلاً تصمیم گرفته شده)؛ چیزی نصب نشد. بسته را دوباره بفرست."
    if code == "E_PACK_ACTIVATION":
        text = "بسته بارگذاری یا آزمایش نشد و فعال نیست: " + _ltr(result.get("message_fa", ""), 200)
        if result.get("rolled_back_to"):
            text += " نسخهٔ قبلی (%s) دوباره فعال و سالم ماند." % fa(result["rolled_back_to"])
        return text
    if status == "approval_required":
        return "بدون تأیید صریح تو چیزی نصب نمی‌شود؛ بنویس «بله» اگر می‌خواهی."
    return "نصب کامل نشد و چیزی فعال نیست. دلیل: " + str(result.get("message_fa") or result.get("code") or "نامشخص")[:300]


# ------------------------------------------------------------------ list / history / status
def no_packs():
    return ("هنوز هیچ بسته‌ای نصب نکرده‌ام. «بسته» یعنی قابلیتی که از بیرون (مثلاً از ChatGPT یا Claude) برایم نوشته می‌شود و با تأیید تو نصب می‌شود، "
            "بی‌آنکه برنامه را دوباره بسازی. بگو «پرامپت بسته برای …» تا متن آمادهٔ درخواست را بدهم.")


def pack_list(rows, pending=(), restart=(), safe=None):
    if not rows and not pending:
        return no_packs()
    lines = []
    if safe and safe.get("level"):
        lines.append("⚠\ufe0f برنامه الان در «حالت امن» است: هیچ بستهٔ کدی بارگذاری نشده تا برنامه همان‌طور که ساخته شده کار کند. برای برگشت بگو «حالت امن را تمام کن».")
    if rows:
        lines.append("بسته‌های نصب‌شده:")
    for r in rows:
        ver = "نسخهٔ %s" % fa(r["active_version"]) if r.get("active_version") else "بدون نسخهٔ فعال"
        lines.append("• «%s» (%s) — %s، %s؛ %s" % (r["title"], _ltr(r["pack_id"], 40), kind_label(r["kind"], r["kind"]), ver, STATE_LABEL.get(r["state"], r["state"])))
        if len(r.get("versions") or []) > 1:
            lines.append("   نسخه‌های نگه‌داشته‌شده: " + "، ".join(fa(v) for v in r["versions"]))
        if r.get("quarantine"):
            lines.append("   دلیل قرنطینه: " + _ltr(r["quarantine"].get("reason", ""), 80))
    if pending:
        lines.append("پیشنهادهای منتظر تأیید: " + "، ".join("«%s»" % p["title"] for p in pending))
    if restart:
        lines.append("برای اعمال کامل این بسته‌ها برنامه را یک بار کامل ببند و باز کن: " + "، ".join(_ltr(p, 40) for p in restart))
    return "\n".join(lines)


def pack_history(events, titles=()):
    if not events:
        return "هنوز رویدادی برای بسته‌ها ثبت نشده است."
    lines = ["تاریخچهٔ بسته‌ها (قدیمی ← تازه):"]
    for e in events:
        key = str(e.get("kind", "")).replace(".", "_")
        what = EVENT_LABEL.get(key, key)
        detail = e.get("detail") or {}
        extra = " (%s)" % _ver(detail["version"]) if isinstance(detail.get("version"), int) else ""
        lines.append("• %s — %s%s" % (_ltr(e.get("subject") or "—", 40), what, extra))
    lines.append("این تاریخچه زنجیرهٔ هش‌دار است؛ دست‌کاری‌اش از بیرون تشخیص داده می‌شود.")
    return "\n".join(lines)


def status(summary, rows=()):
    lines = ["وضعیت بسته‌ها: %s نصب‌شده، %s فعال، %s خاموش، %s در قرنطینه." % (
        fa(summary["installed"]), fa(summary["active"]), fa(summary["disabled"]), fa(summary["quarantined"]))]
    safe = summary.get("safe_mode") or {}
    if safe.get("level"):
        lines.append("⚠\ufe0f «حالت امن» روشن است (%s): بستهٔ کدی بارگذاری نشده؛ بستهٔ زبان در دسترس است. «حالت امن را تمام کن» را بگو تا دوباره بارگذاری شوند." % _ltr(safe.get("reason") or "؟", 40))
    else:
        lines.append("حالت امن: خاموش (برنامه عادی کار می‌کند).")
    if summary.get("pending_restart"):
        lines.append("منتظر باز شدن دوبارهٔ برنامه: %s بسته." % fa(summary["pending_restart"]))
    if summary.get("pending_proposals"):
        lines.append("پیشنهاد باز: %s." % fa(summary["pending_proposals"]))
    audit = summary.get("audit")
    if audit is not None:
        lines.append("تاریخچهٔ هش‌دار: " + ("سالم (%s رویداد)" % fa(audit.get("entries", 0)) if audit.get("ok") else "خراب شده؛ از رویداد %s به بعد قابل‌اعتماد نیست." % fa(audit.get("first_bad_seq") or 0)))
    if summary.get("state_recovery"):
        lines.append("فایل وضعیت بسته‌ها خراب بود و کنار گذاشته شد؛ بسته‌های قبلی را دوباره بفرست (فایل‌های خود بسته‌ها پاک نشده‌اند).")
    return "\n".join(lines)


def which_pack(action, rows):
    names = "، ".join("«%s»" % r["title"] for r in rows[:8])
    return "کدام بسته را %s؟ یکی از این‌ها را نام ببر: %s." % (action, names)


def no_such_pack():
    return "بستهٔ نصب‌شده‌ای با این نام پیدا نکردم. بگو «بسته‌ها» تا فهرست را ببینی."


# ------------------------------------------------------------------ questions and their results
def ask_rollback(title, current, target):
    return "«%s» را از %s به %s برگردانم؟ (بله / نه)" % (title, _ver(current), _ver(target))


def rolled_back(result):
    text = "«%s» به %s برگشت و فعال است (قبلاً %s فعال بود)." % (result.get("pack_id"), _ver(result.get("to_version")), _ver(result.get("from_version")))
    if not result.get("hot", True):
        text += " برای اعمال کامل، برنامه را یک بار ببند و باز کن."
    return text


def rollback_failed(result):
    code = result.get("code")
    if code == "E_PACK_NO_PREVIOUS":
        return "نسخهٔ قدیمی‌تری برای برگشتن نیست؛ چیزی تغییر نکرد."
    if code == "E_PACK_NO_VERSION":
        return "آن نسخه از این بسته نصب نیست؛ چیزی تغییر نکرد."
    return "برگرداندن ممکن نشد و چیزی تغییر نکرد: " + _ltr(result.get("message_fa") or result.get("code") or "نامشخص", 200)


def ask_disable(title):
    return "بستهٔ «%s» را خاموش کنم؟ فایل‌هایش می‌ماند و هر وقت خواستی دوباره روشنش می‌کنم. (بله / نه)" % title


def ask_enable(title):
    return "بستهٔ «%s» را دوباره روشن کنم؟ (قبل از روشن‌شدن فایل‌هایش دوباره با اثر انگشتشان تطبیق داده می‌شود.) (بله / نه)" % title


def ask_remove(title):
    return "بستهٔ «%s» را کاملاً حذف کنم؟ همهٔ نسخه‌ها و داده‌های خودش پاک می‌شود و برنمی‌گردد. (بله / نه)" % title


def disabled(result):
    text = "بستهٔ «%s» خاموش شد." % (result.get("title") or result.get("pack_id"))
    if result.get("restart_needed"):
        text += " چون بخشی از خود برنامه را عوض کرده بود، تا برنامه را یک بار کامل نبندی و باز نکنی کاملاً از کار نمی‌افتد."
    return text


def enabled(result):
    return "بستهٔ «%s» دوباره روشن شد." % (result.get("title") or result.get("pack_id"))


def removed(result):
    text = "بستهٔ «%s» حذف شد." % (result.get("title") or result.get("pack_id"))
    if result.get("restart_needed"):
        text += " برنامه را یک بار کامل ببند و باز کن تا اثرش کاملاً برود."
    return text


def switch_failed(result):
    code = result.get("code")
    if code == "E_PACK_VERIFY":
        return "فایل‌های این بسته با اثر انگشت ثبت‌شده نمی‌خوانند (دست‌کاری یا خرابی)؛ روشنش نکردم. می‌توانی بستهٔ سالمش را دوباره بفرستی."
    if code == "E_PACK_ACTIVATION":
        return approve_failed(result)
    return "انجام نشد و چیزی تغییر نکرد: " + _ltr(result.get("message_fa") or result.get("code") or "نامشخص", 200)


# ------------------------------------------------------------------ safe mode
def ask_safe_leave():
    return ("«حالت امن» را تمام کنم؟ بستهٔ کدهای نصب‌شده دوباره بارگذاری می‌شوند (بستهٔ جایگزین‌کنندهٔ خود برنامه فقط بعد از بستن و باز کردن برنامه). "
            "اگر باز هم برنامه خراب شد، دوباره خودش به حالت امن می‌رود. (بله / نه)")


def safe_left(report):
    loaded, failed = len(report.get("loaded") or ()), len(report.get("failed") or ())
    text = "حالت امن تمام شد."
    if loaded or failed or report.get("restart"):
        text += " %s بستهٔ کد بارگذاری شد" % fa(loaded)
        if failed:
            text += "، %s بسته سالم نبود و به قرنطینه رفت" % fa(failed)
        if report.get("restart"):
            text += "، %s بسته بعد از بستن و باز کردن برنامه فعال می‌شود" % fa(len(report["restart"]))
        text += "."
    return text


def not_in_safe_mode():
    return "برنامه در حالت امن نیست؛ همه‌چیز عادی کار می‌کند."


# ------------------------------------------------------------------ help and prompt
def help_text():
    return ("«بسته» راهِ بزرگ‌شدنِ این برنامه از داخل خودش است، بدون ساختن نسخهٔ تازه در GitHub:\n"
            "• بستهٔ زبان: داده‌های پرسش‌وپاسخ فارسی؛ هر چه بیشتر بدهی، بیشتر می‌فهمم.\n"
            "• بستهٔ کد: قابلیت تازه؛ فقط بعد از بررسی امنیتی و «بله»ی تو نصب می‌شود، نسخه‌بندی دارد، برمی‌گردد و اگر خراب شود برنامه خودش به حالت سالم برمی‌گردد.\n"
            "راه کار: بگو «پرامپت بسته برای …» و آنچه می‌خواهی را بنویس؛ متنی می‌دهم که به ChatGPT یا Claude می‌دهی؛ جوابش را همین‌جا در چت بچسبان؛ بررسی می‌کنم و می‌پرسم نصبش کنم یا نه.\n"
            "دستورهای من: «بسته‌ها»، «تاریخچهٔ بسته‌ها»، «بستهٔ … را برگردان / خاموش کن / روشن کن / حذف کن»، «وضعیت بسته‌ها»، «حالت امن».")


def prompt_reply(prompt_text, from_memory=False):
    head = "این متن را کامل کپی کن و به ChatGPT یا Claude (یا هر دستیار دیگر) بده؛ جوابش را همین‌جا در چت بچسبان:"
    if from_memory:
        head = "درخواستی را که قبلاً گفته بودی (و نتوانستم انجام بدهم) در متن گذاشتم. " + head
    return head + "\n\n" + prompt_text


__all__ = ["proposal", "proposal_noop", "proposal_rejected", "proposal_failed", "pack_not_found", "other_schema", "ask_risky",
           "risky_needs_word", "approved", "approve_failed", "no_packs", "pack_list", "pack_history", "status", "which_pack",
           "no_such_pack", "ask_rollback", "rolled_back", "rollback_failed", "ask_disable", "ask_enable", "ask_remove",
           "disabled", "enabled", "removed", "switch_failed", "ask_safe_leave", "safe_left", "not_in_safe_mode", "help_text",
           "prompt_reply", "KIND_LABEL", "STATE_LABEL", "PERMISSION_LABEL", "kind_label"]
