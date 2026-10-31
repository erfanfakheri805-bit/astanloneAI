"""
Persian conversation brain - messages about the language model that runs on the phone
=====================================================================================
Two families, both built only from real results:

* importing a model file the user picked himself («مدل را از فایل وارد کن») - what is asked, what happened, and exactly which step
  failed. A model is called usable only when `model_runtime` says so (hash, compatibility, load, a real test answer); a build of the
  app without the engine says so plainly; the app never claims it can tell whether a file really is the model its name says.
* the answers of that model in the chat - one honest note the first time ("a small model on the phone, it can be wrong") and clear
  messages when the model is busy, too slow or failed. A model's answer itself is shown as text and is never acted on.

Nothing here says "done" about something that did not happen.
"""

from self_builder import fa_text

from . import hub_messages_tools as HT

fa = fa_text.fa_number
_SIZE = HT._size
_LTR = HT._ltr

LICENSE_FA = {"gemma": "«Gemma» (شرایط استفادهٔ گوگل)", "llama": "«Llama» (مجوز متا)", "user_supplied": "نامشخص (برنامه آن را نمی‌شناسد)"}
FORMAT_FA = {"task": "task (MediaPipe)", "gguf": "gguf (llama.cpp)", "ngram_json": "مدل آماریِ n-gram (json)"}


# ================================================================== importing a model file
def import_how():
    return ("برای وارد کردنِ مدلِ زبانی باید یک فایل مدل روی گوشی‌ات باشد (قالب «.task»، مثل Gemma). برنامه خودش چنین فایلی را از اینترنت "
            "نمی‌گیرد، چون بیشترِ آن‌ها فقط بعد از ورود و پذیرفتنِ شرایط در سایت منبع (مثلاً Hugging Face) به دست می‌آیند و آن کار با خودت است.\n"
            "۱) فایل را از منبعِ مطمئن روی گوشی بگیر.\n"
            "۲) در همین صفحه دکمهٔ «📦 فایل مدل» را بزن و فایل را انتخاب کن؛ برنامه آن را از گوشی کپی می‌کند (برای فایل‌های چندگیگی چند دقیقه طول می‌کشد؛ پیشرفتش بالای کادر پیام دیده می‌شود).\n"
            "۳) بعد از کپی، خودِ برنامه می‌پرسد که وارد کند یا نه (اگر نپرسید، بگو «مدل را وارد کن»).\n"
            "مدل‌های کوچک حدود نیم تا دو گیگابایت‌اند و به جای خالیِ کافی نیاز دارند. مدلِ کوچکِ روی گوشی هم به‌اندازهٔ ChatGPT هوشمند نیست.")


def import_which(files):
    lines = ["چند فایل مدل در پوشهٔ ورودی هست؛ کدام را وارد کنم؟"]
    for f in files[:8]:
        lines.append("• %s (%s)" % (_LTR(f["name"], 100), _SIZE(f["size"])))
    lines.append("بگو «مدل %s را وارد کن»." % _LTR(files[0]["name"], 100))
    return "\n".join(lines)


def import_missing(name, names):
    lines = ["فایلی به نام «%s» در پوشهٔ ورودیِ برنامه نیست." % _LTR(name, 100)]
    if names:
        lines.append("فایل‌های مدلی که هست: " + "، ".join(_LTR(n, 100) for n in names[:6]) + ".")
    else:
        lines.append("هنوز هیچ فایل مدلی انتخاب نشده؛ با دکمهٔ «📦 فایل مدل» انتخابش کن و دوباره بگو.")
    return "\n".join(lines)


def import_ask(name, size, fmt, license_name, engine_ok, engine_reason=""):
    lines = ["فایل «%s» (%s، قالب %s) را به‌عنوان مدلِ زبانیِ برنامه وارد کنم؟" % (_LTR(name, 100), _SIZE(size), FORMAT_FA.get(str(fmt).replace("-", "_"), _LTR(fmt, 20)))]
    lines.append("• برنامه اثرانگشت (SHA-256) فایل را از روی همین فایل حساب می‌کند تا هر تغییرِ بعدی در آن دیده شود؛ ولی نمی‌تواند بفهمد این فایل واقعاً "
                 "همان مدلی است که اسمش را گذاشته‌اند. فقط اگر از منبعِ مطمئن گرفته‌ای ادامه بده.")
    lines.append("• مجوزِ مدل: %s. با «بله» می‌گویی شرایطِ استفادهٔ آن را خوانده‌ای و می‌پذیری." % LICENSE_FA.get(str(license_name).replace("-", "_"), _LTR(license_name, 40)))
    lines.append("• بعد از واردشدن، نسخهٔ موقتیِ فایل از پوشهٔ ورودی پاک می‌شود (تا گوشی دو برابر پر نشود) و مدل یک‌بار واقعاً آزموده می‌شود؛ ممکن است چند دقیقه طول بکشد.")
    if not engine_ok:
        lines.append("• توجه: این نسخهٔ برنامه موتورِ اجرای این قالب را ندارد%s؛ فایل فقط ذخیره و بررسی می‌شود و اجرا نمی‌شود تا نسخه‌ای نصب شود که موتور دارد."
                     % ((" (" + engine_reason + ")") if engine_reason else ""))
    lines.append("(بله / نه)")
    return "\n".join(lines)


