"""
brain_hub.catalog - what the existing packages REALLY are (from the Prompt-957 audit)
=====================================================================================
Two static tables, written from reading the code and from a dynamic trace of real Persian messages through
`Core.process_input` (not from file names):

  CONNECTED   packages that run on the normal chat path (`core -> skills -> persian_brain / understanding /
              knowledge / learning / reasoning / planning ...`). They are described as `brain.*` nodes.
  SCAFFOLDS   packages that are contracts, registries, validators and planners ("foundations"): nothing in the
              chat path calls them and their "executors" are boundaries without a real implementation. They are
              listed as `infra.*` nodes with the state `scaffold_only`, so nobody mistakes a data model for a
              working feature (for example: the image/audio operation records are data only; they render no
              pixel and synthesize no sound).

`package_present(name)` only asks the import system whether the package exists in THIS build (it imports nothing).
An entry whose `package` is None is not probed: earlier frozen boundary tests forbid production code outside the
image/audio package from naming it, so that entry is keyed by its `area_id` alone (the tests of this prompt check the
mapping to the real package).
The user-facing wishes that need a model, a permission, native code or a policy decision are in `gaps.py`.
"""

import importlib.util
from dataclasses import dataclass
from typing import Optional, Tuple

from .graph import Blocker

__all__ = ["ConnectedArea", "Scaffold", "CONNECTED", "SCAFFOLDS", "package_present"]


