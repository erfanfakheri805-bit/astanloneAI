"""
Persian conversation brain - hub messages (extensions, internet, prompt)
========================================================================
Every sentence here is built from the RESULT of a real hub call (the validator's verdict, the manager's activation
report, the permission store ...). Nothing says "installed", "active" or "learned" unless the result it was given says
so; a failure always says what did NOT happen. Technical text that comes from a validator (English) is quoted inside a
bidi isolate so it cannot scramble the Persian around it.
"""

import re

from self_builder import fa_text

from . import messages as M

fa = fa_text.fa_number
MAX_ISSUES = 6
_ISSUE_CHARS = 170
_INDENT_RE = re.compile(r"indent", re.IGNORECASE)      # Python's own wording for a broken indentation

STAGE_LABEL = {
    "package": "بستهٔ ورودی (اندازه، قالب JSON یا ZIP)", "manifest": "ساختار و فیلدهای بسته", "id": "شناسه",
    "source": "قواعد کد (زیرمجموعهٔ مجاز پایتون)", "consistency": "سازگاری کد با مجوزها و وابستگی‌های اعلام‌شده",
    "tests": "آزمون‌های پذیرش",
}
PERMISSION_LABEL = {"network": "اینترنت (فقط خواندن متن صفحه‌ها)", "clock": "ساعت دستگاه", "storage": "حافظهٔ کوچک خودش",
                    "compute": "محاسبه"}
STATE_LABEL = {"active": "فعال", "disabled": "غیرفعال", "permission_blocked": "منتظر مجوز", "broken": "خراب (بررسی ناموفق)"}
EVENT_LABEL = {                      # keyed by the audit event name with "." written as "_"
    "ext_proposed": "پیشنهاد شد", "ext_approved": "تأیید شد", "ext_activated": "فعال شد", "ext_declined": "رد شد",
    "ext_rejected": "بسته نپذیرفته شد", "ext_rolled_back": "به نسخهٔ قبل برگشت", "ext_disabled": "غیرفعال شد",
    "ext_enabled": "دوباره فعال شد", "ext_activation_failed": "فعال‌سازی ناموفق بود", "ext_proposal_expired": "پیشنهاد منقضی شد",
    "ext_permission_granted": "مجوز داده شد", "ext_permission_revoked": "مجوز گرفته شد", "ext_repaired": "نسخه ترمیم شد",
    "ext_integrity_failed": "یکپارچگی فایل رد شد", "ext_auto_rollback": "خودکار به نسخهٔ سالم قبلی برگشت (فایل‌های نسخهٔ فعال سالم نبود)",
    "ext_auto_disabled": "خودکار غیرفعال شد (فایل‌هایش سالم نبود و نسخهٔ سالمی برای برگشتن نبود)", "ext_rollback_failed": "برگرداندن ناموفق بود",
    "ext_reconciled": "بررسی خودکار یکپارچگی حافظهٔ افزونه‌ها",
}


def _ltr(text, limit=_ISSUE_CHARS):
    return M.ltr(" ".join(str(text).split())[:limit])


def perm_names(perms):
    return "، ".join(PERMISSION_LABEL.get(p, p) for p in perms)


_perm_names = perm_names


def _ver(n):
    return "نسخهٔ " + fa(n) if isinstance(n, int) and not isinstance(n, bool) else "نسخهٔ نامشخص"


