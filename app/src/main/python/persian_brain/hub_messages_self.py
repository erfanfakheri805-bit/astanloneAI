"""
Persian conversation brain - what the assistant says about ITSELF
=================================================================
The answers to «چه کارهایی می‌توانی؟», «مغز فارسی داری؟», «خودت را ارتقا بده», «صدایم را می‌شنوی؟», «می‌توانی از ChatGPT کمک بگیری؟»
and the helpful reply to a question nothing in the app can answer.

Every line that says "I can" or "I have" is written from a plain-data snapshot of what THIS phone's app really has right now (see
`hub_self.snapshot`): a language model that passed its checks, installed packs, the assistant apps found on the phone, the native
doors the installed APK declares. A thing that is absent is never claimed; the reply says what is missing and what to do. Nothing here
starts, installs or sends anything: it only explains, and every action it names still needs the user's own «بله».

The snapshot is a dict:
    model       {"state": "usable" | "imported" | "none", "title": str, "reason": str}
    packs       {"active": int, "installed": int, "safe": bool}
    assistants  [{"id": str, "title": str, "installed": bool}]
    native      set of the feature names the installed APK declares
    internet    bool (the user's internet switch)
    wish        str, the last thing the user asked that nothing here could answer (24 hours at most), '' when none
"""

MODEL_BUTTON = "📦 فایل مدل"
VOICE_BUTTON = "🎤 گفتار"


def _fa(n):
    from self_builder import fa_text
    return fa_text.fa_number(n)


def _titles(snap):
    return [a["title"] for a in snap.get("assistants") or [] if a.get("installed")]


def _has(snap, feature):
    return feature in (snap.get("native") or ())


def model_line(snap):
    """One honest line about the language model, for «brain» and «about»."""
    model = snap.get("model") or {"state": "none"}
    if model["state"] == "usable":
        return "یک مدل زبانیِ واقعی («%s») روی همین گوشی بارگذاری و آزموده شده است؛ به پرسش‌های آزاد با آن جواب می‌دهم (مدلی کوچک است و به‌اندازهٔ ChatGPT هوشمند نیست)." % model.get("title", "")
    if model["state"] == "imported":
        reason = (model.get("reason") or "").strip()
        return ("مدل «%s» وارد شده ولی هنوز قابل اجرا نیست%s." % (model.get("title", ""), ("؛ " + reason) if reason else ""))
    return "هنوز هیچ مدل زبانی‌ای روی گوشی ندارم، برای همین به پرسش‌هایی که قاعده‌اش را بلد نیستم جواب آزاد نمی‌دهم."


def grow_ways(snap):
    """The three honest ways to make the assistant smarter, as lines. Used by «brain», «upgrade» and the fallback."""
    model = (snap.get("model") or {}).get("state")
    lines = []
    if model == "usable":
        lines.append("۱) مدل زبانی: هست و کار می‌کند؛ مدل بزرگ‌تر یا بهتری هم بخواهی، با دکمهٔ «%s» وارد کن." % MODEL_BUTTON)
    elif model == "imported":
        lines.append("۱) مدل زبانی: فایلش وارد شده ولی اجرا نمی‌شود؛ بگو «وضعیت مدل‌ها» تا علتش را دقیق بگویم (اغلب این نسخهٔ برنامه موتور اجرای آن قالب را ندارد).")
    else:
        lines.append("۱) مدل زبانی: یک فایل مدل (قالب «.task» مثل Gemma، یا «.gguf») را از منبعِ مطمئن روی گوشی بگیر و با دکمهٔ «%s» وارد کن؛ بگو «چطور مدل وارد کنم؟» تا قدم‌به‌قدم بگویم." % MODEL_BUTTON)
    lines.append("۲) بسته (قابلیت یا دانشِ تازه بدون ساختن نسخهٔ جدید): بگو «پرامپت بسته برای …» و آنچه می‌خواهی؛ متنی می‌دهم که به ChatGPT یا Claude می‌دهی. جوابش را همین‌جا بچسبان یا از آن برنامه به این برنامه «اشتراک‌گذاری» کن؛ من بررسی و در محیطِ ایزوله آزمایش می‌کنم و فقط با «بله»ی تو نصب می‌شود (نسخه‌بندی و بازگشت دارد).")
    titles = _titles(snap)
    asker = ("«%s»" % "» یا «".join(titles)) if titles else "ChatGPT یا Claude"
    lines.append("۳) پرسیدن از %s: بگو «از ChatGPT بخواه …» (یا Claude)؛ درخواست را آماده می‌کنم و فقط بعد از «بله»ی تو به آن برنامه می‌فرستم." % asker)
    return lines


