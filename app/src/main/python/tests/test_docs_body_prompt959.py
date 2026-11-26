"""
Prompt 959 (stage B, the body) - the two documents about the BODY must stay true.

  docs/body_prompt959.md           the technical document: the rules, the parts, the life of a job, «ایست», the report, the one-time code, the limits
  docs/body_guide_fa_prompt959.md  the Persian user guide: every sentence it tells the user to say is run through the REAL classifiers (a hint that does
                                   not work is a bug), every number it states is the code's, and the messages it quotes are the app's real messages

If the code changes and a document is not updated, a test here fails instead of the document quietly lying to the user. The same file also keeps the
OLDER documents honest in the other direction: they once said that the notification button and the cancelling of a running answer "are not there yet",
and the body made both true - a sentence that stays behind would be a lie in the other direction.
"""
import inspect
import json
import os
import re
import sys
import unittest
import unittest.mock
from xml.etree import ElementTree as ET

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import platform_boot
from brain_hub import body, selftest, service
from brain_hub import ownbrain_catalog as catalog
from native_bridge import body as door
from native_bridge import otp
from persian_brain import hub_body
from persian_brain import hub_body_commands as BC
from persian_brain import hub_brain_commands as HBC
from persian_brain import hub_hooks
from persian_brain import hub_messages_body as HB
from persian_brain import hub_messages_ownbrain as BM
from persian_brain import hub_ownbrain_commands as OC
from persian_brain import normalization as nz
from self_builder import fa_text

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", ".."))
DOCS = os.path.join(REPO, "docs")
TECH = os.path.join(DOCS, "body_prompt959.md")
GUIDE = os.path.join(DOCS, "body_guide_fa_prompt959.md")
OWN_TECH = os.path.join(DOCS, "own_brain_prompt959.md")
OWN_GUIDE = os.path.join(DOCS, "own_brain_guide_fa_prompt959.md")
CLOUD_GUIDE = os.path.join(DOCS, "cloud_brain_guide_fa_prompt959.md")
BRAIN_V2 = os.path.join(DOCS, "brain_v2_prompt959.md")
MAIN = os.path.join(REPO, "app", "src", "main")
JAVA_DIR = os.path.join(MAIN, "java", "com", "erfan", "standaloneai")
TESTS = os.path.join(PY_ROOT, "tests")
DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(number):
    return str(number).translate(DIGITS)


def read(path):
    if not os.path.isfile(path):
        raise unittest.SkipTest("%s is not part of this checkout layout" % os.path.basename(path))
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def flat(text):
    return re.sub(r"\s+", " ", text)


def all_quoted(text):
    found = []
    for match in re.finditer(r"«([^»]+)»", text):
        phrase = match.group(1).strip()
        if phrase not in found:
            found.append(phrase)
    return found


def section_fa(text, number):
    match = re.search(r"^## %s\..*?(?=^## |\Z)" % re.escape(fa(number)), text, re.S | re.M)
    return match.group(0) if match else ""


def section_en(text, number):
    match = re.search(r"^## %d\..*?(?=^## |\Z)" % number, text, re.S | re.M)
    return match.group(0) if match else ""


def classify(phrase):
    norm = nz.normalize(phrase)
    return BC.classify(phrase, norm, fa_text.words(norm))


def own(phrase):
    norm = nz.normalize(phrase)
    return OC.classify(phrase, norm, fa_text.words(norm))


# ====================================================================== what the guide quotes, and in which role
BODY_COMMANDS = {                       # phrase -> (body command, its slots)
    "گزارش آزمایشی": (BC.SELFTEST, {"copy": False}),
    "گزارش آزمایشی را کپی کن": (BC.SELFTEST, {"copy": True}),
    "چک‌لیست دسترسی‌ها": (BC.ACCESS, {}),
    "صفحهٔ باتری را باز کن": (BC.OPEN, {"target": "battery"}),
    "تنظیمات برنامه را باز کن": (BC.OPEN, {"target": "app"}),
    "تنظیمات اعلان را باز کن": (BC.OPEN, {"target": "notifications"}),
    "مجوز پیامک را بده": (BC.SMS_PERMISSION, {}),
    "کد پیامک را بخوان": (BC.SMS, {"minutes": BC.DEFAULT_MINUTES}),
    "کد پیامک ۵ دقیقهٔ اخیر را بخوان": (BC.SMS, {"minutes": 5}),
    "کدِ پیامکِ یک ساعت اخیر را بخوان": (BC.SMS, {"minutes": 60}),
}
HALT_WORDS = ("ایست", "بایست", "توقف کن", "استاپ")
ONE_HOUR = "کدِ پیامکِ یک ساعت اخیر را بخوان"      # said in the troubleshooting section, not in the table of section 5
OTHER_COMMANDS = {"مغز خودت را بگیر": "own_get", "ادامه دانلود مغز": "own_resume", "ادامه": "resume", "بله": "confirm"}
LABELS = {"بدنهٔ برنامه", "بدنه", "آزموده‌شده با دوبله", "آزموده نشده", "موفق شد", "هی جارویس", "درخواست", "اجازه", "اجازهٔ اعلان", "نامعلوم",
          "شروع خودکار", "بدون محدودیت", "بهینه‌سازیِ باتری", "تنظیمِ محدودشده", "اجازهٔ تنظیماتِ محدودشده", "Allow restricted settings",
          "کد", "رمز", "تایید", "یک‌بارمصرف",
          "ارسال"}                                       # words, names and labels (Android's own screens; the page's send button, held against the page in PageStopButtonDocTests): nothing to type
APP_SAYS = {"در حال گرفتنِ مغز", HB.CODE_PREFIX.strip(), HB.CODE_MASK}                  # exact texts of the app (a test below compares each one)
NESTED = {"ایست انجام نشد؛ برنامه را باز کن و «ایست",                                  # two sentences of the app that hold a «quoted» word themselves:
          "برای خواندنِ کدِ پیامک، اندروید باید اجازهٔ «پیامک",                          # the simple scan above cuts them at the inner quote; the full
          "در پیامک‌های … دقیقهٔ اخیر کدِ یک‌بارمصرفی پیدا نکردم"}                        # texts are compared in `test_what_the_guide_quotes_...`
KNOWN = set(BODY_COMMANDS) | set(HALT_WORDS) | set(OTHER_COMMANDS) | LABELS | APP_SAYS | NESTED