# ------------------------------------------------------------------ proposals
def proposal(result, network_on=None):
    """The review the user sees BEFORE anything is installed (a pending proposal)."""
    review = result.get("review") or {}
    tests = result.get("tests") or {}
    title, cid = result.get("title") or result.get("capability_id"), result.get("capability_id")
    lines = [f"بستهٔ «{title}» ({_ltr(cid)}) را بررسی کردم؛ هنوز چیزی نصب یا فعال نشده است:"]
    lines.append("• قالب، قواعد کد و مجوزها معتبرند و کد در محیط ایزوله اجرا شد؛ آزمون‌ها: %s از %s موفق." % (
        fa(tests.get("passed", 0)), fa(tests.get("total", 0))))
    names = [i.get("label") or i.get("name") for i in review.get("inputs") or []]
    outs = [o.get("label") or o.get("name") for o in review.get("outputs") or []]
    if names or outs:
        lines.append("• ورودی‌ها: %s؛ خروجی‌ها: %s." % ("، ".join(map(str, names)) or "ندارد", "، ".join(map(str, outs)) or "ندارد"))
    examples = [e for e in (review.get("examples") or []) if isinstance(e, str)][:2]
    if examples:
        lines.append("• نمونه جمله‌ها: " + "، ".join("«%s»" % e for e in examples))
    perms = list(result.get("permissions") or [])
    if perms:
        lines.append("• مجوزهایی که می‌خواهد: " + _perm_names(perms) + ". با نصب، همین‌ها به خود این افزونه داده می‌شود.")
        if "network" in perms:
            state = "نامعلوم است" if network_on is None else ("روشن است" if network_on else "خاموش است")
            lines.append("• برای اینکه واقعاً اینترنت داشته باشد، مجوز اینترنت خود برنامه هم باید روشن باشد (الان %s)." % state)
    else:
        lines.append("• مجوز اضافه‌ای نمی‌خواهد (فقط محاسبه).")
    if review.get("source_sha256"):
        lines.append("• کد: %s خط، SHA-256 %s" % (fa(review.get("source_lines", 0)), _ltr(review["source_sha256"][:12])))
    prov = review.get("provenance") or {}
    source = prov.get("source") or prov.get("author")
    if isinstance(source, str) and source.strip():
        lines.append("• منبعی که بسته گفته: " + _ltr(source, 80))
    planned = result.get("planned_version")
    if result.get("action") == "update":
        lines.append("• این به‌روزرسانی یک افزونهٔ نصب‌شده است؛ می‌شود %s و نسخهٔ فعلی نگه داشته می‌شود تا هر وقت خواستی برگردی." % _ver(planned))
    else:
        lines.append("• این یک افزونهٔ تازه است؛ می‌شود %s." % _ver(planned))
    lines.append("نصب و فعالش کنم؟ (بله / نه) — اگر چیز دیگری بنویسی، این پیشنهاد کنار گذاشته می‌شود.")
    return "\n".join(lines)


def proposal_noop(result):
    return "این بسته با نسخهٔ فعالِ «%s» (%s) دقیقاً یکی است؛ چیزی تغییر نکرد." % (result.get("title") or result.get("capability_id"),
                                                                                    _ver(result.get("version")))


def proposal_rejected(result):
    stage = STAGE_LABEL.get(result.get("stage"), str(result.get("stage") or "نامشخص"))
    lines = ["بسته را نپذیرفتم (مرحله: %s). هیچ چیزی نصب یا فعال نشد." % stage]
    issues = result.get("issues") or []
    for issue in issues[:MAX_ISSUES]:
        where = issue.get("path") or ""
        text = issue.get("message") or issue.get("code") or ""
        lines.append("• " + (_ltr(where, 60) + ": " if where else "") + _ltr(text))
    if len(issues) > MAX_ISSUES:
        lines.append("… و %s مشکل دیگر." % fa(len(issues) - MAX_ISSUES))
    if any(_INDENT_RE.search(str(i.get("message") or "")) for i in issues):
        lines.append("به‌نظر می‌رسد تورفتگی خط‌های کد موقع فرستادن از بین رفته است (گفتگو فاصله‌های پشت‌سرهم را یکی می‌کند). "
                     "در بسته تورفتگی را با \\t بنویس (دستور آمادهٔ افزونه همین را می‌گوید) و دوباره بفرست.")
    lines.append("اگر بسته را از یک دستیار گرفته‌ای، همین فهرست را به او بده تا اصلاحش کند، بعد دوباره بفرستش.")
    return "\n".join(lines)


def package_not_found():
    return ("نشانهٔ ext.v1 را دیدم، ولی یک شیء JSON کامل و بسته‌شده پیدا نکردم (شاید ناقص کپی شده یا از ۲۰۰٬۰۰۰ بایت بزرگ‌تر است). "
            "چیزی نصب نشد؛ بستهٔ کامل را دوباره بفرست.")


def package_other_schema(name):
    return ("این بسته با قالب «%s» نوشته شده، ولی این برنامه فقط قالب ext.v1 را می‌شناسد؛ چیزی نصب یا فعال نشد. "
            "بگو «پرامپت افزونه» تا دستور درست را برای دستیارت بگیری." % _ltr(name, 20))


def store_unusable_ask():
    return ("حافظهٔ افزونه‌ها خراب است و باز نمی‌شود، برای همین فعلاً نمی‌توانم افزونه‌ای بپذیرم یا اجرا کنم. "
            "می‌خواهی آن را کنار بگذارم تا از نو شروع شود؟ (چیزی پاک نمی‌شود؛ پوشه‌های خراب فقط تغییر نام می‌دهند و افزونه‌ها را باید دوباره بفرستی.) (بله / نه)")


