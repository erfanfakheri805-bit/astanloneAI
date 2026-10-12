"""
FINAL-EXIT-001 - Persian conversation brain.

Tests of persian_brain/: the Persian normalization, the closed word lists, the intent classifier
(GREETING, QUESTION, REQUEST, COMMAND, STATEMENT, TEACHING, CONTINUATION, REFERENCE, FEEDBACK, UNKNOWN -
a table of more than two hundred sentences, spelling variants, negatives and a fuzz run), the persisted
dialogue state (restart, expiry, damaged data), the three activation scopes, the multi-turn flows through
the real memory database and the real Self-Builder service, the single SkillSystem seam, and the rule that
the brain answers from facts - there is no table of "message -> answer" anywhere in the package.

Every test works in its own temporary directory; nothing is ever written into the source tree.

Run directly:
    python -m unittest tests.test_persian_brain_final_exit001 -v
"""

import ast
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persian_brain
from persian_brain import activation, dialogue as dlg_mod, intents as I, lexicon as lx, messages as M
from persian_brain import normalization as nz
from persian_brain.brain import PersianBrain, dynamic_skill, get_brain
from self_builder import service as sb_service

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_DIR = os.path.join(SRC_DIR, "persian_brain")


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class KeyValueMemory:
    """Just the key-value part of MemorySystem the dialogue state uses."""

    def __init__(self):
        self.store = {}
        self.writes = 0
        self.fail_reads = False
        self.fail_writes = False

    def get_state(self, key):
        if self.fail_reads:
            raise RuntimeError("read failed")
        return self.store.get(key)

    def set_state(self, key, value):
        if self.fail_writes:
            raise RuntimeError("write failed")
        self.writes += 1
        self.store[key] = json.loads(json.dumps(value))


