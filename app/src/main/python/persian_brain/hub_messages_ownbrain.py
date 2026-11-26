"""
Persian conversation brain - the words of the OWN BRAIN («مغز خودکار»)  (Prompt 959, stage B)
==============================================================================================
What the assistant says while it gets a language brain FOR ITSELF: the offer (what it is, what it costs, where it comes from, what it
cannot promise), the progress, a stop and a continue, the reasons a step failed, the removal, and the test answer.

Every line is written from the facts the service reports (`brain_hub.ownbrain`): a number is the service's number, "ready" is said only
when the model produced a real test answer, and what could not be checked is said so. Nothing here starts, downloads or deletes anything -
the conversation module (`hub_ownbrain`) does that, and only after the user's explicit «بله».
"""

from net_tools.download import download_message
from net_tools.resumable import RESUMABLE_MESSAGES
from self_builder import fa_text

fa = fa_text.fa_number

START = "مغز خودت را بگیر"                       # the sentences the replies tell the user to say (each one is understood; a test proves it)
STATUS = "وضعیت مغز"
PAUSE = "دانلود مغز را متوقف کن"
RESUME = "ادامه دانلود مغز"
DELETE = "مغز را پاک کن"
TEST = "آزمایش مغز"
RETRY = "مغز را دوباره امتحان کن"

_ENGINE_MISSING = frozenset({"unavailable_platform", "dependency_missing", "no_runtime_for_format", "runtime_hint_unavailable", "engine_missing",
                             "class_missing"})
_GB = 1_000_000_000
_MB = 1_000_000


# ================================================================== small formatters
def size(n):
    """«۲٫۶ گیگابایت» / «۹۶۴ مگابایت»; «نامشخص» for what is not known."""
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return "نامشخص"
    if n >= _GB:
        return "%s گیگابایت" % fa(round(n / _GB, 1))
    if n >= _MB:
        return "%s مگابایت" % fa(int(round(n / _MB)))
    return "%s کیلوبایت" % fa(max(1, int(round(n / 1000))))


def percent(n):
    return "%s٪" % fa(max(0, min(100, int(n))))


def eta_text(seconds):
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        return ""
    if seconds < 60:
        return "کمتر از یک دقیقه"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return "حدود %s دقیقه" % fa(minutes)
    hours, rest = divmod(minutes, 60)
    return "حدود %s ساعت%s" % (fa(hours), (" و %s دقیقه" % fa(rest)) if rest else "")


def ram_use(choice):
    """About how much memory the engine takes while it answers (an estimate from the file size, said as an estimate)."""
    half_gb = max(1, int(round(choice.size_hint * 1.2 / (_GB / 2))))
    return "%s گیگابایت" % fa(half_gb / 2)


def _free(facts):
    free = int((facts or {}).get("free") or 0)
    return size(free) if free else "نامعلوم"


# ================================================================== the offer
def what_it_is():
    return ("یعنی: خودم یک مدلِ زبانیِ آزاد را از اینترنت می‌آورم، درستی‌اش را چک می‌کنم و روی همین گوشی اجرا می‌کنم — بدون کلید، بدون حساب، "
            "بدون هزینه و بدون هیچ سرویسِ هوش مصنوعیِ دیگر. خودِ این مدل همان «مغزِ زبانی» است: فارسیِ تو را مستقیم می‌خواند و می‌فهمد، مترجمِ جدا لازم "
            "ندارد؛ و بعد از نصب، فهمیدن و جواب‌دادن روی خودِ گوشی انجام می‌شود و اینترنت هم لازم نیست.")