def hub_error(result):
    code = str((result or {}).get("code") or "")
    if code == "E_HUB_IO":
        return "نوشتن روی حافظهٔ برنامه ممکن نشد؛ چیزی تغییر نکرد. فضای خالی گوشی را بررسی کن و دوباره امتحان کن."
    return "یک خطای غیرمنتظره رخ داد؛ چیزی نصب یا تغییر نکرد."


def declined():
    return "باشه؛ پیشنهاد را کنار گذاشتم و چیزی نصب نشد."


def nothing_changed():
    return "باشه؛ چیزی تغییر نکرد."


QUESTION_LABEL = {
    "install": "نصب افزونه", "rollback": "برگرداندن نسخهٔ افزونه", "disable": "غیرفعال‌کردن افزونه", "enable": "فعال‌کردن افزونه",
    "perm_grant": "دادن مجوز به افزونه", "net_on": "روشن‌کردن اینترنت", "model_download": "دانلود مدل",
    "model_license": "تأیید مجوز مدل", "model_remove": "حذف مدل", "repair_store": "ترمیم حافظهٔ افزونه‌ها",
}


def question_expired(type_):
    return ("پرسش «%s» بیش از ۳۰ دقیقه بی‌جواب مانده بود و منقضی شد؛ چیزی نصب یا تغییر نکرد. "
            "اگر هنوز می‌خواهی، درخواست را دوباره بگو (بستهٔ افزونه را دوباره بفرست)." % QUESTION_LABEL.get(type_, "درخواست قبلی"))


def nothing_pending_for_proposal(status):
    if status == "expired":
        return "این پیشنهاد منقضی شده بود؛ چیزی نصب نشد. بسته را دوباره بفرست."
    return "این پیشنهاد دیگر باز نیست (قبلاً تصمیم دربارهٔ آن گرفته شده)؛ چیزی تغییر نکرد."


# ------------------------------------------------------------------ approval results
def approved(result, examples=()):
    perms = list(result.get("permissions_granted") or [])
    tests = result.get("tests") or {}
    lines = ["«%s» نصب و فعال شد (%s)." % (result.get("title") or result.get("capability_id"), _ver(result.get("version"))),
             "پس از نصب از دیسک دوباره بررسی شد: قابل بارگذاری و قابل فراخوانی است، در فهرست ثبت شده و آزمون‌ها %s از %s موفق‌اند." % (
                 fa(tests.get("passed", 0)), fa(tests.get("total", 0)))]
    if perms:
        lines.append("مجوزهای داده‌شده به این افزونه: " + _perm_names(perms) + ".")
    prev = result.get("previous_version")
    if prev:
        lines.append("نسخهٔ قبلی (%s) نگه داشته شد؛ با «افزونهٔ %s را برگردان» می‌توانی به آن برگردی." % (fa(prev), result.get("title") or ""))
    examples = [e for e in examples if isinstance(e, str)][:1]
    if examples:
        lines.append("امتحانش کن، مثلاً بنویس: «%s»" % examples[0])
    return "\n".join(lines)


def approve_failed(result):
    status = result.get("status")
    if status in ("not_pending", "expired"):
        return nothing_pending_for_proposal(status)
    if status == "busy":
        return "یک عملیات دیگر روی افزونه‌ها در حال انجام است؛ چیزی نصب نشد. چند لحظه بعد دوباره «نصب کن» بگو."
    if status == "approval_required":
        return "بدون تأیید صریح تو چیزی نصب نمی‌شود؛ بنویس «بله» اگر می‌خواهی."
    detail = result.get("detail") or result.get("code") or "نامشخص"
    text = "نصب کامل نشد و افزونه فعال نیست. دلیل: " + _ltr(detail) + "."
    if result.get("restored_version"):
        text += " نسخهٔ قبلی (%s) دوباره فعال و سالم ماند." % fa(result["restored_version"])
    return text