# ============================================================================ normalization
class TestNormalization(unittest.TestCase):
    CASES = [
        ("سـلام", "سلام"),                          # tatweel
        ("سَلام", "سلام"),                          # diacritic
        ("مبدّل", "مبدل"),                          # shadda
        ("ك ي ة", "ک ی ه"),                         # Arabic kaf / yeh / teh marbuta
        ("پايتون چيست", "پایتون چیست"),              # Arabic yeh
        ("۱۲۳", "123"),                             # Persian digits
        ("١٢٣", "123"),                             # Arabic-Indic digits
        ("۱٫۵", "1.5"),                             # Persian decimal separator
        ("می‌خواهم", "می خواهم"),                   # ZWNJ is a space
        ("سلااااام", "سلام"),                       # elongation
        ("خیلییییی!!!", "خیلی!"),                    # elongation + punctuation run
        ("چیه؟؟؟", "چیه?"),                         # Arabic question mark, run
        ("سلام 😊 دنیا", "سلام دنیا"),               # emoji
        ("  سلام   دنیا  ", "سلام دنیا"),            # whitespace
        ("‏سلام‎", "سلام"),                # bidi marks
        ("ＡＢＣ", "ABC"),                          # full-width Latin (NFKC)
        ("\t\n", ""),
        ("", ""),
        (None, ""),
    ]

    def test_the_canonical_form(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(nz.normalize(raw), expected)

    def test_normalization_is_idempotent(self):
        for raw, _ in self.CASES:
            once = nz.normalize(raw)
            self.assertEqual(nz.normalize(once), once, raw)

    def test_the_output_has_no_invisible_or_control_characters(self):
        rng = random.Random(20261010)
        pool = list("سلام دنیا abc ۱۲۳ 456 ?!.,؟،؛ ") + ["‌", "‍", "‎", "‏", "ـ", "َ", "ّ",
                                                         "😊", "\n", "\t", " ", "﻿", "ك", "ي", "ٱ", "ﻻ"]
        for _ in range(500):
            raw = "".join(rng.choice(pool) for _ in range(rng.randint(0, 40)))
            out = nz.normalize(raw)
            self.assertEqual(out, nz.normalize(out))
            for ch in out:
                self.assertFalse(ch in "‌‍‎‏ـ﻿ ", repr(raw))
                self.assertTrue(ch == " " or ch.isprintable(), repr(raw))
            self.assertEqual(out, out.strip())
            self.assertNotIn("  ", out)

    def test_elongated_letters_collapse_but_double_letters_stay(self):
        self.assertEqual(nz.collapse_elongation("سلاااام"), "سلام")
        self.assertEqual(nz.collapse_elongation("aaaa"), "a")
        self.assertEqual(nz.collapse_elongation("کتاب"), "کتاب")
        self.assertEqual(nz.collapse_elongation("آفرین"), "آفرین")
        self.assertEqual(nz.collapse_elongation("ببین مممنون"), "ببین مممنون".replace("ممم", "م"))

    def test_the_match_key_ignores_spaces_zwnj_and_the_madda(self):
        self.assertEqual(nz.match_key("آسمان آبی"), nz.match_key("اسمان‌آبی"))
        self.assertEqual(nz.match_key("آسمان"), nz.match_key("اسمان"))
        self.assertNotEqual(nz.match_key("آسمان"), nz.match_key("زمین"))
        self.assertEqual(nz.match_key(None), "")

    def test_tokens_and_helpers(self):
        self.assertEqual(nz.tokens("سلام، چطوری؟"), ["سلام", "چطوری"])
        self.assertEqual(nz.tokens("۱۰ کیلومتر"), ["10", "کیلومتر"])
        self.assertTrue(nz.is_question_text("چطوری؟"))
        self.assertTrue(nz.is_question_text("چطوری؟؟؟"))
        self.assertTrue(nz.is_question_text("چطوری؟!"))                  # a question mark that is followed by "!"
        self.assertTrue(nz.is_question_text("چطوری ؟ !!"))
        self.assertFalse(nz.is_question_text("چطوری"))
        self.assertFalse(nz.is_question_text("چطوری!"))
        self.assertFalse(nz.is_question_text("؟ چطوری"))
        self.assertTrue(nz.has_persian_script("abc سلام"))
        self.assertFalse(nz.has_persian_script("hello world"))


# ============================================================================ lexicon
class TestLexicon(unittest.TestCase):
    def phrase_groups(self):
        return {name: value for name, value in vars(lx).items()
                if name.isupper() and isinstance(value, frozenset) and value and all(isinstance(p, tuple) for p in value)}

    def word_groups(self):
        return {name: value for name, value in vars(lx).items()
                if name.isupper() and isinstance(value, frozenset) and value and all(isinstance(p, str) for p in value)}

    def test_every_phrase_is_stored_as_the_tokens_normalization_produces(self):
        groups = self.phrase_groups()
        self.assertGreaterEqual(len(groups), 12)
        for name, phrases in groups.items():
            for ph in phrases:
                self.assertTrue(ph, name)
                self.assertEqual(lx.phrase(" ".join(ph)), ph, (name, ph))

    def test_every_word_is_a_normalized_token(self):
        groups = self.word_groups()
        self.assertGreaterEqual(len(groups), 15)
        offenders = []
        for name, words in groups.items():
            for w in words:
                # a word that normalization would rewrite (elongation, Arabic letters, ZWNJ ...) can never match anything
                if nz.tokens(w) != [w] or (w.isascii() and w != w.lower()):
                    offenders.append((name, w, nz.tokens(w)))
        self.assertEqual(offenders, [])

    def test_the_vocabularies_are_small_and_structural(self):
        total = sum(len(v) for v in self.phrase_groups().values()) + sum(len(v) for v in self.word_groups().values())
        self.assertLess(total, 900)                          # a few hundred words, not a corpus
        longest = max(len(ph) for group in self.phrase_groups().values() for ph in group)
        self.assertLessEqual(longest, 5)                     # phrases, never whole sentences

    def test_phrase_helpers(self):
        toks = ["سلام", "دوست", "من", "خوبی"]
        self.assertTrue(lx.contains(toks, ("دوست", "من")))
        self.assertFalse(lx.contains(toks, ("من", "دوست")))
        self.assertFalse(lx.contains(toks, ()))
        self.assertFalse(lx.contains(toks, tuple(toks + ["x"])))
        self.assertTrue(lx.starts_with(toks, ("سلام",)))
        self.assertFalse(lx.starts_with(toks, ("دوست",)))
        self.assertTrue(lx.any_phrase(toks, {("نه",), ("خوبی",)}))
        self.assertFalse(lx.any_phrase(toks, {("نه",)}))
        self.assertEqual(lx.phrase("می‌خواهم  بروم"), ("می", "خواهم", "بروم"))

    def test_plural_suffix_tokens_never_become_vocabulary_words(self):
        for group in (lx.CAP_WORDS, lx.LIST_WORDS, lx.STATUS_CONTEXT):
            self.assertFalse(group & {"ها", "های", "هایت", "هات"}, group)


# ============================================================================ intent classification
P_OFFER = I.Context(pending_type="offer_build")
MENTIONS = I.Context(mentions_capability=True)
LAST_INVOKE = I.Context(last_kind="invoke")
LAST_LIST = I.Context(last_kind="list")

# (text, context, kind, sub)  - sub None means "any"; the sentences are ordinary typed Persian.
INTENT_TABLE = [
    # ---- GREETING: hello / wellbeing / thanks / farewell
    ("سلام", None, "GREETING", "hello"), ("سلام!", None, "GREETING", "hello"), ("سلاااام", None, "GREETING", "hello"),
    ("درود", None, "GREETING", "hello"), ("درود بر شما", None, "GREETING", "hello"), ("سلام علیکم", None, "GREETING", "hello"),
    ("صبح بخیر", None, "GREETING", "hello"), ("ظهر بخیر", None, "GREETING", "hello"), ("عصر بخیر", None, "GREETING", "hello"),
    ("شب بخیر", None, "GREETING", "hello"), ("روز بخیر", None, "GREETING", "hello"), ("وقت بخیر", None, "GREETING", "hello"),
    ("سلام عزیزم", None, "GREETING", "hello"), ("سلام دوست من", None, "GREETING", "hello"),
    ("سلام، خوبی؟", None, "GREETING", "wellbeing"), ("سلام چطوری", None, "GREETING", "wellbeing"),
    ("سلام حالت چطوره؟", None, "GREETING", "wellbeing"), ("خوبی؟", None, "GREETING", "wellbeing"),
    ("چطوری؟", None, "GREETING", "wellbeing"), ("حالت چطوره؟", None, "GREETING", "wellbeing"),
    ("چه خبر؟", None, "GREETING", "wellbeing"), ("خوبین؟", None, "GREETING", "wellbeing"),
    ("ممنون", None, "GREETING", "thanks"), ("مرسی", None, "GREETING", "thanks"), ("خیلی ممنون", None, "GREETING", "thanks"),
    ("مرسی از کمکت", None, "GREETING", "thanks"), ("متشکرم", None, "GREETING", "thanks"),
    ("سپاسگزارم", None, "GREETING", "thanks"), ("دستت درد نکنه", None, "GREETING", "thanks"),
    ("ممنونم", None, "GREETING", "thanks"), ("دمت گرم", None, "GREETING", "thanks"),
    ("خداحافظ", None, "GREETING", "farewell"), ("خدانگهدار", None, "GREETING", "farewell"),
    ("فعلا", None, "GREETING", "farewell"), ("بای", None, "GREETING", "farewell"), ("تا فردا", None, "GREETING", "farewell"),
    ("شب خوش", None, "GREETING", "farewell"), ("من میرم", None, "GREETING", "farewell"),
    ("به امید دیدار", None, "GREETING", "farewell"), ("تا بعد", None, "GREETING", "farewell"),
    ("سلام و درود", None, "GREETING", "hello"), ("سلام 😊", None, "GREETING", "hello"), ("سـلام", None, "GREETING", "hello"),
    ("سلام.", None, "GREETING", "hello"), ("سلام سلام", None, "GREETING", "hello"),
    # ---- spelling noise never changes the class
    ("سلاااااام!!!", None, "GREETING", "hello"), ("سَلام", None, "GREETING", "hello"), ("ســلام", None, "GREETING", "hello"),
    ("درود🌹", None, "GREETING", "hello"), ("ممنوووون", None, "GREETING", "thanks"), ("مرررسی", None, "GREETING", "thanks"),
    ("خدااافظ", None, "GREETING", "farewell"),
    # ---- FEEDBACK
    ("آفرین", None, "FEEDBACK", "positive"), ("عالی بود", None, "FEEDBACK", "positive"), ("درست بود", None, "FEEDBACK", "positive"),
    ("احسنت", None, "FEEDBACK", "positive"), ("ایول", None, "FEEDBACK", "positive"), ("خیلی خوب", None, "FEEDBACK", "positive"),
    ("عالیه", None, "FEEDBACK", "positive"), ("درسته", None, "FEEDBACK", "positive"), ("بهتر شد", None, "FEEDBACK", "positive"),
    ("اشتباه بود", None, "FEEDBACK", "negative"), ("غلط بود", None, "FEEDBACK", "negative"),
    ("جوابت درست نبود", None, "FEEDBACK", "negative"), ("اشتباه کردی", None, "FEEDBACK", "negative"),
    ("مزخرف", None, "FEEDBACK", "negative"), ("کار نکرد", None, "FEEDBACK", "negative"), ("درست نیست", None, "FEEDBACK", "negative"),
    ("این جواب غلطه", None, "FEEDBACK", "negative"), ("اشتباهه", None, "FEEDBACK", "negative"),
    ("جوابت بد بود", None, "FEEDBACK", "negative"),
    # ---- TEACHING
    ("یاد بگیر که زمین گرد است", None, "TEACHING", "teach"), ("بدان که آب در صد درجه می‌جوشد", None, "TEACHING", "teach"),
    ("به خاطر بسپار که تهران پایتخت ایران است", None, "TEACHING", "teach"),
    ("یادت باشه که پایتون زبان برنامه نویسی است", None, "TEACHING", "teach"),
    ("حفظ کن که خورشید یک ستاره است", None, "TEACHING", "teach"), ("ذخیره کن که مریخ سیاره سرخ است", None, "TEACHING", "teach"),
    ("بدون که سیب یک میوه است", None, "TEACHING", "teach"), ("یادداشت کن که قم شهری در ایران است", None, "TEACHING", "teach"),
    ("یاد بگیر", None, "TEACHING", "incomplete"), ("یاد بگیر که الف", None, "TEACHING", "incomplete"),
    ("بدان که ب است", None, "TEACHING", "incomplete"),
    # ---- REQUEST: build a capability
    ("یک مبدل کیلومتر به مایل بساز", None, "REQUEST", "build"),
    ("فرمول مساحت دایره را یاد بگیر: pi * r ** 2", None, "REQUEST", "build"),
    ("ابزاری بساز که تعداد کلمات متن را بشمارد", None, "REQUEST", "build"),
    ("یک قابلیت جدید برای تبدیل دما بساز", None, "REQUEST", "build"),
    ("می‌خواهم یک ماشین حساب BMI داشته باشی: وزن / (قد * قد)", None, "REQUEST", "build"),
    ("یه مبدل بساز", None, "REQUEST", "build"), ("قابلیت جدید اضافه کن", None, "REQUEST", "build"),
    ("یک مبدل متر به فوت درست کن", None, "REQUEST", "build"),
    ("ماشین حساب تخفیف بساز: قیمت * (۱ - درصد / ۱۰۰)", None, "REQUEST", "build"),
    ("یک ابزار بساز که متن را معکوس کند", None, "REQUEST", "build"),
    ("تبدیل ساعت به دقیقه را اضافه کن", None, "REQUEST", "build"),
    ("لطفا مبدل پوند به کیلوگرم رو بساز", None, "REQUEST", "build"),
    ("یاد بگیر مایل را به کیلومتر تبدیل کنی", None, "REQUEST", "build"),
    ("من یک مبدل پوند به کیلوگرم لازم دارم", None, "REQUEST", "build"),
    ("قابلیتی بساز که ثانیه را به دقیقه تبدیل کند", None, "REQUEST", "build"),
    ("يك مبدل كيلومتر به مايل بساز", None, "REQUEST", "build"), ("یک  مبدل   کیلومتر   به   مایل   بساز!!!", None, "REQUEST", "build"),
    ("یک مبدل‌ کیلومتر‌ به مایل بساز", None, "REQUEST", "build"),
    ("یک ربات پخش موسیقی بساز", None, "REQUEST", "build_unsupported"),
    ("یک برنامه ویرایش عکس بساز", None, "REQUEST", "build_unsupported"),
    # ---- COMMAND: look at / control the capability registry
    ("قابلیت‌هایت را نشان بده", None, "COMMAND", "list"), ("چه کارهایی بلدی؟", None, "COMMAND", "list"),
    ("لیست قابلیت‌ها", None, "COMMAND", "list"), ("چی بلدی؟", None, "COMMAND", "list"),
    ("خودت چی ساختی؟", None, "COMMAND", "list"), ("چه کارایی بلدی؟", None, "COMMAND", "list"),
    ("وضعیت قابلیت‌ها را بررسی کن", None, "COMMAND", "status"), ("سلامت سیستم رو چک کن", None, "COMMAND", "status"),
    ("تاریخچه تغییرات", None, "COMMAND", "history"), ("چه تغییراتی دادی؟", None, "COMMAND", "history"),
    ("تاریخچه ارتقاها", None, "COMMAND", "history"), ("گزارش تغییرات", None, "COMMAND", "history"),
    ("به نسخه قبلی برگرد", None, "COMMAND", "rollback"), ("برگردان به نسخه ۱", None, "COMMAND", "rollback"),
    ("رولبک نسخه قبلی", None, "COMMAND", "rollback"),
    ("قابلیت تبدیل کیلومتر را غیرفعال کن", None, "COMMAND", "disable"), ("این قابلیت را حذف کن", None, "COMMAND", "disable"),
    ("قابلیت را خاموش کن", None, "COMMAND", "disable"),
    ("راهنما", None, "COMMAND", "help"), ("کمک", None, "COMMAND", "help"), ("مثال بزن", None, "COMMAND", "help"),
    ("چطوری استفاده کنم؟", None, "COMMAND", "help"), ("نمونه بده", None, "COMMAND", "help"),
    ("جزئیات قابلیت تبدیل", None, "COMMAND", "detail"), ("توضیحات قابلیت تبدیل کیلومتر", None, "COMMAND", "detail"),
    # ---- CONTINUATION: the answer to a question the brain asked
    ("بله", P_OFFER, "CONTINUATION", "confirm"), ("آره", P_OFFER, "CONTINUATION", "confirm"),
    ("باشه", P_OFFER, "CONTINUATION", "confirm"), ("حتما", P_OFFER, "CONTINUATION", "confirm"),
    ("بساز", P_OFFER, "CONTINUATION", "confirm"), ("اوکی", P_OFFER, "CONTINUATION", "confirm"),
    ("آره بساز", P_OFFER, "CONTINUATION", "confirm"), ("بله لطفا", P_OFFER, "CONTINUATION", "confirm"),
    ("yes", P_OFFER, "CONTINUATION", "confirm"),
    ("نه", P_OFFER, "CONTINUATION", "deny"), ("نخیر", P_OFFER, "CONTINUATION", "deny"), ("نه ممنون", P_OFFER, "CONTINUATION", "deny"),
    ("لازم نیست", P_OFFER, "CONTINUATION", "deny"), ("نمیخوام", P_OFFER, "CONTINUATION", "deny"),
    ("no", P_OFFER, "CONTINUATION", "deny"),
    ("بیخیال", P_OFFER, "CONTINUATION", "cancel"), ("لغو", P_OFFER, "CONTINUATION", "cancel"),
    ("منصرف شدم", P_OFFER, "CONTINUATION", "cancel"), ("ولش کن", P_OFFER, "CONTINUATION", "cancel"),
    ("cancel", P_OFFER, "CONTINUATION", "cancel"),
    ("ادامه بده", None, "CONTINUATION", "more"), ("بیشتر توضیح بده", None, "CONTINUATION", "more"),
    ("ادامه", None, "CONTINUATION", "more"), ("بیشتر بگو", None, "CONTINUATION", "more"),
    ("توضیح بیشتر", None, "CONTINUATION", "more"),
    # ---- REFERENCE: "the same one, for ..."
    ("برای ۲۰ چی؟", LAST_INVOKE, "REFERENCE", "recompute"), ("همان را برای ۵۰ حساب کن", LAST_INVOKE, "REFERENCE", "recompute"),
    ("و ۳۰؟", LAST_INVOKE, "REFERENCE", "recompute"), ("همون رو برای ۱۰۰ بزن", LAST_INVOKE, "REFERENCE", "recompute"),
    ("دوباره", LAST_INVOKE, "REFERENCE", "repeat"), ("یک بار دیگه", LAST_INVOKE, "REFERENCE", "repeat"),
    ("برای ۲۰ چی؟", None, "QUESTION", "general"), ("برای ۲۰ چی؟", LAST_LIST, "QUESTION", "general"),
    # ---- QUESTION
    ("پایتون چیست؟", None, "QUESTION", "general"), ("تهران کجاست؟", None, "QUESTION", "general"),
    ("چرا آسمان آبی است؟", None, "QUESTION", "general"), ("کی تو را ساخته؟", None, "QUESTION", "general"),
    ("خورشید چیه؟", None, "QUESTION", "general"), ("خوبی‌های این برنامه چیست؟", None, "QUESTION", None),
    ("پایتون چیست؟؟؟", None, "QUESTION", "general"), ("پايتون چيست؟", None, "QUESTION", "general"),
    ("آیا می‌توانی تبدیل متر به فوت را انجام بدهی؟", None, "QUESTION", "capability"),
    ("بلدی مساحت دایره را حساب کنی؟", None, "QUESTION", "capability"),
    ("میتونی تبدیل لیتر به گالن را انجام بدی؟", None, "QUESTION", "capability"),
    ("چی دوست دارم؟", None, "QUESTION", "likes"), ("چه چیزهایی دوست دارم؟", None, "QUESTION", "likes"),
    ("چه چیزایی دوست ندارم؟", None, "QUESTION", "likes"),
    ("۱۰ کیلومتر چند مایل است؟", None, "QUESTION", None), ("چقدر طول می‌کشد؟", None, "QUESTION", None),
    # ---- STATEMENT
    ("زمین گرد است", None, "STATEMENT", "assertion"), ("پایتون یک زبان برنامه‌نویسی است", None, "STATEMENT", "assertion"),
    ("هوا خوب است", None, "STATEMENT", "assertion"), ("تهران پایتخت ایران است", None, "STATEMENT", "assertion"),
    ("زمين گرد است", None, "STATEMENT", "assertion"),
    # ---- UNKNOWN (left to the application's existing pipeline)
    ("", None, "UNKNOWN", "empty"), ("   ", None, "UNKNOWN", "empty"), ("؟؟؟", None, "UNKNOWN", None),
    ("...", None, "UNKNOWN", None), ("۱۲۳", None, "UNKNOWN", None), ("بلبلی عصر شنبه", None, "UNKNOWN", None),
    ("آب", None, "UNKNOWN", None), ("😊", None, "UNKNOWN", None), ("نمی‌دانم", None, "UNKNOWN", None),
    ("کتاب", None, "UNKNOWN", None), ("فردا میرم مسافرت", None, "UNKNOWN", None), ("دیروز باران آمد", None, "UNKNOWN", None),
    # ---- words that only look like an intent
    ("امروز هوا خوبه", None, "UNKNOWN", None),                    # weather talk, not feedback
    ("سلامتی من خوب نیست", None, "UNKNOWN", None),                # "سلامتی" is not "سلام"
    ("من دانشجو هستم", None, "UNKNOWN", None),                    # a personal fact: the existing Persian NLU owns it
    ("بله", None, "UNKNOWN", None), ("نه", None, "UNKNOWN", None),  # yes / no with nothing asked
    ("سلام ممنون", None, "GREETING", "hello"),
    # ---- spoken object clitics: «غیرفعالش کن» = «غیرفعال کن» + "it"
    ("غیرفعالش کن", MENTIONS, "COMMAND", "disable"), ("خاموشش کن", MENTIONS, "COMMAND", "disable"),
    ("حذفش کن", MENTIONS, "COMMAND", "disable"), ("برگردونش به نسخه قبلی", None, "COMMAND", "rollback"),
    ("لغوش کن", P_OFFER, "CONTINUATION", "cancel"), ("فراموشش کن", P_OFFER, "CONTINUATION", "cancel"),
    ("غیرفعالش کن", None, "REQUEST", "generic"),                      # no capability in sight: not a registry command
    # ---- a question mark followed by "!" is still a question
    ("بلدی مساحت دایره را حساب کنی؟!", None, "QUESTION", "capability"), ("پایتون چیست؟!", None, "QUESTION", "general"),
    ("چطوری؟!", None, "GREETING", "wellbeing"), ("آفرین؟!", None, "QUESTION", None),
    ("آیا قابلیت تبدیل متر به فوت را داری؟", None, "QUESTION", "capability"),
]


class TestIntentTable(unittest.TestCase):
    def test_the_table_is_large_and_covers_every_intent_kind(self):
        self.assertGreaterEqual(len(INTENT_TABLE), 200)
        self.assertEqual({row[2] for row in INTENT_TABLE}, set(I.KINDS))

    def test_every_sentence_is_classified_as_expected(self):
        wrong = []
        for text, ctx, kind, sub in INTENT_TABLE:
            got = I.classify(text, ctx or I.Context())
            if got.kind != kind or (sub is not None and got.sub != sub):
                wrong.append((text, (ctx.pending_type, ctx.last_kind) if ctx else None, (kind, sub), (got.kind, got.sub)))
        self.assertEqual(wrong, [])

    def test_the_class_does_not_depend_on_typographic_noise(self):
        rng = random.Random(77)
        stable = [row for row in INTENT_TABLE if row[2] in ("GREETING", "FEEDBACK", "REQUEST", "COMMAND", "QUESTION")
                  and row[1] is None]
        noises = (lambda s: s.replace(" ", "‌ "), lambda s: s + " 🙂", lambda s: "  " + s + "  ",
                  lambda s: s.replace("ی", "ي").replace("ک", "ك"), lambda s: s + "!!", lambda s: "‏" + s)
        for text, _, kind, sub in rng.sample(stable, 60):
            for noise in noises:
                got = I.classify(noise(text))
                self.assertEqual((got.kind, got.sub if sub else None), (kind, sub), (text, noise(text)))

    def test_intents_carry_their_evidence_and_serialise(self):
        got = I.classify("سلام، ۱۰ کیلومتر چند مایل است؟")
        self.assertEqual((got.kind, got.slots["rest"]), ("GREETING", "10 کیلومتر چند مایل است"))
        d = got.to_dict()
        self.assertEqual(set(d), {"kind", "sub", "confidence", "evidence", "slots"})
        json.dumps(d)                                                   # plain data
        self.assertTrue(0.0 <= d["confidence"] <= 1.0)
        self.assertTrue(got.is_("GREETING") and got.is_("GREETING", "hello") and not got.is_("QUESTION"))
        build = I.classify("یک مبدل کیلومتر به مایل بساز")
        self.assertIn("request", build.slots)
        self.assertNotIn("request", build.to_dict()["slots"])          # the parsed request object is not exported
        self.assertIn("build_verb", " ".join(build.evidence))

    def test_a_pending_question_is_only_answered_by_short_yes_no_words(self):
        ctx = I.Context(pending_type="confirm_build")
        for text in ("بله", "نه", "بیخیال"):
            self.assertEqual(I.classify(text, ctx).kind, "CONTINUATION")
        for text in ("آره ولی ضریب را عوض کن", "نه، کیلومتر به مایل", "بله این قابلیت را فقط برای من بساز و بعد ذخیره کن"):
            self.assertNotEqual(I.classify(text, ctx).kind, "CONTINUATION", text)

    def test_answer_words(self):
        self.assertEqual(I.answer_word(["بله"]), "confirm")
        self.assertEqual(I.answer_word(["آره", "بساز"]), "confirm")
        self.assertEqual(I.answer_word(["نه", "ممنون"]), "deny")
        self.assertEqual(I.answer_word(["لازم", "نیست"]), "deny")
        self.assertEqual(I.answer_word(["منصرف", "شدم"]), "cancel")
        self.assertIsNone(I.answer_word([]))
        self.assertIsNone(I.answer_word(["بله", "نه"]))
        self.assertIsNone(I.answer_word(["x"] * 9))

    def test_the_version_number_of_a_rollback_command(self):
        for text, version in (("برگردان به نسخه ۱", 1), ("به نسخه ۳ برگرد", 3), ("برگرد به ورژن 2", 2),
                              ("به نسخه قبلی برگرد", None)):
            got = I.classify(text)
            self.assertEqual((got.kind, got.sub, got.slots["version"]), ("COMMAND", "rollback", version), text)

    def test_context_changes_what_a_command_means(self):
        self.assertEqual(I.classify("جزئیات").kind, "UNKNOWN")                    # "details" of what?
        got = I.classify("جزئیات", I.Context(last_kind="describe"))
        self.assertEqual((got.kind, got.sub), ("COMMAND", "detail"))
        got = I.classify("غیرفعالش کن", I.Context(mentions_capability=True))
        self.assertEqual((got.kind, got.sub), ("COMMAND", "disable"))


class TestIntentRobustness(unittest.TestCase):
    def test_fuzzed_text_never_raises_and_always_yields_a_known_kind(self):
        rng = random.Random(20261011)
        words = ["سلام", "ممنون", "بساز", "مبدل", "کیلومتر", "به", "مایل", "چند", "است", "؟", "!", "۱۰", "10", "یاد", "بگیر",
                 "که", "نسخه", "قبلی", "برگرد", "بله", "نه", "قابلیت", "pi", "*", "**", "(", ")", "😊", "‌", "x", "\n", ""]
        for _ in range(1500):
            text = " ".join(rng.choice(words) for _ in range(rng.randint(0, 14)))
            ctx = I.Context(rng.choice([None, "offer_build", "confirm_build", "ask_inputs"]),
                            rng.choice([None, "invoke", "build", "list", "describe", "knowledge"]), rng.random() < 0.3)
            got = I.classify(text, ctx)
            self.assertIn(got.kind, I.KINDS, text)
            self.assertIsInstance(got.slots, dict)
            self.assertTrue(0.0 <= got.confidence <= 1.0)

    def test_random_unicode_never_raises(self):
        rng = random.Random(99)
        for _ in range(600):
            text = "".join(chr(rng.choice([rng.randint(0x20, 0x7e), rng.randint(0x600, 0x6ff), rng.randint(0x200b, 0x200f),
                                            rng.randint(0x1f300, 0x1f3ff), 0x20, 0xa0])) for _ in range(rng.randint(0, 60)))
            self.assertIn(I.classify(text).kind, I.KINDS)

    def test_very_long_and_degenerate_inputs(self):
        for text in ("سلام " * 5000, "ا" * 100000, "؟" * 10000, "‌" * 5000, "۱" * 3000, "(" * 2000, " ".join(["بساز"] * 2000)):
            self.assertIn(I.classify(text).kind, I.KINDS)


# ============================================================================ dialogue state
class TestDialogue(unittest.TestCase):
    def setUp(self):
        self.mem = KeyValueMemory()
        self.clock = FakeClock()

    def dlg(self):
        return dlg_mod.Dialogue(self.mem, self.clock).load()

    def test_a_fresh_dialogue_is_empty_and_writes_nothing(self):
        d = self.dlg()
        self.assertEqual((d.pending, d.pending_type, d.last), (None, None, None))
        self.assertFalse(d.commit())
        self.assertEqual(self.mem.writes, 0)

    def test_pending_question_and_topic_survive_a_restart(self):
        d = self.dlg()
        d.set_pending("offer_build", {"archetype": "unit_conversion", "slots": {"from_unit": "km", "to_unit": "mi"},
                                      "value": 10.0, "question": "۱۰ کیلومتر چند مایل است؟"})
        d.set_last("invoke", capability_id="unit_km_to_mi", title="تبدیل", inputs={"value": 10.0}, version=1)
        self.assertTrue(d.commit())
        self.assertEqual(self.mem.writes, 1)
        again = self.dlg()                                         # "the app was killed and started again"
        self.assertEqual(again.pending_type, "offer_build")
        self.assertEqual(again.pending["data"]["slots"], {"from_unit": "km", "to_unit": "mi"})
        self.assertEqual(again.pending["data"]["value"], 10.0)
        self.assertEqual((again.last["kind"], again.last["capability_id"], again.last["inputs"]),
                         ("invoke", "unit_km_to_mi", {"value": 10.0}))
        self.assertFalse(again.commit())                           # loaded and unchanged: nothing is written
        self.assertEqual(self.mem.writes, 1)

    def test_only_a_real_change_is_written(self):
        d = self.dlg()
        d.set_pending("confirm_teach", {"sentence": "زمین گرد است"})
        d.commit()
        d = self.dlg()
        d.clear_pending()
        self.assertTrue(d.commit())
        self.assertIsNone(self.mem.store[dlg_mod.STATE_KEY]["pending"])
        self.assertFalse(self.dlg().commit())
        self.assertEqual(self.mem.writes, 2)

    def test_a_pending_question_expires_after_the_time_to_live(self):
        d = self.dlg()
        d.set_pending("offer_build", {"archetype": "text_tool", "slots": {"ops": ["count_words"]}})
        d.commit()
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS - 1)
        self.assertEqual(self.dlg().pending_type, "offer_build")   # still valid
        self.clock.advance(1)
        self.assertEqual(self.dlg().pending_type, "offer_build")   # exactly at the limit
        self.clock.advance(0.5)
        expired = self.dlg()
        self.assertIsNone(expired.pending)
        self.assertTrue(expired.commit())                          # the expiry is written back
        self.assertIsNone(self.mem.store[dlg_mod.STATE_KEY]["pending"])

    def test_touching_the_pending_question_renews_its_lifetime(self):
        d = self.dlg()
        d.set_pending("ask_inputs", {"capability_id": "x"})
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS - 5)
        self.assertEqual(d.bump_attempts(), 1)
        self.assertEqual(d.bump_attempts(), 2)
        d.update_pending_data(have={"a": 1.0})
        d.commit()
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS - 5)
        again = self.dlg()
        self.assertEqual((again.pending_type, again.pending["attempts"], again.pending["data"]["have"]),
                         ("ask_inputs", 2, {"a": 1.0}))

    def test_a_pending_question_stamped_in_the_future_is_ignored(self):
        self.mem.store[dlg_mod.STATE_KEY] = {"v": 1, "last": None, "pending": {
            "type": "offer_build", "ts": self.clock() + 3600, "attempts": 0, "data": {}}}
        self.assertIsNone(self.dlg().pending)

    def test_damaged_or_foreign_state_is_ignored_never_raised(self):
        now = self.clock()
        for raw in (None, "text", 12, [], {}, {"v": 2}, {"v": 1}, {"v": 1, "pending": "x", "last": 5},
                    {"v": 1, "pending": {"type": "bogus", "ts": now}},
                    {"v": 1, "pending": {"type": "offer_build", "ts": "abc"}},
                    {"v": 1, "pending": {"type": "offer_build", "ts": now, "attempts": "x"}},
                    {"v": 1, "pending": {"type": "offer_build", "ts": None}},
                    {"v": 1, "last": {"kind": "bogus"}}, {"v": 1, "last": ["kind", "invoke"]}):
            self.mem.store[dlg_mod.STATE_KEY] = raw
            d = self.dlg()
            self.assertIsNone(d.pending, raw)
            self.assertIsNone(d.last, raw)
            d.commit()                                             # and it can be overwritten by a valid state
            d.set_pending("confirm_disable", {"capability_id": "x"})
            self.assertTrue(d.commit())
            self.assertEqual(self.dlg().pending_type, "confirm_disable")

    GOOD_DATA = {
        "offer_build": {"archetype": "unit_conversion", "slots": {"from_unit": "km", "to_unit": "mi"}, "value": 10.0,
                        "question": "q"},
        "confirm_build": {"request": {"status": "ready", "kind": "unit_conversion", "slots": {}, "missing": []},
                          "text": "t"},
        "confirm_rollback": {"capability_id": "unit_km_to_mi", "version": 1},
        "confirm_disable": {"capability_id": "unit_km_to_mi"},
        "confirm_teach": {"sentence": "زمین گرد است"},
        "clarify_build": {"kind": "unit_conversion", "slots": {}, "missing": ["to_unit"], "note": None, "text": "t"},
        "ask_inputs": {"capability_id": "formula_x", "title": "BMI", "have": {"v1": 70.0}, "missing": ["v2"]},
    }
    BAD_DATA = {
        "offer_build": [{}, {"archetype": 5, "slots": {}}, {"archetype": "unit_conversion", "slots": "km"},
                        {"archetype": "unit_conversion", "slots": {}, "value": "abc"},
                        {"archetype": "unit_conversion", "slots": {}, "value": True},
                        {"archetype": "unit_conversion", "slots": {}, "payload": 5}],
        "confirm_build": [{}, {"request": "bad"}, {"request": {"slots": "x"}}, {"request": {"missing": "x"}},
                          {"request": {"status": 3}}, {"request": {}, "text": 5}],
        "confirm_rollback": [{}, {"capability_id": 5}, {"capability_id": ""}, {"capability_id": "x" * 200},
                             {"capability_id": "c", "version": "2"}],
        "confirm_disable": [{}, {"capability_id": None}, {"capability_id": ["c"]}],
        "confirm_teach": [{}, {"sentence": 5}, {"sentence": ""}],
        "clarify_build": [{}, {"kind": 5, "slots": {}, "missing": []}, {"kind": None, "slots": "x", "missing": []},
                          {"kind": None, "slots": {}, "missing": "x"}, {"kind": None, "slots": {}, "missing": [1]}],
        "ask_inputs": [{}, {"capability_id": 5}, {"capability_id": "c", "have": "x"},
                       {"capability_id": "c", "missing": "x"}, {"capability_id": "c", "title": 5}],
    }

    def stored_pending(self, type_, data):
        self.mem.store[dlg_mod.STATE_KEY] = {"v": 1, "last": None, "pending": {
            "type": type_, "ts": self.clock(), "attempts": 0, "data": data}}
        return self.dlg()

    def test_the_data_every_kind_of_question_is_stored_with_is_accepted(self):
        self.assertEqual(set(self.GOOD_DATA), set(dlg_mod.PENDING_TYPES))
        for type_, data in self.GOOD_DATA.items():
            with self.subTest(type=type_):
                self.assertEqual(self.stored_pending(type_, data).pending_type, type_)

    def test_a_pending_question_whose_data_has_the_wrong_shape_is_treated_as_no_question(self):
        self.assertEqual(set(self.BAD_DATA), set(dlg_mod.PENDING_TYPES))
        for type_, variants in self.BAD_DATA.items():
            for data in variants:
                with self.subTest(type=type_, data=data):
                    d = self.stored_pending(type_, data)
                    self.assertIsNone(d.pending)
                    self.assertTrue(d.commit())                       # and the damaged question is written back as cleared
                    self.assertIsNone(self.mem.store[dlg_mod.STATE_KEY]["pending"])

    def test_a_topic_whose_fields_have_the_wrong_shape_is_ignored(self):
        good = {"kind": "invoke", "capability_id": "unit_km_to_mi", "title": "T", "inputs": {"value": 10.0},
                "version": 1}
        self.mem.store[dlg_mod.STATE_KEY] = {"v": 1, "pending": None, "last": dict(good, ts=self.clock())}
        self.assertEqual(self.dlg().last["capability_id"], "unit_km_to_mi")
        for field, value in (("capability_id", 5), ("title", ["x"]), ("inputs", "abc"), ("inputs", [1]),
                             ("version", "1"), ("name", 5)):
            with self.subTest(field=field):
                self.mem.store[dlg_mod.STATE_KEY] = {"v": 1, "pending": None, "last": dict(good, **{field: value})}
                self.assertIsNone(self.dlg().last)

    def test_sanitising_clamps_attempts_and_keeps_the_data_json_safe(self):
        self.mem.store[dlg_mod.STATE_KEY] = {"v": 1, "last": None, "pending": {
            "type": "clarify_build", "ts": self.clock(), "attempts": 999,
            "data": {"kind": None, "slots": {"deep": [1, 2, {"x": float("nan")}]}, "missing": []}}}
        d = self.dlg()
        self.assertEqual(d.pending["attempts"], 20)
        json.dumps(d.pending, allow_nan=False)

    def test_a_failing_memory_never_breaks_the_conversation(self):
        self.mem.fail_reads = True
        d = self.dlg()
        self.assertEqual((d.pending, d.last), (None, None))
        self.mem.fail_reads = False
        self.mem.fail_writes = True
        d.set_pending("offer_build", {})
        self.assertFalse(d.commit())                               # reported, not raised

    def test_unknown_kinds_are_refused(self):
        d = self.dlg()
        with self.assertRaises(ValueError):
            d.set_pending("bogus")
        with self.assertRaises(ValueError):
            d.set_last("bogus")
        self.assertEqual(d.bump_attempts(), 0)                     # nothing pending: nothing to count
        d.update_pending_data(x=1)                                 # and no error either

    def test_every_pending_type_and_topic_kind_is_accepted(self):
        d = self.dlg()
        for t in sorted(dlg_mod.PENDING_TYPES):
            d.set_pending(t, {"x": t})
            self.assertEqual(d.pending_type, t)
        for k in sorted(dlg_mod.LAST_KINDS):
            d.set_last(k, capability_id="c")
            self.assertEqual(d.last["kind"], k)

    def size_of(self):
        return len(json.dumps(self.mem.store[dlg_mod.STATE_KEY], sort_keys=True, ensure_ascii=False).encode("utf-8"))

    def test_the_stored_state_is_size_bounded_and_the_topic_goes_first(self):
        d = self.dlg()
        d.set_pending("clarify_build", {"a": ["x" * 600] * 10})
        d.set_last("describe", capability_id="c", blob=["z" * 600] * 20)
        self.assertTrue(d.commit())
        stored = self.mem.store[dlg_mod.STATE_KEY]
        self.assertLessEqual(self.size_of(), dlg_mod.MAX_STATE_BYTES)
        self.assertIsNone(stored["last"])                          # the topic goes first, the open question matters more
        self.assertEqual(stored["pending"]["type"], "clarify_build")
        self.assertEqual(len(stored["pending"]["data"]["a"]), 10)

    def test_an_oversized_open_question_is_dropped_rather_than_stored(self):
        d = self.dlg()
        d.set_pending("offer_build", {"small": 1})
        d.commit()
        d = self.dlg()
        d.set_pending("clarify_build", {"a": ["x" * 600] * 40, "b": ["y" * 600] * 40})
        d.commit()
        self.assertLessEqual(self.size_of(), dlg_mod.MAX_STATE_BYTES)
        self.assertEqual(self.mem.store[dlg_mod.STATE_KEY], {"v": 1, "pending": None, "last": None})

    def test_clean_json_bounds_depth_width_and_length(self):
        clean = dlg_mod._clean_json
        self.assertEqual(clean({"a": 1, "b": [True, None, "x"], "c": 1.5}), {"a": 1, "b": [True, None, "x"], "c": 1.5})
        self.assertIsNone(clean(float("nan")))
        self.assertIsNone(clean(float("inf")))
        self.assertEqual(len(clean("x" * 5000)), 600)
        self.assertEqual(len(clean(list(range(500)))), 40)
        self.assertEqual(len(clean({str(i): i for i in range(500)})), 40)
        self.assertEqual(len(next(iter(clean({"k" * 500: 1})))), 60)
        deep = cur = {}
        for _ in range(20):
            cur["n"] = {}
            cur = cur["n"]
        depth, node = 0, clean(deep)
        while isinstance(node, dict) and node:
            depth, node = depth + 1, node["n"]
        self.assertLessEqual(depth, 7)
        self.assertEqual(clean(object().__class__), str(object))   # anything exotic becomes a plain string