def _choice_lines(choice, facts, partial):
    lines = ["• سازنده: %s." % choice.source_fa,
             "• فارسی‌اش: %s." % choice.persian_fa,
             "• حجم: حدود %s؛ یک‌بار از اینترنت می‌آید و همین‌قدر جای گوشی را می‌گیرد (الان %s جای آزاد داری)." % (size(choice.exact_size or choice.size_hint), _free(facts))]
    if partial > 0:
        lines.append("• از قبل %s از آن را گرفته‌ام و از همان‌جا ادامه می‌دهم." % size(partial))
    lines.append("• هنگام جواب‌دادن: حدود %s از حافظهٔ رم و کمی باتری مصرف می‌شود (برآوردِ من، نه اندازه‌گیری)؛ چون فقط روی پردازنده اجرا می‌شود جواب‌ها "
                 "کند است، چند ثانیه تا چند دقیقه، و بارِ اولِ هر نوبت که مدل در حافظه بارگذاری می‌شود کندتر است. ده دقیقه بعد از آخرین پرسش حافظه را پس می‌دهم."
                 % ram_use(choice))
    return lines


def _tail_lines():
    return ["• از کجا: فقط از huggingface.co (و سرورهای فایلِ خودش). اگر در ایران باز نشد، VPN روشن کن. فایل باید دقیقاً همان اثرانگشتِ (SHA-256) باشد که "
            "از قبل در برنامه ثبت شده؛ اگر حتی یک بیت فرق کند نصبش نمی‌کنم.",
            "• اینترنتِ برنامه: با «بله»، «اینترنتِ برنامه» هم روشن می‌شود (اگر خاموش است). هر وقت بگویی «اینترنت را خاموش کن» یا «ایست»، دانلود همان لحظه "
            "می‌ایستد و آنچه گرفته‌ام می‌ماند.",
            "• هر وقت خواستی: «%s» (از همان‌جا ادامه می‌دهم) یا «%s» (جا آزاد می‌شود)." % (PAUSE, DELETE),
            "• صادقانه: روی گوشیِ تو هنوز آزمایش نشده. بعد از دانلود یک پرسشِ واقعی از آن می‌پرسم و فقط اگر جواب داد می‌گویم «آماده است»؛ "
            "مدلی که روی گوشی جا می‌شود کوچک است و به‌اندازهٔ ChatGPT هوشمند نیست."]


def _alt_line(alt, choice):
    if alt is None or alt.key == choice.key:
        return ""
    word = "سبک" if alt.key == "light" else "قوی"
    return "نسخهٔ دیگر: «%s» (حدود %s؛ فارسی‌اش: %s)؛ برای انتخابش بگو «%s»." % (alt.short_fa, size(alt.exact_size or alt.size_hint), alt.persian_fa, word)


def offer_card(choice, alt, facts, partial=0, ask=True):
    """The consent card for `choice` (`alt`: the other brain that also fits this phone, or None). With `ask=False` (a plain explanation)
    the closing question is replaced by how to start."""
    lines = ["🧠 می‌خواهی خودم یک مغزِ زبانیِ مخصوصِ خودم را بگیرم؟", "", what_it_is(), "", "پیشنهادِ من برای این گوشی: «%s»" % choice.short_fa]
    lines.extend(_choice_lines(choice, facts, partial))
    lines.extend(_tail_lines())
    extra = _alt_line(alt, choice)
    if extra:
        lines.append(extra)
    lines.append("اگر موافقی بگو «بله». نمی‌خواهی؟ بگو «نه»." if ask else "برای شروع بگو «%s»؛ تا «بله»ی تو نگویی هیچ‌چیز دانلود نمی‌شود." % START)
    return "\n".join(lines)


def clarify_consent(choice):
    return ("چرا می‌پرسم؟ چون این کار حجمِ اینترنتِ تو (حدود %s) و جای گوشی‌ات را مصرف می‌کند و نمی‌خواهم بی‌اجازه‌ی تو شروع کنم. "
            "چیزی که می‌آورم یک فایلِ مدل است، نه برنامه: هیچ کدی از آن اجرا نمی‌شود و فقط متن می‌سازد. «بله» یعنی شروع کن، «نه» یعنی ولش کن؛ "
            "نسخهٔ دیگر را هم با «سبک» یا «قوی» می‌شود انتخاب کرد." % size(choice.exact_size or choice.size_hint))


