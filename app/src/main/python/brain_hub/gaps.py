"""
brain_hub.gaps - the honest answer to "can you do X?" for things that are NOT possible yet
===========================================================================================
Every wish in the project vision that cannot work today is a `Gap` with the EXACT missing piece(s): a model, an
engine/native piece (= a new APK), a permission the APK does not declare, hardware, an Android/store policy, an
external service the product refuses to use, or a consequential action that needs its own reviewed design. Each gap
also says what DOES exist (the connection point) and one truthful next step.

`match_gap(text)` returns the gap a sentence asks about, or None. It is deliberately narrow: the sentence must contain
a topic word AND look like a request or an ability question («بساز», «می‌تونی», «می‌خوام» ...), or be a wake-word address.
Nothing here claims, starts, schedules or installs anything.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from self_builder import fa_text

from .graph import Blocker

__all__ = ["Gap", "GAPS", "get_gap", "match_gap", "gap_ids"]


@dataclass(frozen=True)
class Gap:
    gap_id: str
    title_fa: str
    title_en: str
    words: Tuple[str, ...]            # topic words / phrases (any of them)
    state: str                        # dependency_blocked | not_implemented | policy_blocked | scaffold_only
    exists_fa: str
    exists_en: str
    blockers: Tuple[Blocker, ...]
    next_fa: str
    next_en: str
    needs_frame: bool = True          # False: the topic word alone is enough (a wake word)
    examples_fa: Tuple[str, ...] = ()


def _b(kind, fa, en):
    return Blocker(kind, fa, en)


NEW_APK = _b("new_apk", "این کار کد Java یا native تازه می‌خواهد؛ یعنی یک APK جدید باید ساخته و نصب شود (برنامه خودش APK نمی‌سازد و بی‌صدا نصب نمی‌کند).",
             "This needs new Java or native code, i.e. a newly built APK (the app never builds or silently installs an APK).")
HEAVY = _b("hardware", "مدل‌های این کار معمولاً چند صد مگابایت تا چند گیگابایت‌اند و روی بیشتر گوشی‌ها کند یا ناممکن‌اند.",
           "Models for this are usually hundreds of MB to several GB and are slow or impossible on most phones.")

GAPS = (
    Gap("image_generation", "ساخت تصویر و نقاشی", "Image generation",
        ("نقاشی", "عکس", "تصویر", "لوگو", "پوستر", "کاراکتر"), "dependency_blocked",
        "ثبت‌کنندهٔ عملیات تصویر در برنامه فقط رکورد نگه می‌دارد و تصویری نمی‌سازد.",
        "The image-operation registry in the app only keeps records; it renders nothing.",
        (_b("model", "یک مدل تولید تصویر روی دستگاه لازم است.", "An on-device image-generation model is required."),
         _b("native_code", "موتور اجرای مدل (ONNX/TFLite و مانند آن) در APK نیست.", "No inference engine (ONNX/TFLite or similar) is in the APK."), HEAVY),
        "می‌توانی کارت یک مدل را ثبت کنی تا وضعیتش دقیق نشان داده شود؛ اما اجرا شدنش به APK جدید با موتور مناسب نیاز دارد.",
        "You can register a model card so its status is shown exactly; running it needs a new APK with a suitable engine.",
        True, ("یک نقاشی از گربه بکش", "برام لوگو بساز")),
    Gap("video_animation", "ساخت ویدیو، کلیپ، انیمیشن، انیمه و مانگا", "Video, animation, anime and manga",
        ("ویدیو", "ویدئو", "فیلم", "کلیپ", "انیمیشن", "انیمه", "مانگا", "کارتون"), "dependency_blocked",
        "فقط قراردادهای داده‌ای برای عملیات تصویر و صدا وجود دارد؛ تولیدی انجام نمی‌شود.", "Only data contracts for image and audio operations exist; nothing is generated.",
        (_b("model", "مدل تولید ویدیو/تصویر و موتور اجرای آن لازم است.", "A video/image generation model and its engine are required."),
         _b("native_code", "رمزگذار ویدیو و موتور مدل در APK نیست.", "No video encoder or model engine is in the APK."), HEAVY),
        "این در توان یک گوشی بدون مدل بزرگ نیست؛ فعلاً می‌توانم فقط متن و فهرست صحنه‌ها را اگر مدل نوشتن داشتم بنویسم (آن هم هنوز ندارم).",
        "This is beyond a phone without a large model; at most a scene list could be written once a text model exists (it does not yet).",
        True, ("برام یک ویدیو بساز", "میتونی انیمیشن درست کنی؟")),
    Gap("music_audio", "ساخت آهنگ، موسیقی و صدا", "Music and audio generation",
        ("آهنگ", "موسیقی", "ملودی", "صدا", "ترانه"), "dependency_blocked",
        "ثبت‌کنندهٔ عملیات صدا در برنامه فقط رکورد است؛ صدایی تولید نمی‌شود.", "The audio-operation registry in the app is records only; no sound is produced.",
        (_b("model", "مدل تولید موسیقی/صدا یا یک سینتی‌سایزر لازم است.", "A music/audio model or a synthesizer is required."),
         NEW_APK),
        "پخش یا ساخت صدا کد صدای اندروید (Java) و موتور تولید می‌خواهد که در این نسخه نیست.",
        "Playing or producing audio needs Android audio code (Java) and a generator, neither of which is in this version.",
        True, ("یک آهنگ برام بساز", "موسیقی پخش کن")),
    Gap("game_creation", "ساخت بازی", "Game creation",
        ("بازی",), "scaffold_only",
        "پروژه/صحنه/شخصیت بازی فقط به‌صورت رکورد و اعتبارسنج در کد هست (game_creation).",
        "Game projects/scenes/characters exist only as records and validators in the code (game_creation).",
        (_b("dependency", "موتور اجرا و تولید دارایی (تصویر/صدا) وجود ندارد.", "There is no runtime or asset generation (images/audio)."),
         _b("model", "طراحی خودکار بازی از یک توضیح آزاد، مدل زبانی لازم دارد.", "Designing a game from a free description needs a language model.")),
        "یک افزونهٔ متنی ساده (مثل حدس عدد) را اگر بسته‌اش را بدهی می‌توانم اعتبارسنجی، آزمایش و با تأیید تو فعال کنم.",
        "If you give me its package I can validate, test and (with your approval) activate a simple text-only extension, such as a number-guessing helper.",
        True, ("برای من یک بازی بساز",)),
    Gap("three_d", "مدل سه‌بعدی و رندر", "3D models and rendering",
        ("سه بعدی", "سهبعدی", "3d", "ریندر", "رندر"), "dependency_blocked",
        "هیچ کد سه‌بعدی در برنامه نیست.", "There is no 3D code in the app.",
        (_b("native_code", "موتور رندر (OpenGL/Filament) و مدل سه‌بعدی لازم است.", "A rendering engine (OpenGL/Filament) and a 3D model are required."), NEW_APK, HEAVY),
        "این کار فقط با یک APK جدید و موتور رندر ممکن می‌شود.", "This only becomes possible with a new APK and a rendering engine.",
        True, ("یک مدل سه بعدی بساز",)),
    Gap("ui_self_change", "تغییر ظاهر و دکمه‌های خود برنامه", "Changing the app's own UI",
        ("رابط کاربری", "ظاهر برنامه", "ظاهر", "تم", "دکمه", "حالت شب", "حالت روز", "تاریک", "صفحه اصلی"), "not_implemented",
        "ظاهر برنامه فایل‌های ثابتِ داخل APK است و سرور محلی آن‌ها را بدون لایهٔ سفارشی‌سازی می‌دهد.",
        "The UI is static files inside the APK and the local server serves them without a customization layer.",
        (_b("new_apk", "برای بارگذاری ظاهر سفارشی از حافظهٔ برنامه، یک هوک در سرور/صفحه لازم است که یک APK جدید می‌خواهد.",
            "Loading a user-made UI from app storage needs a server/page hook, which needs a new APK."),),
        "تغییر ظاهر فعلاً فقط با ساخت نسخهٔ جدید برنامه شدنی است؛ از داخل گفت‌وگو نمی‌توانم صفحه را بازنویسی کنم.",
        "Changing the look currently requires building a new version of the app; I cannot rewrite the page from inside the chat.",
        True, ("حالت شب را اضافه کن", "یک دکمه به صفحه اضافه کن")),
    Gap("wake_word_voice", "صدا زدن «جارویس» و گفت‌وگوی صوتی", "Wake word and voice conversation",
        ("جارویس", "ژارویس", "هی جارویس", "میکروفون", "حرف بزن", "صحبت کن", "بخوان برایم"), "dependency_blocked",
        "قراردادهای داده‌ای صدا (voice) و گزارش وضعیت میکروفون (android.microphone) هست؛ ضبط یا تشخیص گفتار نیست.",
        "Voice data contracts (voice) and the microphone status report (android.microphone) exist; there is no recording or recognition.",
        (_b("permission", "مجوز میکروفون (RECORD_AUDIO) در برنامه اعلام نشده است.", "The microphone permission (RECORD_AUDIO) is not declared in the app."),
         _b("model", "تشخیص گفتار فارسی و کلمهٔ بیدارباش (wake word) مدل می‌خواهد.", "Persian speech recognition and a wake-word detector need models."),
         _b("native_code", "گوش‌دادن دائم در اندروید یک سرویس پیش‌زمینه (Java) می‌خواهد.", "Always-on listening on Android needs a foreground service (Java)."), NEW_APK),
        "اول باید نسخهٔ جدید APK با مجوز میکروفون و سرویس صوتی ساخته شود؛ بعد مدل گفتار.",
        "A new APK with the microphone permission and an audio service has to come first; then a speech model.",
        False, ("جارویس ساعت چنده", "هی جارویس")),
    Gap("speaker_identity", "شناسایی گوینده با صدا", "Speaker identification",
        ("گوینده", "صدای من", "هویت صوتی", "صدایم را بشناس"), "scaffold_only",
        "فقط رکورد و اعتبارسنج پروفایل صوتی در کد هست (voice).", "Only voice-profile records and validators exist in the code (voice).",
        (_b("permission", "مجوز میکروفون اعلام نشده است.", "The microphone permission is not declared."),
         _b("model", "مدل استخراج و تطبیق «اثر صدا» لازم است.", "A voice-embedding model is required."), NEW_APK),
        "نیازمند همان زیرساخت صوتیِ بالا به‌علاوهٔ یک مدل گوینده است.", "It needs the audio groundwork above plus a speaker model.",
        True, ("صدای من را بشناس",)),
    Gap("phone_control", "کنترل گوشی (قفل، تنظیمات)", "Phone control (unlock, settings)",
        ("قفل گوشی", "تنظیمات گوشی", "روشنایی", "بلوتوث", "وای فای", "حالت پرواز", "صفحه قفل"), "policy_blocked",
        "وضعیت «تنظیمات» در کاتالوگ اندروید هست ولی هیچ کنشی برایش پیاده نشده (android.settings_write).",
        "A 'settings' feature exists in the Android catalog but no action is implemented for it (android.settings_write).",
        (_b("policy", "اندروید اجازه نمی‌دهد یک برنامه قفل صفحه را باز کند.", "Android does not let an app unlock the screen."),
         _b("permission", "تغییر تنظیمات سیستم مجوز ویژه (WRITE_SETTINGS) و تأیید دستی کاربر در تنظیمات می‌خواهد.",
            "Changing system settings needs a special permission (WRITE_SETTINGS) granted by hand in Settings."), NEW_APK),
        "برخی تنظیمات (مثل روشنایی) بعد از یک APK جدید با تأیید خودت شدنی است؛ باز کردن قفل نه.",
        "Some settings (such as brightness) become possible after a new APK with your approval; unlocking does not.",
        True, ("قفل گوشی را باز کن", "وای فای را خاموش کن")),
    Gap("social_posting", "پاسخ و پست خودکار در شبکه‌های اجتماعی", "Automatic replies and scheduled posts",
        ("پست", "استوری", "کانال", "پیج", "اینستا", "اینستاگرام", "توییتر", "ایکس"), "not_implemented",
        "فقط خواندن (GET) پیاده شده؛ ارسال (POST) و ورود به حساب پیاده نشده است.", "Only reading (GET) is implemented; sending (POST) and account sign-in are not.",
        (_b("external_service", "هر شبکه کلید/توکن حساب و شرایط API خودش را دارد (اسرار شخصی که نباید در کد باشند).",
            "Each network has its own account key/token and API terms (personal secrets that must not live in code)."),
         _b("consequential", "ارسال پست به نام تو یک کار پیامددار است و باید هر بار صریحاً تأیید شود.",
            "Posting in your name is consequential and would need explicit approval each time."),
         _b("native_code", "زمان‌بندی نیاز به کار پس‌زمینه دارد.", "Scheduling needs background work."), NEW_APK),
        "اول باید اتصال رسمی هر شبکه و مخزن امن توکن‌ها طراحی شود؛ هنوز ندارم.",
        "A per-network official connection and a safe token store have to be designed first; I have neither yet.",
        True, ("هر روز ساعت ۸ یک پست در اینستاگرام بگذار",)),
    Gap("other_apps", "کنترل برنامه‌های دیگر (تلگرام، اینستاگرام ...)", "Controlling other apps",
        ("تلگرام", "اینستاگرام", "واتساپ", "برنامه دیگر", "برنامه‌های دیگر", "اپلیکیشن دیگر"), "policy_blocked",
        "هیچ اتصالی به برنامه‌های دیگر وجود ندارد.", "There is no connection to other apps.",
        (_b("policy", "کنترل برنامهٔ دیگر فقط با «سرویس دسترسی‌پذیری» ممکن است که کاربر باید دستی فعالش کند و سیاست‌های فروشگاه‌ها محدودش می‌کنند.",
            "Controlling another app needs an Accessibility service that the user must enable by hand and that stores restrict."),
         NEW_APK),
        "اگر سرویس رسمی و کلید دسترسی داشته باشی، اتصال جداگانه و با تأیید صریح ممکن است؛ الان وجود ندارد.",
        "With an official service and your own access key a separate, explicitly approved connection is possible; none exists now.",
        True, ("به پیام‌های تلگرام جواب بده",)),
    Gap("phone_calls", "جواب دادن به تماس تلفنی", "Answering phone calls",
        ("تماس", "تلفن", "زنگ", "جواب تلفن"), "policy_blocked",
        "وضعیت «تلفن» در کاتالوگ اندروید هست ولی با محدودیت سیاست‌ها و بدون کنش پیاده‌شده.",
        "A 'telephony' feature exists in the Android catalog, limited by policy and without an implemented action.",
        (_b("policy", "اندروید ضبط و پاسخ خودکار تماس را برای برنامه‌های معمولی محدود کرده است؛ برنامه باید «برنامهٔ پیش‌فرض تلفن» شود.",
            "Android restricts call recording and automatic answering for ordinary apps; the app would have to be the default dialer."),
         _b("permission", "مجوزهای تلفن در برنامه اعلام نشده است.", "Telephony permissions are not declared in the app."), NEW_APK),
        "فعلاً هیچ تماسی را جواب نمی‌دهم و اعلان صوتی تماس هم ندارم.", "For now I answer no calls and have no spoken call notifications.",
        True, ("به تماس‌هایم جواب بده",)),
    Gap("idle_web_gathering", "جمع‌آوری خودکار اطلاعات از اینترنت هنگام بیکاری", "Gathering information from the web while idle",
        ("یوتیوب", "جمع آوری", "جمع‌آوری", "خبر", "اخبار", "وقتی بیکاری", "وقتی بیکار"), "not_implemented",
        "خواندن یک صفحهٔ وب با اجازهٔ تو کار می‌کند (tool.web_fetch).", "Reading one web page with your permission works (tool.web_fetch).",
        (_b("native_code", "اجرای کار در پس‌زمینه (WorkManager یا سرویس پیش‌زمینه) کد Java تازه می‌خواهد؛ اندروید پردازش‌های پس‌زمینه را می‌بندد.",
            "Background work (WorkManager or a foreground service) needs new Java code; Android stops background processes."), NEW_APK,
         _b("external_service", "خواندن از ChatGPT یا یوتیوب مثل یک سرویس هوش مصنوعی/وابسته به شرایط استفادهٔ آن‌هاست و با اصل «بدون هوش مصنوعی بیرونی» نمی‌خواند.",
            "Reading from ChatGPT or YouTube means relying on an external AI service/terms of use, against the 'no external AI' rule.")),
        "می‌توانی آدرس یک صفحه را بدهی تا همین الان (با مجوز اینترنت) بخوانم؛ زمان‌بندی خودکار هنوز نیست.",
        "You can give me a page address and I will read it now (with the internet permission); automatic scheduling does not exist yet.",
        True, ("وقتی بیکاری از یوتیوب اطلاعات جمع کن", "یه خبر از اینترنت برام بیار")),
    Gap("income_crypto", "کسب درآمد، ارز دیجیتال و برداشت به تومان", "Earning income, crypto and cash-out",
        ("درآمد", "ارز دیجیتال", "رمزارز", "رمز ارز", "بیت کوین", "بیتکوین", "کیف پول", "کیفپول", "برداشت", "کسب درآمد", "پول"), "policy_blocked",
        "فقط مدل دادهٔ هدف و راهبرد مالی در حافظه هست (financial)؛ هیچ پولی جابه‌جا نمی‌شود.",
        "Only an in-memory financial goal/strategy data model exists (financial); no money is moved.",
        (_b("consequential", "جابه‌جایی پول یا ارز دیجیتال برگشت‌ناپذیر و دارای پیامد حقوقی است؛ بدون طراحی و بازبینی جداگانه ساخته نمی‌شود.",
            "Moving money or crypto is irreversible and legally consequential; it is not built without a separate reviewed design."),
         _b("external_service", "به حساب بانکی، صرافی یا کیف پول و کلید خصوصی نیاز دارد که نباید در برنامه ذخیره یا حدس زده شود.",
            "It needs a bank, exchange or wallet and private keys that must never be stored or guessed by the app.")),
        "می‌توانم برایت فقط یک برنامهٔ بودجه یا محاسبهٔ ساده بسازم؛ معامله یا برداشت نه.",
        "I can only build you a budget or a simple calculator; no trading or withdrawals.",
        True, ("برام ارز دیجیتال استخراج کن و به تومان تبدیلش کن",)),
    Gap("windows_companion", "«بدن دوم» ویندوزی", "A Windows 'second body'",
        ("ویندوز", "کامپیوتر", "لپ تاپ", "لپتاپ"), "not_implemented",
        "هستهٔ پایتون روی دسکتاپ هم اجرا می‌شود (برای آزمون)، ولی بستهٔ ویندوز و همگام‌سازی با گوشی وجود ندارد.",
        "The Python core also runs on a desktop (for tests), but there is no Windows package or phone sync.",
        (_b("design", "بسته‌بندی ویندوز، ارتباط امن با گوشی و همگام‌سازی حافظه هنوز طراحی نشده است.",
            "Windows packaging, a secure phone link and memory sync are not designed yet."),),
        "این یک پروژهٔ جداگانه است.", "This is a separate project.", True, ("نسخهٔ ویندوز بساز",)),
    Gap("local_code_model", "نوشتن خودکار کد افزونه توسط خود برنامه", "Writing extension code by itself",
        ("کد+بنویس", "برنامه+بنویس", "خودت+بنویس", "کد+بساز", "کدش را بنویس"), "dependency_blocked",
        "مسیر واقعیِ رشد: بستهٔ افزونه (ext.v1) را تو یا ChatGPT می‌نویسی و من اعتبارسنجی، آزمایش و با تأیید تو فعال می‌کنم.",
        "The real growth path: you or ChatGPT write an extension package (ext.v1); I validate, test and, with your approval, activate it.",
        (_b("model", "نوشتن کد از یک توضیح آزاد یک مدل زبانیِ کدنویس روی دستگاه می‌خواهد؛ مدل n-gram موجود یک مدل زبانی واقعی نیست.",
            "Writing code from a free description needs an on-device code-writing language model; the existing n-gram model is not a real LLM."),
         _b("native_code", "اجرای مدل‌های بزرگ (llama.cpp) کتابخانهٔ native می‌خواهد که در این APK نیست.",
            "Running larger models (llama.cpp) needs a native library that is not in this APK.")),
        "پرامپت آمادهٔ ساخت افزونه را از من بگیر و نتیجه را همین‌جا بچسبان.",
        "Ask me for the ready-made extension prompt and paste the result here.",
        True, ("خودت یک کد برای این کار بنویس",)),
    Gap("camera_vision", "دیدن با دوربین و تشخیص تصویر", "Seeing through the camera",
        ("دوربین", "تشخیص تصویر", "عکس بگیر"), "dependency_blocked",
        "وضعیت دوربین در کاتالوگ اندروید هست (android.camera) ولی کنشی پیاده نشده.", "A camera status exists in the Android catalog (android.camera) but no action is implemented.",
        (_b("permission", "مجوز دوربین اعلام نشده است.", "The camera permission is not declared."),
         _b("model", "تشخیص تصویر مدل بینایی می‌خواهد.", "Image recognition needs a vision model."), NEW_APK),
        "اول مجوز و کد دوربین در یک APK جدید، بعد مدل.", "First the permission and camera code in a new APK, then a model.",
        True, ("با دوربین ببین این چیه",)),
)

_BY_ID = {g.gap_id: g for g in GAPS}

# request / ability markers, matched on normalized tokens (ZWNJ already became a space)
_PREFIXES = ("بساز", "تولید", "بکش", "طراحی", "بنویس", "ایجاد", "پخش", "بفرست", "ارسال", "بخر", "بفروش", "بیار", "بگیر",
             "ببین", "بگذار", "بذار", "بزار", "میتون", "میتوان", "بلدی", "امکان", "قابلیت", "میخوا", "بتون", "بتوان", "بشناس")
_PAIRS = (("درست", "کن"), ("آماده", "کن"), ("اضافه", "کن"), ("باز", "کن"), ("تنظیم", "کن"), ("عوض", "کن"), ("تغییر", "بده"),
          ("جواب", "بده"), ("پاسخ", "بده"), ("می", "تونی"), ("می", "توانی"), ("می", "خوام"), ("می", "خواهم"), ("می", "تونه"),
          ("یاد", "بگیر"), ("کار", "کن"), ("روشن", "کن"), ("خاموش", "کن"), ("فعال", "کن"), ("نصب", "کن"), ("جمع", "کن"),
          ("پست", "کن"), ("بنویس", "برام"))


def gap_ids():
    return tuple(g.gap_id for g in GAPS)


def get_gap(gap_id):
    return _BY_ID.get(gap_id)


def _has_frame(tokens):
    for i, tok in enumerate(tokens):
        if tok.startswith(_PREFIXES):
            return True
        if i > 0 and tok in ("کن", "کنی", "کنید", "کنم"):               # «... کن»: a spoken imperative
            return True
        for first, second in _PAIRS:
            if tok == first and i + 1 < len(tokens) and tokens[i + 1].startswith(second):
                return True
    return False


def _has_word(joined, tokens, word):
    if "+" in word:                                                       # "a+b": every part must appear
        return all(_has_word(joined, tokens, part) for part in word.split("+"))
    word = fa_text.canon(word)
    if " " in word:
        return (" " + word + " ") in joined
    return word in tokens


def match_gap(text) -> Optional[Gap]:
    """The gap a sentence asks about (see the module docstring), or None."""
    if not isinstance(text, str) or not text.strip() or len(text) > 400:
        return None
    norm = fa_text.canon(text)
    tokens = fa_text.words(norm)
    if not tokens:
        return None
    joined = " " + " ".join(tokens) + " "
    framed = _has_frame(tokens)
    best, best_hits = None, 0
    for gap in GAPS:
        if gap.needs_frame and not framed:
            continue
        hits = sum(2 if (" " in fa_text.canon(w) or "+" in w) else 1 for w in gap.words if _has_word(joined, tokens, w))
        if hits > best_hits:
            best, best_hits = gap, hits
    return best
