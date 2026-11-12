"""
Prompt 959 (stage A) - the two documents about the cloud brain must stay true.

  docs/brain_v2_prompt959.md             the technical document: modules, the rule of every request, the own-brain teacher flow
  docs/cloud_brain_guide_fa_prompt959.md the Persian user guide: every sentence it tells the user to say is run through the REAL
                                          classifiers (a hint that does not work is a bug), and the numbers it states are the code's

If the code changes and a document is not updated, a test here fails instead of the document quietly lying to the user.
"""
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v2 import history, learned, providers
from brain_v2.service import MAX_CALLS_PER_HOUR
from persian_brain import hub_brain_commands as BC
from persian_brain import hub_intents as HI
from persian_brain import normalization as nz
from self_builder import fa_text

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", "..", "docs"))
TECH = os.path.join(DOCS, "brain_v2_prompt959.md")
GUIDE = os.path.join(DOCS, "cloud_brain_guide_fa_prompt959.md")
DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(number):
    return str(number).translate(DIGITS)


def read(path):
    if not os.path.isfile(path):
        raise unittest.SkipTest("the documentation is not part of this checkout layout")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def quoted(text):
    """Every «…» phrase of `text` that is a complete sentence (a phrase with «…» in it is a template, not something to type)."""
    found = []
    for match in re.finditer(r"«([^»]+)»", text):
        phrase = match.group(1).strip()
        if "…" not in phrase and "<" not in phrase and phrase not in found:
            found.append(phrase)
    return found


def understood(phrase):
    norm = nz.normalize(phrase)
    toks = fa_text.words(norm)
    return bool(HI.classify(phrase, norm, toks, named_pack=True) or BC.classify(phrase, norm, toks) or BC.is_halt(toks) or BC.is_resume(toks))


def section(text, number):
    match = re.search(r"^## %s\..*?(?=^## |\Z)" % re.escape(str(number).translate(DIGITS)), text, re.S | re.M)
    return match.group(0) if match else ""


class TechnicalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.text = read(TECH)

    def test_every_module_of_the_new_packages_is_named(self):
        for name in sorted(os.listdir(os.path.join(PY_ROOT, "brain_v2"))):
            if name.endswith(".py"):
                self.assertIn("`%s`" % name, self.text, "brain_v2/%s is not in the technical document" % name)
        for name in ("post.py", "hub_brain.py", "hub_brain_commands.py", "hub_messages_brain.py"):
            self.assertIn("`%s`" % name, self.text)

    def test_the_numbers_are_the_codes(self):
        self.assertIn("hourly cap (%d)" % MAX_CALLS_PER_HOUR, self.text)
        self.assertIn("at most %d answers" % learned.MAX_ITEMS, self.text)
        self.assertIn("last %d exchanges, %d hours" % (history.MAX_TURNS, history.TTL_SECONDS // 3600), self.text)

    def test_the_files_it_names_are_the_real_file_names(self):
        from brain_v2 import keyvault, settings
        for name in (settings.FILE_NAME, keyvault.FILE_NAME, history.FILE_NAME, learned.FILE_NAME):
            self.assertIn("`%s`" % name, self.text)

    def test_the_seven_pinned_files_are_named_as_unchanged(self):
        for name in ("android_entry.py", "core/core.py", "ael/interpreter.py", "runtime_integration/bridge.py", "interface/server.py",
                     "runtime_integration/runtime_core.py", "runtime_growth/runtime_growth_cycle.py"):
            self.assertIn(name, self.text)

    def test_the_providers_in_the_guide_are_the_presets(self):
        guide = read(GUIDE)
        for pid in providers.ORDER:
            preset = providers.PRESETS[pid]
            if preset.key_page:
                self.assertIn(preset.key_page, guide, pid)


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.text = read(GUIDE)

    def test_every_sentence_the_guide_tells_the_user_to_say_is_understood(self):
        not_commands = {"بله", "نه", "۱", "این جواب غلط بود",          # answers to the app's own question / the follow-up of a brain answer
                        "آزموده‌شده با دوبله", "آزموده نشده", "موفقیت نهایی", "هی جارویس", "به سرویس نرسیدم", "اینترنتِ برنامه", "وصل شد",
                        "نامعتبر", "اطلاعاتِ شخصی (ایمیل، تلفن، کدِ ملی) هم برود؟", "بسته", "هنوز چیزی نصب یا فعال نشده", "بررسی", "لطفاً",
                        "فهمیدنِ فارسی", "جوابِ مغز ابری به‌خاطرِ محدودیتِ طول نصفه ماند", "مدل نامعتبر", "حالت امن", "ChatGPT",
                        "از ChatGPT بخواه", "از مغزت بخواه برایم X بسازد", "مغز ابری"}
        checked = 0
        for phrase in quoted(self.text):
            if phrase in not_commands:
                continue
            checked += 1
            self.assertTrue(understood(phrase), "the guide tells the user to say «%s» but the app does not understand it" % phrase)
        self.assertGreaterEqual(checked, 20, "the guide must really be checked, not skipped")

    def test_the_examples_of_the_own_brain_teacher_are_requests_to_the_brain(self):
        examples = [p for p in quoted(section(self.text, 6)) if p.startswith("از ")]
        self.assertEqual(len(examples), 3)
        for phrase in examples:
            norm = nz.normalize(phrase)
            command = HI.classify(phrase, norm, fa_text.words(norm))
            self.assertIsNotNone(command, phrase)
            self.assertEqual((command.kind, command.slots["assistant"]), (HI.TEACHER_ASK, "brain"), phrase)

    def test_the_numbers_in_the_guide_are_the_codes(self):
        self.assertIn("%s درخواست" % fa(MAX_CALLS_PER_HOUR), self.text)
        self.assertIn("حداکثر %s جواب" % fa(learned.MAX_ITEMS), self.text)
        self.assertEqual((history.MAX_TURNS, history.TTL_SECONDS), (6, 6 * 3600), "the guide says «شش تبادل، شش ساعت»")
        self.assertIn("شش تبادل، شش ساعت", self.text)

    def test_the_guide_says_what_is_not_tested(self):
        self.assertIn("آزموده نشده", self.text)
        self.assertIn("فیلترشکن", self.text)
        self.assertIn("«بله»ی دوم", self.text)


if __name__ == "__main__":
    unittest.main()