def cancelled():
    return "باشه، چیزی دانلود نشد و چیزی عوض نشد. هر وقت خواستی بگو «%s»." % START


def setup_failed():
    return "نتوانستم این گفتگو را راه بیندازم (ذخیره‌سازیِ پرسش ناموفق بود)؛ چیزی دانلود نشد. چند لحظه بعد دوباره بگو «%s»." % START


# ================================================================== a request that cannot start (said BEFORE anything is downloaded)
def blocked(code, detail="", choice=None, facts=None):
    facts = facts or {}
    if code == "engine_missing" and (detail == "api_mismatch" or facts.get("engine_code") == "api_mismatch"):
        # the engine IS in the APK but is not shaped as the app expects (found by `LiteRtLmBridge.probe()` before anything is downloaded)
        reason = facts.get("engine_reason_fa") or "موتورِ مغز داخلِ برنامه هست ولی با شکلی که برنامه از آن انتظار دارد نمی‌خواند."
        api = str(facts.get("engine_api") or "").strip()
        text = ("%s این ایرادِ برنامه است، نه گوشی یا اینترنتِ تو. چیزی دانلود نکردم؛ همین پیام را%s برای سازندهٔ برنامه بفرست "
                "تا با این موتور هماهنگش کند. (نکتهٔ فنی: api_mismatch)" % (reason, " (همراهِ فهرستِ فنیِ زیر)" if api else ""))
        return text + ("\n\nفهرستِ فنیِ موتور (فقط نامِ کلاس‌ها و متدها):\n" + api[:1500]) if api else text
    if code == "engine_missing":
        return ("این نسخهٔ برنامه موتورِ اجرای مغزِ زبانی را ندارد (کتابخانهٔ LiteRT-LM داخلش نیست)، پس دانلودش بی‌فایده است و چیزی دانلود نکردم. "
                "باید نسخه‌ای نصب شود که با موتور ساخته شده باشد؛ بعد از آن دوباره بگو «%s». (نکتهٔ فنی: %s)" % (START, detail or facts.get("engine_code") or "نامشخص"))
    if code == "ram_unknown":
        return "نتوانستم اندازهٔ حافظهٔ گوشی را بخوانم و حدس نمی‌زنم؛ برای همین چیزی دانلود نکردم."
    if code == "ram_too_small":
        have, need = _pair(detail)
        return ("حافظهٔ رمِ این گوشی (%s) از حداقلِ لازم برای «%s» (%s) کمتر است؛ دانلودش فایده‌ای ندارد و چیزی دانلود نکردم."
                % (size(have), choice.short_fa if choice else "این مغز", size(need)))
    if code == "not_enough_space":
        have, need = _pair(detail)
        return ("جای خالیِ گوشی کافی نیست: برای «%s» حدود %s لازم است (با کمی جای اضافه که گوشی نخوابد) و %s آزاد است. چیزی دانلود نکردم؛ "
                "جا باز کن و دوباره بگو «%s»." % (choice.short_fa if choice else "این مغز", size(need), size(have), START))
    if code == "offline":
        return "گوشی الان اینترنت ندارد؛ چیزی دانلود نکردم. وقتی وصل شدی (و اگر لازم بود VPN را روشن کردی) دوباره بگو «%s»." % START
    if code == "network_off":
        return ("اینترنتِ برنامه خاموش است، برای همین چیزی دانلود نکردم (خودم آن را بی‌اجازه دوباره روشن نمی‌کنم). بگو «اینترنت را روشن کن» "
                "و بعد همان دستور را دوباره بگو.")
    if code == "network_failed":
        return "نتوانستم اینترنتِ برنامه را روشن کنم (ذخیرهٔ تنظیم ناموفق بود)؛ چیزی دانلود نشد. چند لحظه بعد دوباره بگو «%s»." % START
    if code == "already_running":
        return "همین الان دارم روی مغزِ خودم کار می‌کنم؛ لازم نیست دوباره بگویی. پیشرفتش را با «%s» ببین." % STATUS
    if code == "have_other":
        return "یک مغزِ دیگر از قبل نصب است. اگر می‌خواهی جایش را عوض کنم اول بگو «%s» و بعد دوباره «%s»." % (DELETE, START)
    if code == "nothing_to_resume":
        return "دانلودی نیست که ادامه بدهم. اگر می‌خواهی از اول شروع کنم بگو «%s»." % START
    return "نتوانستم شروع کنم (%s)؛ چیزی دانلود نشد." % (code or "نامشخص")


