"""
Persian conversation brain - hub messages (capability map, models, Android, unsupported wishes)
==============================================================================================
Same rules as `hub_messages`: built only from real results; never a claim that something was installed, learned or
started unless the result says so. A model is called "usable" only when its status says so (after the integrity,
compatibility, loading and real inference checks); an Android feature is never called "working" on the strength of
a permission or a catalog entry.
"""

from urllib.parse import urlsplit

from self_builder import fa_text

from . import hub_messages as HM
from . import messages as M

fa = fa_text.fa_number
_MIB = 1024 * 1024
STAGE_LABEL = {"verify": "صحت فایل (اندازه و SHA-256)", "compatibility": "سازگاری با موتورهای موجود", "load": "بارگذاری در موتور",
               "smoke": "آزمون استنتاج واقعی", "download": "دانلود", "import": "وارد کردن فایل"}
LICENSE_POLICY_TEXT = {"permissive": "آزاد (سازگار)", "needs_review": "نیازمند بازبینی و تأیید صریح تو", "restricted": "محدودکننده (رد می‌شود)",
                       "unknown": "ناشناخته (رد می‌شود)"}


def _ltr(text, limit=170):
    return M.ltr(" ".join(str(text).split())[:limit])


def _size(n):
    if not isinstance(n, int) or n <= 0:
        return "نامشخص"
    return "%s مگابایت" % fa(round(n / _MIB, 1)) if n >= _MIB else "%s بایت" % fa(n)


# ------------------------------------------------------------------ capability map
def overview(summary, usable_titles, gap_lines, missing_only=False):
    """`summary` = graph.summary(); `usable_titles` = what can be used now; `gap_lines` = ready-made lines about what cannot yet."""
    states = summary.get("by_state") or {}
    total = summary.get("total") or sum(states.values())
    usable = summary.get("usable", sum(states.get(s, 0) for s in ("active", "available")))
    lines = []
    if not missing_only:
        lines.append("نقشهٔ قابلیت‌ها (از وضعیت واقعی همین لحظه): %s مورد ثبت است و %s مورد قابل استفاده است." % (fa(total), fa(usable)))
        order = (("active", "فعال و آزمایش‌شده"), ("available", "آماده (آزمون عملی خودش را هنوز ندارد)"), ("pending_approval", "منتظر تأیید تو"),
                 ("permission_blocked", "منتظر مجوز"), ("dependency_blocked", "نیازمند چیزی که اینجا نیست"),
                 ("scaffold_only", "فقط طرح و قرارداد؛ چیزی اجرا نمی‌کند"), ("not_implemented", "پیاده‌سازی نشده"),
                 ("policy_blocked", "ممنوع یا محدود به‌خاطر سیاست"), ("broken", "خراب"), ("disabled", "غیرفعال"),
                 ("registered", "ثبت‌شده ولی هنوز قابل استفاده نیست"))
        for key, label in order:
            if states.get(key):
                lines.append("• %s: %s" % (label, fa(states[key])))
        if usable_titles:
            lines.append("قابل استفاده الان: " + "، ".join(usable_titles))
        if gap_lines:
            lines.append("چیزهایی که هنوز نمی‌توانم (نمونه):")
    else:
        lines.append("این‌ها را هنوز نمی‌توانم، و علتش دقیقاً این است:")
    lines.extend(gap_lines)
    lines.append("برای جزئیات هر کدام همان را بپرس؛ مثلاً «می‌تونی آهنگ بسازی؟».")
    return "\n".join(lines)


def gap_reply(gap, lead=True):
    """The honest answer for a wish the app cannot do: what exists, the exact missing pieces, one next step."""
    lines = ["این را هنوز نمی‌توانم انجام بدهم: %s." % gap.title_fa] if lead else ["دقیق‌تر دربارهٔ «%s»:" % gap.title_fa]
    if gap.exists_fa:
        lines.append("آنچه واقعاً هست: " + gap.exists_fa)
    if gap.blockers:
        lines.append("آنچه کم است:")
        lines.extend("• " + b.text_fa for b in gap.blockers[:4])
    if gap.next_fa:
        lines.append("قدم بعدی: " + gap.next_fa)
    lines.append("اگر بخشی از این با پایتونِ ساده شدنی است، بگو «پرامپت افزونه» تا یک بستهٔ قابل‌آزمایش بگیری (من چیزی را نصب‌شده نمی‌دانم مگر آزمونش را گذرانده و تو «بله» گفته باشی).")
    return "\n".join(lines)