# ============================================================================ activation scopes
class FakePlatform(__import__("platform_layer").PlatformAdapter):
    """Any platform adapter that is not the plain desktop one (the Android app installs its own)."""

    def app_data_dir(self):
        return tempfile.gettempdir()

    def skill_definitions_dir(self):
        return tempfile.gettempdir()

    def temp_dir(self):
        return tempfile.gettempdir()

    def log(self, component, message, level="INFO"):
        pass


class TestActivation(unittest.TestCase):
    def setUp(self):
        import platform_layer
        self.platform_layer = platform_layer
        original = platform_layer.get_platform()
        self.addCleanup(platform_layer.set_platform, original)
        platform_layer.set_platform(platform_layer.DesktopPlatformAdapter(data_dir=tempfile.gettempdir()))
        env = dict(os.environ)
        env.pop(activation.ENV_VAR, None)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mem = KeyValueMemory()

    def android(self):
        self.platform_layer.set_platform(FakePlatform())

    def test_a_plain_library_core_only_gets_the_capability_domain(self):
        self.assertEqual(activation.scope_for(self.mem), activation.SCOPE_CAPABILITIES)

    def test_the_application_runtime_gets_the_whole_conversation(self):
        self.android()                                              # android_entry.start() installs its adapter first
        self.assertEqual(activation.scope_for(self.mem), activation.SCOPE_FULL)

    def test_the_environment_variable_switches_the_scope(self):
        for value, expected in (("1", "full"), ("true", "full"), ("YES", "full"), ("on", "full"), ("Full", "full"),
                                (" on ", "full"), ("0", "off"), ("false", "off"), ("no", "off"), ("OFF", "off"),
                                ("", "capabilities"), ("maybe", "capabilities")):
            with mock.patch.dict(os.environ, {activation.ENV_VAR: value}):
                self.assertEqual(activation.scope_for(self.mem), expected, value)
        self.android()
        with mock.patch.dict(os.environ, {activation.ENV_VAR: "off"}):
            self.assertEqual(activation.scope_for(self.mem), "off")                 # the switch wins over the platform
        with mock.patch.dict(os.environ, {activation.ENV_VAR: "maybe"}):
            self.assertEqual(activation.scope_for(self.mem), "full")                 # an unknown value is no switch

    def test_an_explicit_scope_wins_over_everything_and_can_be_reset(self):
        self.android()
        with mock.patch.dict(os.environ, {activation.ENV_VAR: "full"}):
            activation.enable(self.mem, activation.SCOPE_CAPABILITIES)
            self.assertEqual(activation.scope_for(self.mem), "capabilities")
            activation.disable(self.mem)
            self.assertEqual(activation.scope_for(self.mem), "off")
            activation.enable(self.mem)
            self.assertEqual(activation.scope_for(self.mem), "full")
            activation.reset(self.mem)
            self.assertEqual(activation.scope_for(self.mem), "full")                 # automatic again (environment)
        with mock.patch.dict(os.environ, {activation.ENV_VAR: "0"}):
            self.assertEqual(activation.scope_for(self.mem), "off")

    def test_overrides_belong_to_one_memory_and_do_not_keep_it_alive(self):
        import gc
        import weakref
        other = KeyValueMemory()
        activation.enable(self.mem, "full")
        self.assertEqual(activation.scope_for(other), "capabilities")
        ref = weakref.ref(other)
        activation.enable(other, "off")
        before = len(activation._OVERRIDES)
        del other
        gc.collect()
        self.assertIsNone(ref())
        self.assertEqual(len(activation._OVERRIDES), before - 1)

    def test_an_unknown_scope_is_refused(self):
        with self.assertRaises(ValueError):
            activation.enable(self.mem, "everything")

    def test_a_broken_platform_layer_means_the_capability_scope_not_a_crash(self):
        with mock.patch.object(self.platform_layer, "get_platform", side_effect=RuntimeError("no platform")):
            self.assertEqual(activation.scope_for(self.mem), "capabilities")

    def test_the_documented_names(self):
        self.assertEqual(activation.ENV_VAR, "STANDALONE_AI_PERSIAN_BRAIN")
        self.assertEqual((activation.SCOPE_FULL, activation.SCOPE_CAPABILITIES, activation.SCOPE_OFF),
                         ("full", "capabilities", "off"))