def _pair(detail):
    """«have/need» (the service's detail string) -> two ints."""
    try:
        have, need = str(detail).split("/", 1)
        return int(have), int(need)
    except (ValueError, TypeError):
        return 0, 0


def none_fits(facts):
    return ("این گوشی برای هیچ‌کدام از مغزهایی که می‌توانم بگیرم کافی نیست (رم: %s، جای آزاد: %s). چیزی دانلود نکردم؛ اگر جا باز کنی یا گوشیِ "
            "قوی‌تری داشته باشی دوباره بگو «%s»." % (size(int((facts or {}).get("ram") or 0)), _free(facts), START))


# ================================================================== running
def started(choice, resumed=False, net_turned_on=False):
    lines = ["%s دارم «%s» را می‌گیرم (حدود %s)." % ("ادامه دادم ✅" if resumed else "شروع کردم ✅", choice.short_fa, size(choice.exact_size or choice.size_hint)),
             "• پیشرفت را با «%s» ببین؛ «%s» هم کار می‌کند." % (STATUS, PAUSE),
             "• تا تمام نشود جمله‌های آزاد را نمی‌فهمم؛ بقیهٔ کارهایم (یادگرفتن، ابزارها و …) مثل قبل کار می‌کنند.",
             "• برنامه را باز نگه دار؛ هنوز در پس‌زمینه با اعلانِ ثابت ادامه نمی‌دهم. اگر اندروید برنامه را ببندد، دفعهٔ بعد که بازش کنی از همان‌جا ادامه می‌دهم."]
    if net_turned_on:
        lines.append("• «اینترنتِ برنامه» را هم روشن کردم (چون گفتی بله)؛ با «اینترنت را خاموش کن» دانلود همان لحظه می‌ایستد.")
    return "\n".join(lines)


def _speed_part(st):
    parts = []
    if st.get("speed"):
        parts.append("سرعت حدود %s در ثانیه" % size(st["speed"]))
    eta = eta_text(st.get("eta"))
    if eta:
        parts.append("%s مانده" % eta)
    return ("؛ " + "، ".join(parts)) if parts else ""


_STAGE_FA = {"load": "بارگذاریِ مغز در حافظه", "smoke": "پرسشِ آزمایشی", "compat": "بررسیِ سازگاری با این گوشی", "verify": "بررسیِ فایل",
             "adopt": "جابه‌جاییِ فایل به جای مدل‌ها", "register": "ثبتِ مغز"}


def _again(next_step):
    return (" بعد از رفع مشکل «%s» را بگو." % RETRY) if next_step else ""


