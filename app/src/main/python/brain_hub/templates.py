"""
brain_hub.templates - the prompt a user can hand to ANY assistant of their choice to get an `ext.v1` extension package
===================================================================================================================
The app itself never calls an AI service. When the user wants a capability the app does not have, the app can give
them a ready-made request ("prompt") that they paste into whatever assistant they like (a chat site, a friend, an
offline tool); the answer is a single JSON package that they paste back into this app's chat. The app then validates,
tests and shows it, and activates it only after the user's explicit yes.

`build_prompt(request)` embeds the user's wish and states the rules EXACTLY as the validator enforces them: every
list and number below is read from the live `ext_runtime` constants, so this text cannot drift from the code, and the
included example is a real package that the real manager accepts (a test proves it).
"""

import json
import re

from ext_runtime import guards, limits, manifest, srcvalidate

__all__ = ["build_prompt", "example_package", "prompt_facts", "MAX_REQUEST_CHARS"]

MAX_REQUEST_CHARS = 600
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩]")


def example_package():
    """A small, complete, valid package (the model answer's shape). Used verbatim inside the prompt."""
    return {
        "schema": "ext.v1", "id": "bmi_calc", "title": "محاسبهٔ شاخص توده بدنی",
        "description": "شاخص توده بدنی (BMI) را از وزن به کیلوگرم و قد به متر حساب می‌کند.",
        "inputs": [{"name": "weight", "type": "number", "min": 10, "max": 400, "label": "وزن (کیلوگرم)"},
                   {"name": "height", "type": "number", "min": 0.5, "max": 2.5, "label": "قد (متر)"}],
        "outputs": [{"name": "bmi", "type": "number", "label": "BMI"}],
        "source": "def run(weight, height):\n\tbmi = round(weight / (height * height), 1)\n\tif bmi < 0:\n\t\tbmi = 0\n\treturn {'bmi': bmi}\n",
        "triggers": ["bmi وزن {weight:number} قد {height:number}"],
        "answer": "BMI شما {bmi} است.",
        "examples": ["bmi وزن 70 قد 1.75"],
        "tests": [{"name": "نمونهٔ عادی", "inputs": {"weight": 70, "height": 1.75}, "expect": {"bmi": 22.9}},
                  {"name": "وزن بسیار کم", "inputs": {"weight": 45, "height": 1.8}, "expect": {"bmi": 13.9}}],
    }


def prompt_facts():
    """The live numbers and lists the prompt states (for tests and documentation)."""
    return {
        "top_keys": list(manifest._TOP_KEYS),                      # noqa: SLF001 - the one source of truth
        "input_types": list(limits.INPUT_TYPES),
        "output_types": list(limits.OUTPUT_TYPES),
        "permissions": list(limits.OPTIONAL_PERMISSIONS),
        "dependencies": list(limits.ALLOWED_DEPENDENCIES),
        "builtins": sorted(n for n in srcvalidate.BUILTIN_NAMES if n[:1].islower()),
        "string_methods": sorted(guards.STR_METHODS),
        "list_methods": sorted(guards.LIST_METHODS),
        "dict_methods": sorted(guards.DICT_METHODS),
        "math_names": sorted(guards.MATH_NAMES),
        "max_package_bytes": limits.MAX_PACKAGE_BYTES,
        "max_source_bytes": limits.MAX_SOURCE_BYTES,
        "max_inputs": limits.MAX_INPUTS, "max_outputs": limits.MAX_OUTPUTS, "max_tests": limits.MAX_TESTS,
        "max_triggers": limits.MAX_TRIGGERS, "max_answer_chars": 300,
        "max_fuel": limits.MAX_FUEL, "max_seconds": limits.MAX_SECONDS,
        "slot_types": ["number", "integer", "text", "word", "list_number", "list_text"],
    }