def _failure_text(status, size_hint=0):
    code = status.code
    if code == "model_id_taken":
        return ("با همین نام مدل دیگری ثبت است که فایلش فرق دارد. اگر می‌خواهی جایگزینش کنم، اول بگو «مدل %s را پاک کن» و دوباره وارد کن."
                % _LTR(status.model_id, 64))
    if code == "insufficient_space":
        need = ("(حدود %s) " % _SIZE(int(size_hint * 1.1))) if size_hint else ""
        return "جای خالیِ گوشی برای این مدل کافی نیست %sو چیزی کپی نشد." % need
    if code == "file_missing":
        return "فایل دیگر در پوشهٔ ورودی نیست؛ دوباره با «📦 فایل مدل» انتخابش کن."
    if code == "unknown_format":
        return "قالبِ این فایل را نمی‌شناسم (فقط «.task» و «.gguf»)."
    if code == "bad_arguments":
        return "نامِ این فایل برای وارد کردن مناسب نیست (فقط حروف انگلیسی، رقم، نقطه و خط‌تیره)."
    if code in ("model_file_unreadable", "io_error"):
        return "هنگام خواندن یا کپی‌کردنِ فایل خطای ذخیره‌سازی رخ داد."
    if code == "size_mismatch":
        return "اندازهٔ فایل هنگام کپی عوض شد؛ دوباره امتحان کن."
    if code == "invalid_card":
        return "این فایل برای وارد کردن معتبر نیست (خالی است یا بیش از حد بزرگ)."
    return (status.message_fa or "وارد کردن انجام نشد.")


def import_failed(status, name, size_hint=0):
    return "فایل «%s» وارد نشد: %s\nچیزی نصب یا فعال نشد." % (_LTR(name, 100), _failure_text(status, size_hint))


def _engine_missing(code):
    return code in ("unavailable_platform", "dependency_missing", "no_runtime_for_format", "runtime_hint_unavailable")


def import_done(model_id, title, report, imported_before=False):
    """The result of an approved import followed by the verification pipeline (`report` is a `PipelineReport`)."""
    lines = ["فایل مدل را از قبل داشتم و دوباره کپی نشد." if imported_before else
             "فایل وارد شد؛ اثرانگشتش حساب و نسخهٔ موقتیِ ورودی پاک شد."]
    for stage in report.stages:
        label = HT.STAGE_LABEL.get(stage.stage, stage.stage)
        lines.append("• %s: %s" % (label, "گذشت" if stage.ok else "ناموفق (%s)" % _LTR(stage.code, 40)))
    status = report.status
    if status.usable:
        lines.append("نتیجه: مدلِ «%s» همهٔ مراحل را گذراند و قابل استفاده است. از این به بعد هر پیامی که بخش‌های دیگرِ برنامه جوابش را نداشته باشند، "
                     "از همین مدل می‌پرسم. (مدلِ کوچکِ روی گوشی ممکن است اشتباه کند؛ برای کارهای سنگین بگو «از ChatGPT بخواه …».)" % title)
        return "\n".join(lines)
    last = report.stages[-1] if report.stages else None
    if last is not None and not last.ok and _engine_missing(last.code):
        lines.append("نتیجه: فایل ذخیره و صحت‌سنجی شد، ولی این نسخهٔ برنامه موتورِ اجرای مدل را ندارد (باید نسخه‌ای نصب شود که با موتور ساخته شده). "
                     "فایل نگه داشته شد؛ آن‌وقت فقط بگو «مدل %s را آماده کن»." % _LTR(model_id, 64))
    elif last is not None and not last.ok and last.code == "license_needs_ack":
        lines.append("نتیجه: مجوزِ مدل هنوز تأیید نشده؛ بگو «مجوز مدل %s را می‌پذیرم»." % _LTR(model_id, 64))
    else:
        lines.append("نتیجه: %s مدل قابل استفاده نیست." % (status.message_fa or ""))
    return "\n".join(lines)


# ================================================================== the model's answers in the chat
def first_answer_note(title):
    return ("— این جواب را مدلِ زبانیِ داخلِ گوشی («%s») ساخت، نه یک جستجو یا ChatGPT؛ ممکن است اشتباه باشد. "
            "برای چیزهای مهم خودت چک کن یا بگو «از ChatGPT بخواه …»." % _LTR(title, 60))


def llm_busy():
    return "مدلِ زبانی هنوز مشغولِ جوابِ قبلی است؛ چند ثانیه صبر کن و دوباره بپرس."


def llm_timeout(seconds):
    return ("مدلِ زبانی در %s ثانیه جواب نداد (گوشی کند است یا پرسش سنگین). هنوز دارد کار می‌کند؛ کمی بعد دوباره بپرس. "
            "اگر پرسش سنگین است بگو «از ChatGPT بخواه …»." % fa(int(seconds)))


def llm_failed(code):
    if code == "model_not_usable":
        return "مدلِ زبانی الان قابل استفاده نیست؛ بگو «مدل‌ها» تا وضعیتش را ببینی."
    if code == "empty":
        return "مدلِ زبانی این بار جوابی نساخت؛ یک‌بار دیگر و کمی روشن‌تر بپرس."
    return "مدلِ زبانی این بار نتوانست جواب بدهد (%s). چیزی تغییر نکرد؛ دوباره امتحان کن." % _LTR(code or "نامشخص", 40)


__all__ = ["import_how", "import_which", "import_missing", "import_ask", "import_failed", "import_done", "first_answer_note",
           "llm_busy", "llm_timeout", "llm_failed", "LICENSE_FA", "FORMAT_FA"]