class GuideSentencesTests(unittest.TestCase):
    def setUp(self):
        self.text = read(GUIDE)

    def test_every_quoted_phrase_has_a_known_role(self):
        unknown = [p for p in all_quoted(self.text) if p not in KNOWN]
        self.assertEqual(unknown, [], "the guide quotes a phrase this test does not know: say whether it is something to say, a label or something the "
                                      "app says, and put it in the matching table")

    def test_every_sentence_to_say_is_understood_as_the_command_the_guide_says(self):
        wrong = []
        for phrase, (kind, slots) in BODY_COMMANDS.items():
            command = classify(phrase)
            got = None if command is None else (command.kind, dict(command.slots))
            if got != (kind, slots):
                wrong.append((phrase, (kind, slots), got))
            self.assertIsNone(own(phrase), "the own brain must not take over «%s»" % phrase)
        for phrase in HALT_WORDS:
            if not HBC.is_halt(fa_text.words(nz.normalize(phrase))):
                wrong.append((phrase, "halt", None))
            self.assertIsNone(classify(phrase), "the body must not take over the emergency word «%s»" % phrase)
        self.assertTrue(HBC.is_resume(fa_text.words(nz.normalize("ادامه"))))
        self.assertEqual(own("مغز خودت را بگیر").kind, OC.GET)
        self.assertEqual(own("ادامه دانلود مغز").kind, OC.RESUME)
        self.assertEqual(wrong, [])

    def test_everything_the_tables_expect_is_still_in_the_guide(self):
        quoted = set(all_quoted(self.text))
        gone = sorted((set(BODY_COMMANDS) | set(HALT_WORDS) | set(OTHER_COMMANDS) | APP_SAYS | NESTED) - quoted)
        self.assertEqual(gone, [], "the test still checks phrases the guide no longer quotes")

    def test_every_command_of_the_commands_table_is_in_the_table(self):
        table = section_fa(self.text, 5)
        for phrase in set(BODY_COMMANDS) - {ONE_HOUR}:
            self.assertIn("«%s»" % phrase, table)
        self.assertIn("«%s»" % ONE_HOUR, section_fa(self.text, 10), "the longer window is offered where the user finds nothing")
        for asked in (HB.SELFTEST_ASK, HB.SELFTEST_COPY, HB.ACCESS_ASK, HB.OPEN_BATTERY, HB.OPEN_APP, HB.OPEN_NOTIFICATIONS, HB.SMS_ASK, HB.SMS_PERMISSION):
            self.assertIn("«%s»" % asked, table, "the app's own replies tell the user to say it")
        self.assertIn("«ایست» / «ادامه»", table)

    def test_what_the_guide_quotes_from_the_app_is_what_the_app_says(self):
        text = flat(self.text)
        strings = {}
        for name, value in re.findall(r'<string name="([^"]+)"[^>]*>(.*?)</string>', read(os.path.join(MAIN, "res", "values", "strings.xml")), re.S):
            strings[name] = value
        self.assertIn(strings["body_stop_failed"], text, "the notification's own sentence, word for word")
        self.assertIn("برای خواندنِ کدِ پیامک، اندروید باید اجازهٔ «پیامک» را بدهد و هنوز نداده", text)
        self.assertIn("برای خواندنِ کدِ پیامک، اندروید باید اجازهٔ «پیامک» را بدهد و هنوز نداده", flat(HB.sms_need_permission()))
        self.assertTrue(HB.sms_empty(BC.DEFAULT_MINUTES).startswith("در پیامک‌های %s دقیقهٔ اخیر کدِ یک‌بارمصرفی پیدا نکردم" % fa(BC.DEFAULT_MINUTES)))
        self.assertIn("در پیامک‌های … دقیقهٔ اخیر کدِ یک‌بارمصرفی پیدا نکردم", text)
        self.assertIn("«اجازهٔ تنظیماتِ محدودشده»", HB.sms_permission_shown())
        self.assertIn("«اجازهٔ تنظیماتِ محدودشده»", text)
        self.assertEqual(body.describe_ownbrain({"phase": "downloading", "bytes": 1, "total": 2, "percent": 50})[0], "در حال گرفتنِ مغز")
        self.assertIn("«%s»" % "در حال گرفتنِ مغز", text)
        self.assertTrue(HB.CODE_PREFIX.startswith("🔑 کدی که پیدا کردم:"))
        self.assertIn("«%s»" % HB.CODE_PREFIX, text, "the guide shows the start of the answer exactly, with the space the app puts before the code")
        self.assertIn("«%s»" % HB.CODE_MASK, text)

    def test_the_numbers_are_the_codes(self):
        text = flat(self.text)
        self.assertIn("%s دقیقهٔ اخیر" % fa(BC.DEFAULT_MINUTES), text)
        self.assertIn("تا %s دقیقه" % fa(BC.MAX_MINUTES), text)
        self.assertIn("%s پیامکِ تازه" % fa(door.LOOK_AT), text)
        self.assertIn("%s تا %s رقمی" % (fa(otp.MIN_DIGITS), fa(otp.MAX_DIGITS)), text)
        self.assertIn("تا %s مورد" % fa(selftest.MAX_ERRORS), text)
        self.assertIn("حدودِ شش ساعت در ۲۴ ساعت", text)
        self.assertIn("چند ثانیه بعد", text)

    def test_the_ten_sections_are_there_in_order(self):
        headings = re.findall(r"^## (\S+)\.", self.text, re.M)
        self.assertEqual(headings, [fa(n) for n in range(1, 11)])

    def test_the_status_of_every_feature_is_one_of_the_honest_labels(self):
        rows = [line for line in section_fa(self.text, 1).splitlines() if line.startswith("| ") and not line.startswith("| ---") and "قابلیت" not in line]
        self.assertEqual(len(rows), 10, "a feature was added or removed: change the table AND this count")
        for row in rows:
            status = row.split(" | ")[1]
            self.assertTrue(any(label in status for label in ("آزموده‌شده با دوبله", "آزموده نشده", "هنوز نیست")), row)
        for row in rows:
            if "همیشه‌روشن" in row or "ویندوز" in row:
                self.assertIn("**هنوز نیست**", row, "what is not built must say so")
            else:
                self.assertNotIn("**هنوز نیست**", row)

    def test_the_guide_says_what_was_not_tested(self):
        for needle in ("هیچ‌چیز از این بخش روی گوشیِ واقعی اجرا نشده", "آزموده نشده", "تضمین نیست", "HyperOS", "اندروید ۱۲", "اجازهٔ تنظیماتِ محدودشده",
                       "«ایست» برای جوابِ مدلِ محلی یک درخواست است", "ساخته نشده", "در گوشیِ انگلیسی‌زبان"):
            self.assertIn(needle, flat(self.text))

    def test_the_guide_never_promises_what_is_not_built(self):
        for line in self.text.splitlines():
            if any(word in line for word in ("هی جارویس", "نسخهٔ ویندوز", "همیشه‌روشن")):
                self.assertTrue(any(mark in line for mark in ("هنوز نیست", "ساخته نشده", "مرحلهٔ بعد", "ثبت شده")), line)

    def test_the_documents_point_at_each_other_and_the_older_ones_point_here(self):
        self.assertIn("docs/body_prompt959.md", self.text)
        self.assertIn("docs/own_brain_guide_fa_prompt959.md", self.text)
        self.assertIn("docs/body_guide_fa_prompt959.md", read(TECH))
        self.assertIn("docs/own_brain_prompt959.md", read(TECH))
        self.assertIn("body_prompt959.md", read(OWN_TECH))
        self.assertIn("docs/body_guide_fa_prompt959.md", read(OWN_GUIDE))

    def test_the_older_documents_no_longer_say_what_the_body_made_untrue(self):
        stale = {OWN_TECH: ("does not yet cancel a running answer", "it does **not** yet cancel an answer", "is a later piece of",
                            "the next piece: `body_prompt959.md`"),
                 OWN_GUIDE: ("«ایست» هنوز جوابِ در حالِ ساخته‌شدن را قطع نمی‌کند", "دانلود در پس‌زمینه هنوز نیست", "**هنوز** قطع نمی‌کند",
                             "مرحلهٔ بعدی، APK تازه"),
                 CLOUD_GUIDE: ("دکمهٔ توقفِ جدا از چت در مرحلهٔ بعد (بدنهٔ برنامه) می‌آید",),
                 BRAIN_V2: ("is part of the next stage (the body of the app)", "a message typed meanwhile is queued by the page")}
        for path, needles in stale.items():
            text = read(path)
            for needle in needles:
                self.assertNotIn(needle, text, "%s still says something the body made untrue" % os.path.basename(path))
            for pattern in (r"does\s+\*{0,2}not\*{0,2}\s+yet\s+cancel", r"\*{0,2}هنوز\*{0,2}\s+قطع\s+نمی"):
                self.assertIsNone(re.search(pattern, flat(text)), "%s: a reworded 'does not yet cancel' (%s)" % (os.path.basename(path), pattern))

    def test_no_older_document_calls_the_body_a_later_piece(self):
        # Prompt 959 (stage B): the body ships in the SAME package as these documents, so a line that names it may not call it "next" or "later"
        later = ("مرحلهٔ بعد", "next piece", "next stage", "later piece", "a later stage", "in a later", "بعداً می‌آید")
        checked = 0
        for path in (OWN_TECH, OWN_GUIDE, CLOUD_GUIDE, BRAIN_V2):
            for number, line in enumerate(read(path).splitlines(), 1):
                if "بدنه" in line or "the body" in line or "body_prompt959" in line:
                    checked += 1
                    for word in later:
                        self.assertNotIn(word, line, "%s:%d calls the body a later piece" % (os.path.basename(path), number))
        self.assertTrue(checked >= 5, "only %d lines name the body: is the scan broken?" % checked)
        for path in (OWN_GUIDE, CLOUD_GUIDE):
            self.assertIn("آزموده نشده", read(path))

    def test_the_page_button_row_says_where_it_was_run_and_where_it_was_not(self):
        rows = [line for line in section_fa(self.text, 1).splitlines() if line.startswith("| دکمهٔ قرمزِ")]
        self.assertEqual(len(rows), 1)
        status = rows[0].split(" | ")[1]
        self.assertIn("آزموده‌شده با دوبله", status)
        self.assertIn("در مرورگرِ واقعیِ کامپیوتر", status, "where it WAS run")
        self.assertIn("**روی گوشیِ واقعی آزموده نشده**", status, "where it was not")
        typed = [line for line in section_fa(self.text, 1).splitlines() if line.startswith("| نوشتنِ «ایست» در چت")]
        self.assertEqual(len(typed), 1)
        self.assertIn("وقتی جوابی در حال ساخته‌شدن نیست", typed[0], "the typed word is offered only where it can leave the page")

    def test_the_stop_section_names_three_ways_and_says_the_truth_about_each(self):
        raw = section_fa(self.text, 4)
        self.assertEqual(re.findall(r"(?m)^(\d+)\. ", raw), ["1", "2", "3"], "the guide names three ways: the page's red button, the typed word, the notification's button")
        section = flat(raw)
        first, second, third = (section.index(mark) for mark in ("1. **دکمهٔ قرمزِ «ایست» در صفحهٔ چت:**", "2. **نوشتنِ «ایست»**", "3. **دکمهٔ اعلان**"))
        self.assertTrue(first < second < third)
        for needle in ("«ارسال» قفل است", "Enter هم چیزی نمی‌فرستد", "متنی که نوشته‌ای در کادر می‌ماند", "به‌جای «ارسال» این دکمه می‌آید",
                       "یک بار زدنش کافی است؛ کلیدِ Enter هرگز آن را نمی‌زند", "وقتی جوابی در حال ساخته‌شدن نیست", "هر سه یک کار می‌کنند"):
            self.assertIn(needle, section)
        typed_way = section[second:third]
        for word in ("بایست", "توقف کن", "استاپ"):
            self.assertIn(word, typed_way, "the typed halt words are listed with the typed way")
        for word in ("حتی", "وسطِ"):
            self.assertNotIn(word, typed_way, "the typed word cannot leave the page while an answer is being made: it is not offered 'even mid-answer'")
        self.assertIn("درخواستِ** رهاکردنِ جواب", section, "the engine is asked, not commanded")

    def test_the_guide_does_not_say_what_the_page_made_untrue(self):
        text = flat(self.text)
        for pattern in (r"حتی\s+وقتی\s+برنامه\s+هنوز\s+دارد\s+جواب", r"حتی\s+وسطِ", r"پشتِ\s+آن\s+جواب\s+منتظر",
                        r"در\s+تاریخچه\s+ثبت\s+نمی", r"همیشه\s+کار\s+می‌کند", r"کادرِ?\s+پیام\s+قفل"):
            self.assertIsNone(re.search(pattern, text), "the guide still says something the stop button made untrue: %s" % pattern)
        self.assertIn("مثلِ هر پیامی در تاریخچه می‌ماند", text, "the stop exchange is kept in the history like any message")
        self.assertIn("خطِ آن جواب بعد از «ایست» می‌آید", text, "and in arrival order")
        self.assertIn("فقط در یک مرورگرِ کامپیوتر آزموده شده", text)

    def test_the_guide_says_the_install_step_is_left_alone_wherever_it_matters(self):
        rows = [line for line in section_fa(self.text, 1).splitlines() if line.startswith("| «ایست» وسطِ نصب و آزمایشِ اولِ مغز")]
        self.assertEqual(len(rows), 1)
        self.assertIn("**روی گوشیِ واقعی آزموده نشده**", rows[0].split(" | ")[1])
        four = flat(section_fa(self.text, 4))
        for needle in ("**یک استثنا: نصب و آزمایشِ اولِ مغز.**", "این مرحله را نمی‌شود وسطش قطع کرد", "«ایست» (از هر سه راه) موتور را دست نمی‌زند",
                       "اعلانِ نصب را برنمی‌دارد", "فقط مغزِ ابری را از درخواستِ تازه بازمی‌دارد", "اگر دکمهٔ اعلان را بزنی، اعلان می‌ماند"):
            self.assertIn(needle, four)
        self.assertIn("(وسطِ نصب و آزمایشِ اولِ مغز نه؛ بخش ۴)", flat(section_fa(self.text, 3)))
        self.assertIn("* **نصب و آزمایشِ اولِ مغز را نمی‌شود قطع کرد.**", section_fa(self.text, 9))
        self.assertIn("نصب را نمی‌شود قطع کرد و اعلان نرود", flat(section_fa(self.text, 8)))
        self.assertIn("نمی‌شود وسطش قطع کرد", BM.install_not_stoppable_note(), "the chat says the same sentence")

    def test_the_checklist_asks_for_the_red_button_during_a_long_local_answer(self):
        section = flat(section_fa(self.text, 8))
        numbers = re.findall(r"(?m)^(\d+)\. ", section_fa(self.text, 8))
        self.assertEqual(numbers, [str(n) for n in range(1, len(numbers) + 1)], "the steps must be numbered 1, 2, 3 ... without a gap")
        self.assertIn("دکمهٔ «ایست»ِ اعلان را امتحان کن", section)
        self.assertIn("دکمهٔ قرمزِ «ایست»", section, "the page's button has a step of its own")
        self.assertLess(section.index("دکمهٔ «ایست»ِ اعلان"), section.index("دکمهٔ قرمزِ «ایست»"))