# ============================================================================ conversations
from memory.memory_system import MemorySystem          # noqa: E402  (after the path set-up above)


class BrainCase(unittest.TestCase):
    """The brain on a real MemorySystem and the real Self-Builder service, in a temporary directory.
    `open_app()` is "the app starts": new MemorySystem, new brain, new Self-Builder service on the same files."""

    scope = activation.SCOPE_FULL

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pb_")
        self.db = os.path.join(self.tmp, "data", "memory.db")
        self.clock = FakeClock()
        self.memory = None
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.close_app)
        self.open_app()

    def open_app(self):
        self.close_app()
        self.memory = MemorySystem(self.db)
        activation.enable(self.memory, self.scope)
        self.brain = PersianBrain(self.memory, clock=self.clock)

    def close_app(self):
        memory, self.memory = self.memory, None
        if memory is None:
            return
        try:
            sb_service.get_service(memory).close()
        finally:
            memory._conn.close()

    def say(self, text):
        return self.brain.respond(text)

    @property
    def sb(self):
        return sb_service.get_service(self.memory)

    def state(self):
        return self.memory.get_state(dlg_mod.STATE_KEY)

    def pending_type(self):
        state = self.state()
        return state["pending"]["type"] if state and state.get("pending") else None

    def build_km(self):
        reply = self.say("یک مبدل کیلومتر به مایل بساز")
        self.assertIn("ساختم", reply)
        return reply

    def two_versions(self):
        """km -> mi at the standard factor (version 1), then at the user's own factor 0.6 (version 2)."""
        self.build_km()
        self.say("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است")
        self.assertIn("ارتقا دادم", self.say("بله"))

    def by_title(self, title):
        (record,) = [c for c in self.sb.capabilities() if c["title"] == title]
        return record

    def assertPersian(self, reply):
        self.assertIsInstance(reply, str)
        self.assertTrue(reply.strip())
        self.assertTrue(nz.has_persian_script(reply), reply)


class TestSocialTalk(BrainCase):
    def test_every_social_kind_gets_a_persian_reply_and_changes_nothing(self):
        for text in ("سلام", "صبح بخیر", "درود", "حالت چطوره؟", "خوبی؟", "ممنون", "مرسی از کمکت", "خداحافظ", "شب خوش",
                     "سلاااام!!!", "سلام عزیزم", "عصر بخیر"):
            reply = self.say(text)
            self.assertPersian(reply)
            self.assertEqual(self.brain.last_trace["intent"]["kind"], "GREETING", text)
            self.assertTrue(self.brain.last_trace["claimed"])
        self.assertIsNone(self.state())                         # talking does not write dialogue state
        self.assertFalse(self.sb.exists())                      # and never creates the capability registry

    def test_replies_fit_the_kind_of_social_message(self):
        self.assertIn("بخیر", self.say("صبح بخیر"))
        self.assertIn("خواهش", self.say("ممنون"))
        self.assertIn("خداحافظ", self.say("خداحافظ"))
        self.assertIn("خوبم", self.say("حالت چطوره؟"))
        self.assertIn("سلام", self.say("سلام"))

    def test_the_same_message_always_gets_the_same_reply(self):
        for text in ("سلام", "سلام دوباره", "مرسی", "خوبی؟"):
            self.assertEqual({self.say(text) for _ in range(5)}.__len__(), 1)

    def test_a_greeting_followed_by_a_request_answers_the_request(self):
        reply = self.say("سلام، یک مبدل کیلومتر به مایل بساز")
        self.assertTrue(reply.startswith("سلام"), reply)
        self.assertIn("ساختم", reply)
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)

    def test_the_stored_name_is_used_in_greetings(self):
        learning = self.brain._learning()
        learning.teach("کاربر.نام", "عرفان", source="persian_nlu_v1", learning_method="persian_nlu_v1")
        self.assertIn("عرفان", self.say("سلام"))
        self.assertIn("عرفان", self.say("ممنون"))
        self.assertIn("عرفان", self.say("خداحافظ"))
        self.assertNotIn("عرفان", self.say("چه کارهایی بلدی؟"))

    def test_personal_facts_are_left_to_the_existing_persian_nlu(self):
        for text in ("من عرفان هستم", "اسم من عرفان است", "من پیتزا را دوست دارم", "اسم من چیست؟"):
            self.assertIsNone(self.say(text), text)
            self.assertFalse(self.brain.last_trace["claimed"])