# ------------------------------------------------------------------ list / history
def ext_list(caps, pending=()):
    if not caps and not pending:
        return ("هنوز افزونه‌ای نصب نکرده‌ام. اگر قابلیتی می‌خواهی که ندارم، بگو «پرامپت افزونه برای …» تا متن آمادهٔ درخواست را بدهم؛ "
                "جواب را اینجا بچسبان تا بررسی و آزمایشش کنم (فقط با «بله»ی تو فعال می‌شود).")
    lines = ["افزونه‌های نصب‌شده:"] if caps else []
    for cap in caps:
        state = STATE_LABEL.get(cap.get("state"), str(cap.get("state")))
        tested = "آزمون‌شده" if cap.get("tested") else "بدون آزمون ثبت‌شده"
        lines.append("• «%s» (%s) — %s، %s، %s" % (cap.get("title"), _ltr(cap.get("capability_id")), state, _ver(cap.get("active_version")), tested))
        if cap.get("state") == "permission_blocked":
            missing = (cap.get("permissions") or {}).get("missing") or []
            lines.append("   منتظر مجوز: " + _perm_names(missing))
    for item in pending:
        lines.append("• پیشنهاد منتظر تأیید: «%s» (%s)" % (item.get("title"), _ver(item.get("planned_version"))))
    return "\n".join(lines)


def ext_history(rows, titles=None):
    if not rows:
        return "هنوز رویدادی برای افزونه‌ها ثبت نشده است."
    lines = ["تازه‌ترین رویدادهای افزونه‌ها:"]
    titles = titles or {}
    for row in rows[:10]:
        cid = row.get("capability_id")
        label = EVENT_LABEL.get(str(row.get("event")).replace(".", "_")) or _ltr(row.get("event"), 60)
        ver = (" — " + _ver(row.get("version"))) if row.get("version") else ""
        if not cid:                                           # an event of the whole store, not of one extension
            lines.append("• %s" % label)
            continue
        lines.append("• «%s»: %s%s" % (titles.get(cid) or _ltr(cid, 60), label, ver))
    return "\n".join(lines)


# ------------------------------------------------------------------ roll back / switch / permissions
def ask_rollback(title, current, target):
    return "افزونهٔ «%s» از %s به %s برگردانده شود؟ (بله / نه)" % (title, _ver(current), _ver(target) if target else "نسخهٔ قبلی")


def rolled_back(result):
    return "«%s» از %s به %s برگشت و پس از آن دوباره بررسی شد." % (result.get("title") or result.get("capability_id"),
                                                                    _ver(result.get("from_version")), _ver(result.get("to_version")))


def rollback_failed(result):
    status, code = result.get("status"), result.get("code")
    if status == "nothing_to_roll_back":
        return "این افزونه نسخهٔ قبلیِ سالمی برای برگشتن ندارد؛ چیزی تغییر نکرد. اگر می‌خواهی خاموشش کنم، بگو «افزونه را غیرفعال کن»."
    if status == "approval_required":
        return "بدون تأیید صریح تو چیزی برنمی‌گردد."
    if code == "E_EXT_BAD_TARGET":
        return "آن نسخه وجود ندارد یا هیچ‌وقت بررسی‌اش موفق نبوده؛ چیزی تغییر نکرد."
    return "برگرداندن انجام نشد و چیزی تغییر نکرد (%s)." % _ltr(result.get("detail") or code or status or "نامشخص", 80)


def ask_disable(title):
    return "افزونهٔ «%s» غیرفعال شود؟ (حذف نمی‌شود؛ هر وقت خواستی دوباره فعالش می‌کنم.) (بله / نه)" % title


def disabled(result):
    return "«%s» غیرفعال شد؛ دیگر اجرا نمی‌شود، ولی نسخه‌ها و تاریخچه‌اش حفظ شده است." % (result.get("title") or result.get("capability_id"))


def ask_enable(title):
    return "افزونهٔ «%s» دوباره فعال شود؟ (پیش از فعال‌شدن یکپارچگی و آزمون‌هایش دوباره بررسی می‌شود.) (بله / نه)" % title


def enabled(result):
    return "«%s» دوباره فعال شد." % (result.get("title") or result.get("capability_id"))


def switch_failed(result):
    status = result.get("status")
    if status == "approval_required":
        return "بدون تأیید صریح تو چیزی تغییر نمی‌کند."
    if result.get("code") == "E_EXT_VERIFY":
        return "فعال نشد: بررسی دوباره رد شد (%s). چیزی تغییر نکرد." % _ltr(result.get("detail") or "", 100)
    return "این کار انجام نشد و چیزی تغییر نکرد."


def ask_permission(title, permission):
    return "مجوز «%s» به افزونهٔ «%s» داده شود؟ (بله / نه)" % (PERMISSION_LABEL.get(permission, permission), title)