# ====================================================================== the technical document
FILE_TOKEN = re.compile(r"^[A-Za-z0-9_./-]+\.(?:py|java|xml|md|gradle|js|html|css)$")
PINNED = ("android_entry.py", "core/core.py", "ael/interpreter.py", "runtime_integration/bridge.py", "interface/server.py",
          "runtime_integration/runtime_core.py", "runtime_growth/runtime_growth_cycle.py")
FIVE_JAVA = ("BodyService.java", "LiteRtLmBridge.java", "MainActivity.java", "PyAccessibilityService.java", "StopReceiver.java")
MANIFEST = os.path.join(MAIN, "AndroidManifest.xml")
STRINGS = os.path.join(MAIN, "res", "values", "strings.xml")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
TECH_COMMANDS = {                                   # the sentences the technical document quotes -> the command they must be
    "گزارش آزمایشی": (BC.SELFTEST, {"copy": False}),
    "چک‌لیست دسترسی‌ها": (BC.ACCESS, {}),
    "صفحهٔ باتری را باز کن": (BC.OPEN, {"target": "battery"}),
    "تنظیمات برنامه را باز کن": (BC.OPEN, {"target": "app"}),
    "تنظیمات اعلان را باز کن": (BC.OPEN, {"target": "notifications"}),
    "مجوز پیامک را بده": (BC.SMS_PERMISSION, {}),
    "کد پیامک را بخوان": (BC.SMS, {"minutes": BC.DEFAULT_MINUTES}),
}
NOT_COMMANDS = ("کد تأیید چیه؟", "رمز وای‌فای را بگو")  # a question and a general sentence: the document says they are never taken for the command
TECH_LABELS = {"هی جارویس", "کپی کن", "۵ دقیقه", "و N کارِ دیگر", "شروع خودکار", "بدون محدودیت", "Allow restricted settings",
               "کد", "رمز", "تایید", "یکبار مصرف", "بله", "ارسال"}                      # words, modifiers and the names of switches: nothing to classify here