def failure_text(code, detail="", *, next_step=True):
    """Why the brain could not be completed, in words, and what stays (never says "done"). A failure of the download itself ends with what to say
    (`next_step`; the status leaves it out when it adds the «continue» line itself)."""
    if code in _ENGINE_MISSING:
        return ("فایل کامل و سالم است و نگه داشته شد، ولی این نسخهٔ برنامه موتورِ اجرای آن را ندارد؛ باید نسخه‌ای نصب شود که با موتور ساخته شده باشد. "
                "بعد از آن «%s» را بگو (دانلودِ دوباره لازم نیست)." % RETRY)
    if code == "crashed_before":
        return ("دفعهٔ قبل هنگام بارگذاریِ مغز برنامه از کار افتاد. برای اینکه گوشی در چرخه نیفتد خودم دوباره امتحان نمی‌کنم. اگر می‌خواهی یک بار دیگر "
                "امتحان کنم بگو «%s»؛ اگر باز هم از کار افتاد یعنی این مغز با این گوشی نمی‌سازد: «%s» و بعد نسخهٔ سبک را بگیر." % (RETRY, DELETE))
    if code == "api_mismatch":
        return ("فایل سالم است و نگه داشته شد، ولی موتورِ داخلِ برنامه با شکلی که انتظار می‌رفت نمی‌خواند؛ این ایرادِ برنامه است، نه گوشی‌ات. "
                "همین پیام را برای سازندهٔ برنامه بفرست تا هماهنگش کند؛ بعد از نصبِ نسخهٔ درست «%s» را بگو (دانلودِ دوباره لازم نیست). "
                "(نکتهٔ فنی: api_mismatch%s)" % (RETRY, (" — " + str(detail)[:80]) if detail else ""))
    if code in ("engine_load_failed", "model_file_invalid", "model_file_unreadable", "not_loaded") or code.startswith("engine_"):
        return ("فایل سالم است ولی موتور نتوانست مغز را بارگذاری کند (%s). اغلب حافظهٔ رم کم آمده؛ برنامه‌های دیگر را ببند و «%s» را بگو." % (code, RETRY))
    if code in ("smoke_test_failed", "smoke_failed") or str(detail) == "smoke":
        return ("مغز بارگذاری شد ولی به پرسشِ آزمایشی جوابِ درستی نداد (%s)؛ برای همین «آماده» نمی‌گویم. «%s» را بگو تا دوباره آزمایش کنم." % (code, RETRY))
    if code in ("hash_mismatch", "size_mismatch", "remote_changed", "host_not_allowed"):
        text = (RESUMABLE_MESSAGES.get(code) or download_message(code))[0]
        if "نصب نشد" not in text:
            text += " چیزی نصب نشد."
        return text + " اگر هر بار همین شد، یعنی فایلِ روی سرور عوض شده و باید برنامه با اثرانگشتِ تازه ساخته شود." + _again(next_step)
    if code == "permission_denied":
        return RESUMABLE_MESSAGES[code][0] + " اول «اینترنت را روشن کن» را بگو." + _again(next_step)
    if code in RESUMABLE_MESSAGES or code in ("offline", "dns_failure", "connect_refused", "timeout", "tls_error", "protocol_error", "http_error",
                                              "too_many_redirects", "unknown_error", "io_error", "permission_denied", "insufficient_space"):
        text = (RESUMABLE_MESSAGES.get(code) or download_message(code))[0]
        if code in ("dns_failure", "connect_refused", "timeout", "tls_error", "offline", "interrupted") and "VPN" not in text:
            text += " (اگر در ایران هستی و سایت باز نمی‌شود، VPN را روشن کن.)"
        return text + _again(next_step)
    if code == "not_usable":
        return ("فایل مغز روی گوشی هست ولی الان آمادهٔ کار نیست و دلیلِ دقیقش را نمی‌دانم. «%s» را بگو تا یک بار دیگر بارگذاری و آزمایشش کنم؛ "
                "اگر نشد «%s»." % (RETRY, DELETE))
    stage = _STAGE_FA.get(str(detail))
    where = (" در مرحلهٔ %s" % stage) if stage else ""
    return ("کار با کدِ «%s»%s متوقف شد؛ برای همین «آماده» نمی‌گویم. چیزی را پاک نکردم. برای یک بار دیگر امتحان «%s» را بگو؛ "
            "اگر می‌خواهی همه‌چیز پاک شود «%s»." % (code or "نامشخص", where, RETRY, DELETE))