# ======================================================================================= help
def help_more():
    """The lines the full app adds under «راهنما»: the older list only knows what the Self-Builder does; these are the ways the assistant itself grows.
    Every sentence in quotes here is a real command (a test says each one is understood)."""
    return "\n".join(["و برای بزرگ‌ترکردنِ خودم (هر کدام فقط با «بله»ی تو):",
                      "• «چه کارهایی بلدی؟» / «مغز فارسی داری؟» / «چطور باهوش‌ترت کنم؟»",
                      "• «بسته چیست؟» و «پرامپت بسته برای …» (قابلیت یا دانشِ تازه بدون نسخهٔ تازهٔ برنامه)",
                      "• «از ChatGPT بخواه …» (یا Claude؛ فقط بعد از «بله»ی تو فرستاده می‌شود)",
                      "• «چطور مدل وارد کنم؟» و «مدل‌ها»",
                      "• «نقشهٔ قابلیت‌ها»"])


# ======================================================================================= about
def about(snap, registry=None):
    """«چه کارهایی می‌توانی؟» / «چه کارهایی بلدی؟»: everything this app really has right now, what it cannot do yet, and - when `registry` (the lines
    about the tools the assistant built for itself) is given - what it built."""
    from . import messages as M
    lines = ["من دستیار شخصی و فارسی‌زبانِ تو هستم (نه ChatGPT و نه Claude) و روی همین گوشی کار می‌کنم؛ بدون اجازهٔ تو چیزی از گفتگوهایمان جایی فرستاده نمی‌شود.",
             "من این کارها را بلدم:"]
    lines.extend("• " + ability for ability in M.BUILTIN_ABILITIES)
    if registry:
        lines.append("")
        lines.extend(registry)
        lines.append("")
    lines.append("و این‌ها را هم واقعاً دارم (وضعیتِ همین لحظهٔ همین گوشی):")
    if snap.get("internet"):
        lines.append("• خواندنِ یک صفحهٔ وب: «صفحهٔ https://… را بخوان» (اینترنتِ برنامه الان روشن است؛ فقط خواندن).")
    else:
        lines.append("• خواندنِ یک صفحهٔ وب، بعد از اینکه خودت اینترنتِ برنامه را روشن کنی («اینترنت را روشن کن»؛ فقط خواندن).")
    if _has(snap, "voice_input"):
        lines.append("• گفتار به متن: دکمهٔ «%s» کنار کادر پیام؛ حرفت اول در کادر می‌نشیند و تا «ارسال» نزنی چیزی فرستاده نمی‌شود." % VOICE_BUTTON)
    model = (snap.get("model") or {}).get("state")
    if model == "usable":
        lines.append("• پاسخ آزاد به پرسش‌ها با یک مدل زبانیِ کوچک که روی همین گوشی است («%s»)." % snap["model"].get("title", ""))
    packs = snap.get("packs") or {}
    if packs.get("active"):
        lines.append("• %s بستهٔ نصب‌شده و فعال (رشد از داخلِ خودم، بدون نسخهٔ تازهٔ برنامه)." % _fa(packs["active"]))
    else:
        lines.append("• بستهٔ کد و بستهٔ زبان: راهِ بزرگ‌شدنِ من از داخلِ خودم؛ هنوز بسته‌ای نصب نشده («بسته چیست؟»).")
    titles = _titles(snap)
    if titles:
        lines.append("• پرسیدن از «%s» با اجازهٔ تو (برنامه‌اش روی گوشی هست)." % "» و «".join(titles))
    else:
        lines.append("• پرسیدن از ChatGPT یا Claude با اجازهٔ تو (برنامه‌شان روی گوشی دیده نشد؛ سایتشان باز می‌شود).")
    lines.append("چیزهایی که هنوز نمی‌توانم:")
    if model != "usable":
        lines.append("• جواب آزاد به هر پرسشی (مدل زبانی ندارم).")
    lines.append("• ساخت عکس، ویدیو و آهنگ (موتورش را ندارم؛ می‌توانم از ChatGPT یا Claude بخواهم راهش را برایم بسازند).")
    lines.append("• گوش‌دادنِ همیشگی و صدا زدنِ «جارویس»، و حرف‌زدن با صدا.")
    lines.append("فهرست دقیق: «نقشهٔ قابلیت‌ها». برای بزرگ‌ترکردنِ من: «چطور باهوش‌ترت کنم؟».")
    return "\n".join(lines)