TECH_NESTED = {"ایست انجام نشد؛ برنامه را باز کن و «ایست"}                      # the notification's sentence holds a «quoted» word itself (compared in full below)
TECH_KNOWN = set(TECH_COMMANDS) | set(HALT_WORDS) | set(NOT_COMMANDS) | TECH_LABELS | TECH_NESTED


def find_file(name):
    """Where a backticked file name lives in the checkout: a path is read from the python root, the repository or the app's main folder, a bare name is searched."""
    for base in (PY_ROOT, REPO, MAIN, JAVA_DIR, os.path.join(MAIN, "res", "values")):
        candidate = os.path.join(base, name)
        if os.path.exists(candidate):
            return candidate
    if "/" not in name:
        for folder, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "build", ".gradle")]
            if name in files:
                return os.path.join(folder, name)
    return None


def app_strings():
    found = {}
    for name, value in re.findall(r'<string name="([^"]+)"[^>]*>(.*?)</string>', read(STRINGS), re.S):
        found[name] = value
    return found


def body_modules():
    import importlib
    return [importlib.import_module(name) for name in (
        "brain_hub.body", "brain_hub.selftest", "brain_hub.service", "platform_boot", "native_bridge.body", "native_bridge.otp",
        "persian_brain.hub_body_commands", "persian_brain.hub_body", "persian_brain.hub_messages_body", "persian_brain.hub_hooks", "persian_brain.brain")]


def has_name(modules, token):
    """True when `token` is an attribute of one of the modules or of a class that one of them defines."""
    for module in modules:
        if hasattr(module, token):
            return True
        for value in vars(module).values():
            if inspect.isclass(value) and value.__module__ == module.__name__ and hasattr(value, token):
                return True
    return False


def python_object(head):
    """The module or class a dotted name starts with (`hub_body.scrub_codes` -> the module `persian_brain.hub_body`, `Body.emergency_stop` -> the class)."""
    import importlib
    for package in ("persian_brain", "brain_hub", "native_bridge", ""):
        try:
            return importlib.import_module("%s.%s" % (package, head) if package else head)
        except ImportError:
            continue
    for module in body_modules():
        if hasattr(module, head):
            return getattr(module, head)
    return None


NAMES_NOT_IN_CODE = {"ownbrain"}              # the job's own name, a plain word (the registry's use of it is tested in test_body_prompt959)
NOT_CODE_REFERENCES = {"android.jar"}         # a file of the Android SDK, not a name in this code