def status(st, brain_title=""):
    """The honest account of where the own brain stands (`st` is `OwnBrain.status()`)."""
    phase = st.get("phase")
    title = st.get("title_fa") or brain_title
    pct = percent(st.get("percent", 0))
    if phase == "ready":
        return ("🧠 مغزِ خودم آماده است ✅ («%s»). یک پرسشِ واقعی را جواب داد و از آن به بعد هر جمله‌ای را که قاعده‌هایم نفهمند به آن می‌سپارم. "
                "مدلی کوچک است و ممکن است اشتباه کند. «%s» را بگو تا همین الان یک پرسش بپرسم؛ «%s» جا را آزاد می‌کند." % (title, TEST, DELETE))
    if phase == "downloading":
        if st.get("sub") == "verify":
            return "🧠 «%s» کامل آمد؛ دارم اثرانگشتش را با مقدارِ ثبت‌شده در برنامه مقایسه می‌کنم (چند دقیقه؛ تا تمام نشود چیزی نصب نمی‌شود)." % title
        return "🧠 دارم «%s» را می‌گیرم: %s (%s از %s)%s." % (title, pct, size(st.get("bytes")), size(st.get("total")), _speed_part(st))
    if phase == "installing":
        return ("🧠 فایل کامل و تأییدشده است؛ دارم مغز را نصب و برای بار اول آزمایش می‌کنم (بارگذاریِ مدل چند دقیقه طول می‌کشد). "
                "تا وقتی یک پرسشِ واقعی را جواب نداده «آماده» نمی‌گویم.")
    if phase == "paused":
        code = st.get("code")
        why = {"user_paused": "به خواستِ تو متوقف شد", "halted": "با «ایست» متوقف شد", "app_closed": "برنامه بسته شد و دانلود نیمه ماند",
               "net_off": "با خاموش‌شدنِ اینترنتِ برنامه متوقف شد"}.get(code, "متوقف شد")
        again = ("اول «اینترنت را روشن کن» و بعد «%s»" % RESUME) if code == "net_off" else ("«%s»" % RESUME)
        return ("🧠 دانلودِ «%s» %s؛ %s گرفته شده و می‌ماند. %s را بگو تا از همان‌جا ادامه بدهم، یا «%s» تا همه‌چیز پاک شود."
                % (title, why, pct, again, DELETE))
    if phase == "failed":
        tail = ("\n«%s» را بگو تا از همان‌جا ادامه بدهم." % RESUME) if st.get("resumable") else ""
        return "🧠 مغزِ «%s» کامل نشد: %s%s" % (title, failure_text(st.get("code") or "", st.get("detail") or "", next_step=not st.get("resumable")), tail)
    return "هنوز مغزی برای خودم نگرفته‌ام. بگو «%s» تا توضیح بدهم و فقط با «بله»ی تو شروع کنم." % START


def paused(st):
    return ("دانلود را متوقف کردم؛ %s گرفته شده و همین‌جا می‌ماند (چیزی پاک نشد). «%s» را بگو تا از همان‌جا ادامه بدهم." % (percent(st.get("percent", 0)), RESUME))


def nothing_running(st):
    if st.get("phase") == "ready":
        return "الان دانلودی در کار نیست؛ مغز آماده است. («%s» اگر می‌خواهی جا آزاد شود.)" % DELETE
    if st.get("phase") == "installing":
        return busy_installing()
    return "الان دانلودی در کار نیست. %s" % status(st)


def busy_installing():
    """The download is finished and the model is being installed and tested for the first time: that step cannot be cut in the middle."""
    return ("دانلود تمام شده و الان دارم مغز را نصب و آزمایش می‌کنم؛ این مرحله را نمی‌شود وسطش قطع کرد و چند دقیقه طول می‌کشد. "
            "وقتی تمام شد می‌توانی «%s» یا «%s» را بگویی؛ پیشرفتش را با «%s» ببین." % (DELETE, TEST, STATUS))


def halted_note():
    return "دانلودِ مغزِ خودم هم متوقف شد (آنچه گرفته‌ام می‌ماند)؛ با «ادامه» از همان‌جا ادامه می‌دهم."


def install_not_stoppable_note():
    """«ایست» while the finished file is installed and tested for the first time: nothing is stopped, and the reply must not pretend it was."""
    return "نصب و آزمایشِ اولِ مغزِ خودم را نمی‌شود وسطش قطع کرد؛ چند دقیقه طول می‌کشد و خودش تمام می‌شود (پیشرفتش: «%s»)." % STATUS