def permission_granted(result):
    return "مجوز «%s» به «%s» داده شد." % (PERMISSION_LABEL.get(result.get("permission"), result.get("permission")),
                                          result.get("title") or result.get("capability_id"))


def permission_revoked(result, title):
    return ("مجوز «%s» از «%s» گرفته شد؛ تا وقتی دوباره ندهی، این افزونه اجرا نمی‌شود."
            % (PERMISSION_LABEL.get(result.get("permission"), result.get("permission")), title))


def permission_failed(result):
    if result.get("code") == "E_EXT_PERMISSION":
        return "نسخهٔ فعال این افزونه آن مجوز را اعلام نکرده؛ پس چیزی داده نشد."
    return "این کار انجام نشد و چیزی تغییر نکرد."


def which_extension(action, caps):
    names = "، ".join("«%s»" % c.get("title") for c in caps[:6])
    return ("کدام افزونه را %s؟ نامش را بنویس" % action) + ((" (مثلاً " + names + ")") if names else "") + "."


def no_extensions():
    return "هیچ افزونه‌ای نصب نیست."


# ------------------------------------------------------------------ using an installed extension
def ext_answer(out):
    """The answer of a real, successful extension call, with an honest footer about who produced it."""
    answer = out.get("answer") or ""
    return "%s\n— افزونهٔ «%s» · %s" % (answer, out.get("title") or out.get("capability_id"), _ver(out.get("version")))


def ext_needs_inputs(hit, example=None):
    labels = "، ".join(str(m.get("label") or m.get("name")) for m in hit.get("missing") or [])
    text = "برای «%s» این مقدارها را هم لازم دارم: %s." % (hit.get("title"), labels)
    if example:
        text += " مثلاً: «%s»" % example
    return text


def ext_invalid_inputs(hit):
    probs = "؛ ".join("%s: %s" % (p.get("name"), _ltr(p.get("message") or p.get("code"), 80)) for p in (hit.get("problems") or [])[:4])
    return "ورودی‌ها برای «%s» معتبر نبود (%s). چیزی اجرا نشد." % (hit.get("title"), probs)


def ext_disabled(hit):
    return "افزونهٔ «%s» برای این جمله مناسب است ولی غیرفعال است. اگر می‌خواهی، بگو «افزونهٔ %s را فعال کن»." % (hit.get("title"), hit.get("title"))


def ext_failed(out):
    status, title = out.get("status"), out.get("title") or out.get("capability_id")
    if status == "blocked_permission":
        missing = out.get("missing_permissions") or []
        return "«%s» اجرا نشد: مجوز %s ندارد." % (title, _perm_names(missing))
    if status == "integrity_failed":
        tail = " به نسخهٔ سالم %s برگشتم؛ دوباره امتحان کن." % fa(out["repaired_to"]) if out.get("repaired_to") else " نسخهٔ سالمی برای برگشتن نبود."
        return "فایل‌های «%s» سالم نبود و اجرا نشد (%s)." % (title, _ltr(out.get("reason") or "", 80)) + tail
    if status == "limit":
        return "«%s» از سقف زمان یا گام اجرا بیشتر شد و متوقف شد؛ نتیجه‌ای نیست." % title
    if status == "bad_output":
        return "«%s» خروجی نامعتبر داد، پس چیزی به‌عنوان جواب نمی‌دهم." % title
    if status == "runtime_error":
        err = out.get("error") or {}
        return "«%s» هنگام اجرا خطا داد (%s)؛ جوابی ندارم." % (title, _ltr(err.get("message") or err.get("detail") or err.get("code") or "", 100))
    if status == "disabled":
        return "«%s» غیرفعال است." % title
    return "«%s» اجرا نشد." % title


# ------------------------------------------------------------------ internet
def net_status(app_allowed, device):
    state = {"online": "آنلاین", "offline": "آفلاین", "unknown": "نامشخص"}.get(getattr(device, "state", None) or "unknown", "نامشخص")
    lines = ["مجوز اینترنتِ برنامه: " + ("روشن (فقط خواندن متن صفحه‌ها با https)" if app_allowed else "خاموش"),
             "وضعیت اتصال گوشی (طبق خود دستگاه): " + state]
    if not app_allowed:
        lines.append("برای روشن‌کردن بگو «اینترنت را روشن کن»؛ تا آن موقع گفت‌وگو و حافظه کاملاً آفلاین کار می‌کنند.")
    return "\n".join(lines)