class TechDocTests(unittest.TestCase):
    def setUp(self):
        self.text = read(TECH)
        self.flat = flat(self.text)

    # ---------------------------------------------------------------- shape
    def test_the_ten_sections_are_there_in_order(self):
        self.assertEqual(re.findall(r"^## (\d+)\.", self.text, re.M), [str(n) for n in range(1, 11)])

    def test_the_first_lines_say_what_was_never_run(self):
        head = flat(self.text[:900])
        for needle in ("built and tested with stand-ins - never run on a phone", "REAL `android.jar`", "listed in section 8"):
            self.assertIn(needle, head)

    def test_every_file_it_names_exists(self):
        missing = []
        for token in re.findall(r"`([^`\n]+)`", self.text):
            if FILE_TOKEN.match(token) and find_file(token) is None:
                missing.append(token)
            elif token.endswith("/") and not (os.path.isdir(os.path.join(PY_ROOT, token)) or os.path.isdir(os.path.join(REPO, token))):
                missing.append(token)
        self.assertEqual(missing, [])

    def test_the_two_documents_and_the_piece_before_are_linked(self):
        self.assertIn("`docs/body_guide_fa_prompt959.md`", self.text)
        self.assertIn("`docs/own_brain_prompt959.md`", self.text)
        self.assertTrue(os.path.isfile(GUIDE) and os.path.isfile(OWN_TECH))

    # ---------------------------------------------------------------- the parts
    def test_the_parts_table_names_every_module_of_the_body(self):
        table = section_en(self.text, 3)
        for name in ("brain_hub/body.py", "brain_hub/selftest.py", "brain_hub/service.py", "platform_boot.py", "native_bridge/body.py", "native_bridge/otp.py",
                     "persian_brain/hub_body_commands.py", "persian_brain/hub_body.py", "persian_brain/hub_messages_body.py", "persian_brain/hub_hooks.py",
                     "persian_brain/brain.py", "BodyService.java", "StopReceiver.java", "LiteRtLmBridge.java", "MainActivity.java", "AndroidManifest.xml",
                     "strings.xml"):
            self.assertIn("`%s`" % name, table)
            self.assertIsNotNone(find_file(name), name)
        on_disk = set()
        for folder in ("brain_hub", "native_bridge", "persian_brain"):
            for name in os.listdir(os.path.join(PY_ROOT, folder)):
                if name.endswith(".py") and ("body" in name or name in ("selftest.py", "otp.py")):
                    on_disk.add("%s/%s" % (folder, name))
        self.assertTrue(len(on_disk) >= 7, on_disk)
        for rel in sorted(on_disk):
            self.assertIn("`%s`" % rel, table, "a module of the body that the table does not name")

    def test_the_names_the_document_uses_exist_in_the_code(self):
        names = {"Body": (body, "Body"), "MAX_JOBS": (body, "MAX_JOBS"), "emergency_stop_all": (body, "emergency_stop_all"),
                 "describe_ownbrain": (body, "describe_ownbrain"), "on_ownbrain": (body.Body, "on_ownbrain"), "_sync": (body.Body, "_sync"),
                 "collect": (selftest, "collect"), "quick": (selftest, "quick"), "live_hubs": (service, "live_hubs"),
                 "emergency_stop": (platform_boot, "emergency_stop"), "BodyDoor": (door, "BodyDoor"), "PhoneDoor": (door, "PhoneDoor"),
                 "SmsDoor": (door, "SmsDoor"), "latest_code": (door.SmsDoor, "latest_code"), "extract_code": (otp, "extract_code"),
                 "redact": (otp, "redact"), "scrub_codes": (hub_body, "scrub_codes"), "tick": (hub_body, "tick"), "SCRUB_KEY": (hub_body, "SCRUB_KEY"),
                 "after_emergency": (hub_body, "after_emergency"), "stop_while_busy": (hub_body, "stop_while_busy"),
                 "emergency_while_busy": (hub_hooks, "emergency_while_busy")}
        for name, (owner, attribute) in names.items():
            self.assertTrue(hasattr(owner, attribute), name)
            self.assertIn(name, self.text, "the test expects the document to name %s" % name)
        for method in ("hold", "release", "running"):
            self.assertTrue(hasattr(door.BodyDoor, method), method)
        self.assertIn("def cancel_model_generation(self)", read(os.path.join(PY_ROOT, "brain_hub", "builtin_tools.py")))
        self.assertIn("`hub.cancel_model_generation()`", self.text)

    def test_the_java_layer_is_the_five_thin_files(self):
        self.assertEqual(sorted(n for n in os.listdir(JAVA_DIR) if n.endswith(".java")), sorted(FIVE_JAVA))
        self.assertIn("five files now (%s)" % ", ".join("`%s`" % n for n in sorted(FIVE_JAVA)), self.flat)

    def test_the_java_surface_is_what_the_document_says(self):
        service_java = read(os.path.join(JAVA_DIR, "BodyService.java"))
        for name in ("hold", "release", "isRunning"):
            self.assertRegex(service_java, r"public static \w+ %s\(" % name)
        self.assertIn("stopFromNotification", service_java)
        receiver = read(os.path.join(JAVA_DIR, "StopReceiver.java"))
        for needle in ("goAsync", "new Thread", "stopFromNotification"):
            self.assertIn(needle, receiver)
        self.assertRegex(read(os.path.join(JAVA_DIR, "LiteRtLmBridge.java")), r"void cancel\(")
        self.assertIn('"%s"' % door.FEATURE_SERVICE, read(os.path.join(JAVA_DIR, "MainActivity.java")))
        self.assertEqual(door.FEATURE_SERVICE, "body_service")
        self.assertIn("`body_service`", self.text)

    def test_every_dotted_name_in_the_document_resolves(self):
        unresolved = []
        checked = 0
        for token in sorted(set(re.findall(r"`([^`\s]+)`", self.text))):
            match = re.match(r"^([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?:\(\))?$", token)
            if not match or FILE_TOKEN.match(token) or token in NOT_CODE_REFERENCES:
                continue
            head, tail = match.groups()
            checked += 1
            if os.path.isfile(os.path.join(JAVA_DIR, head + ".java")):
                ok = tail in read(os.path.join(JAVA_DIR, head + ".java"))
            elif head == "hub":                                              # a hub object: the method is defined by the tool layer
                ok = ("def %s(self)" % tail) in read(os.path.join(PY_ROOT, "brain_hub", "builtin_tools.py"))
            else:
                owner = python_object(head)
                ok = owner is not None and (hasattr(owner, tail) or has_name([owner], tail))
            if not ok:
                unresolved.append(token)
        self.assertTrue(checked >= 15, "the check found only %d dotted names: is the pattern broken?" % checked)
        self.assertEqual(unresolved, [])

    def test_every_name_in_the_parts_table_is_real(self):
        rows = [line for line in section_en(self.text, 3).splitlines() if line.startswith("| ") and not line.startswith("| ---") and "Layer" not in line]
        self.assertEqual(len(rows), 16, "a part was added or removed: change the table AND this count")
        modules = body_modules()
        unresolved = []
        checked = 0
        for row in rows:
            cells = [cell.strip() for cell in row.strip().strip("|").split(" | ")]
            layer, files, what = cells[0], re.findall(r"`([^`]+)`", cells[1]), cells[2]
            sources = ""
            if layer != "Python":
                sources = "".join(read(find_file(rel)) for rel in files)
            for token in re.findall(r"`([^`]+)`", what):
                if re.search(r"[\s={}\"]", token) or "." in token:         # a value, a literal or a dotted name (the test above)
                    continue
                token = token.replace("()", "")
                checked += 1
                if layer == "Python":
                    ok = has_name(modules, token) or os.path.isfile(os.path.join(JAVA_DIR, token + ".java")) or token in NAMES_NOT_IN_CODE
                else:
                    ok = token in sources
                if not ok:
                    unresolved.append((files, token))
        self.assertTrue(checked >= 30, "the check found only %d names: is the pattern broken?" % checked)
        self.assertEqual(unresolved, [])

    # ---------------------------------------------------------------- numbers
    def test_the_numbers_are_the_codes(self):
        expected = ["`MAX_JOBS = %d`" % body.MAX_JOBS, "`MIN_GAP_SECONDS = %s`" % body.MIN_GAP_SECONDS, "every %s seconds" % body.MIN_GAP_SECONDS,
                    "a title of at most %d characters, a text of at most %d, a percent from -1 to 100" % (door.MAX_TITLE, door.MAX_TEXT),
                    "`MAX_EMERGENCY_CHARS = %d`" % hub_hooks.MAX_EMERGENCY_CHARS,
                    "`SCRUB_DELAYS = (%s, %s)`" % tuple(hub_body.SCRUB_DELAYS),
                    "`DEFAULT_MINUTES = %d`" % BC.DEFAULT_MINUTES, "`MAX_MINUTES = %d`" % BC.MAX_MINUTES, "`LOOK_AT = %d`" % door.LOOK_AT,
                    "`MIN_DIGITS = %d`" % otp.MIN_DIGITS, "`MAX_DIGITS = %d`" % otp.MAX_DIGITS,
                    "`MAX_ERRORS = %d`" % selftest.MAX_ERRORS, "`MAX_API_CHARS = %d`" % selftest.MAX_API_CHARS]
        for needle in expected:
            self.assertIn(needle, self.flat)
        self.assertIn("-1 <= percent <= 100", inspect.getsource(door.BodyDoor.hold))
        self.assertEqual(hub_body.SCRUB_DELAYS[0], 4.0)
        self.assertIn("at most about four seconds", self.flat)
        self.assertEqual(len(selftest.SECTIONS), 9)
        self.assertIn("has nine sections", self.flat)
        self.assertIn("`SECTIONS = (%s)`" % ", ".join('"%s"' % name for name in selftest.SECTIONS), self.flat)

    def test_the_model_sizes_are_the_catalogs(self):
        self.assertEqual(round(catalog.LIGHT_CHOICE.size_hint / 1e9), 1)
        self.assertEqual(round(catalog.STRONG_CHOICE.size_hint / 1e9, 1), 2.6)
        self.assertIn("a 1-2.6 GB model", self.flat)

    def test_the_java_timings_of_the_repeated_stop_are_the_documented_ones(self):
        source = read(os.path.join(JAVA_DIR, "LiteRtLmBridge.java"))
        repeat = int(re.search(r"CANCEL_REPEAT_MS\s*=\s*(\d+)L?", source).group(1))
        give_up = int(re.search(r"CANCEL_GIVE_UP_MS\s*=\s*(\d+)L?", source).group(1))
        self.assertEqual(give_up % 1000, 0)
        self.assertIn("every %d ms (`CANCEL_REPEAT_MS`)" % repeat, self.flat)
        self.assertIn("at most %d seconds (`CANCEL_GIVE_UP_MS`)" % (give_up // 1000), self.flat)

    # ---------------------------------------------------------------- the rules
    def test_every_name_in_the_kept_by_column_is_real(self):
        rows = [line for line in section_en(self.text, 2).splitlines() if re.match(r"\| \d+ \|", line)]
        self.assertEqual(len(rows), 11)
        service_tests = read(os.path.join(TESTS, "test_body_service_prompt959.py"))
        objects = {"Body": body.Body, "hub_body": hub_body, "SmsDoor": door.SmsDoor}
        for row in rows:
            cells = [cell.strip() for cell in row.strip().strip("|").split(" | ")]
            names = re.findall(r"`([^`]+)`", cells[-1])
            self.assertTrue(names, row)
            for name in names:
                if FILE_TOKEN.match(name):
                    self.assertIsNotNone(find_file(name), name)
                elif name.endswith("Tests"):
                    self.assertRegex(service_tests, r"(?m)^class %s\(" % name)
                else:
                    head, _, tail = name.partition(".")
                    self.assertIn(head, objects, name)
                    if tail:
                        self.assertTrue(hasattr(objects[head], tail), name)

    def test_the_manifest_has_what_the_document_says(self):
        manifest = read(MANIFEST)
        for permission in ("FOREGROUND_SERVICE_DATA_SYNC", "READ_SMS"):
            self.assertIn("`%s`" % permission, self.text)
            self.assertIn('android.permission.%s"' % permission, manifest)
        root = ET.fromstring(manifest)
        services = [e for e in root.iter("service") if (e.get(ANDROID_NS + "name") or "").endswith("BodyService")]
        receivers = [e for e in root.iter("receiver") if (e.get(ANDROID_NS + "name") or "").endswith("StopReceiver")]
        self.assertEqual((len(services), len(receivers)), (1, 1))
        self.assertEqual(services[0].get(ANDROID_NS + "foregroundServiceType"), "dataSync")
        self.assertEqual(services[0].get(ANDROID_NS + "exported"), "false")
        self.assertEqual(receivers[0].get(ANDROID_NS + "exported"), "false")
        self.assertIn("the service (type `dataSync`, not exported), the receiver (not exported)", self.flat)
        types = [e.get(ANDROID_NS + "foregroundServiceType") for e in root.iter("service") if e.get(ANDROID_NS + "foregroundServiceType")]
        self.assertEqual(types, ["dataSync"], "the document says there is no microphone service")

    def test_the_six_strings_and_the_button_word_are_the_apps(self):
        strings = app_strings()
        names = re.findall(r'<string name="(body_[a-z_]+)"', read(STRINGS))
        self.assertEqual(len(names), 6)
        self.assertIn("six strings", self.flat)
        self.assertEqual(strings["body_stop"], "ایست")
        self.assertIn(strings["body_stop_failed"], self.flat)

    def test_what_is_not_built_is_not_in_the_code(self):
        manifest = read(MANIFEST)
        for needle in ("WAKE_LOCK", "RECORD_AUDIO", "REQUEST_INSTALL_PACKAGES", "SYSTEM_ALERT_WINDOW"):
            self.assertNotIn(needle, manifest)
        for name in os.listdir(JAVA_DIR):
            if name.endswith(".java"):
                self.assertNotIn("WakeLock", read(os.path.join(JAVA_DIR, name)), name)
        self.assertIn("**Not built:** an always-on service, a microphone service («هی جارویس»), any wake lock, in-app updates, the Windows body.", self.flat)

    # ---------------------------------------------------------------- «ایست»
    def test_the_ways_in_are_four_and_the_chat_words_are_halt_words(self):
        table = section_en(self.text, 5).split("`Body.emergency_stop` stops")[0]
        rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| ---") and "Way in" not in line]
        self.assertEqual(len(rows), 4, "a way in was added or removed: change the table, the guide AND this count")
        for word in HALT_WORDS:
            self.assertIn("«%s»" % word, rows[0])
            self.assertTrue(HBC.is_halt(fa_text.words(nz.normalize(word))), word)
        self.assertIn("`MAX_EMERGENCY_CHARS = %d`" % hub_hooks.MAX_EMERGENCY_CHARS, rows[1])
        for name in ("hub_hooks.early", "hub_brain.early", "hub_body.after_emergency", "Body.emergency_stop"):
            self.assertIn("`%s`" % name, rows[0])
        for name in ("requestStop", "interface/static/app.js", "/api/message"):                       # the button of the chat page
            self.assertIn("`%s`" % name, rows[2])
        for name in ("StopReceiver", "BodyService.stopFromNotification", "platform_boot.emergency_stop", "emergency_stop_all"):
            self.assertIn("`%s`" % name, rows[3])

    def test_the_stop_goes_download_engine_cloud_and_releases_last(self):
        section = section_en(self.text, 5)
        order = re.findall(r"^\* \*\*(\w+)\*\*", section, re.M)
        self.assertEqual(order, ["download", "engine", "cloud"])
        source = inspect.getsource(body.Body.emergency_stop)
        positions = [source.index('"%s"' % name) for name in order]
        self.assertEqual(positions, sorted(positions), "the stop does not run in the order the document names")
        self.assertIn("and then releases the service last", self.flat)

    def test_the_json_the_notification_gets_has_the_documented_keys(self):
        with unittest.mock.patch.object(body, "emergency_stop_all", return_value={"hubs": 2, "stopped": ["download"], "released": True}):
            answer = json.loads(platform_boot.emergency_stop())
        self.assertEqual(answer, {"ok": True, "hubs": 2, "stopped": ["download"], "released": True})
        fallback = '{"ok":true,"hubs":0,"stopped":[],"released":false}'
        self.assertEqual(sorted(json.loads(fallback)), sorted(answer))
        self.assertIn("`%s`" % fallback, self.text)
        self.assertIn(fallback, read(os.path.join(JAVA_DIR, "BodyService.java")).replace('\\"', '"'))
        self.assertIn('{"ok", "hubs", "stopped", "released"}', self.text)

    def test_the_senders_of_the_stop_word_are_not_taken_for_body_commands(self):
        for word in HALT_WORDS:
            self.assertIsNone(classify(word), word)

    # ---------------------------------------------------------------- what is said
    def test_every_quoted_phrase_has_a_known_role(self):
        unknown = [p for p in all_quoted(self.text) if p not in TECH_KNOWN]
        self.assertEqual(unknown, [], "a quoted phrase the test does not know: say whether it is a command, a label or the app's own text")
        gone = sorted(TECH_KNOWN - set(all_quoted(self.text)))
        self.assertEqual(gone, [], "the test still expects phrases the document no longer quotes")

    def test_every_sentence_quoted_is_the_command_the_document_says(self):
        for phrase, (kind, slots) in TECH_COMMANDS.items():
            command = classify(phrase)
            self.assertIsNotNone(command, phrase)
            self.assertEqual((command.kind, dict(command.slots)), (kind, slots), phrase)
        for phrase in NOT_COMMANDS:
            self.assertIsNone(classify(phrase), "the document says «%s» is never taken for the command" % phrase)
        self.assertEqual(OC.confirm_word(fa_text.words(nz.normalize("بله"))), "confirm")
        self.assertEqual(classify("کد پیامک ۵ دقیقه را بخوان").slots["minutes"], 5)

    def test_the_keywords_of_the_code_rule_find_a_code(self):
        listed = re.search(r"with a keyword \(([^)]*)\)", flat(section_en(self.text, 7))).group(1)
        persian = re.findall(r"«([^»]+)»", listed)
        self.assertEqual(persian, ["کد", "رمز", "تایید", "یکبار مصرف"])
        for word in persian + ["code", "otp"]:
            self.assertEqual(str(otp.extract_code("%s: 482913" % word)), "482913", word)
        for needle in ("`%s`" % HB.CODE_MASK, "`%s`" % HB.SENDER_MASK, "`%s`" % HB.CODE_PREFIX):
            self.assertIn(needle, self.text)
        self.assertIn("`<path>`", self.text)
        self.assertIn("<path>", inspect.getsource(selftest))
        self.assertIn("کارِ دیگر", inspect.getsource(body))

    # ---------------------------------------------------------------- honesty and pins
    def test_the_limits_are_written_down(self):
        for needle in ("Nothing here ran on a phone", "never run on a phone", "`not_allowed`", "about six hours in 24 hours", "this app targets 34",
                       "was not checked on a device", "Allow restricted settings", "does not recall one that is on its way", "The masking has a window",
                       "stored like any message, in arrival order", "HyperOS may still close the app", "The stop of a local answer is a request", "was exercised against a stand-in",
                       "A button that cannot reach Python says so", "this was not observed here"):
            self.assertIn(needle, self.flat)

    def test_the_install_exception_is_written_down(self):
        for needle in ("**One step is left alone: the install.**", "`_installing(brain)`, read AFTER the halt", '`{"stopped": [...], "released": False, "busy": True}`',
                       "the key `busy` is there only then", "The cloud brain is still halted.", '`emergency_stop_all` adds `"busy": True`',
                       '`platform_boot.emergency_stop()` then answers `"ok": false`', "**The install cannot be stopped.**",
                       "(never while the own brain installs, see below)"):
            self.assertIn(needle, self.flat)

    def test_the_document_does_not_say_what_the_page_button_made_untrue(self):
        for pattern in (r"is\s+not\s+logged", r"not\s+(?:stored|logged|recorded)\s+in\s+the\s+(?:chat\s+)?history", r"disables\s+«ارسال»\s+and\s+the\s+message\s+box",
                        r"message\s+box\s+(?:is|are)\s+disabled", r"chat\s+word\s+typed\s+while\s+another\s+answer",
                        r"stop\s+(?:control|button)[^.]{0,80}(?:next|later)\s+(?:stage|piece)"):
            self.assertIsNone(re.search(pattern, self.flat), "the document still says something the stop button made untrue: %s" % pattern)
        self.assertIn("The stop exchange is stored like any message, in arrival order.", self.flat)
        self.assertIn("so they stand BEFORE the line of the answer that was cut (a test pins the order)", self.flat)

    def test_section_nine_names_the_seven_pinned_files_and_the_version_lines(self):
        section = section_en(self.text, 9)
        self.assertIn("seven pinned production files", section)
        for rel in PINNED:
            self.assertIn("`%s`" % rel, section)
            self.assertTrue(os.path.isfile(os.path.join(PY_ROOT, rel)), rel)
        gradle = read(os.path.join(REPO, "app", "build.gradle"))
        self.assertRegex(gradle, r'(?m)^\s*versionCode 2\s*$')
        self.assertRegex(gradle, r'(?m)^\s*versionName "0\.2\.0"\s*$')
        self.assertIn('`versionCode 2` and `versionName "0.2.0"`', section)

    def test_the_test_table_names_every_test_file_of_the_body(self):
        section = section_en(self.text, 10)
        named = set(re.findall(r"`tests/([A-Za-z0-9_]+\.(?:py|js))`", section))
        on_disk = {n for n in os.listdir(TESTS) if n.endswith((".py", ".js"))
                   and re.match(r"(test_body_|test_selftest_|test_docs_body|body_support|test_stop_button_|browser_stop_driver_)", n)}
        on_disk.add("test_litertlm_bridge_jvm_prompt959.py")
        self.assertEqual(named, on_disk)
        stubs = sorted(os.listdir(os.path.join(TESTS, "jvm_stub_body")))
        self.assertEqual(stubs, ["BodyServiceMain.java", "PyObject.java", "Python.java"])
        for name in stubs:
            self.assertIn("`%s`" % name, section)
        self.assertIn("`tests/jvm_stub_body/`", section)
        service_tests = read(os.path.join(TESTS, "test_body_service_prompt959.py"))
        for needle in ("ANDROID_JAR", "ANDROID_HOME", "ANDROID_SDK_ROOT", "android-34"):
            self.assertIn(needle, service_tests)
            self.assertIn(needle, section)


# ====================================================================== the step the stop leaves alone, against the code
class InstallStepDocTests(unittest.TestCase):
    """What the documents say about the install step (the stop leaves it alone), held against the code. The behaviour is run in
    test_body_prompt959 and in test_body_chat_prompt959 (a real chat on a held first test question)."""

    def test_the_step_the_documents_call_the_install_is_the_phase_the_stop_looks_at(self):
        self.assertIn('"installing"', inspect.getsource(body._installing))
        own = read(os.path.join(PY_ROOT, "brain_hub", "ownbrain.py"))
        self.assertGreaterEqual(own.count('phase="installing"'), 3, "the own brain no longer says 'installing': the stop looks at a phase that never comes")

    def test_the_order_the_document_promises_is_the_order_in_the_code(self):
        emergency = inspect.getsource(body.Body.emergency_stop)
        self.assertLess(emergency.index("brain.halt()"), emergency.index("_installing(brain)"), "the phase is read AFTER the halt")
        self.assertIn("if not installing:", emergency, "the engine is asked only outside the install")
        early_return = 'return {"stopped": stopped, "released": False, "busy": True}'
        self.assertIn(early_return, emergency)
        self.assertLess(emergency.index("_halt_cloud(hub)"), emergency.index(early_return), "the cloud brain is still halted during the install")
        self.assertLess(emergency.index(early_return), emergency.index("self._jobs.clear()"), "the install keeps its job: the early return comes before the jobs are cleared")

    def test_the_notification_button_says_no_with_the_same_four_keys(self):
        with unittest.mock.patch("brain_hub.body.emergency_stop_all", return_value={"hubs": 1, "stopped": [], "released": False, "busy": True}):
            answer = json.loads(platform_boot.emergency_stop())
        self.assertEqual(sorted(answer), ["hubs", "ok", "released", "stopped"], "the keys are the same as ever: busy never travels to Java")
        self.assertIs(answer["ok"], False)

    def test_java_keeps_the_notification_and_says_so_when_python_says_no(self):
        java = read(os.path.join(PY_ROOT, "..", "java", "com", "erfan", "standaloneai", "BodyService.java"))
        self.assertRegex(flat(java), r"isOk\(answer\)\) \{ release\(app\); \} else \{ postIfRunning\(app, app\.getString\(R\.string\.body_stop_failed\)\);")


# ====================================================================== the chat page's stop button, against what the documents say
STATIC = os.path.join(PY_ROOT, "interface", "static")


def function_body(js, name):
    """The text of `function name(...) { ... }` up to its closing brace (the page's functions are flat and their braces balance)."""
    start = js.index("function %s(" % name)
    depth, index = 0, js.index("{", start)
    for position in range(index, len(js)):
        if js[position] == "{":
            depth += 1
        elif js[position] == "}":
            depth -= 1
            if depth == 0:
                return js[start:position + 1]
    raise AssertionError("function %s is not closed" % name)


class PageStopButtonDocTests(unittest.TestCase):
    """The sentences the documents say about the page's stop button, held against the page itself. What the button DOES is run (in a real
    browser too) by test_stop_button_prompt959; here only the documents are compared with the code, so that neither can drift on its own."""

    def setUp(self):
        self.tech = flat(read(TECH))
        self.guide = flat(read(GUIDE))
        self.js = read(os.path.join(STATIC, "app.js"))
        self.css = read(os.path.join(STATIC, "style.css"))
        self.html = read(os.path.join(STATIC, "index.html"))
        self.i18n = read(os.path.join(STATIC, "i18n.js"))

    def test_the_two_labels_the_documents_quote_are_the_pages_own(self):
        self.assertRegex(self.i18n, r'(?m)^\s*send:\s*"ارسال",')
        self.assertRegex(self.i18n, r'(?m)^\s*stop:\s*"ایست",')
        self.assertRegex(self.html, r'<button\b[^>]*\bid="send-btn"[^>]*>ارسال</button>')
        self.assertRegex(self.html, r'<button\b[^>]*\bid="stop-btn"[^>]*>ایست</button>')
        self.assertTrue(HBC.is_halt(fa_text.words(nz.normalize("ایست"))), "the word of the button is not a halt word")
        self.assertIn("(which the brain takes for a halt word; a test pins it)", self.tech)
        self.assertIn("def test_the_word_the_button_sends_is_a_halt_word_of_the_brain(", read(os.path.join(TESTS, "test_stop_button_prompt959.py")))

    def test_the_page_sends_nothing_while_busy_but_the_message_box_stays_editable(self):
        self.assertIn("sendBtn.disabled = value;", function_body(self.js, "setBusy"))
        for forbidden in ("inputEl.disabled", "inputEl.readOnly", 'inputEl.setAttribute("disabled"', 'inputEl.setAttribute("readonly"'):
            self.assertNotIn(forbidden, self.js, "the message box is locked now: the documents say it stays editable")
        submit = function_body(self.js, "submit")
        self.assertIn("if (!text || busy) return;", submit)
        self.assertLess(submit.index("busy) return"), submit.index('inputEl.value = ""'), "the typed text must stay in the box when nothing is sent")
        self.assertIn("if (busy) return;", function_body(self.js, "sendMessage"))
        self.assertRegex(self.js, r'inputEl\.addEventListener\("keydown",[^}]*\bsubmit\(\);')
        for needle in ("`if (busy) return`", "«ارسال» is disabled, Enter does nothing, what the user typed stays in the message box"):
            self.assertIn(needle, self.tech)
        for needle in ("«ارسال» قفل است", "Enter هم چیزی نمی‌فرستد", "متنی که نوشته‌ای در کادر می‌ماند"):
            self.assertIn(needle, self.guide)
        for text in (self.tech, self.guide, flat(read(BRAIN_V2))):
            for pattern in (r"ارسال»\s+and\s+the\s+message\s+box", r"message\s+box\s+(?:is|are)\s+disabled", r"کادرِ?\s+پیام\s+قفل"):
                self.assertIsNone(re.search(pattern, text), "a document says the message box is locked: %s" % pattern)

    def test_the_swap_with_the_send_button_is_a_css_rule_on_the_forms_aria_busy(self):
        self.assertRegex(self.css, r'\.composer\[aria-busy="true"\]\s+\.send-btn\s*\{\s*display:\s*none;\s*\}')
        self.assertIn('formEl.setAttribute("aria-busy", value ? "true" : "false");', function_body(self.js, "setBusy"))
        self.assertRegex(self.html, r'<form\b(?=[^>]*\bid="input-form")(?=[^>]*\bclass="[^"]*\bcomposer\b)[^>]*>')
        self.assertIn("a rule of `style.css` on the form's `aria-busy`", self.tech)

    def test_the_button_uses_the_one_existing_route_once_per_answer_and_only_a_click_presses_it(self):
        body = function_body(self.js, "requestStop")
        self.assertIn('fetch("/api/message"', body)
        self.assertIn("JSON.stringify({ text: S.stop })", body)
        self.assertIn("if (!busy || stopping) return;", body)
        self.assertIn("stopBtn.disabled = true;", body)
        self.assertIn("stopping = true;", body)
        self.assertIn("stopping = false;", function_body(self.js, "setBusy"), "a new answer must be stoppable again")
        self.assertEqual(self.js.count("requestStop"), 2, "the function and its one click listener: nothing else (Enter, a timer) may press it")
        self.assertIn('stopBtn.addEventListener("click", requestStop)', self.js)
        self.assertIn('if path == "/api/message":', read(os.path.join(PY_ROOT, "interface", "server.py")))
        for needle in ("`requestStop` in `interface/static/app.js` posts «ایست» to the existing `/api/message` on a request of its own",
                       "once per answer (the button disables itself and a flag guards it)", "Enter never presses it"):
            self.assertIn(needle, self.tech)
        self.assertIn("یک بار زدنش کافی است؛ کلیدِ Enter هرگز آن را نمی‌زند", self.guide)

    def test_the_page_part_of_the_parts_table_names_four_files_that_exist(self):
        rows = [line for line in section_en(read(TECH), 3).splitlines() if line.startswith("| Page |")]
        self.assertEqual(len(rows), 1)
        files = re.findall(r"`([^`]+)`", rows[0].split(" | ")[1])
        self.assertEqual(sorted(files), ["app.js", "i18n.js", "index.html", "style.css"])
        for name in files:
            self.assertTrue(os.path.isfile(os.path.join(STATIC, name)), name)
        self.assertIn("`requestStop`", rows[0])
        self.assertIn("the word `stop`", rows[0])

    def test_the_documents_say_where_the_browser_run_is_skipped_and_that_no_phone_ran_it(self):
        self.assertIn("skipped where Node's Playwright is missing", self.tech)
        self.assertIn("and never on a phone", self.tech)
        source = read(os.path.join(TESTS, "test_stop_button_prompt959.py"))
        self.assertIn("self.skipTest(", source)
        self.assertIn("Node's Playwright is not installed", source)
        self.assertIn("the GitHub test job has no Playwright", flat(source))
        self.assertTrue(os.path.isfile(os.path.join(TESTS, "browser_stop_driver_prompt959.js")))
        self.assertIn("**روی گوشیِ واقعی آزموده نشده**", self.guide)


if __name__ == "__main__":
    unittest.main()