def net_off_note(st):
    """Added to the reply of «اینترنت را خاموش کن» when the own brain's download was running: it stopped with the switch."""
    return ("دانلودِ مغزِ خودم هم همان لحظه متوقف شد؛ %s گرفته شده و می‌ماند. بعد از روشن‌کردنِ اینترنت «%s» را بگو تا از همان‌جا ادامه بدهم."
            % (percent(st.get("percent", 0)), RESUME))


def resumed_note():
    return "دانلودِ مغزِ خودم را هم از همان‌جا ادامه دادم."


# ================================================================== delete
def ask_delete(info):
    held = int(info.get("held") or 0)
    return ("مغزِ خودم را کامل پاک کنم؟ (مدل، آنچه نیمه‌کاره گرفته‌ام و ثبتش؛ حدود %s جا آزاد می‌شود. بعدش جمله‌های آزاد را دوباره نمی‌فهمم "
            "و برای داشتنش باید دوباره بگیری.) (بله / نه)" % size(held)) if held else "مغزِ خودم را پاک کنم؟ (بله / نه)"


def deleted(freed):
    if freed:
        return "پاک شد؛ حدود %s جا آزاد شد. هر وقت خواستی دوباره بگو «%s»." % (size(freed), START)
    return "پاک شد (چیزی روی گوشی نبود که جا آزاد کند). هر وقت خواستی دوباره بگو «%s»." % START


def delete_cancelled():
    return "باشه، چیزی پاک نشد."


def nothing_to_delete():
    return "مغزی روی گوشی نیست که پاک کنم. هر وقت خواستی بگو «%s»." % START


# ================================================================== test and retry
def not_ready_for_test(st):
    return "هنوز مغزم آماده نیست، پس چیزی برای آزمایش نیست. %s" % status(st)


def test_ok(text, seconds):
    return ("آزمایش گذشت ✅ — جوابِ واقعیِ مغز (در %s ثانیه):\n«%s»" % (fa(round(float(seconds), 1)), text))


def test_failed(code, seconds):
    if code == "timeout":
        return ("مغز در %s ثانیه جواب نداد و کارش را قطع کردم؛ گوشی کند است یا بارگذاری طول کشید. کمی بعد دوباره «%s» را بگو."
                % (fa(int(seconds)), TEST))
    return "آزمایش ناموفق بود (%s)؛ برای همین «آماده» نمی‌گویم. «%s» را بگو." % (code or "نامشخص", RETRY)


def retry_started():
    return "دوباره امتحان می‌کنم: فایل را از نو بررسی و مغز را بارگذاری و با یک پرسشِ واقعی آزمایش می‌کنم."


# ================================================================== the model's answers in the chat
def first_answer_note(title):
    return ("— این جواب را مغزِ خودم («%s»، روی همین گوشی) ساخت؛ نه جستجو است و نه ChatGPT و بدون هیچ سرویسِ بیرونی. مدلی کوچک است و ممکن است "
            "اشتباه کند؛ برای چیزهای مهم خودت چک کن." % title)


def llm_timeout(seconds, cancelled=False):
    return ("مغزِ خودم در %s ثانیه جواب نداد%s. بارِ اولِ هر نوبت که مدل در حافظه بارگذاری می‌شود کند است؛ کمی بعد دوباره بپرس. "
            "اگر باز هم کند بود، «%s» را بگو یا نسخهٔ سبک را بگیر." % (fa(int(seconds)), " و کارش را قطع کردم" if cancelled else "", STATUS))