# ======================================================================================= brain
def brain(snap):
    lines = ["«مغز فارسیِ» من دو لایه دارد:",
             "۱) لایهٔ همیشه‌حاضر، بدون هیچ فایلِ اضافه: فهمیدنِ جمله‌های فارسی برای کارهایی که قاعده‌اش را دارم (سلام و احوال‌پرسی، اسم و علایقت، «یاد بگیر که …»، پرسیدن از چیزهایی که یادم داده‌ای، ساختن ابزارِ ساده، و دستورهای مدیریتِ خودم مثل بسته‌ها، مدل و اینترنت). این لایه قاعده‌محور است؛ هر جملهٔ آزادی را نمی‌فهمد.",
             "۲) لایهٔ زبانی، برای هر پرسش و هر موضوع: به یک مدل زبانیِ واقعی نیاز دارد. " + model_line(snap),
             "برای باهوش‌ترشدنِ من این سه راه هست (هر کدام فقط با اجازهٔ تو):"]
    lines.extend(grow_ways(snap))
    lines.append("صادقانه: مدلی که روی گوشی جا می‌شود کوچک است؛ برای کارهای سنگین، پرسیدن از ChatGPT یا Claude بهتر است.")
    return "\n".join(lines)


# ======================================================================================= upgrade
def upgrade(snap):
    lines = ["می‌توانم خودم را بزرگ‌تر کنم، ولی فقط از راه‌هایی که امن و برگشت‌پذیرند:",
             "• «بسته» (بستهٔ کد و بستهٔ زبان): قابلیت یا دانشِ تازه‌ای که ChatGPT یا Claude می‌نویسد. من فقط بررسی، در محیطِ ایزوله آزمایش و پیشنهاد می‌کنم؛ فقط با «بله»ی تو نصب می‌شود، نسخه‌بندی دارد، با یک دستور برمی‌گردد و اگر خراب شود برنامه خودش به حالتِ سالم برمی‌گردد.",
             "• مدل زبانی: با فایلِ مدل و دکمهٔ «%s»." % MODEL_BUTTON,
             "• فایل‌های اصلیِ برنامه و بخشِ اندروید را بی‌صدا و خودسرانه عوض نمی‌کنم؛ آن‌ها فقط با ساختنِ نسخهٔ تازه در GitHub و نصبِ آن عوض می‌شوند (آن کارِ تو است).",
             "شروع: بگو چه قابلیتی می‌خواهی، مثلاً «از ChatGPT بخواه برایم قابلیتِ … بسازد»؛ یا «پرامپت بسته برای …» تا متنِ آماده بدهم. همین الان هم می‌توانی برای راه‌های دیگر بگویی «چطور باهوش‌ترت کنم؟»."]
    return "\n".join(lines)


# ======================================================================================= voice
def voice(snap):
    lines = []
    if _has(snap, "voice_input"):
        lines.append("گفتار به متن دارم: دکمهٔ «%s» (کنار کادرِ پیام) پنجرهٔ گفتارِ خودِ اندروید را باز می‌کند؛ حرفت اول در کادر می‌نشیند و تا «ارسال» نزنی چیزی فرستاده نمی‌شود." % VOICE_BUTTON)
        lines.append("پنجرهٔ گفتار را اندروید (معمولاً سرویس گوگل) اجرا می‌کند و دقتش به همان بستگی دارد؛ من خودم میکروفون را باز نمی‌کنم.")
    else:
        lines.append("این نسخهٔ برنامه دکمهٔ گفتار ندارد (یا روی اندروید اجرا نمی‌شود)؛ نسخه‌ای که ساخته می‌شود دارد، ولی هنوز روی گوشی آزموده نشده است.")
    lines.append("چیزهایی که هنوز ندارم: گوش‌دادنِ همیشگی، صدا زدنِ «جارویس»، و جواب‌دادن با صدای بلند.")
    return "\n".join(lines)