def package_present(name):
    """True when `name` is importable in this build (nothing is imported)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class ConnectedArea:
    area_id: str
    package: str
    title_fa: str
    title_en: str
    summary_fa: str
    summary_en: str
    entry: str


@dataclass(frozen=True)
class Scaffold:
    area_id: str
    package: Optional[str]
    title_fa: str
    title_en: str
    summary_fa: str
    summary_en: str
    missing: Tuple[Blocker, ...]


CONNECTED = (
    ConnectedArea(
        "conversation", "persian_brain", "گفت‌وگوی فارسی", "Persian conversation",
        "مغز گفت‌وگو: سلام و احوال‌پرسی، فهمیدن درخواست‌ها، پرسیدن سؤال تکمیلی، یادگیری جمله‌ها و صدا زدن قابلیت‌ها.",
        "The conversation brain: greetings, understanding requests, follow-up questions, learning sentences, calling capabilities.",
        "پیام ← /api/message ← RuntimeCore ← Core ← SkillSystem ← persian_brain"),
    ConnectedArea(
        "memory", "memory", "حافظه و دانش", "Memory and knowledge",
        "حافظهٔ ماندگار (پایگاه SQLite) برای نام و علایق تو، جمله‌های آموخته‌شده و وضعیت گفت‌وگو؛ بعد از بستن برنامه می‌ماند.",
        "Persistent memory (SQLite) for your name and likes, taught sentences and dialogue state; it survives restarts.",
        "persian_brain ← knowledge / learning / concepts ← memory.db"),
    ConnectedArea(
        "understanding", "understanding", "فهم زبان فارسی", "Persian language understanding",
        "تحلیل جملهٔ فارسی (نرمال‌سازی، نیت، اطلاعات شخصی) که قبل از هر چیز روی پیام اجرا می‌شود.",
        "Persian sentence analysis (normalization, intent, personal facts) that runs on every message first.",
        "Core ← understanding.persian_nlu"),
    ConnectedArea(
        "pipeline", "reasoning", "استدلال و برنامه‌ریزی داخلی", "Internal reasoning and planning",
        "زنجیرهٔ هستهٔ برنامه (context، reasoning، planning، capabilities) که روی هر پیام اجرا می‌شود؛ وقتی چیزی نمی‌داند صادقانه می‌گوید «هنوز نمی‌توانم».",
        "The Core pipeline (context, reasoning, planning, capabilities) that runs on each message; when it knows nothing it honestly says it cannot yet.",
        "Core.process_input ← parser ← context ← reasoning ← planning"),
    ConnectedArea(
        "language_intelligence", "language_intelligence", "زیرساخت زبان و مدل محلی", "Language-intelligence plumbing",
        "زیرساخت قراردادی برای مدل زبانی محلی (LocalLanguageModelBackend). بدون یک مدل واقعی که بارگذاری و آزمایش شده باشد، چیزی تولید نمی‌کند.",
        "The contract plumbing for a local language model (LocalLanguageModelBackend). Without a loaded, smoke-tested model it generates nothing.",
        "Core ← language_intelligence ← model_runtime (only with a usable model)"),
    ConnectedArea(
        "ael", "ael", "دستورهای AEL", "AEL commands",
        "زبان فرمان داخلی (TEACH، UPGRADE ...) که مستقیم به هسته می‌رسد. توجه: فرمان UPGRADE فقط یک رکورد در تاریخچهٔ ارتقا ثبت می‌کند و کد برنامه را عوض نمی‌کند.",
        "The internal command language (TEACH, UPGRADE ...). Note: UPGRADE only records an entry in the upgrade history; it does not change program code.",
        "Core ← ael.interpreter"),
)


def _b(kind, fa, en):
    return Blocker(kind, fa, en)


SCAFFOLDS = (
    Scaffold(
        "agent", "agent", "حلقهٔ عامل (Agent)", "Agent loop",
        "یک هماهنگ‌کنندهٔ قطعی که تصمیم می‌گیرد یک «برنامه»ٔ آماده الان اجرا شود یا نه. خودش هدف یا برنامه نمی‌سازد و به گفت‌وگو وصل نیست.",
        "A deterministic coordinator that decides whether an existing plan should run now. It creates no goals or plans and is not connected to chat.",
        (_b("design", "چیزی از درخواست تو «هدف» و «برنامه» نمی‌سازد؛ این اتصال هنوز نوشته نشده.",
            "Nothing turns your request into a goal and a plan yet; that connection is not written."),)),
    Scaffold(
        "autonomy", "autonomy", "خودمختاری کنترل‌شده", "Controlled autonomy",
        "قراردادها و اعتبارسنج‌های داده برای فرایند تأیید و تکامل داخلی (درخواست تأیید، تصمیم، سیاست مجوز). اجراکننده ندارد.",
        "Data contracts and validators for an approval-gated evolution process (approval requests, decisions, permission policy). No executor.",
        (_b("design", "فقط رکورد و اعتبارسنج است؛ کاری را اجرا نمی‌کند. مسیر واقعی تأیید در هاب (تأیید صریح کاربر) جداگانه ساخته شده.",
            "Records and validators only; it executes nothing. The real approval path lives in the hub (explicit user approval)."),)),
    Scaffold(
        "code_generation", "code_generation", "تولید کد", "Code generation",
        "پایه‌های اعتبارسنجی و اعمال کدِ تولیدشده و یک تولیدکنندهٔ قالبیِ تابع. به گفت‌وگو وصل نیست و مدل نویسندهٔ کد ندارد.",
        "Foundations for validating and applying generated code and a template-based function generator. Not connected to chat; no code-writing model.",
        (_b("model", "برای نوشتن کدِ تازه از یک درخواست آزاد، یک مدل زبانیِ توانا در نوشتن کد لازم است که در برنامه نیست.",
            "Writing new code from a free request needs a capable code-writing language model, which the app does not have."),)),
    Scaffold(
        "financial", "financial", "برنامه‌ریزی مالی", "Financial planning",
        "مدل داده‌ی هدف مالی و راهبرد درآمد (در حافظه). هیچ اتصالی به بانک، کیف پول یا بازار ندارد و هیچ پولی جابه‌جا نمی‌کند.",
        "An in-memory data model of financial goals and revenue strategies. No connection to a bank, wallet or market; it moves no money.",
        (_b("consequential", "کار مالی واقعی پیامد جدی و حقوقی دارد؛ بدون طراحی و تأیید جداگانه ساخته نمی‌شود.",
            "Real financial actions have serious and legal consequences; they are not built without a separate, reviewed design."),)),
    Scaffold(
        "game_creation", "game_creation", "ساخت بازی", "Game creation",
        "رکوردها و اعتبارسنج‌های پروژه، صحنه، شخصیت و دارایی بازی. موتور بازی، تصویر یا کدِ قابل‌اجرا تولید نمی‌کند.",
        "Records and validators for game projects, scenes, characters and assets. It produces no game engine, images or runnable code.",
        (_b("dependency", "موتور اجرای بازی و تولید دارایی (تصویر/صدا) وجود ندارد.", "There is no game runtime or asset generation (images/audio)."),)),
    Scaffold(
        "images_audio", None, "تصویر و صدا", "Images and audio",
        "ثبت و برنامه‌ریزی «عملیات تصویر/صدا» به‌صورت داده. اجراکننده‌ها فقط فراداده می‌سازند؛ هیچ پیکسلی ساخته و هیچ صدایی تولید نمی‌شود.",
        "Registries and plans for image/audio operations as data. The executors only produce metadata; no pixel is rendered and no sound synthesized.",
        (_b("model", "ساخت یا ویرایش واقعی تصویر و صدا مدل یا کتابخانهٔ پردازشی می‌خواهد که در این برنامه نیست.",
            "Real image/audio generation or editing needs a model or processing library that is not in this app."),)),
    Scaffold(
        "research", "research", "پژوهش خودکار", "Autonomous research",
        "قرارداد درخواست، منبع، اعتماد، شواهد و جمع‌بندی پژوهش. خودش چیزی نمی‌خواند؛ فقط ساختار داده است. (خواندن صفحهٔ وب را حالا tool.web_fetch انجام می‌دهد.)",
        "Contracts for research requests, sources, trust, evidence and synthesis. It reads nothing itself. (Reading a web page is now done by tool.web_fetch.)",
        (_b("design", "حلقهٔ جست‌وجو ← خواندن ← جمع‌بندی ← ذخیره هنوز نوشته نشده.", "The search -> read -> summarize -> store loop is not written yet."),)),
    Scaffold(
        "tools", "tools", "ثبت ابزارها (قدیمی)", "Legacy tool registry",
        "یک ثبت‌کنندهٔ ساده در حافظه برای تعریف ابزار. ابزار واقعی را حالا همین هاب (گراف قابلیت‌ها) نگه می‌دارد.",
        "A simple in-memory registry of tool definitions. The real tool registry is now this hub (the capability graph).",
        (_b("design", "فقط تعریف داده است؛ نقش واقعی را گراف قابلیت‌های هاب بازی می‌کند.", "Definitions only; the hub's capability graph plays the real role."),)),
    Scaffold(
        "upgrade", "upgrade", "موتور ارتقای خود (قدیمی)", "Self-upgrade engine (legacy)",
        "قراردادهای درخواست، برنامه، سندباکس، تراکنش و ممیزیِ ارتقا. تغییری در کد برنامه نمی‌دهد. مسیر واقعی افزودن قابلیت: افزونه‌های هاب و Self-Builder.",
        "Contracts for upgrade requests, plans, sandbox, transaction and audit. It changes no program code. The real way to add capabilities: hub extensions and the Self-Builder.",
        (_b("new_apk", "تغییر کد Java/native یا فایل‌های اصلی برنامه فقط با ساخت APK جدید ممکن است.",
            "Changing Java/native code or the app's own files is only possible with a newly built APK."),)),
    Scaffold(
        "voice", "voice", "صدا و شناسایی گوینده", "Voice and speaker identity",
        "قراردادهای ثبت‌نام و تأیید هویت صوتی (پروفایل، درخواست، تصمیم). ضبط صدا و مدل گوینده ندارد.",
        "Contracts for voice enrollment and verification (profile, request, decision). No audio capture and no speaker model.",
        (_b("permission", "مجوز میکروفون در برنامه اعلام نشده است.", "The microphone permission is not declared in the app."),
         _b("model", "مدل تشخیص گوینده یا گفتار در برنامه نیست.", "There is no speaker or speech model in the app."))),
    Scaffold(
        "web", "web", "قراردادهای وب (قدیمی)", "Web contracts (legacy)",
        "قراردادهای قدیمیِ درخواست وب (طرح، اعتبارسنج، اجراکننده) که عمداً چیزی اجرا نمی‌کردند. خواندن واقعی صفحه (فقط GET، با مجوز اینترنت) را net_tools جداگانه انجام می‌دهد و از این قراردادها استفاده نمی‌کند.",
        "The older web-request contract chain (plans, validators, executors), which deliberately executed nothing. Real page reading (GET only, with the internet permission) is done by net_tools on its own; it does not use these contracts.",
        (_b("design", "ارسال (POST) و هر عملیاتی غیر از خواندن در این قراردادها اجرا نمی‌شود؛ فقط خواندنِ GET از راه «خواندن صفحهٔ وب» کار می‌کند.",
            "POST and every non-read operation in these contracts is not executed; only GET reads run, through 'Web page reading'."),)),
)