def llm_failed(code):
    if code in ("crashed_before",):
        return failure_text("crashed_before")
    if code in _ENGINE_MISSING:
        return "این نسخهٔ برنامه موتورِ اجرای مغز را ندارد؛ «%s» را بگو." % STATUS
    if code == "empty":
        return "مغزِ خودم این بار جوابی نساخت؛ یک‌بار دیگر و کمی روشن‌تر بپرس."
    if code == "cancelled":                                                     # Prompt 959 (stage B): the user's «ایست» (or the notification's button) cut the answer
        return "جوابِ مغزِ خودم را همان‌طور که خواستی متوقف کردم (ایست)؛ چیزی تغییر نکرد. هر وقت خواستی دوباره بپرس."
    if code == "model_not_usable":
        return "مغزِ خودم الان قابل استفاده نیست؛ «%s» را بگو تا علتش را ببینی." % STATUS
    return "مغزِ خودم این بار نتوانست جواب بدهد (%s). چیزی تغییر نکرد؛ دوباره امتحان کن، و اگر تکرار شد «%s» را بگو." % (code or "نامشخص", STATUS)


# ================================================================== the lead lines other replies use (see hub_messages_self)
def lead_line(phase, pct=0):
    """One short line for the «I do not know» replies, by the state of the own brain."""
    if phase == "downloading":
        return "🧠 مغزِ خودم الان در حال گرفته‌شدن است (%s)؛ تمام که شد جمله‌های آزاد را هم می‌فهمم. «%s» را بگو تا ببینی چقدر مانده." % (percent(pct), STATUS)
    if phase == "installing":
        return ("🧠 مغزِ خودم دانلود شده و الان دارم نصب و آزمایشش می‌کنم (چند دقیقه)؛ تمام که شد جمله‌های آزاد را هم می‌فهمم. «%s» را بگو تا ببینی "
                "در چه مرحله‌ای است." % STATUS)
    if phase == "paused":
        return "🧠 مغزِ خودم نیمه‌کاره مانده (%s گرفته شده)؛ «%s» را بگو تا از همان‌جا ادامه بدهم." % (percent(pct), RESUME)
    if phase == "failed":
        return "🧠 مغزِ خودم کامل نشد؛ «%s» را بگو تا علتش را بگویم." % STATUS
    if phase == "ready":
        return "🧠 مغزِ خودم آماده است ولی این بار جوابی نداد؛ «%s» را بگو تا ببینم سالم است." % TEST
    return ("🧠 ساده‌ترین راه (بدون کلید، بدون هزینه و بدون هیچ سرویسِ دیگر): بگو «%s»؛ خودم یک مغزِ زبانیِ آزاد را از اینترنت می‌گیرم و روی همین "
            "گوشی اجرا می‌کنم. اول توضیح می‌دهم و فقط با «بله»ی تو شروع می‌کنم." % START)


def about_line(phase, pct=0):
    """The line under «what I cannot do yet» / in «how can I be made smarter»: the own brain's way, by its state."""
    if phase in ("downloading", "installing", "paused", "failed", "ready"):
        return lead_line(phase, pct)
    return ("راهش: بگو «%s» — خودم یک مغزِ زبانیِ آزاد را از اینترنت می‌گیرم، چک می‌کنم و روی همین گوشی اجرا می‌کنم؛ بدون کلید و بدون هزینه، "
            "و فقط با «بله»ی تو." % START)


def lead_short(phase, pct=0):
    if phase in ("downloading", "installing", "paused", "failed", "ready"):
        return lead_line(phase, pct)
    return "یا بگو «%s» تا خودم برای خودم یک مغزِ زبانی بگیرم (بدون کلید و هزینه)." % START


__all__ = ["size", "percent", "eta_text", "ram_use", "what_it_is", "offer_card", "clarify_consent", "cancelled", "setup_failed", "blocked", "none_fits",
           "started", "failure_text", "status", "paused", "nothing_running", "busy_installing", "halted_note", "install_not_stoppable_note", "net_off_note", "resumed_note", "ask_delete", "deleted",
           "delete_cancelled", "nothing_to_delete", "not_ready_for_test", "test_ok", "test_failed", "retry_started", "first_answer_note",
           "llm_timeout", "llm_failed", "lead_line", "lead_short", "about_line", "START", "STATUS", "PAUSE", "RESUME", "DELETE", "TEST", "RETRY"]