def ask_net_on(url=None):
    tail = " بعد از روشن‌شدن همان صفحه را می‌خوانم." if url else ""
    return ("اینترنت برنامه الان خاموش است. روشنش کنم؟ فقط خواندن متن صفحه‌های https با سقف حجم و زمان انجام می‌شود و هر لحظه با «اینترنت را خاموش کن» قطع می‌شود."
            + tail + " (بله / نه)")


def net_on_done(changed=True):
    return "اینترنت روشن شد." if changed else "اینترنت از قبل روشن بود."


def net_off_done():
    return "اینترنت خاموش شد؛ از حالا هیچ درخواست شبکه‌ای فرستاده نمی‌شود (گفت‌وگو و حافظه آفلاین ادامه دارند)."


def net_change_failed(code):
    return "مجوز اینترنت تغییر نکرد (%s)." % _ltr(code or "نامشخص", 60)


def fetch_ok(result):
    text = (result.get("text") or "").strip()
    shown = text[:1200] + ("…" if len(text) > 1200 else "")
    head = "متن صفحه را خواندم"
    if result.get("title"):
        head += " — " + _ltr(result["title"], 100)
    notes = []
    if result.get("truncated"):
        notes.append("بخشی از صفحه به‌خاطر سقف حجم خوانده نشد")
    tail = ("\n(" + "؛ ".join(notes) + ")") if notes else ""
    return "%s:\n%s%s\nمنبع: %s" % (head, shown or "(متنی برای نمایش نبود)", tail, _ltr(result.get("final_url") or result.get("url") or "", 120))


def fetch_failed(result, device=None):
    message = result.get("message_fa") or "صفحه خوانده نشد."
    return message + " چیزی ذخیره یا اجرا نشد."


def prompt_reply(prompt, from_memory=False):
    intro = ("این متن را عیناً به هر دستیاری که دوست داری بده (مثلاً یک سایت گفت‌وگو یا دوستت). جوابی که برمی‌گرداند یک بستهٔ JSON است؛ "
             "همان را اینجا در گفت‌وگو بچسبان. من فقط بررسی و آزمایشش می‌کنم و خلاصه را نشان می‌دهم؛ بدون «بله»ی تو چیزی فعال نمی‌شود.")
    if from_memory:
        intro += "\n(درخواستی که قبلاً گفتی و نتوانستم انجام بدهم در متن آمده است.)"
    return intro + "\n\n" + prompt


def ext_help():
    return M.numbered([
        "بگو «پرامپت افزونه برای …» و قابلیتی را که می‌خواهی بنویس؛ من یک متن آمادهٔ دقیق می‌دهم.",
        "آن متن را به هر دستیاری بده؛ جوابش یک بستهٔ JSON با برچسب ext.v1 است (من خودم به هیچ سرویس هوش مصنوعی وصل نمی‌شوم).",
        "بسته را همین‌جا بچسبان. من قالب و کد را اعتبارسنجی، در محیط ایزوله آزمایش و مجوزها را نمایش می‌دهم.",
        "فقط اگر «بله» بگویی نصب و فعال می‌شود؛ بعد از آن با جملهٔ عادی صدایش می‌زنی، با نسخه و تاریخچه، و هر وقت خواستی برش می‌گردانی.",
    ]) + "\nمحدودیت صادقانه: افزونه فقط پایتونِ محدودِ ایزوله است (محاسبه، ساعت، حافظهٔ کوچک، خواندن متن صفحه با مجوز اینترنت)؛ کار با فایل، میکروفون، دوربین، تماس یا کد Java/native به APK جدید نیاز دارد."


__all__ = ["proposal", "proposal_noop", "proposal_rejected", "package_not_found", "package_other_schema", "store_unusable_ask", "hub_error", "declined", "nothing_changed", "question_expired", "QUESTION_LABEL", "perm_names",
           "approved", "approve_failed", "ext_list", "ext_history", "ask_rollback", "rolled_back", "rollback_failed",
           "ask_disable", "disabled", "ask_enable", "enabled", "switch_failed", "ask_permission", "permission_granted",
           "permission_revoked", "permission_failed", "which_extension", "no_extensions", "ext_answer", "ext_needs_inputs",
           "ext_invalid_inputs", "ext_disabled", "ext_failed", "net_status", "ask_net_on", "net_on_done", "net_off_done",
           "net_change_failed", "fetch_ok", "fetch_failed", "prompt_reply", "ext_help", "nothing_pending_for_proposal"]