# ======================================================================================= outside
def outside(snap):
    titles = _titles(snap)
    apps = ("برنامهٔ «%s» روی گوشی دیده شد" % "» و «".join(titles)) if titles else "برنامهٔ ChatGPT یا Claude روی گوشی دیده نشد؛ سایتشان باز می‌شود"
    lines = ["بله، ولی فقط با اجازهٔ تو و از همین راه‌ها:",
             "• وب: صفحه‌ای را که آدرسش را بدهی می‌خوانم (فقط خواندن، با اینترنتِ روشن). جستجوی گوگل ندارم؛ آدرس را بده: «صفحهٔ https://… را بخوان».",
             "• ChatGPT و Claude (%s): بگو «از ChatGPT بخواه …»؛ درخواست را آماده می‌کنم، تو «بله» می‌گویی و آن را به آن برنامه می‌فرستم. جوابش را کپی کن یا از آن برنامه به این برنامه «اشتراک‌گذاری» کن و بگو «جواب آمد»؛ من فقط می‌خوانم و اگر بسته بود بررسی می‌کنم و با «بله»ی تو نصب می‌شود." % apps,
             "• واردشدن به برنامهٔ دیگر و تایپ‌کردن در آن: فقط اگر خودت «سرویس دسترسی‌پذیری» را در تنظیمات اندروید روشن کنی و برای همان برنامه اجازه بدهی (بگو «تنظیمات دسترسی‌پذیری» تا صفحه‌اش را باز کنم). اندروید اجازه نمی‌دهد برنامه خودش این سرویس را روشن کند.",
             "هیچ‌کدام بی‌صدا یا بدون اجازه انجام نمی‌شود، و جوابِ برنامهٔ دیگر را فقط به‌عنوان متن می‌خوانم و اجرا نمی‌کنم."]
    wish = " ".join(str(snap.get("wish") or "").split())[:120]
    if wish:                                              # the last thing nothing here could answer: one plain «از ChatGPT بخواه» takes it on
        lines.append("آخرین درخواستی که جوابش را نداشتم: «%s». اگر همین را می‌خواهی، فقط بگو «از ChatGPT بخواه» تا برایش آماده کنم." % wish)
    return "\n".join(lines)


# ======================================================================================= nothing answers
def unknown_first(snap, remembered=True):
    """The reply to a question or request no rule, no taught fact and no language model could answer (first time in a while).
    `remembered` is True only when the sentence really was kept for «از ChatGPT بخواه» (the line is left out otherwise)."""
    lines = ["این را نمی‌دانم و از خودم جوابی برایش ندارم."]
    model = snap.get("model") or {}
    if model.get("state") == "imported":
        lines.append(model_line(snap))
    lines.append("برای اینکه به پرسش‌های آزاد هم جواب بدهم، این راه‌ها هست (هر کدام فقط با اجازهٔ تو):")
    lines.extend(grow_ways(snap))
    if remembered:
        lines.append("پرسشت را به‌خاطر سپردم: اگر فقط بگویی «از ChatGPT بخواه»، همین را برایش آماده می‌کنم.")
    return "\n".join(lines)


def unknown_short(snap, remembered=True):
    """The same, shorter, when it was said a moment ago."""
    if remembered:
        return ("این را هم نمی‌دانم. بگو «از ChatGPT بخواه» تا همین پرسش را برایش آماده کنم (فقط با «بله»ی تو فرستاده می‌شود)، "
                "یا فایل مدل را با دکمهٔ «%s» وارد کن." % MODEL_BUTTON)
    return "این را هم نمی‌دانم. برای جوابِ آزاد، فایل مدل را با دکمهٔ «%s» وارد کن، یا بگو «از ChatGPT بخواه …» و پرسشت را بنویس." % MODEL_BUTTON


__all__ = ["about", "brain", "upgrade", "voice", "outside", "unknown_first", "unknown_short", "model_line", "grow_ways", "help_more",
           "MODEL_BUTTON", "VOICE_BUTTON"]