def unsupported_with_hint(base):
    """The old «I cannot build that» text plus the way to extend the app from inside it."""
    return base + "\nاگر آن چیزی که می‌خواهی با پایتونِ ساده شدنی است، بگو «پرامپت افزونه برای …» تا متن آمادهٔ درخواست را بدهم؛ جوابش را اینجا بچسبان تا آزمایشش کنم."


# ------------------------------------------------------------------ models
def models_list(statuses, runtimes):
    lines = []
    if statuses:
        lines.append("مدل‌های ثبت‌شده:")
        for st in statuses:
            card = st.card or {}
            title = card.get("title") or st.model_id
            mark = "قابل استفاده" if st.usable else "هنوز قابل استفاده نیست"
            policy = LICENSE_POLICY_TEXT.get(st.license_policy, "")
            lines.append("• «%s» (%s) — %s؛ %s" % (title, _ltr(st.model_id), mark, st.message_fa))
            if policy and not st.usable:
                lines.append("   مجوز: %s" % policy)
    else:
        lines.append("هیچ مدلی ثبت نشده است. برای ثبت، کارت مدل (یک JSON با model_id, title, version, format, source_url, sha256, size_bytes, license) را اینجا بچسبان؛ ثبت‌کردن چیزی دانلود نمی‌کند.")
    if runtimes:
        lines.append("موتورهای اجرای مدل در این نسخه:")
        for rt in runtimes:
            lines.append("• %s — %s" % (_ltr(rt.get("name")), "آماده" if rt.get("available") else "در دسترس نیست: " + str(rt.get("reason_fa") or "")))
    lines.append("یادآوری: مدل آماری n-gram فقط ادامهٔ متن می‌سازد و یک مدل زبانی بزرگ (LLM) نیست.")
    return "\n".join(lines)


def card_not_valid(code):
    return "این کارت مدل معتبر نیست و ثبت نشد (%s). چیزی دانلود یا ذخیره نشد." % _ltr(code or "نامشخص", 80)


def model_registered(st):
    card = st.card or {}
    lines = ["کارت مدل «%s» (%s) ثبت شد؛ هنوز هیچ فایلی دریافت نشده و مدل قابل استفاده نیست." % (card.get("title") or st.model_id, _ltr(st.model_id))]
    lines.append("قالب: %s؛ حجم اعلام‌شده: %s؛ مجوز: %s (%s)." % (_ltr(card.get("format") or "?", 20), _size(card.get("size_bytes")),
                                                                  _ltr(card.get("license") or "?", 40), LICENSE_POLICY_TEXT.get(st.license_policy, "ناشناخته")))
    if st.license_policy == "needs_review" and not st.license_ack:
        lines.append("پیش از دانلود باید مجوز را بخوانی و بگویی «مجوز مدل %s را می‌پذیرم»." % st.model_id)
    elif st.license_policy in ("restricted", "unknown"):
        lines.append("با این مجوز دانلود انجام نمی‌شود.")
    else:
        lines.append("برای دانلود (فقط با تأیید صریح تو) بگو «مدل %s را دانلود کن»." % st.model_id)
    return "\n".join(lines)


def model_failure(st):
    return (st.message_fa or "این کار انجام نشد.") + " چیزی تغییر نکرد."


def ask_model_license(st):
    card = st.card or {}
    return ("مجوز مدل «%s» «%s» است و نیاز به بازبینی دارد. آیا آن را خوانده‌ای و می‌پذیری؟ (این فقط اجازهٔ دانلود را باز می‌کند؛ هنوز چیزی دانلود نمی‌شود.) (بله / نه)"
            % (card.get("title") or st.model_id, _ltr(card.get("license") or "?", 40)))


def model_license_done(st):
    return "تأیید مجوز ثبت شد. حالا اگر بخواهی بگو «مدل %s را دانلود کن»؛ دانلود باز هم تأیید جدا می‌خواهد." % st.model_id


def ask_model_download(st, network_on):
    card = st.card or {}
    host = ""
    try:
        host = urlsplit(card.get("source_url") or "").hostname or ""
    except ValueError:
        host = ""
    lines = ["دانلود مدل «%s» (%s): حجم %s از %s." % (card.get("title") or st.model_id, _ltr(st.model_id), _size(card.get("size_bytes")), _ltr(host or "?", 60)),
             "بعد از دانلود، SHA-256 و اندازه با کارت می‌خوانند یا فایل رد می‌شود؛ سپس سازگاری، بارگذاری و یک آزمون استنتاج واقعی انجام می‌شود. تا همهٔ این‌ها نگذرد، «قابل استفاده» نیست."]
    if not network_on:
        lines.append("توجه: مجوز اینترنت برنامه خاموش است؛ بدون آن دانلود انجام نمی‌شود (بگو «اینترنت را روشن کن»).")
    lines.append("دانلود شود؟ (بله / نه)")
    return "\n".join(lines)