def _clean_request(text):
    text = _CONTROL_RE.sub(" ", str(text or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_REQUEST_CHARS]


def build_prompt(request_text=""):
    """The Persian request to paste into any assistant. `request_text` is the user's own wish (clipped, control characters removed)."""
    facts = prompt_facts()
    wish = _clean_request(request_text) or "(اینجا بنویس چه قابلیتی می‌خواهی)"
    example = json.dumps(example_package(), ensure_ascii=False, indent=1)
    lines = [
        "تو یک «بستهٔ افزونه» برای یک دستیار فارسی آفلاین روی گوشی می‌نویسی. فقط و فقط یک شیء JSON معتبر بده، داخل یک بلاک کد با برچسب json",
        "(یعنی همان قالبی که پایین‌تر در نمونه می‌بینی) و هیچ توضیح دیگری ننویس.",
        "",
        "درخواست من: " + wish,
        "",
        "## قالب بسته (schema: ext.v1)",
        "کلیدهای مجاز سطح بالا (هر کلید دیگری خطا می‌دهد): " + "، ".join(facts["top_keys"]) + ".",
        "- schema = \"ext.v1\"؛ id = حروف کوچک انگلیسی/عدد/زیرخط، ۳ تا ۴۰ نویسه، با حرف شروع شود.",
        "- title (فارسی، حداکثر %d نویسه)، description (حداکثر %d نویسه)." % (limits.MAX_TITLE_CHARS, limits.MAX_DESCRIPTION_CHARS),
        "- inputs: حداکثر %d ورودی. هر کدام name (انگلیسی snake_case، همان نام پارامتر تابع)، type از: %s، "
        "و اختیاری label, required, default, min/max (فقط number/integer), max_items (فقط لیست‌ها)." % (
            facts["max_inputs"], "، ".join(facts["input_types"])),
        "- outputs: ۱ تا %d خروجی با name و type از: %s." % (facts["max_outputs"], "، ".join(facts["output_types"])),
        "- source: کد پایتون، حداکثر %d بایت، با تابعی به نام run(...) که دقیقاً پارامترهای inputs را بگیرد و یک dict برگرداند "
        "که کلیدهایش دقیقاً نام outputs باشد." % facts["max_source_bytes"],
        "- triggers: ۱ تا %d عبارت که پیام کاربر را به افزونه وصل می‌کند؛ توضیح پایین‌تر." % facts["max_triggers"],
        "- answer: قالب جملهٔ جواب (حداکثر %d نویسه) با جای‌گذاری {نام_خروجی}. جای‌گذار فقط نام ورودی/خروجی تعریف‌شده باشد." % facts["max_answer_chars"],
        "- tests: ۱ تا %d آزمون {name?, inputs, expect} یا {inputs, expect_error: true}. حداقل یکی موفق باشد؛ نتیجه‌ها باید قطعی (deterministic) باشند. "
        "بدون آزمون، افزونه هرگز فعال نمی‌شود." % facts["max_tests"],
        "- اختیاری: examples (حداکثر ۵ جملهٔ کوتاه)، fixtures ({clock: عدد, store: {...}, web: {آدرس: متن}} فقط برای آزمون‌ها)، "
        "provenance ({author, source, note})، permissions، dependencies.",
        "- کل بسته حداکثر %d بایت." % facts["max_package_bytes"],
        "",
        "## قواعد کد (زیرمجموعهٔ محدود پایتون؛ هر چیز دیگر رد می‌شود)",
        "- تورفتگی خط‌های کد را فقط با نویسهٔ tab بنویس و در JSON آن را به‌صورت \\t بیاور (مثل نمونهٔ پایین)، نه با فاصله: "
        "گفتگو فاصله‌های پشت‌سرهم را یکی می‌کند و تورفتگی با فاصله خراب می‌شود. داخل رشته‌های کد هم دو فاصلهٔ پشت‌سرهم نگذار.",
        "- فقط توابع ساده. این‌ها مجاز نیست: class، import به‌جز math، نام یا ویژگی‌ای که با زیرخط شروع شود، open/eval/exec/print/input، "
        "yield و async، global، with، del، assert، دکوراتور، str.format و قالب‌بندی با %.",
        "- مجاز: if/for/while/try-except (ValueError, TypeError, ZeroDivisionError, KeyError, IndexError, Exception, OverflowError)، "
        "lambda، فهرست‌سازی (comprehension)، f-string ساده.",
        "- توابع آماده: " + " ".join(facts["builtins"]) + ".",
        "- متدهای رشته: " + " ".join(facts["string_methods"]) + ".",
        "- متدهای لیست: " + " ".join(facts["list_methods"]) + "؛ دیکشنری: " + " ".join(facts["dict_methods"]) + ".",
        "- اگر math لازم است باید هم در dependencies بنویسی [\"math\"] هم در کد import math کنی؛ نام‌های مجاز: " + " ".join(facts["math_names"]) + ".",
        "- سقف اجرا: حدود %d گام و %.0f ثانیه برای هر بار اجرا؛ حلقهٔ بی‌پایان رد می‌شود." % (facts["max_fuel"], facts["max_seconds"]),
        "",
        "## مجوزها (کمترین دسترسی)",
        "- فقط مجوزی را در permissions بنویس که کد واقعاً استفاده می‌کند؛ مجوز اضافه یا استفادهٔ بدون اعلام، رد می‌شود.",
        "- clock: تابع clock_now() ساعت دستگاه را (ثانیه) می‌دهد.",
        "- storage: store_get(key, default) / store_put(key, value) / store_delete(key) / store_keys() برای حافظهٔ کوچک خود افزونه.",
        "- network: web_fetch_text(url) فقط «متن قابل‌دیدن» صفحه را برمی‌گرداند (برچسب‌های HTML حذف شده‌اند، نه خود HTML) "
        "و فقط وقتی کاربر اینترنت را روشن کرده باشد کار می‌کند. در fixtures.web همان متن را بگذار.",
        "- هر چیز دیگر (فایل، میکروفون، دوربین، پیامک، تماس، اجرای دستور) در افزونه ممکن نیست و نباید درخواستش را بدهی.",
        "",
        "## عبارت‌های فعال‌ساز (triggers)",
        "اجزا با فاصله جدا می‌شوند: کلمه | چندگزینه‌ای الف|ب | [اختیاری] | {slot} یا {slot:نوع} | * (هر چند کلمه).",
        "نوع slot از: " + "، ".join(facts["slot_types"]) + ". نام slot باید یکی از inputs باشد (number→number/integer، integer→integer، text→text/word، "
        "list_number→list_number، list_text→list_text). یک جملهٔ داخل «...» عیناً به‌عنوان text گرفته می‌شود.",
        "عبارت باید کل جمله را بپوشاند (فقط چند کلمهٔ مؤدبانهٔ مثل لطفا حذف می‌شود)، پس روی جمله‌های بی‌ربط فعال نمی‌شود.",
        "",
        "## یک نمونهٔ کامل و معتبر (قالب پاسخ تو باید همین‌طور باشد)",
        "```json",
        example,
        "```",
        "",
        "حالا فقط بستهٔ JSON مربوط به درخواست من را بده.",
    ]
    return "\n".join(lines)