class TestCapabilityConversation(BrainCase):
    def test_a_missing_capability_is_offered_not_faked(self):
        reply = self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("هنوز ندارم", reply)
        self.assertIn("بسازمش", reply)
        self.assertFalse(self.sb.exists())                      # nothing was built or even created
        self.assertEqual(self.pending_type(), "offer_build")

    def test_declining_the_offer_builds_nothing(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("انجام نمی‌دهم", self.say("نه"))
        self.assertFalse(self.sb.exists())
        self.assertIsNone(self.pending_type())

    def test_accepting_the_offer_builds_it_for_real_and_answers_the_original_question(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        reply = self.say("بله")
        self.assertIn("ساختم", reply)
        self.assertIn("۱۳ از ۱۳", reply)                         # the real test count of the real build
        self.assertIn("جواب سؤالت", reply)
        self.assertIn("۶٫۲۱۳۷۱۲", reply)
        record = self.sb.capability("unit_km_to_mi")
        self.assertEqual((record["version"], record["status"]), (1, "active"))
        self.assertIsNone(self.pending_type())
        self.assertIn("۱۲٫۴۲۷۴۲۴", self.say("۲۰ کیلومتر چند مایل است؟"))     # and it keeps working afterwards

    def test_text_tools_are_offered_built_and_used(self):
        reply = self.say("تعداد کلمات این متن را بشمار: سلام دنیای زیبا")
        self.assertIn("هنوز ندارم", reply)
        reply = self.say("بله")
        self.assertIn("ساختم", reply)
        self.assertIn("شمارش کلمات: ۳", reply)
        self.assertIn("شمارش کلمات: ۴", self.say("تعداد کلمات این متن را بشمار: یک دو سه چهار"))

    def test_a_question_about_a_capability_is_answered_honestly(self):
        reply = self.say("آیا تبدیل لیتر به گالن را بلدی؟")
        self.assertTrue(reply.startswith("نه"), reply)
        self.assertIn("هنوز ندارم", reply)
        self.assertFalse(self.sb.exists())
        self.say("نه")
        self.build_km()
        reply = self.say("آیا قابلیت تبدیل کیلومتر به مایل را داری؟")
        self.assertTrue(reply.startswith("بله"), reply)
        self.assertIn("نسخه‌ی ۱", reply)
        reply = self.say("آیا قابلیت تبدیل متر به فوت را داری؟")      # "the capability" + "do you have" still names ONE capability
        self.assertTrue(reply.startswith("نه"), reply)
        self.assertEqual(self.pending_type(), "offer_build")

    def test_a_build_request_that_misses_a_detail_is_clarified_then_built(self):
        reply = self.say("یک مبدل بساز")
        self.assertIn("کدام واحد", reply)
        self.assertEqual(self.pending_type(), "clarify_build")
        self.assertFalse(self.sb.exists())
        reply = self.say("کیلومتر به مایل")
        self.assertIn("ساختم", reply)
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        self.assertIsNone(self.pending_type())

    def test_the_brain_gives_up_on_a_clarification_that_never_gets_answered(self):
        self.say("یک مبدل بساز")
        self.assertIn("هنوز مطمئن نیستم", self.say("نمی‌دانم"))
        self.assertIn("هنوز مطمئن نیستم", self.say("فرقی نمی‌کند"))
        self.assertIn("کنار گذاشتم", self.say("هر چی"))
        self.assertIsNone(self.pending_type())
        self.assertFalse(self.sb.exists())

    def test_a_formula_with_persian_variable_names_is_built_and_the_safe_repair_is_reported(self):
        reply = self.say("یک ماشین حساب BMI بساز: وزن / (قد * قد)")
        self.assertIn("ساختم", reply)
        self.assertIn("به‌صورت امن اصلاح کردم", reply)
        self.assertIn("نام‌های فارسی متغیرها", reply)
        record = self.by_title("BMI")
        self.assertEqual((record["kind"], record["version"], record["status"]), ("formula", 1, "active"))

    def test_a_non_standard_factor_needs_confirmation_and_a_no_changes_nothing(self):
        self.build_km()
        text = "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است"
        reply = self.say(text)
        self.assertIn("بسازم؟", reply)
        self.assertIn("۰٫۶", reply)
        self.assertEqual(self.pending_type(), "confirm_build")
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)      # nothing yet
        self.assertIn("انجام نمی‌دهم", self.say("نه"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        self.say(text)
        reply = self.say("بله")
        self.assertIn("ارتقا دادم", reply)
        self.assertIn("نسخه‌ی ۲", reply)
        record = self.sb.capability("unit_km_to_mi")
        self.assertEqual((record["version"], [v["status"] for v in record["versions"]]), (2, ["superseded", "active"]))
        self.assertIn("۱۰ کیلومتر = ۶ مایل", self.say("۱۰ کیلومتر چند مایل است؟"))

    def test_asking_for_a_capability_that_already_exists_changes_nothing(self):
        self.build_km()
        reply = self.say("یک مبدل کیلومتر به مایل بساز")
        self.assertIn("همین حالا دارم", reply)
        self.assertEqual(len(self.sb.capability("unit_km_to_mi")["versions"]), 1)

    def test_what_cannot_be_built_is_said_plainly_and_nothing_is_created(self):
        for text in ("یک ربات پخش موسیقی بساز", "یک برنامه ویرایش عکس بساز"):
            reply = self.say(text)
            self.assertIn("نمی‌توانم", reply)
            self.assertIn("برنامه‌نویس", reply)
            self.assertNotIn("ساختم", reply)
        self.assertFalse(self.sb.exists())

    def test_a_failed_build_is_reported_as_failed_and_leaves_nothing_active(self):
        from self_builder import sandbox
        from self_builder.errors import SandboxError
        with mock.patch.object(sandbox, "load_module", side_effect=SandboxError("boom", code="E_SANDBOX_LOAD")):
            reply = self.say("یک مبدل کیلومتر به مایل بساز")
        self.assertIn("ساخت ناموفق بود", reply)
        self.assertIn("E_SANDBOX_LOAD", reply)
        self.assertNotIn("ساختم", reply)
        self.assertEqual(self.sb.capabilities(), [])
        self.assertIsNone(self.pending_type())
        self.assertIn("هنوز ندارم", self.say("۱۰ کیلومتر چند مایل است؟"))          # honest afterwards, too

    def test_usage_follow_ups_refer_to_the_last_capability(self):
        self.build_km()
        self.assertIn("۱۰ کیلومتر = ۶٫۲۱۳۷۱۲ مایل", self.say("۱۰ کیلومتر چند مایل است؟"))
        self.assertIn("۳۰ کیلومتر = ۱۸٫۶۴۱۱۳۶ مایل", self.say("برای ۳۰ چی؟"))
        self.assertIn("۵۰ کیلومتر", self.say("همان را برای ۵۰ حساب کن"))
        self.assertIn("۵۰ کیلومتر", self.say("دوباره"))
        reply = self.say("ادامه بده")                              # "go on" after a calculation explains how it was done
        self.assertIn("ضریب", reply)
        self.assertIn("۰٫۶۲۱۳۷۱۱۹۲", reply)

    def test_a_formula_asks_for_its_missing_values_and_remembers_the_ones_given(self):
        self.say("یک ماشین حساب BMI بساز: وزن / (قد * قد)")
        self.assertEqual(self.by_title("BMI")["version"], 1)
        reply = self.say("BMI را حساب کن")
        self.assertEqual(self.pending_type(), "ask_inputs")
        self.assertIn("وزن", reply)
        reply = self.say("وزن ۷۰")
        self.assertIn("قد", reply)
        reply = self.say("قد ۱٫۷۵")
        self.assertIn("۲۲٫۸۵", reply)
        self.assertIsNone(self.pending_type())

    def test_a_calculation_error_is_explained_and_does_not_break_the_capability(self):
        self.say("یک ماشین حساب BMI بساز: وزن / (قد * قد)")
        reply = self.say("BMI را با وزن ۷۰ و قد ۰ حساب کن")
        self.assertIn("تقسیم بر صفر", reply)
        self.assertIn("۲۲٫۸۵", self.say("BMI را با وزن ۷۰ و قد ۱٫۷۵ حساب کن"))


class TestFeedbackAndRollback(BrainCase):
    def test_feedback_is_recorded_against_the_version_that_answered(self):
        self.build_km()
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ثبت کردم", self.say("آفرین"))
        self.say("۲۰ کیلومتر چند مایل است؟")
        self.assertIn("ثبت کردم", self.say("اشتباه بود"))
        summary = self.sb.feedback_summary("unit_km_to_mi", 1)
        self.assertEqual((summary.get("positive"), summary.get("negative")), (1, 1))

    def test_feedback_without_an_answer_to_refer_to_records_nothing(self):
        self.assertNotIn("ثبت کردم", self.say("آفرین"))
        self.assertNotIn("ثبت کردم", self.say("اشتباه بود"))

    def test_negative_feedback_on_an_upgraded_capability_offers_the_rollback(self):
        self.two_versions()
        self.say("۱۰ کیلومتر چند مایل است؟")
        reply = self.say("اشتباه بود")
        self.assertIn("برگردانم", reply)
        self.assertEqual(self.pending_type(), "confirm_rollback")
        reply = self.say("بله")
        self.assertIn("برگشتم", reply)
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        self.assertIn("۶٫۲۱۳۷۱۲", self.say("۱۰ کیلومتر چند مایل است؟"))

    def test_rollback_by_command_by_version_number_and_back_again(self):
        self.two_versions()
        self.assertIn("نسخه‌ی ۱", self.say("به نسخه قبلی برگرد"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        reply = self.say("برگردان به نسخه ۲")
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 2)
        self.assertIn("نسخه‌ی ۲", reply)
        self.assertIn("نسخه‌ی ۱", self.say("به نسخه قبلی برگرد"))       # going forward did not spoil version 1
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        self.assertIn("۶٫۲۱۳۷۱۲", self.say("۱۰ کیلومتر چند مایل است؟"))

    def test_rollback_with_nothing_to_return_to_says_so_and_offers_to_switch_it_off(self):
        self.build_km()
        reply = self.say("به نسخه قبلی برگرد")
        self.assertIn("برای بازگشت ندارم", reply)
        self.assertIn("E_ROLLBACK_NO_TARGET", reply)
        self.assertIn("چیزی تغییر نکرد", reply)
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)
        self.assertEqual(self.pending_type(), "confirm_disable")
        self.assertIn("غیرفعال شد", self.say("بله"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "disabled")

    def test_disable_asks_first_and_a_rebuild_brings_the_capability_back(self):
        self.build_km()
        reply = self.say("قابلیت تبدیل کیلومتر به مایل را غیرفعال کن")
        self.assertIn("(بله / نه)", reply)
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "active")       # not before the answer
        self.assertIn("باشه، انجام نمی‌دهم", self.say("نه"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "active")
        self.say("قابلیت تبدیل کیلومتر به مایل را غیرفعال کن")
        self.assertIn("غیرفعال شد", self.say("بله"))
        self.assertIn("هنوز ندارم", self.say("۱۰ کیلومتر چند مایل است؟"))               # honest: it is switched off
        self.say("نه")
        self.build_km()
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "active")
        self.assertIn("۶٫۲۱۳۷۱۲", self.say("۱۰ کیلومتر چند مایل است؟"))


class TestRegistryCommands(BrainCase):
    def test_the_list_names_the_built_capabilities_and_the_builtin_abilities(self):
        reply = self.say("چه کارهایی بلدی؟")
        self.assertIn("گفت‌وگوی فارسی", reply)
        self.assertIn("هنوز قابلیتی برای خودم نساخته‌ام", reply)
        self.build_km()
        self.say("یک مبدل متر به فوت بساز")
        reply = self.say("قابلیت‌هایت را نشان بده")
        self.assertIn("تبدیل کیلومتر به مایل", reply)
        self.assertIn("تبدیل متر به فوت", reply)
        self.assertIn("(۲)", reply)

    def test_details_history_and_status(self):
        self.build_km()
        reply = self.say("جزئیات تبدیل کیلومتر به مایل")
        self.assertIn("تبدیل کیلومتر به مایل", reply)
        self.assertIn("نسخه", reply)
        reply = self.say("تاریخچه تغییرات")
        self.assertIn("ساخت «تبدیل کیلومتر به مایل»", reply)
        reply = self.say("وضعیت قابلیت‌ها را بررسی کن")
        self.assertPersian(reply)
        self.assertNotIn("خطا", reply)

    def test_help_and_examples(self):
        reply = self.say("راهنما")
        self.assertIn("بساز", reply)
        self.assertPersian(self.say("مثال بزن"))

    def test_commands_about_nothing_say_there_is_nothing(self):
        for text in ("به نسخه قبلی برگرد", "تاریخچه تغییرات", "جزئیات قابلیت تبدیل"):
            reply = self.say(text)
            self.assertPersian(reply)
            self.assertNotIn("ساختم", reply)
        self.assertFalse(self.sb.exists())


class TestKnowledgeAndTeaching(BrainCase):
    def test_taught_facts_are_stored_and_answered(self):
        self.assertIn("یاد گرفتم", self.say("یاد بگیر که پایتون یک زبان برنامه‌نویسی است"))
        reply = self.say("پایتون چیست؟")
        self.assertIn("زبان برنامه", reply)
        self.assertEqual(self.brain.last_trace["intent"]["kind"], "QUESTION")
        self.assertEqual(self.state()["last"]["kind"], "knowledge")
        self.assertPersian(self.say("ادامه بده"))

    def test_taught_facts_survive_a_restart(self):
        self.say("یاد بگیر که پایتون یک زبان برنامه‌نویسی است")
        self.open_app()
        self.assertIn("زبان برنامه", self.say("پایتون چیست؟"))

    def test_a_plain_statement_is_only_remembered_after_the_user_agrees(self):
        reply = self.say("زمین گرد است")
        self.assertIn("(بله / نه)", reply)
        self.assertEqual(self.pending_type(), "confirm_teach")
        self.assertIsNone(self.say("زمین چیست؟"))                 # nothing was learned yet (and the old question is dropped)
        self.say("زمین گرد است")
        self.assertIn("یاد گرفتم", self.say("بله"))
        self.assertIn("گرد", self.say("زمین چیست؟"))

    def test_declining_a_statement_stores_nothing(self):
        self.say("زمین گرد است")
        self.assertIn("یادداشت نکردم", self.say("نه"))
        self.assertIsNone(self.say("زمین چیست؟"))

    def test_an_incomplete_teaching_command_asks_for_the_sentence(self):
        reply = self.say("یاد بگیر")
        self.assertPersian(reply)
        self.assertNotIn("یاد گرفتم", reply)

    def test_unknown_knowledge_questions_are_left_to_the_existing_pipeline(self):
        self.assertIsNone(self.say("خورشید چیست؟"))
        self.assertIsNone(self.say("امروز هوا چطوره؟"))

    def test_likes_questions_use_the_stored_likes(self):
        self.assertIn("هنوز چیزی دربارهٔ علایقت نمی‌دانم", self.say("چی دوست دارم؟"))
        self.brain._learning().teach("کاربر.دوست_دارد.پیتزا", "پیتزا", source="persian_nlu_v1",
                                     learning_method="persian_nlu_v1")
        self.assertIn("پیتزا", self.say("چی دوست دارم؟"))


# ============================================================================ the open question
class TestPendingState(BrainCase):
    """A question the brain asked is state of the APPLICATION, not of the process: it lives in memory.db,
    so the app can be killed after the question and the answer still means the same thing."""

    def test_an_open_offer_survives_a_restart(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertEqual(self.pending_type(), "offer_build")
        self.open_app()
        self.assertEqual(self.pending_type(), "offer_build")
        reply = self.say("بله")
        self.assertIn("ساختم", reply)
        self.assertIn("جواب سؤالت", reply)
        self.assertIn("۶٫۲۱۳۷۱۲", reply)
        self.assertIsNone(self.pending_type())

    def test_an_open_clarification_survives_a_restart(self):
        self.say("یک مبدل بساز")
        self.open_app()
        self.assertEqual(self.pending_type(), "clarify_build")
        self.assertFalse(self.sb.exists())
        self.assertIn("ساختم", self.say("کیلومتر به مایل"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)

    def test_an_open_confirmation_survives_a_restart(self):
        self.build_km()
        self.say("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است")
        self.assertEqual(self.pending_type(), "confirm_build")
        self.open_app()
        self.assertEqual(self.pending_type(), "confirm_build")
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)           # still nothing changed
        self.assertIn("ارتقا دادم", self.say("بله"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 2)

    def test_the_values_given_so_far_survive_restarts_between_the_answers(self):
        self.say("یک ماشین حساب BMI بساز: وزن / (قد * قد)")
        self.say("BMI را حساب کن")
        self.open_app()
        reply = self.say("وزن ۷۰")
        self.assertIn("قد", reply)
        self.assertEqual(self.pending_type(), "ask_inputs")
        self.open_app()
        self.assertIn("۲۲٫۸۵", self.say("قد ۱٫۷۵"))
        self.assertIsNone(self.pending_type())

    def test_an_open_rollback_question_survives_a_restart(self):
        self.two_versions()
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.say("اشتباه بود")
        self.assertEqual(self.pending_type(), "confirm_rollback")
        self.open_app()
        self.assertIn("برگشتم", self.say("بله"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["version"], 1)

    def test_an_open_switch_off_question_survives_a_restart(self):
        self.build_km()
        self.say("قابلیت تبدیل کیلومتر به مایل را غیرفعال کن")
        self.open_app()
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "active")
        self.assertIn("غیرفعال شد", self.say("بله"))
        self.assertEqual(self.sb.capability("unit_km_to_mi")["status"], "disabled")

    def test_an_open_teaching_question_survives_a_restart(self):
        self.say("زمین گرد است")
        self.open_app()
        self.assertIn("یاد گرفتم", self.say("بله"))
        self.assertIn("گرد", self.say("زمین چیست؟"))

    def test_the_last_topic_survives_a_restart(self):
        self.build_km()
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.open_app()
        self.assertIn("۳۰ کیلومتر = ۱۸٫۶۴۱۱۳۶ مایل", self.say("برای ۳۰ چی؟"))
        self.assertIn("ضریب", self.say("ادامه بده"))

    # ------------------------------------------------------------------ expiry
    def test_a_question_nobody_answers_expires_and_nothing_happens(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS + 1)
        self.assertIn("سؤال بازی ندارم", self.say("بله"))
        self.assertFalse(self.sb.exists())                      # a late "yes" built nothing
        self.assertIsNone(self.pending_type())

    def test_a_question_that_is_still_fresh_is_answered(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS - 1)
        self.assertIn("ساختم", self.say("بله"))

    def test_the_lifetime_runs_on_across_a_restart(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.open_app()
        self.clock.advance(dlg_mod.PENDING_TTL_SECONDS + 1)
        self.assertIn("سؤال بازی ندارم", self.say("بله"))
        self.assertFalse(self.sb.exists())

    def test_every_answer_to_a_clarification_renews_its_lifetime(self):
        self.say("یک مبدل بساز")
        for _ in range(2):
            self.clock.advance(dlg_mod.PENDING_TTL_SECONDS - 60)
            self.assertIn("هنوز مطمئن نیستم", self.say("نمی‌دانم"))
        self.assertEqual(self.pending_type(), "clarify_build")

    # ------------------------------------------------------------ replacement
    def test_an_unrelated_message_drops_the_open_question(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("سلام", self.say("سلام"))
        self.assertIsNone(self.pending_type())
        self.assertIn("سؤال بازی ندارم", self.say("بله"))       # the old offer is gone: this yes builds nothing
        self.assertFalse(self.sb.exists())

    def test_a_new_build_request_replaces_the_open_offer(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ساختم", self.say("یک مبدل متر به فوت بساز"))
        self.assertIsNone(self.pending_type())
        titles = [c["title"] for c in self.sb.capabilities()]
        self.assertEqual(titles, ["تبدیل متر به فوت"])          # the offered km -> mi was NOT built behind the user's back
        self.assertIn("سؤال بازی ندارم", self.say("بله"))

    def test_a_new_question_replaces_the_open_offer(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.say("۱۰ متر چند فوت است؟")
        self.assertEqual(self.state()["pending"]["data"]["slots"], {"from_unit": "m", "to_unit": "ft"})
        self.assertIn("ساختم", self.say("بله"))
        self.assertEqual([c["title"] for c in self.sb.capabilities()], ["تبدیل متر به فوت"])

    def test_a_yes_is_answered_once_and_repeated_yes_answers_never_build_again(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ساختم", self.say("بله"))
        for _ in range(3):
            self.assertIn("سؤال بازی ندارم", self.say("بله"))
        self.assertEqual(len(self.sb.capability("unit_km_to_mi")["versions"]), 1)

    def test_a_bare_no_without_a_question_is_said_plainly(self):
        self.assertIn("سؤال بازی ندارم", self.say("نه"))
        self.assertIsNone(self.state())

    def test_cancel_closes_any_open_question(self):
        for first in ("۱۰ کیلومتر چند مایل است؟", "یک مبدل بساز", "زمین گرد است"):
            self.say(first)
            self.assertIsNotNone(self.pending_type(), first)
            self.assertIn("لغو شد", self.say("بی‌خیال"))
            self.assertIsNone(self.pending_type())
        self.assertFalse(self.sb.exists())

    # ----------------------------------------------------------------- damage
    def damaged(self, type_, data, attempts=0):
        self.memory.set_state(dlg_mod.STATE_KEY, {"v": 1, "last": None, "pending": {
            "type": type_, "ts": self.clock(), "attempts": attempts, "data": data}})

    DAMAGED = [
        ("offer_build", {}), ("offer_build", {"archetype": "unit_conversion", "slots": "bad"}),
        ("offer_build", {"archetype": "unit_conversion", "slots": {"from_unit": "km", "to_unit": "mi"}, "value": "abc"}),
        ("offer_build", {"archetype": "evil_kind", "slots": {"a": 1}}),
        ("offer_build", {"archetype": "unit_conversion", "slots": {"from_unit": "zzz", "to_unit": "yyy"}}),
        ("offer_build", {"archetype": "text_tool", "slots": {"ops": "bad"}}),
        ("confirm_build", {}), ("confirm_build", {"request": "bad"}),
        ("confirm_build", {"request": {"status": "ready", "kind": "evil", "slots": {}}}),
        ("confirm_build", {"request": {"status": "ready", "kind": "unit_conversion", "slots": {"from_unit": "km"}}}),
        ("confirm_rollback", {}), ("confirm_rollback", {"capability_id": 5}),
        ("confirm_rollback", {"capability_id": "../../etc/passwd"}),
        ("confirm_rollback", {"capability_id": "nonexistent", "version": 7}),
        ("confirm_disable", {}), ("confirm_disable", {"capability_id": "nonexistent"}),
        ("confirm_teach", {}), ("confirm_teach", {"sentence": 5}),
        ("clarify_build", {}), ("clarify_build", {"kind": "unit_conversion", "slots": "bad", "missing": "bad"}),
        ("ask_inputs", {}), ("ask_inputs", {"capability_id": "nonexistent"}),
    ]

    def test_a_damaged_open_question_never_breaks_a_conversation_or_builds_anything_unasked(self):
        for type_, data in self.DAMAGED:
            for answer in ("بله", "کیلومتر به مایل", "نه"):
                with self.subTest(type=type_, data=data, answer=answer):
                    self.damaged(type_, data)
                    reply = self.say(answer)
                    self.assertTrue(reply is None or (isinstance(reply, str) and reply.strip()), reply)
                    self.assertEqual(self.sb.capabilities(), [])      # whatever was damaged built nothing
                    self.assertIsNone(self.pending_type())            # and the question is gone afterwards
        self.assertEqual([e for e in self.memory.recent_errors(100) if e["operation"] == "persian_brain"], [])

    def test_damaged_state_of_any_kind_is_ignored(self):
        for raw in ("garbage", {"v": 2}, [1, 2, 3], 12, None, {"v": 1, "pending": "x", "last": "y"}):
            self.memory.set_state(dlg_mod.STATE_KEY, raw)
            self.assertIn("سلام", self.say("سلام"), raw)
            self.assertIn("سؤال بازی ندارم", self.say("بله"), raw)

    def test_a_damaged_open_question_is_answered_like_no_question(self):
        self.damaged("offer_build", {"archetype": "unit_conversion", "slots": "bad"})
        self.assertIn("سؤال بازی ندارم", self.say("بله"))
        self.assertEqual(self.state()["pending"], None)

    def test_a_question_that_only_fails_in_the_builder_is_reported_as_failed_not_as_built(self):
        self.damaged("offer_build", {"archetype": "unit_conversion", "slots": {"from_unit": "zzz", "to_unit": "yyy"}})
        reply = self.say("بله")
        self.assertIn("ساخت ناموفق بود", reply)
        self.assertNotIn("ساختم", reply)
        self.assertEqual(self.sb.capabilities(), [])


class TestOpenQuestionVersusNewRequest(BrainCase):
    """An open question is answered by an ANSWER. Another request, a question or just a sentence that has a number
    in it is never taken for one (it would silently put the wrong value into a calculation or a wrong name on a
    capability) - it replaces the open question, and the old half-finished request is dropped, not completed."""

    def bmi(self):
        self.say("یک ماشین حساب BMI بساز: وزن / (قد * قد)")
        return self.by_title("BMI")

    def test_a_complete_new_request_replaces_an_open_naming_question(self):
        self.say("یک ماشین حساب بساز: وزن / (قد * قد)")
        self.assertEqual(self.pending_type(), "clarify_build")                       # «what shall I call it?»
        reply = self.say("یک مبدل کیلومتر به مایل بساز")
        self.assertIn("ساختم", reply)
        self.assertEqual([c["title"] for c in self.sb.capabilities()], ["تبدیل کیلومتر به مایل"])
        self.assertIsNone(self.pending_type())                                       # nothing is left half-finished

    def test_a_new_formula_request_replaces_the_old_unnamed_one(self):
        self.say("یک ماشین حساب بساز: a + b")
        self.say("یک ماشین حساب بساز: x * y")
        self.assertEqual(self.state()["pending"]["data"]["slots"], {"expression": "x * y"})   # the NEW expression
        self.assertIn("ساختم", self.say("مجموع حاصلضرب"))
        (record,) = self.sb.capabilities()
        self.assertEqual(record["spec"]["expression"].replace(" ", ""), "x*y")

    def test_a_naming_answer_is_still_a_naming_answer(self):
        self.say("یک ماشین حساب بساز: وزن / (قد * قد)")
        self.assertIn("ساختم", self.say("شاخص توده بدنی"))
        self.assertEqual([c["title"] for c in self.sb.capabilities()], ["شاخص توده بدنی"])

    def test_a_new_request_with_numbers_is_not_taken_for_the_awaited_values(self):
        self.bmi()
        self.say("BMI را حساب کن")
        reply = self.say("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است")
        self.assertNotIn("BMI", reply)                                               # the old question is gone, not computed
        self.assertIn("بسازم؟", reply)                                                # the new request is handled as itself
        self.assertEqual(self.pending_type(), "confirm_build")

    def test_a_question_with_numbers_is_not_taken_for_the_awaited_values(self):
        self.bmi()
        self.say("BMI را حساب کن")
        reply = self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("کیلومتر به مایل", reply)
        self.assertNotIn("وزن", reply)
        self.assertEqual(self.pending_type(), "offer_build")

    def test_the_word_one_is_not_a_value_unless_it_answers(self):
        self.bmi()
        self.say("BMI را حساب کن")
        self.assertIn("ساختم", self.say("یک ابزار بساز که تعداد کلمات متن را بشمارد"))     # «یک» is not the number 1 here
        self.assertEqual([c["title"] for c in self.sb.capabilities()], ["BMI", "شمارش کلمات"])
        self.assertIsNone(self.pending_type())
        self.say("BMI را حساب کن")
        reply = self.say("یک روز خوب")                                                 # not an answer either: asked again
        self.assertIn("وزن", reply)
        self.assertEqual(self.pending_type(), "ask_inputs")
        self.assertEqual(self.state()["pending"]["data"]["have"], {})
        self.assertIn("وزن = ۱", self.say("وزن یک"))                                    # but «وزن یک» names a value: 1

    def test_named_bare_and_unit_answers_are_answers(self):
        self.bmi()
        self.say("BMI را حساب کن")
        self.assertIn("۲۲٫۸۵", self.say("۷۰ و ۱٫۷۵"))                                    # bare numbers, in order
        self.say("BMI را حساب کن")
        self.say("۷۰")
        self.assertEqual(self.state()["pending"]["data"]["have"], {"v1": 70.0})
        self.assertIn("۲۲٫۸۵", self.say("۱٫۷۵"))                                          # one at a time
        self.say("BMI را حساب کن")
        self.assertIn("۲۲٫۸۵", self.say("وزن ۷۰ کیلو و قد ۱٫۷۵ متر"))                      # named, with unit words
        self.say("BMI را حساب کن")
        self.assertIn("۲۲٫۸۵", self.say("قد=۱٫۷۵ وزن=۷۰"))

    def test_too_many_numbers_or_other_words_are_not_an_answer_and_it_gives_up_after_three(self):
        self.bmi()
        self.say("BMI را حساب کن")
        self.assertIn("وزن", self.say("۷۰ ۱٫۷۵ ۹"))                                      # three numbers for two values
        self.assertIn("وزن", self.say("امروز ۷۰ نفر آمدند"))                              # numbers inside a sentence
        self.assertEqual(self.pending_type(), "ask_inputs")
        self.assertIn("کنار گذاشتم", self.say("هر چی"))
        self.assertIsNone(self.pending_type())

    def test_a_question_mark_marks_a_new_topic_but_the_word_what_does_not(self):
        self.bmi()
        self.say("BMI را حساب کن")
        self.assertIn("وزن", self.say("هر چی"))                                          # «whatever»: still waiting
        self.assertEqual(self.pending_type(), "ask_inputs")
        self.assertIsNone(self.say("اسم تو چیست؟"))                                      # a real question: another topic
        self.assertIsNone(self.pending_type())

    def test_the_matcher_tells_answers_from_messages_with_numbers_in_them(self):
        from self_builder import matcher
        record = self.bmi()
        cases = [("۷۰", "bare"), ("۷۰ و ۱٫۷۵", "bare"), ("۷۰ کیلو", "bare"), ("وزن ۷۰", "named"), ("قد=۱٫۷۵", "named"),
                 ("وزن برابر ۷۰ است", "named"), ("یک", "bare"), ("۷۰ ۱٫۷۵ ۹", None), ("یک روز خوب", None),
                 ("۱۰ کیلومتر چند مایل است؟", None), ("یک مبدل کیلومتر به مایل بساز", None), ("نمی‌دانم", None),
                 ("", None)]
        for text, kind in cases:
            with self.subTest(text=text):
                self.assertEqual(matcher.value_answer(record, text)["kind"], kind)
        have = {"v1": 70.0}
        answer = matcher.value_answer(record, "۱٫۷۵", have)
        self.assertEqual((answer["kind"], answer["values"], answer["missing"]), ("bare", {"v1": 70.0, "v2": 1.75}, []))
        self.assertEqual(matcher.value_answer(record, "۱٫۷۵ ۹", have)["kind"], None)       # one value is missing, not two

    def test_a_compound_greeting_with_a_name_is_greeting_plus_statement(self):
        for text in ("سلام، من عرفان هستم", "سلام من عرفان هستم"):
            reply = self.say(text)
            self.assertIn("عرفان", reply, text)
            self.assertTrue(reply.startswith("سلام"), reply)
        self.assertEqual(self.brain._user_name(), "عرفان")
        for text in ("سلام دوست من", "سلام جان من", "سلام من"):
            self.assertIn("سلام", self.say(text))
            self.assertEqual(self.brain.last_trace["intent"]["slots"].get("rest"), None, text)       # a plain greeting


# ============================================================================ the other scopes
class TestCapabilitiesScope(BrainCase):
    """A plain library Core: only the capability domain is the brain's; everything else stays exactly as it
    always was (the application's own frozen tests pin that behaviour)."""
    scope = activation.SCOPE_CAPABILITIES

    def test_social_talk_is_left_to_the_existing_pipeline(self):
        for text in ("سلام", "صبح بخیر", "ممنون", "خداحافظ", "حالت چطوره؟", "مرسی از کمکت", "شب خوش"):
            self.assertIsNone(self.say(text), text)
            self.assertFalse(self.brain.last_trace["claimed"])
            self.assertEqual(self.brain.last_trace["scope"], "capabilities")

    def test_teaching_statements_knowledge_and_personal_memory_are_left_alone(self):
        for text in ("یاد بگیر که پایتون یک زبان برنامه‌نویسی است", "زمین گرد است", "پایتون چیست؟", "چی دوست دارم؟",
                     "اسم من چیست؟", "من عرفان هستم", "امروز هوا چطوره؟"):
            self.assertIsNone(self.say(text), text)
        self.assertFalse(self.sb.exists())

    def test_a_bare_yes_no_go_on_or_that_one_are_left_alone_without_a_question(self):
        for text in ("بله", "نه", "ادامه بده", "همان را دوباره", "برای ۳۰ چی؟", "آفرین", "اشتباه بود"):
            self.assertIsNone(self.say(text), text)
        self.assertIsNone(self.state())

    def test_the_capability_domain_is_fully_the_brains(self):
        self.assertIn("هنوز ندارم", self.say("۱۰ کیلومتر چند مایل است؟"))
        self.assertIn("ساختم", self.say("بله"))
        self.assertIn("۲۰ کیلومتر = ۱۲٫۴۲۷۴۲۴ مایل", self.say("۲۰ کیلومتر چند مایل است؟"))
        self.assertIn("تبدیل کیلومتر به مایل", self.say("چه کارهایی بلدی؟"))
        self.assertIn("نسخه", self.say("جزئیات تبدیل کیلومتر به مایل"))
        self.assertIn("ساخت «تبدیل کیلومتر به مایل»", self.say("تاریخچه تغییرات"))
        self.assertIn("بله", self.say("آیا قابلیت تبدیل کیلومتر به مایل را داری؟")[:3])
        self.assertIn("(بله / نه)", self.say("قابلیت تبدیل کیلومتر به مایل را غیرفعال کن"))
        self.assertIn("غیرفعال شد", self.say("بله"))
        self.assertPersian(self.say("راهنما"))

    def test_a_compound_greeting_answers_only_the_request(self):
        reply = self.say("سلام، یک مبدل کیلومتر به مایل بساز")
        self.assertFalse(reply.startswith("سلام"), reply)
        self.assertIn("ساختم", reply)

    def test_feedback_is_the_brains_only_after_one_of_its_own_answers(self):
        self.assertIsNone(self.say("آفرین"))
        self.build_km()
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ثبت کردم", self.say("آفرین"))

    def test_yes_no_answers_to_its_own_questions_work_in_this_scope_too(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("انجام نمی‌دهم", self.say("نه"))
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ساختم", self.say("بله"))


class TestOffScope(BrainCase):
    scope = activation.SCOPE_OFF

    def test_everything_is_left_to_the_existing_pipeline_and_nothing_is_created(self):
        for text in ("سلام", "یک مبدل کیلومتر به مایل بساز", "۱۰ کیلومتر چند مایل است؟", "بله", "چه کارهایی بلدی؟",
                     "یاد بگیر که پایتون یک زبان است"):
            self.assertIsNone(self.say(text), text)
            self.assertIsNone(self.brain.last_trace)
        self.assertFalse(self.sb.exists())
        self.assertIsNone(self.state())
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.db)) if not n.startswith("memory.db")], [])

    def test_the_scope_can_be_changed_while_the_app_runs(self):
        self.assertIsNone(self.say("سلام"))
        activation.enable(self.memory, activation.SCOPE_FULL)
        self.assertIn("سلام", self.say("سلام"))
        activation.disable(self.memory)
        self.assertIsNone(self.say("سلام"))

    def test_an_explicit_scope_argument_wins_over_the_activation_state(self):
        self.assertIsNone(self.brain.respond("سلام"))
        self.assertIn("سلام", self.brain.respond("سلام", scope=activation.SCOPE_FULL))
        self.assertIsNone(self.brain.respond("سلام", scope=activation.SCOPE_CAPABILITIES))


class TestRegistryUnavailable(BrainCase):
    """The registry is on the device but cannot be opened (a damaged database): the brain must neither claim
    «I do not have it» nor offer to build over it - it says it cannot tell, and changes nothing."""

    def damage(self):
        self.build_km()
        self.close_app()
        path = os.path.join(self.tmp, "data", "self_builder", "self_builder.db")
        with open(path, "wb") as f:
            f.write(b"this is not a database" * 100)
        self.open_app()

    def test_questions_and_commands_about_capabilities_say_the_registry_is_unavailable(self):
        self.damage()
        self.assertIsNotNone(self.sb.unavailable())
        for text in ("۱۰ کیلومتر چند مایل است؟", "آیا قابلیت تبدیل کیلومتر به مایل را داری؟", "تاریخچه تغییرات",
                     "به نسخه قبلی برگرد", "قابلیت تبدیل کیلومتر به مایل را غیرفعال کن",
                     "تعداد کلمات این متن را بشمار: سلام دنیا"):
            reply = self.say(text)
            self.assertIn("باز نمی‌شود", reply, text)
            self.assertIn("E_STORE_OPEN", reply)
            self.assertNotIn("هنوز ندارم", reply)
            self.assertNotIn("بسازمش", reply)
            self.assertIsNone(self.pending_type())

    def test_the_list_keeps_the_builtin_abilities_and_says_what_it_cannot_list(self):
        self.damage()
        reply = self.say("چه کارهایی بلدی؟")
        self.assertIn("گفت‌وگوی فارسی", reply)
        self.assertIn("باز نمی‌شود", reply)
        self.assertNotIn("هنوز قابلیتی برای خودم نساخته‌ام", reply)

    def test_the_status_report_shows_the_error_code(self):
        self.damage()
        self.assertIn("E_STORE_OPEN", self.say("وضعیت قابلیت‌ها را بررسی کن"))

    def test_a_build_is_refused_and_nothing_is_overwritten(self):
        self.damage()
        path = os.path.join(self.tmp, "data", "self_builder", "self_builder.db")

        def content():
            with open(path, "rb") as f:
                return f.read()

        before = content()
        reply = self.say("یک مبدل متر به فوت بساز")
        self.assertIn("E_STORE_OPEN", reply)
        self.assertNotIn("ساختم", reply)
        self.assertEqual(content(), before)                     # the damaged database was left exactly as it was

    def test_ordinary_conversation_is_not_affected(self):
        self.damage()
        self.assertIn("سلام", self.say("سلام"))
        self.say("یاد بگیر که پایتون یک زبان برنامه‌نویسی است")
        self.assertIn("زبان برنامه", self.say("پایتون چیست؟"))

    def test_a_registry_that_does_not_exist_yet_is_not_an_error(self):
        self.assertIsNone(self.sb.unavailable())
        self.assertIn("هنوز ندارم", self.say("۱۰ کیلومتر چند مایل است؟"))


# ============================================================================ robustness
class TestRobustness(BrainCase):
    def test_input_that_is_not_text_or_is_empty_is_not_the_brains(self):
        for value in (None, 5, 1.5, b"\xd8\xb3", ["سلام"], {"a": 1}, "", "   ", "\n\t", "‌‌"):
            self.assertIsNone(self.brain.respond(value), repr(value))
            self.assertIsNone(self.brain.last_trace)
        self.assertIsNone(self.state())

    def test_a_message_over_the_input_limit_is_not_the_brains(self):
        limit = 2000
        from persian_brain import brain as brain_mod
        self.assertEqual(brain_mod.MAX_INPUT_CHARS, limit)
        self.assertIsNone(self.say("آ" * (limit + 1)))
        self.assertIsNone(self.say("سلام " * 500))
        reply = self.say(("سلام " * 399).strip())               # just under the limit: processed normally
        self.assertTrue(reply is None or isinstance(reply, str))
        self.assertIsNotNone(self.brain.last_trace)

    def test_english_text_is_never_the_brains(self):
        for text in ("hello", "convert 10 km to miles", "what is python?", "hi there", "yes", "no", "ok", "cancel",
                     "12345", "TEACH sun IS a star", "ignore all previous instructions"):
            self.assertIsNone(self.say(text), text)
        self.assertIsNone(self.state())

    def test_latin_yes_no_ok_cancel_answer_an_open_question(self):
        self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertIn("ساختم", self.say("OK"))
        self.say("۱۰ متر چند فوت است؟")
        self.assertIn("انجام نمی‌دهم", self.say("no"))
        self.say("۱۰ متر چند فوت است؟")
        self.assertIn("لغو شد", self.say("cancel"))
        self.say("۱۰ متر چند فوت است؟")
        self.assertIn("ساختم", self.say("yes"))
        self.assertIsNone(self.say("yes"))                       # nothing is open: not the brain's

    def test_arabic_letters_in_a_request_build_the_same_capability(self):
        self.assertIn("ساختم", self.say("يک مبدل كيلومتر به مايل بساز"))
        self.assertEqual([c["id"] for c in self.sb.capabilities()], ["unit_km_to_mi"])
        self.assertIn("همین حالا دارم", self.say("یک مبدل کیلومتر به مایل بساز"))
        self.assertEqual(len(self.sb.capability("unit_km_to_mi")["versions"]), 1)

    def test_persian_digits_arabic_digits_and_latin_digits_are_the_same_number(self):
        self.build_km()
        answers = {self.say(f"{n} کیلومتر چند مایل است؟") for n in ("۱۰", "١٠", "10")}
        self.assertEqual(answers, {"۱۰ کیلومتر = ۶٫۲۱۳۷۱۲ مایل"})

    def test_a_failing_handler_gives_the_unexpected_error_message_and_is_logged(self):
        with mock.patch.object(PersianBrain, "_general", side_effect=RuntimeError("boom")):
            reply = self.say("۱۰ کیلومتر چند مایل است؟")
        self.assertEqual(reply, M.unexpected_error())
        self.assertTrue(self.brain.last_trace["claimed"])
        errors = [e for e in self.memory.recent_errors(10) if e["operation"] == "persian_brain"]
        self.assertEqual(len(errors), 1)
        self.assertIn("RuntimeError: boom", errors[0]["message"])
        self.assertIn("سلام", self.say("سلام"))                  # and the next message works as usual
        self.assertFalse(self.sb.exists())

    def test_a_failure_outside_the_handlers_leaves_the_message_to_the_existing_pipeline(self):
        with mock.patch.object(dlg_mod.Dialogue, "load", side_effect=RuntimeError("boom")):
            self.assertIsNone(self.say("سلام"))
        self.assertIsNone(self.brain.last_trace)
        errors = [e for e in self.memory.recent_errors(10) if e["operation"] == "persian_brain"]
        self.assertEqual(len(errors), 1)
        self.assertIn("سلام", self.say("سلام"))

    def test_a_broken_error_log_does_not_hide_the_original_problem_either(self):
        with mock.patch.object(dlg_mod.Dialogue, "load", side_effect=RuntimeError("boom")), \
                mock.patch.object(self.memory, "log_error", side_effect=RuntimeError("log broken")):
            self.assertIsNone(self.say("سلام"))

    def test_a_dialogue_state_that_cannot_be_written_does_not_break_the_answer(self):
        with mock.patch.object(self.memory, "set_state", side_effect=RuntimeError("disk full")):
            self.assertIn("هنوز ندارم", self.say("۱۰ کیلومتر چند مایل است؟"))
        self.assertIsNone(self.pending_type())                   # not stored: the next «بله» is honest about it
        self.assertIn("سؤال بازی ندارم", self.say("بله"))
        self.assertFalse(self.sb.exists())

    def test_concurrent_messages_are_serialised_and_all_answered(self):
        import threading
        results, errors = [], []

        def worker():
            try:
                for text in ("سلام", "۱۰ کیلومتر چند مایل است؟", "چه کارهایی بلدی؟", "ممنون"):
                    results.append((text, self.brain.respond(text)))
            except BaseException as e:                           # pragma: no cover - reported below
                errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 32)
        by_text = {}
        for text, reply in results:
            by_text.setdefault(text, set()).add(reply)
        for text, replies in by_text.items():
            self.assertEqual(len(replies), 1, text)              # one and the same answer, whatever the interleaving
            self.assertTrue(None not in replies)
        self.assertFalse(self.sb.exists())

    def test_a_long_random_conversation_never_raises_and_never_builds_anything_unasked(self):
        words = ("سلام چطوری ممنون خداحافظ چیست چه چرا کجا کی چند کیلومتر مایل متر فوت لیتر گالن وزن قد تبدیل قابلیت نسخه "
                 "تاریخچه جزئیات راهنما مثال ادامه همان دوباره آفرین اشتباه برگرد غیرفعال وضعیت یاد بگیر زمین گرد است پایتون "
                 "زبان من تو او را برای با از به در که یک ۱۰ ۲۰ ۳٫۵ ؟ ! . ،").split()
        rng = random.Random(20261010)
        for _ in range(400):
            text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 9)))
            reply = self.brain.respond(text)
            self.assertTrue(reply is None or (isinstance(reply, str) and reply.strip()), text)
        self.assertEqual([e for e in self.memory.recent_errors(100) if e["operation"] == "persian_brain"], [])
        self.assertFalse(self.sb.exists())                       # without a build request (and no «بله») nothing is built


# ============================================================================ the one seam into Core
from core.core import Core                              # noqa: E402
import runtime_integration.bridge as runtime_bridge      # noqa: E402


class CoreCase(unittest.TestCase):
    """The real Core (the application's own conversation pipeline) in a temporary directory, as a plain
    desktop library would run it. `open_core()` is "the process starts" on the same files."""

    def setUp(self):
        import platform_layer
        self.platform_layer = platform_layer
        self.tmp = tempfile.mkdtemp(prefix="pbcore_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        original = platform_layer.get_platform()
        self.addCleanup(platform_layer.set_platform, original)
        platform_layer.set_platform(platform_layer.DesktopPlatformAdapter(data_dir=self.tmp))
        silence = mock.patch.object(platform_layer.DesktopPlatformAdapter, "log")        # Core's start-up log line
        silence.start()
        self.addCleanup(silence.stop)
        env = dict(os.environ)
        env.pop(activation.ENV_VAR, None)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cores = []
        self.addCleanup(self.close_all)
        self.core = self.open_core()

    def open_core(self, sub="app"):
        base = os.path.join(self.tmp, sub)
        core = Core(memory_db_path=os.path.join(base, "data", "memory.db"),
                    skill_definitions_dir=os.path.join(base, "skills"))
        self.cores.append(core)
        return core

    def restart(self, sub="app"):
        self.close_all()
        self.core = self.open_core(sub)
        return self.core

    def close_all(self):
        cores, self.cores = self.cores, []
        for core in cores:
            try:
                sb_service.get_service(core.memory).close()
            finally:
                core.memory._conn.close()


class TestSkillSeam(CoreCase):
    LEGACY = ("hello", "سلام", "ممنون", "بله", "پایتون چیست؟", "TEACH sun IS a star", "what is sun?",
              "من عرفان هستم", "اسم من چیست؟")

    def test_the_brain_reaches_the_conversation_through_the_skill_system(self):
        skill = self.core.skills.find_matching_skill("یک مبدل کیلومتر به مایل بساز")
        self.assertEqual(skill["name"], "persian_conversation")
        self.assertIs(skill["dynamic"], True)
        self.assertEqual(skill["trigger"], {"type": "dynamic"})
        self.assertIn("ساختم", skill["response"])
        self.assertIsNone(self.core.skills.find_matching_skill("pure english sentence nobody handles"))

    def test_a_plain_core_answers_everything_but_the_capability_domain_exactly_as_before(self):
        a = self.core
        b = self.open_core("other")
        activation.disable(b.memory)                                      # the brain switched off completely
        for text in self.LEGACY:
            self.assertEqual(a.process_input(text), b.process_input(text), text)
        self.assertEqual(activation.scope_for(a.memory), "capabilities")

    def test_the_english_greeting_skill_is_unchanged_in_every_scope(self):
        for scope in ("capabilities", "full", "off"):
            activation.enable(self.core.memory, scope)
            self.assertTrue(self.core.process_input("hello").startswith("Hello!"), scope)

    def test_the_capability_domain_works_in_a_plain_core_and_survives_a_restart(self):
        self.assertIn("هنوز ندارم", self.core.process_input("۱۰ کیلومتر چند مایل است؟"))
        self.restart()
        self.assertIn("ساختم", self.core.process_input("بله"))
        self.restart()
        self.assertIn("۲۰ کیلومتر = ۱۲٫۴۲۷۴۲۴ مایل", self.core.process_input("۲۰ کیلومتر چند مایل است؟"))
        self.assertIn("تبدیل کیلومتر به مایل", self.core.process_input("چه کارهایی بلدی؟"))

    def test_inside_the_application_runtime_the_whole_conversation_is_persian(self):
        self.platform_layer.set_platform(FakePlatform())                   # what android_entry.start() installs
        self.assertEqual(activation.scope_for(self.core.memory), "full")
        for text, expected in (("سلام", "سلام"), ("ممنون", "خواهش"), ("خداحافظ", "خداحافظ"), ("صبح بخیر", "بخیر")):
            self.assertIn(expected, self.core.process_input(text), text)

    def test_the_environment_switch_turns_the_whole_conversation_on_for_a_library_core(self):
        with mock.patch.dict(os.environ, {activation.ENV_VAR: "1"}):
            self.assertIn("سلام", self.core.process_input("سلام"))
        self.assertNotIn("خوشحالم که اینجایی", self.core.process_input("سلام"))      # and off again without it

    def test_the_stored_name_comes_from_the_existing_persian_nlu(self):
        activation.enable(self.core.memory, "full")
        self.assertIn("عرفان", self.core.process_input("من عرفان هستم"))               # the existing step stored it
        self.assertIn("عرفان", self.core.process_input("سلام"))
        self.assertIn("عرفان", self.core.process_input("ممنون"))
        self.assertEqual(self.core.process_input("اسم من چیست؟"), "اسمت عرفان است.")      # and it still answers that
        self.restart()
        activation.enable(self.core.memory, "full")
        self.assertIn("عرفان", self.core.process_input("سلام"))

    def test_a_compound_greeting_stores_the_fact_and_answers(self):
        activation.enable(self.core.memory, "full")
        reply = self.core.process_input("سلام، من عرفان هستم")
        self.assertIn("عرفان", reply)
        self.assertEqual(self.core.process_input("اسم من چیست؟"), "اسمت عرفان است.")

    def test_a_failing_brain_leaves_the_message_to_the_existing_pipeline(self):
        activation.enable(self.core.memory, "full")
        other = self.open_core("other")
        activation.disable(other.memory)
        with mock.patch.object(PersianBrain, "respond", side_effect=RuntimeError("boom")):
            failing = self.core.process_input("سلام")
        self.assertEqual(failing, other.process_input("سلام"))                # exactly what the application said before
        self.assertTrue(self.core.process_input("hello").startswith("Hello!"))

    def test_a_failing_activation_check_does_the_same(self):
        activation.enable(self.core.memory, "full")
        with mock.patch.object(activation, "scope_for", side_effect=RuntimeError("boom")):
            reply = self.core.process_input("سلام")
        self.assertNotIn("خوشحالم که اینجایی", reply)

    def test_ael_commands_never_reach_the_brain(self):
        activation.enable(self.core.memory, "full")
        with mock.patch.object(PersianBrain, "respond", side_effect=AssertionError("the brain must not see AEL")) as m:
            self.assertIn("[AEL OK]", self.core.process_input("TEACH sun IS a star"))
            self.assertEqual(self.core.process_input("what is sun?"), "a star")  # a legacy question is answered by the old path
        self.assertEqual(m.call_count, 1)                                     # only the conversation question was offered to it

    def test_the_reply_is_labelled_as_a_skill_answer_for_the_runtime_bridge(self):
        activation.enable(self.core.memory, "full")
        self.core._turn_state = {}
        self.core.process_input("سلام")
        self.assertEqual(self.core._turn_state["source"], runtime_bridge.SOURCE_SKILL)
        self.assertEqual(runtime_bridge.SOURCE_SKILL, "skill")

    def test_the_reply_and_the_question_are_logged_like_any_other_turn(self):
        activation.enable(self.core.memory, "full")
        self.core.process_input("سلام")
        rows = self.core.memory.query("SELECT role, content FROM conversation_log ORDER BY id")
        self.assertEqual([r["role"] for r in rows[-2:]], ["user", "assistant"])
        self.assertIn("سلام", rows[-1]["content"])

    def test_a_plain_core_has_no_registry_after_ordinary_conversation(self):
        for text in self.LEGACY:
            self.core.process_input(text)
        self.assertFalse(sb_service.get_service(self.core.memory).exists())
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "app", "data", "self_builder")))


# ============================================================================ no side effects
def tree_state(root):
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        state[os.path.relpath(dirpath, root)] = "dir"
        for name in filenames:
            st = os.stat(os.path.join(dirpath, name))
            state[os.path.relpath(os.path.join(dirpath, name), root)] = (st.st_size, st.st_mtime_ns)
    return state


class TestNoSideEffects(BrainCase):
    def test_importing_the_packages_creates_nothing_and_loads_nothing_else(self):
        import subprocess
        cwd = tempfile.mkdtemp(prefix="pbcwd_")
        self.addCleanup(shutil.rmtree, cwd, ignore_errors=True)
        code = ("import sys, json, threading\n"
                "import persian_brain, self_builder\n"
                "lazy = sorted(m for m in sys.modules if m.split('.')[0] in ('persian_brain', 'self_builder'))\n"
                "import persian_brain.brain, self_builder.service\n"
                "print(json.dumps({'lazy': lazy, 'threads': threading.active_count()}))\n")
        env = {"PYTHONPATH": SRC_DIR, "PYTHONDONTWRITEBYTECODE": "1", "PATH": os.environ.get("PATH", ""),
               "HOME": cwd, "TMPDIR": cwd}
        out = subprocess.run([sys.executable, "-B", "-c", code], cwd=cwd, env=env, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        info = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(info["lazy"], ["persian_brain", "self_builder"])       # the packages themselves: nothing more
        self.assertEqual(info["threads"], 1)
        self.assertEqual(os.listdir(cwd), [])                                  # not a file, not a directory

    def conversation(self):
        for text in ("سلام", "۱۰ کیلومتر چند مایل است؟", "بله", "۲۰ کیلومتر چند مایل است؟", "آفرین",
                     "یک ماشین حساب BMI بساز: وزن / (قد * قد)", "BMI را با وزن ۷۰ و قد ۱٫۷۵ حساب کن",
                     "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است", "بله", "اشتباه بود", "بله",
                     "چه کارهایی بلدی؟", "تاریخچه تغییرات", "وضعیت قابلیت‌ها را بررسی کن",
                     "قابلیت تبدیل کیلومتر به مایل را غیرفعال کن", "بله", "یاد بگیر که پایتون یک زبان است"):
            self.assertIsNotNone(self.say(text), text)

    def test_a_whole_conversation_uses_no_network_and_starts_no_process(self):
        import socket
        import subprocess

        def forbidden(*args, **kwargs):
            raise AssertionError("the conversation must not use the network or start a process")

        with mock.patch.object(socket.socket, "connect", forbidden), \
                mock.patch.object(socket, "create_connection", forbidden), \
                mock.patch.object(socket, "getaddrinfo", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(os, "system", forbidden), \
                mock.patch.object(os, "popen", forbidden):
            self.conversation()
        self.assertEqual([e for e in self.memory.recent_errors(100) if e["operation"] == "persian_brain"], [])

    def test_the_application_source_tree_is_not_written_to(self):
        before = tree_state(SRC_DIR)
        self.conversation()
        self.assertEqual(tree_state(SRC_DIR), before)

    def test_everything_the_conversation_writes_is_inside_the_data_directory(self):
        self.conversation()
        data = os.path.dirname(self.db)
        top = sorted(os.listdir(self.tmp))
        self.assertEqual(top, ["data"])
        self.assertEqual(sorted(n for n in os.listdir(data) if not n.startswith("memory.db")), ["self_builder"])


# ============================================================================ no table of replies
class TestNoResponseTable(unittest.TestCase):
    """The brain answers from facts (the stored name, the taught sentences, the capability registry, the dialogue
    state) through small word lists and parameterised message templates. This test reads the SOURCE and proves
    that there is no table of «message -> answer» (a «giant response dictionary») anywhere in the package."""

    IDENTIFIER = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]*$")          # machine names: stage, kind, error code

    def modules(self):
        for name in sorted(os.listdir(BRAIN_DIR)):
            if name.endswith(".py"):
                path = os.path.join(BRAIN_DIR, name)
                with open(path, encoding="utf-8") as f:
                    yield name, ast.parse(f.read(), filename=path)

    @staticmethod
    def persian(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and nz.has_persian_script(node.value)

    @staticmethod
    def docstring_ids(tree):
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
        return ids

    def test_a_dictionary_that_holds_persian_sentences_is_keyed_by_machine_states(self):
        """A table of «what the user says -> what I answer» would map (Persian) text to Persian text. The dictionaries
        that exist are closed enumerations: archetype / stage / error-code / day-part names -> a short label, or a
        spoken word -> an internal class name."""
        looked_at = 0
        for name, tree in self.modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                if not any(self.persian(v) for v in node.values):
                    continue
                for key in node.keys:
                    looked_at += 1
                    if isinstance(key, ast.Constant):
                        self.assertRegex(key.value, self.IDENTIFIER, f"{name}:{node.lineno}: {key.value!r}")
                    else:
                        self.assertIsInstance(key, (ast.Name, ast.Attribute), f"{name}:{node.lineno}")
        self.assertGreaterEqual(looked_at, 20)                                    # (the scan really looked at the tables)

    def test_no_dictionary_maps_persian_text_to_persian_text(self):
        for name, tree in self.modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    pairs = [1 for k, v in zip(node.keys, node.values)
                             if k is not None and self.persian(k) and self.persian(v)]
                    self.assertEqual(pairs, [], f"{name}:{node.lineno}")

    def test_a_long_list_of_persian_strings_is_a_vocabulary_of_words_and_short_phrases_never_of_replies(self):
        seen = 0
        for name, tree in self.modules():
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                    strings = [e for e in node.elts if self.persian(e)]
                    if len(strings) > 8:
                        seen += 1
                        for e in strings:
                            self.assertLessEqual(len(e.value.split()), 3, f"{name}:{e.lineno}: {e.value!r}")
        self.assertGreaterEqual(seen, 1)

    def test_the_matching_code_holds_words_and_short_phrases_never_sentences(self):
        """normalization / intents / dialogue / activation / lexicon: no Persian sentence at all (a vocabulary
        inside word_set(...) may be long; every other constant is a word or a phrase of at most five words)."""
        checked = 0
        for name, tree in self.modules():
            if name not in ("normalization.py", "intents.py", "dialogue.py", "activation.py", "lexicon.py", "__init__.py"):
                continue
            docs = self.docstring_ids(tree)
            in_word_set = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "word_set":
                    in_word_set.update(id(a) for a in node.args)
            for node in ast.walk(tree):
                if self.persian(node) and id(node) not in docs:
                    checked += 1
                    if id(node) in in_word_set:
                        for word in node.value.split():
                            self.assertNotIn(" ", word)
                    else:
                        self.assertLessEqual(len(node.value.split()), 5, f"{name}:{node.lineno}: {node.value!r}")
        self.assertGreaterEqual(checked, 300)

    def test_every_sentence_the_brain_says_is_a_template_inside_a_function(self):
        """messages.py: the module-level containers hold at most a handful of strings (labels / capability names),
        everything else is a function that builds its sentence from the facts it is given."""
        (tree,) = [t for n, t in self.modules() if n == "messages.py"]
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                strings = [n for n in ast.walk(node.value) if self.persian(n)]
                self.assertLessEqual(len(strings), 8, f"messages.py:{node.lineno}")
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.assertGreaterEqual(len(functions), 60)                             # many small templates, not one big table
        with_parameters = [f for f in functions if f.args.args]
        self.assertGreaterEqual(len(with_parameters), len(functions) // 2)      # and most of them are filled with facts

    def test_unknown_messages_get_no_invented_answer(self):
        tmp = tempfile.mkdtemp(prefix="pbnt_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        mem = MemorySystem(os.path.join(tmp, "data", "memory.db"))
        self.addCleanup(mem._conn.close)
        activation.enable(mem, activation.SCOPE_FULL)
        brain = PersianBrain(mem)
        for text in ("خورشید چیست؟", "امروز هوا چطوره؟", "پایتخت فرانسه کجاست؟", "فیلم دیشب را دیدی؟", "چرا آسمان آبی است؟",
                     "بهترین کتاب کدام است؟"):
            self.assertIsNone(brain.respond(text), text)

    def test_the_replies_follow_the_facts_not_the_wording_of_a_table(self):
        """Same sentence, different stored facts -> different (and correct) answers."""
        tmp = tempfile.mkdtemp(prefix="pbnt_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        brains = []
        for sub in ("a", "b"):
            mem = MemorySystem(os.path.join(tmp, sub, "memory.db"))
            self.addCleanup(mem._conn.close)
            activation.enable(mem, activation.SCOPE_FULL)
            brains.append(PersianBrain(mem))
        a, b = brains
        for brain, name, fact in ((a, "سارا", "گرد است"), (b, "نیما", "مسطح است")):
            brain._learning().teach("کاربر.نام", name, source="persian_nlu_v1", learning_method="persian_nlu_v1")
            brain._learning().teach("زمین", fact, source="persian_brain_v1", learning_method="persian_brain_v1")
        self.assertIn("سارا", a.respond("سلام"))
        self.assertIn("نیما", b.respond("سلام"))
        self.assertNotIn("نیما", a.respond("سلام"))
        self.assertIn("گرد", a.respond("زمین چیست؟"))
        self.assertIn("مسطح", b.respond("زمین چیست؟"))