def _download_reason(status):
    """Why a download failed, in the downloader's own words (hash mismatch, offline, too large ...) when it said why."""
    if status.code == "download_failed" and status.reasons:
        try:
            from net_tools.download import download_message
            return download_message(str(status.reasons[0]))[0]
        except Exception:
            pass
    return status.message_fa


def model_pipeline(model_id, download_status, report):
    """The result of an approved download followed by the verification pipeline."""
    lines = []
    if download_status is not None and not download_status.ok:
        return "دانلود انجام نشد: %s چیزی قابل استفاده نشد." % _download_reason(download_status)
    if download_status is not None:
        lines.append("فایل دریافت شد.")
    if report is None:
        lines.append("مراحل تأیید هنوز اجرا نشده است؛ مدل قابل استفاده نیست.")
        return "\n".join(lines)
    for stage in report.stages:
        label = STAGE_LABEL.get(stage.stage, stage.stage)
        lines.append("• %s: %s" % (label, "گذشت" if stage.ok else "ناموفق (%s)" % _ltr(stage.code, 40)))
    st = report.status
    if st.usable:
        lines.append("نتیجه: مدل «%s» همهٔ مراحل را گذراند و قابل استفاده است." % model_id)
    else:
        lines.append("نتیجه: %s مدل قابل استفاده نیست." % st.message_fa)
    return "\n".join(lines)


def ask_model_remove(title):
    return "مدل «%s» حذف شود؟ (فایل و ثبتش پاک می‌شود.) (بله / نه)" % title


def model_removed(st):
    return st.message_fa if not st.ok else "مدل از ثبت و از حافظه حذف شد."


def which_model(action, statuses):
    names = "، ".join(_ltr(s.model_id) for s in statuses[:6])
    return "کدام مدل را %s؟ شناسه‌اش را بنویس%s." % (action, (" (ثبت‌شده‌ها: " + names + ")") if names else "")


def no_models():
    return "هیچ مدلی ثبت نشده است."


# ------------------------------------------------------------------ Android / permissions
def android_status(rows, titles):
    lines = ["وضعیت ویژگی‌های اندروید (فقط پیش‌شرط‌ها؛ هیچ‌کدام روی دستگاه واقعی آزموده نشده):"]
    for row in rows[:14]:
        title = titles.get(row.feature_id) or row.feature_id
        action = ("عملیات پیاده‌سازی‌شده: " + "، ".join(row.actions)) if row.implemented and row.actions else "هنوز هیچ عملیاتی برایش نوشته نشده"
        lines.append("• %s — %s (%s)" % (title, row.message_fa, action))
    lines.append("برنامه هیچ مجوز حساسی را خودش نمی‌گیرد و فقط با تأیید تو، آن هم برای ویژگی‌ای که عملیاتش نوشته شده، درخواست می‌دهد.")
    return "\n".join(lines)


def permissions(app_rows, ext_caps):
    lines = ["مجوزهای برنامه:"]
    for row in app_rows:
        lines.append("• %s — %s (%s)" % (row.get("label_fa"), "روشن" if row.get("granted") else "خاموش", row.get("covers_fa")))
    ext_lines = []
    for cap in ext_caps:
        perms = cap.get("permissions") or {}
        declared = perms.get("declared") or []
        if declared:
            granted = set(perms.get("granted") or [])
            ext_lines.append("• «%s»: %s" % (cap.get("title"), "، ".join(
                "%s (%s)" % (HM.PERMISSION_LABEL.get(p, p), "داده‌شده" if p in granted else "ندارد") for p in declared)))
    if ext_lines:
        lines.append("مجوزهای افزونه‌ها:")
        lines.extend(ext_lines)
    lines.append("مجوزهای اندروید (میکروفون، دوربین و …) جدا هستند؛ بگو «وضعیت اندروید».")
    return "\n".join(lines)


def hub_unavailable():
    return "در این اجرا مسیر ذخیره‌سازی برنامه مشخص نیست؛ بخش افزونه‌ها و ابزارها در دسترس نیست (گفت‌وگو و حافظه سر جایشان‌اند)."


def unexpected():
    return "هنگام انجام این کار خطای غیرمنتظره‌ای رخ داد و چیزی تغییر نکرد."


__all__ = ["overview", "gap_reply", "unsupported_with_hint", "models_list", "card_not_valid", "model_registered", "model_failure",
           "ask_model_license", "model_license_done", "ask_model_download", "model_pipeline", "ask_model_remove", "model_removed",
           "which_model", "no_models", "android_status", "permissions", "hub_unavailable", "unexpected"]
