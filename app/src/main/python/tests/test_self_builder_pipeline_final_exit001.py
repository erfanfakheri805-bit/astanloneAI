"""
FINAL-EXIT-001 - Self-Builder pipeline.

Tests of everything that sits on top of the foundations (see
test_self_builder_foundations_final_exit001.py): the Persian request analysis, the safe repairs,
the invocation matcher, the persistent store / registry / workspace, the startup reconciliation
(tampering, crashes, orphans), the build -> validate -> test -> repair -> apply -> persist ->
register -> version -> audit pipeline itself (with injected failures at every stage), rollback,
disable, limits, the memory mirror, the lazy service facade, thread safety and persistence
across real, abruptly terminated processes.

Every test works in its own temporary directory; nothing is ever written into the source tree.

Run directly:
    python -m unittest tests.test_self_builder_pipeline_final_exit001 -v
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_builder import (builder as builder_mod, loader, matcher, mirror, policy, repair, request_parser as rp,
                          sandbox, store as store_mod, templates, units, validator)
from self_builder import spec as spec_mod
from self_builder.errors import PolicyViolation, StoreError
from self_builder.registry import Registry
from self_builder.service import SelfBuilderService, default_root, get_service
from self_builder.store import Store
from self_builder.workspace import Workspace

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================================ helpers
class TempDirCase(unittest.TestCase):
    """A fresh temporary directory per test; services opened through `self.service()` are closed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb_pipe_")
        self.root = os.path.join(self.tmp, "self_builder")
        self._services = []
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self._close_services)

    def _close_services(self):
        for svc in self._services:
            try:
                svc.close()
            except Exception:
                pass

    def service(self, root=None):
        svc = SelfBuilderService(root or self.root)
        self._services.append(svc)
        return svc

    def build(self, svc, text, **kw):
        request = rp.parse_build_request(text)
        self.assertEqual(request.status, rp.STATUS_READY, f"not ready: {text!r} -> {request.to_dict()}")
        return svc.build(text, request, **kw)

    def built(self, svc, text, **kw):
        result = self.build(svc, text, **kw)
        self.assertEqual(result["status"], "applied", f"{text!r}: {result['status']} {result['error']}")
        return result

    def files(self, subdir):
        directory = os.path.join(self.root, subdir)
        return sorted(os.listdir(directory)) if os.path.isdir(directory) else []

    def db(self):
        return sqlite3.connect(os.path.join(self.root, "self_builder.db"))


KM_MI = "یک مبدل کیلومتر به مایل بساز"
KM_MI_06 = "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است"
M_FT = "یک مبدل متر به فوت بساز"
BMI = "یک ماشین حساب BMI بساز: وزن / (قد * قد)"
AREA = "فرمول مساحت دایره را یاد بگیر: pi * r ** 2"
WORDS = "ابزاری بساز که تعداد کلمات متن را بشمارد"
REVERSE = "یک ابزار بساز که متن را معکوس کند"
CAPS = (KM_MI, M_FT, "یک مبدل سلسیوس به فارنهایت بساز", BMI, AREA, WORDS, REVERSE)


# ============================================================================ request analysis
class TestRequestParserTable(unittest.TestCase):
    UNIT_PHRASES = [
        ("یک مبدل کیلومتر به مایل بساز", "km", "mi"),
        ("مبدل کیلومتر به مایل بساز", "km", "mi"),
        ("یه مبدل از کیلومتر به مایل بساز", "km", "mi"),
        ("تبدیل کیلومتر به مایل را یاد بگیر", "km", "mi"),
        ("قابلیت تبدیل کیلومتر به مایل رو اضافه کن", "km", "mi"),
        ("می‌خواهم بتوانی کیلومتر را به مایل تبدیل کنی", "km", "mi"),
        ("میخوام بتونی کیلومتر رو به مایل تبدیل کنی", "km", "mi"),
        ("نیاز دارم که تبدیل متر به فوت را بلد باشی", "m", "ft"),
        ("یک قابلیت جدید برای تبدیل دما از سلسیوس به فارنهایت بساز", "c", "f"),
        ("مبدل سانتی‌متر به اینچ درست کن", "cm", "in"),
        ("لطفا مبدل گرم به اونس رو بساز", "g", "oz"),
        ("یک ابزار برای تبدیل لیتر به گالن بساز", "l", "gal"),
        ("من یک مبدل پوند به کیلوگرم لازم دارم", "lb", "kg"),
        ("یاد بگیر مایل را به کیلومتر تبدیل کنی", "mi", "km"),
        ("تبدیل ساعت به دقیقه را اضافه کن", "h", "min"),
        ("مبدل متر به یارد بساز", "m", "yd"),
        ("مبدل کیلومتر بر ساعت به مایل بر ساعت بساز", "kmh", "mph"),
        # spelling / typography noise
        ("يك مبدل كيلومتر به مايل بساز", "km", "mi"),                         # Arabic yeh / kaf
        ("یک  مبدل   کیلومتر   به   مایل   بساز !!!", "km", "mi"),             # spacing, punctuation
        ("یک مبدل‌ کیلومتر‌ به مایل بساز 🙂", "km", "mi"),                     # ZWNJ, emoji
        ("مبدّل کیلومتر به مایل بساز", "km", "mi"),                            # diacritic
        ("یک مبدل کیلومتر به مایل بسازید لطفاً", "km", "mi"),
        ("لطفاً یک مبدل کیلومتر به مایل بساز", "km", "mi"),
        ("ی مبدل کیلومتر به مایل بساز", "km", "mi"),                           # colloquial "ی"
        ("یک مبدل km به mi بساز", "km", "mi"),                                 # Latin unit symbols
        ("برای من یک مبدل گرم به کیلوگرم بساز", "g", "kg"),
        ("یک مبدل متر به سانتی‌متر درست کن", "m", "cm"),
        ("می‌خواهم یک مبدل فوت به متر داشته باشی", "ft", "m"),
        ("قابلیتی بساز که ثانیه را به دقیقه تبدیل کند", "s", "min"),
    ]
    FORMULA_PHRASES = [
        ("فرمول مساحت دایره را یاد بگیر: pi * r ** 2", "مساحت دایره", "pi * r ** 2"),
        ("یک ماشین حساب BMI بساز: وزن / (قد * قد)", "BMI", "وزن / (قد * قد)"),
        ("یک فرمول بساز برای محیط دایره: ۲ * pi * r", "محیط دایره", "۲ * pi * r"),
        ("فرمول محاسبه سرعت را اضافه کن: مسافت / زمان", "سرعت", "مسافت / زمان"),
        ("ماشین حساب تخفیف بساز: قیمت * (۱ - درصد / ۱۰۰)", "تخفیف", "قیمت * (۱ - درصد / ۱۰۰)"),
        ("یک ماشین‌حساب مالیات بساز: مبلغ * ۰٫۰۹", "مالیات", "مبلغ * ۰٫۰۹"),
        ("فرمول ساده بساز: a + b", "ساده", "a + b"),
    ]
    TEXT_PHRASES = [
        ("ابزاری بساز که تعداد کلمات متن را بشمارد", ["count_words"]),
        ("یک ابزار بساز که متن را معکوس کند", ["reverse"]),
        ("ابزاری که ارقام انگلیسی را فارسی کند بساز", ["to_fa_digits"]),
        ("ابزاری بساز که ارقام انگلیسی را فارسی کند", ["to_fa_digits"]),
        ("ابزاری بساز که اعداد فارسی را انگلیسی کند", ["to_en_digits"]),
        ("ابزاری بساز که ارقام را فارسی کند", ["to_fa_digits"]),
        ("یک قابلیت بساز که فاصله‌های اضافی متن را حذف کند", ["strip_spaces"]),
        ("ابزاری درست کن که حروف متن را بزرگ کند", ["upper"]),
        ("یک ابزار بساز که تعداد حروف را بشمارد", ["count_chars"]),
    ]
    CLARIFY = [
        ("یک مبدل بساز", "unit_conversion", ["from_unit", "to_unit"]),
        ("یک قابلیت جدید بساز", None, ["kind"]),
        ("یک فرمول جدید یاد بگیر", "formula", ["title", "expression"]),
        ("من یک قابلیت جدید نیاز دارم", None, ["kind"]),
        ("یک ابزار بساز", None, ["kind"]),
        ("ماشین حساب بساز", "formula", ["title", "expression"]),
        ("بسازم؟", None, ["kind"]),
        ("ابزاری بساز که تعداد کلمات را بشمارد و متن را معکوس کند", "text_tool", ["ops_order"]),
        ("یک مبدل کیلومتر بساز", "unit_conversion", ["to_unit"]),
    ]
    UNSUPPORTED = [
        "یک نرم‌افزار حسابداری بساز", "یک بازی بساز", "یک برنامه ی چت بساز", "قابلیت ارسال ایمیل بساز",
        "یک ربات تلگرام بساز", "یک مبدل بساز که از اینترنت نرخ ارز را بگیرد", "یک قابلیت بساز که فایل‌ها را پاک کند",
        "کد پایتون دلخواه اجرا کن و قابلیت بساز", "خانه ای بساز", "MBDL km to mi بساز",
        "یک مبدل فایل بساز", "قابلیتی بساز که دوربین را روشن کند", "یک اسکریپت شل بساز",
    ]
    NOT_REQUESTS = [
        "سلام", "کیلومتر چیست؟", "امروز هوا خوب است", "۱۰ کیلومتر چند مایل است؟", "ساختمان بلند است",
        "مبدل چیست؟", "", "   ", "کیلومتر به مایل رو تبدیل کن", "آیا تبدیل متر به فوت را بلدی؟",
        "ممنون", "خداحافظ", "من عرفان هستم", "فردا بارون میاد", "پایتون چیست؟", "چه کارهایی بلدی؟",
    ]

    def test_unit_conversion_phrasings(self):
        for text, a, b in self.UNIT_PHRASES:
            with self.subTest(text=text):
                r = rp.parse_build_request(text)
                self.assertEqual((r.status, r.kind), (rp.STATUS_READY, "unit_conversion"), r.to_dict())
                self.assertEqual((r.slots["from_unit"], r.slots["to_unit"]), (a, b))
                self.assertNotIn("factor", r.slots)

    def test_formula_phrasings(self):
        for text, title, expression in self.FORMULA_PHRASES:
            with self.subTest(text=text):
                r = rp.parse_build_request(text)
                self.assertEqual((r.status, r.kind), (rp.STATUS_READY, "formula"), r.to_dict())
                self.assertEqual((r.slots["title"], r.slots["expression"]), (title, expression))

    def test_text_tool_phrasings(self):
        for text, ops in self.TEXT_PHRASES:
            with self.subTest(text=text):
                r = rp.parse_build_request(text)
                self.assertEqual((r.status, r.kind, r.slots["ops"]), (rp.STATUS_READY, "text_tool", ops), r.to_dict())

    def test_incomplete_requests_ask_for_what_is_missing(self):
        for text, kind, missing in self.CLARIFY:
            with self.subTest(text=text):
                r = rp.parse_build_request(text)
                self.assertEqual((r.status, r.kind, r.missing), (rp.STATUS_CLARIFY, kind, missing), r.to_dict())

    def test_unsupported_subjects_are_refused_honestly(self):
        for text in self.UNSUPPORTED:
            with self.subTest(text=text):
                r = rp.parse_build_request(text)
                self.assertEqual(r.status, rp.STATUS_UNSUPPORTED, r.to_dict())
                self.assertIsNone(r.kind)

    def test_ordinary_sentences_are_not_build_requests(self):
        for text in self.NOT_REQUESTS:
            with self.subTest(text=text):
                self.assertEqual(rp.parse_build_request(text).status, rp.STATUS_NOT_REQUEST)

    def test_there_are_at_least_eighty_distinct_phrasings(self):
        table = ([t for t, *_ in self.UNIT_PHRASES] + [t for t, *_ in self.FORMULA_PHRASES]
                 + [t for t, *_ in self.TEXT_PHRASES] + [t for t, *_ in self.CLARIFY] + self.UNSUPPORTED
                 + self.NOT_REQUESTS)
        self.assertGreaterEqual(len(set(table)), 80)

    def test_explicit_factor_and_example_are_extracted(self):
        r = rp.parse_build_request("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است")
        self.assertEqual((r.status, r.slots["factor"], r.slots["from_unit"], r.slots["to_unit"]),
                         (rp.STATUS_READY, 0.6, "km", "mi"))
        r = rp.parse_build_request("یک مبدل بساز که هر ۱ فوت برابر ۳۰٫۴۸ سانتی‌متر باشد")
        self.assertEqual((r.slots["factor"], r.slots["from_unit"], r.slots["to_unit"]), (30.48, "ft", "cm"))
        r = rp.parse_build_request("یک مبدل کیلومتر به مایل بساز. مثلاً ۱۰ کیلومتر می‌شود ۶٫۲۱")
        self.assertEqual(r.status, rp.STATUS_READY)
        self.assertIn("example_text", r.slots)
        r = rp.parse_build_request("یک مبدل اینچ به سانتی‌متر بساز: هر ۱ اینچ = ۲٫۵۴ سانتی‌متر")
        self.assertEqual(r.slots["factor"], 2.54)

    def test_a_custom_unit_pair_needs_only_names_and_a_factor(self):
        r = rp.parse_build_request("یک مبدل بساز که هر ۱ دلار برابر ۵۰۰۰۰ تومان است")
        self.assertEqual((r.status, r.kind, r.slots["factor"]), (rp.STATUS_READY, "unit_conversion", 50000.0))
        self.assertEqual((r.slots["from_name"], r.slots["to_name"]), ("دلار", "تومان"))
        self.assertNotIn("from_unit", r.slots)

    def test_formula_titles_never_keep_request_words(self):
        for text, title in (("فرمول محاسبه سرعت را اضافه کن: مسافت / زمان", "سرعت"),
                            ("فرمول حجم را ثبت کن: طول * عرض * ارتفاع", "حجم"),
                            ("یک فرمول برای مساحت مستطیل ایجاد کن: طول * عرض", "مساحت مستطیل"),
                            ("ماشین حساب «شاخص توده بدنی» بساز: وزن / (قد * قد)", "شاخص توده بدنی"),
                            ("فرمولی به نام مساحت بساز: a * b", "مساحت")):
            with self.subTest(text=text):
                self.assertEqual(rp.parse_build_request(text).slots.get("title"), title)

    def test_input_limits_and_junk(self):
        for junk in (None, 5, [], {}, b"x"):
            self.assertEqual(rp.parse_build_request(junk).status, rp.STATUS_NOT_REQUEST)
        long_text = "یک مبدل کیلومتر به مایل بساز " + "الف " * (policy.MAX_REQUEST_CHARS // 3)
        self.assertEqual(rp.parse_build_request(long_text).status, rp.STATUS_NOT_REQUEST)

    def test_parsing_is_total_on_random_text(self):
        import random
        rng = random.Random(20260101)
        alphabet = list("ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی۰۱۲۳۴۵۶۷۸۹0123456789 :=+-*/()«»؟?!.,،;‌‍\n\t'\"_abcxyz")
        words = ["مبدل", "بساز", "فرمول", "ابزار", "کیلومتر", "مایل", "به", "از", "را", "که", "تعداد", "کلمات",
                 "متن", "pi", "r", "**", "=", ":", "قابلیت", "یاد", "بگیر", "است", "هر", "برابر", "۱", "۲٫۵"]
        for i in range(400):
            if i % 2:
                text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 120)))
            else:
                text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 14)))
            r = rp.parse_build_request(text)
            self.assertIn(r.status, (rp.STATUS_READY, rp.STATUS_CLARIFY, rp.STATUS_UNSUPPORTED, rp.STATUS_NOT_REQUEST))
            if r.status == rp.STATUS_READY:
                self.assertIn(r.kind, policy.SUPPORTED_ARCHETYPES)
                rp.assemble_spec_inputs(r)               # must be total for every READY request
            r2 = rp.BuildRequest.from_dict(r.to_dict())
            self.assertEqual(r2.to_dict(), r.to_dict())  # (de)serialisable (it is stored in the dialogue)


class TestBuildMarkers(unittest.TestCase):
    def test_markers(self):
        self.assertIn("build_verb", rp.build_markers("یک مبدل بساز"))
        self.assertIn("build_verb", rp.build_markers("قابلیت جدید اضافه کن"))
        self.assertIn("learn", rp.build_markers("تبدیل دما را یاد بگیر"))
        self.assertIn("want_need", rp.build_markers("می‌خواهم این را بلد باشی"))
        self.assertIn("want_need", rp.build_markers("نیاز دارم"))
        self.assertIn("new_capability", rp.build_markers("من یک قابلیت جدید نیاز دارم"))
        self.assertEqual(rp.build_markers("سلام چطوری"), set())

    def test_detect_text_ops(self):
        self.assertEqual(rp.detect_text_ops("تعداد کلمات متن را بشمار"), ["count_words"])
        self.assertEqual(rp.detect_text_ops("متن را معکوس کن"), ["reverse"])
        self.assertEqual(rp.detect_text_ops("ارقام انگلیسی را فارسی کن"), ["to_fa_digits"])
        self.assertEqual(rp.detect_text_ops("ارقام فارسی را به انگلیسی تبدیل کن"), ["to_en_digits"])
        self.assertEqual(rp.detect_text_ops("ارقام فارسی و انگلیسی"), [])      # no direction: ambiguous
        self.assertEqual(rp.detect_text_ops("سلام"), [])


class TestMergeAnswer(unittest.TestCase):
    def merge(self, kind, slots, missing, answer):
        return rp.merge_answer({"kind": kind, "slots": slots, "missing": missing}, answer)

    def test_kind_answers(self):
        for answer, kind, status in (("تبدیل کیلومتر به مایل", "unit_conversion", rp.STATUS_READY),
                                     ("تبدیل واحد", "unit_conversion", rp.STATUS_CLARIFY),
                                     ("فرمول", "formula", rp.STATUS_CLARIFY),
                                     ("ابزار متنی", "text_tool", rp.STATUS_CLARIFY),
                                     ("شمارش کلمات", "text_tool", rp.STATUS_READY),
                                     ("معکوس کردن متن", "text_tool", rp.STATUS_READY)):
            with self.subTest(answer=answer):
                r = self.merge(None, {}, ["kind"], answer)
                self.assertEqual((r.kind, r.status), (kind, status), r.to_dict())

    def test_unit_answers(self):
        r = self.merge("unit_conversion", {}, ["from_unit", "to_unit"], "کیلومتر به مایل")
        self.assertEqual((r.status, r.slots["from_unit"], r.slots["to_unit"]), (rp.STATUS_READY, "km", "mi"))
        r = self.merge("unit_conversion", {}, ["from_unit", "to_unit"], "کیلومتر")
        self.assertEqual((r.status, r.slots["from_unit"], r.missing), (rp.STATUS_CLARIFY, "km", ["to_unit"]))
        r = self.merge("unit_conversion", {"from_unit": "km"}, ["to_unit"], "مایل")
        self.assertEqual((r.status, r.slots["to_unit"]), (rp.STATUS_READY, "mi"))
        r = self.merge("unit_conversion", {"from_unit": "km"}, ["to_unit"], "کیلومتر")     # same unit again
        self.assertEqual((r.status, r.missing), (rp.STATUS_CLARIFY, ["to_unit"]))
        r = self.merge("unit_conversion", {}, ["from_unit", "to_unit"], "هر ۱ دلار برابر ۵۰۰۰۰ تومان است")
        self.assertEqual((r.status, r.slots["factor"]), (rp.STATUS_READY, 50000.0))

    def test_formula_answers(self):
        r = self.merge("formula", {}, ["title", "expression"], "مساحت دایره = pi * r ** 2")
        self.assertEqual((r.status, r.slots["title"], r.slots["expression"]),
                         (rp.STATUS_READY, "مساحت دایره", "pi * r ** 2"))
        r = self.merge("formula", {}, ["title", "expression"], "pi * r ** 2")
        self.assertEqual((r.status, r.missing, r.slots["expression"]), (rp.STATUS_CLARIFY, ["title"], "pi * r ** 2"))
        self.assertNotIn("title", r.slots)                                  # never a junk title made of the formula
        r = self.merge("formula", {"title": "مساحت"}, ["expression"], "pi * r ** 2")
        self.assertEqual((r.status, r.slots["expression"]), (rp.STATUS_READY, "pi * r ** 2"))
        r = self.merge("formula", {"expression": "a+b"}, ["title"], "جمع")
        self.assertEqual((r.status, r.slots["title"]), (rp.STATUS_READY, "جمع"))
        r = self.merge("formula", {}, ["title", "expression"], "مساحت دایره")
        self.assertEqual((r.status, r.missing), (rp.STATUS_CLARIFY, ["expression"]))

    def test_text_tool_answers(self):
        r = self.merge("text_tool", {}, ["ops"], "معکوس کردن متن")
        self.assertEqual((r.status, r.slots["ops"]), (rp.STATUS_READY, ["reverse"]))
        r = self.merge("text_tool", {}, ["ops"], "چیزی")
        self.assertEqual((r.status, r.missing), (rp.STATUS_CLARIFY, ["ops"]))


class TestAnalyzeForUpgrade(unittest.TestCase):
    def test_only_persian_buildable_descriptions_are_ready(self):
        for text in ("ابزاری بساز که تعداد کلمات متن را بشمارد", "یک مبدل کیلومتر به مایل", "تبدیل کیلومتر به مایل"):
            with self.subTest(text=text):
                self.assertEqual(rp.analyze_for_upgrade(text).status, rp.STATUS_READY)
        for text in ("improve the matching speed", "سرعت بیشتر", "", None, "a faster parser"):
            with self.subTest(text=text):
                self.assertIsNone(rp.analyze_for_upgrade(text))


# ============================================================================ repairs
class TestRepairUnits(unittest.TestCase):
    def test_plan_per_error_code(self):
        self.assertEqual(repair.plan_for_error("E_EXPR_TOKEN"), ["normalize_operators", "word_operators"])
        self.assertEqual(repair.plan_for_error("E_EXPR_NON_ASCII_NAME"),
                         ["normalize_operators", "word_operators", "map_identifiers"])
        self.assertEqual(repair.plan_for_error("E_EXPR_ADJACENT"), ["implicit_multiplication"])
        self.assertEqual(repair.plan_for_error("E_EXPR_PAREN_OPEN"), ["balance_parentheses"])
        for code in ("E_EXPR_EMPTY", "E_EXPR_TOO_LONG", "E_EXPR_NUMBER", "E_EXPR_ARITY", "E_UNKNOWN", ""):
            self.assertEqual(repair.plan_for_error(code), [], code)

    def test_only_notation_repairs_are_safe(self):
        for rid in ("normalize_operators", "word_operators", "implicit_multiplication", "map_identifiers"):
            self.assertEqual(repair.REPAIRS[rid]("a", {}).risk, "safe", rid)
        self.assertEqual(repair.REPAIRS["balance_parentheses"]("(a", {}).risk, "guess")

    def test_normalize_operators(self):
        for before, after in (("۳٫۱۴ × r ^ 2", "3.14 * r ** 2"), ("a ÷ b", "a / b"), ("a − b", "a - b"),
                              ("π * r²", "pi * r**2"), ("√x", "sqrt(x)"), ("√(a+b)", "sqrt(a+b)"),
                              ("[a + b] * c", "(a + b) * c"), ("min(a، b)", "min(a, b)"), ("۱۲۳ + ٤٥٦", "123 + 456"),
                              ("ａ ＋ ｂ", "a + b")):
            with self.subTest(before=before):
                out = repair.normalize_operators(before, {})
                self.assertEqual(out.after.replace(" ", ""), after.replace(" ", ""))

    def test_word_operators(self):
        for before, after in (("a ضرب در b", "a * b"), ("a ضربدر b", "a * b"), ("a تقسیم بر b", "a / b"),
                              ("a به توان 2", "a ** 2"), ("a منهای b", "a - b"), ("a به علاوه b", "a + b"),
                              ("a بعلاوه b", "a + b")):
            with self.subTest(before=before):
                self.assertEqual(repair.word_operators(before, {}).after, after)

    def test_implicit_multiplication(self):
        for before, after in (("2r + 3", "2 * r + 3"), ("2(x+1)", "2 * ( x + 1 )"), ("(a)(b)", "( a ) * ( b )"),
                              ("(a+b)c", "( a + b ) * c"), ("a(b+1)", "a * ( b + 1 )"), ("2pi", "2 * pi"),
                              ("x (y)", "x * ( y )")):
            with self.subTest(before=before):
                out = repair.implicit_multiplication(before, {})
                self.assertTrue(out.changed)
                self.assertEqual(out.after, after)

    def test_a_function_like_name_is_never_turned_into_a_product(self):
        for text in ("log(x)", "foo(2)", "tanh(x) + 1", "pow(a, b)", "sin(x)", "sqrt(2)"):
            with self.subTest(text=text):
                out = repair.implicit_multiplication(text, {})
                self.assertFalse(out.changed)
                self.assertEqual(out.after, text)
        # ... but a mapped Persian variable (kept in the labels) is a variable
        out = repair.implicit_multiplication("v1(v2 + 1)", {"v1": "وزن", "v2": "قد"})
        self.assertEqual(out.after, "v1 * ( v2 + 1 )")

    def test_balance_parentheses(self):
        self.assertEqual(repair.balance_parentheses("(a + b * 2", {}).after, "(a + b * 2)")
        self.assertEqual(repair.balance_parentheses("((a + b) * 2", {}).after, "((a + b) * 2)")
        self.assertEqual(repair.balance_parentheses("(a + b))", {}).after, "(a + b)")
        self.assertFalse(repair.balance_parentheses("a + b) * 2", {}).changed)        # not guessable

    def test_map_identifiers_keeps_the_persian_labels(self):
        out = repair.map_identifiers("وزن / (قد * قد)", {})
        self.assertEqual(out.after, "v1 / (v2 * v2)")
        self.assertEqual(out.labels, {"v1": "وزن", "v2": "قد"})
        out = repair.map_identifiers("v1 + طول", {})
        self.assertEqual(out.after, "v1 + v2")        # never collides with an existing name
        self.assertEqual(out.labels, {"v2": "طول"})

    def test_next_expression_repair_skips_applied_and_no_ops(self):
        out = repair.next_expression_repair("E_EXPR_TOKEN", "a × b", {}, [])
        self.assertEqual(out.repair_id, "normalize_operators")
        out2 = repair.next_expression_repair("E_EXPR_TOKEN", "a ضرب در b", {}, ["normalize_operators"])
        self.assertEqual(out2.repair_id, "word_operators")
        self.assertIsNone(repair.next_expression_repair("E_EXPR_TOKEN", "a $ b", {}, []))     # nothing changes
        self.assertIsNone(repair.next_expression_repair("E_EXPR_TOKEN", "a × b", {}, ["normalize_operators",
                                                                                       "word_operators"]))
        self.assertIsNone(repair.next_expression_repair("E_EXPR_UNKNOWN_FUNC", "log(x)", {}, []))
        self.assertIsNone(repair.next_expression_repair("E_NO_SUCH_CODE", "a × b", {}, []))

    def test_every_repair_is_total_on_junk(self):
        junk = ["", " ", "(((", ")))", "×÷", "ضرب در", "‌", "a" * 500, "۱۲۳", "√", "()", "x(", ")x", "a b c"]
        for rid, fn in repair.REPAIRS.items():
            for text in junk:
                with self.subTest(repair=rid, text=text[:20]):
                    out = fn(text, {})
                    self.assertIsInstance(out.after, str)

    def test_classify_test_failures(self):
        def failed(name, source, error=None):
            return {"name": name, "source": source, "actual": {"error": error} if error else {}}
        self.assertEqual(repair.classify_test_failures({"failed": []}), {"class": "none", "names": []})
        self.assertEqual(repair.classify_test_failures({"failed": [failed("ex_0", "user")]})["class"],
                         "example_mismatch")
        self.assertEqual(repair.classify_test_failures({"failed": [failed("auto_1", "auto"), failed("ex_0", "user")]})
                         ["class"], "reference_mismatch")
        for err in ("exception", "timeout", "bad_output"):
            self.assertEqual(repair.classify_test_failures({"failed": [failed("auto_1", "auto", err)]})["class"],
                             "sandbox_fault")

    def test_reorder_candidates(self):
        self.assertEqual(repair.reorder_candidates(1), [])
        self.assertEqual(repair.reorder_candidates(2), [(1, 0)])
        self.assertEqual(len(repair.reorder_candidates(3)), 5)
        self.assertEqual(len(repair.reorder_candidates(4)), 23)
        self.assertEqual(len(repair.reorder_candidates(6)), 24)         # bounded
        self.assertNotIn((0, 1, 2), repair.reorder_candidates(3))


FORMULA_REPAIRS = [
    # request, final expression, repair ids (in order), risk of the last one
    ("فرمول مساحت دایره را یاد بگیر: ۳٫۱۴ × r ^ 2", "3.14 * r ** 2", ["normalize_operators"]),
    ("فرمول سرعت را یاد بگیر: مسافت تقسیم بر زمان", "v1 / v2", ["word_operators", "map_identifiers"]),
    ("فرمول مساحت مستطیل را یاد بگیر: طول ضربدر عرض", "v1 * v2", ["word_operators", "map_identifiers"]),
    ("فرمول ساده را یاد بگیر: ۲r + ۳", "2 * r + 3", ["normalize_operators", "implicit_multiplication"]),
    ("فرمول تست را یاد بگیر: a(b + 1)", "a * ( b + 1 )", ["implicit_multiplication"]),
    ("فرمول تست را یاد بگیر: وزن (قد + 1)", "v1 * ( v2 + 1 )", ["map_identifiers", "implicit_multiplication"]),
]


class TestRepairsThroughThePipeline(TempDirCase):
    def test_safe_repairs_are_applied_logged_and_the_result_is_correct(self):
        svc = self.service()
        for request, expression, ids in FORMULA_REPAIRS:
            with self.subTest(request=request):
                result = self.built(svc, request)
                self.assertEqual([r["repair"] for r in result["repairs"]][-len(ids):], ids)
                self.assertTrue(all(r["risk"] == "safe" for r in result["repairs"]))
                record = svc.capability(result["capability_id"])
                self.assertEqual(record["spec"]["expression"], expression)
                self.assertTrue(record["tests"]["ok"])
                stage_names = [s["stage"] for s in result["stages"]]
                self.assertIn("analyze_failure", stage_names)
                self.assertIn("repair", stage_names)
                self.assertLess(stage_names.index("analyze_failure"), stage_names.index("repair"))

    def test_the_repaired_formula_computes_the_right_numbers(self):
        svc = self.service()
        cid = self.built(svc, "فرمول مساحت دایره را یاد بگیر: ۳٫۱۴ × r ^ 2")["capability_id"]
        out = svc.invoke(cid, {"r": 2})
        self.assertEqual((out["ok"], round(out["value"], 6)), (True, 12.56))
        cid = self.built(svc, "فرمول BMI را یاد بگیر: وزن ÷ (قد × قد)")["capability_id"]
        out = svc.invoke(cid, {"v1": 70, "v2": 1.75})
        self.assertAlmostEqual(out["value"], 22.857142857142858, places=9)

    def test_an_unbalanced_parenthesis_is_a_guess_and_needs_confirmation(self):
        svc = self.service()
        text = "فرمول تست را یاد بگیر: (a + b * 2"
        result = self.build(svc, text)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["confirmation"]["reason"], "guess_repair")
        self.assertEqual(result["confirmation"]["details"]["repairs"][0]["after"], "(a + b * 2)")
        self.assertEqual(svc.capabilities(), [])                       # nothing was activated
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])
        again = self.build(svc, text, confirmed=True)
        self.assertEqual(again["status"], "applied")
        self.assertEqual(svc.capability(again["capability_id"])["spec"]["expression"], "(a + b * 2)")

    def test_a_positional_example_can_verify_a_variable_reorder(self):
        svc = self.service()
        result = self.built(svc, "فرمول تفاضل را یاد بگیر: x - y. مثلاً ۳ و ۴ می‌شود ۱")
        reorder = [r for r in result["repairs"] if r["repair"] == "reorder_variables"]
        self.assertEqual(len(reorder), 1)
        self.assertEqual(reorder[0]["risk"], "guess")
        record = svc.capability(result["capability_id"])
        self.assertEqual([v["name"] for v in record["spec"]["variables"]], ["y", "x"])
        self.assertEqual(svc.invoke(result["capability_id"], {"x": 10, "y": 4})["value"], 6)
        self.assertIsNone(result["confirmation"])                       # verified by the user's own example

    def test_a_correct_example_changes_nothing(self):
        svc = self.service()
        result = self.built(svc, "فرمول مجموع را یاد بگیر: x + y. مثلاً ۳ و ۴ می‌شود ۷")
        self.assertEqual(result["repairs"], [])
        examples = svc.capability(result["capability_id"])["spec"]["examples"]
        self.assertEqual([e["expected"] for e in examples], [7.0])

    def test_unrepairable_requests_fail_cleanly_and_activate_nothing(self):
        svc = self.service()
        cases = [
            ("فرمول تست را یاد بگیر: a + b) * 2", "E_EXPR_PAREN_CLOSE"),
            ("فرمول تست را یاد بگیر: foo(2)", "E_EXPR_UNKNOWN_FUNC"),
            ("فرمول تست را یاد بگیر: log(x) + 1", "E_EXPR_UNKNOWN_FUNC"),
            ("فرمول تست را یاد بگیر: ۲ پی r", "E_EXPR_ADJACENT"),
            ("فرمول تست را یاد بگیر: 1 / 0", "E_SPEC_NO_VARIABLES"),
            ("یک مبدل کیلومتر به کیلوگرم بساز", "E_SPEC_DIMENSION"),
            ("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰ مایل است", "E_SPEC_FACTOR"),
        ]
        for text, code in cases:
            with self.subTest(text=text):
                result = self.build(svc, text)
                self.assertEqual((result["status"], result["error"]["code"]), ("failed", code))
        self.assertEqual(svc.capabilities(), [])
        for sub in (policy.SUBDIR_MODULES, policy.SUBDIR_TESTS, policy.SUBDIR_SPECS, policy.SUBDIR_STAGING):
            self.assertEqual(self.files(sub), [], sub)
        failed_rows = [h for h in svc.history() if h["result"] == "failed"]
        self.assertEqual(len(failed_rows), len(cases))
        self.assertTrue(all(h["error_code"] for h in failed_rows))

    def test_an_example_that_contradicts_the_formula_is_never_applied(self):
        svc = self.service()
        for text in ("فرمول مجموع را یاد بگیر: x + y. مثلاً ۳ و ۴ می‌شود ۸",
                     "فرمول مساحت دایره را یاد بگیر: pi * r ** 2. مثلاً r=2 می‌شود ۱۲",
                     "یک مبدل کیلومتر به مایل بساز. مثلاً ۱۰ کیلومتر می‌شود ۷"):
            with self.subTest(text=text):
                result = self.build(svc, text)
                self.assertEqual((result["status"], result["error"]["code"]), ("failed", "E_BUILD_TESTS_FAILED"))
                self.assertEqual(result["error"]["info"]["failure_class"], "example_mismatch")
        self.assertEqual(svc.capabilities(), [])

    def test_a_matching_example_is_accepted_within_its_tolerance(self):
        svc = self.service()
        self.built(svc, "فرمول مساحت دایره را یاد بگیر: pi * r ** 2. مثلاً r=2 می‌شود ۱۲٫۵۷")
        self.built(svc, "یک مبدل کیلومتر به مایل بساز. مثلاً ۱۰ کیلومتر می‌شود ۶٫۲۱")

    def test_repairs_are_bounded(self):
        svc = self.service()
        with mock.patch.object(policy, "MAX_REPAIR_ATTEMPTS", 1):
            result = self.build(svc, "فرمول ساده را یاد بگیر: ۲r + ۳")       # needs two repairs
        self.assertEqual(result["status"], "failed")
        self.assertEqual(svc.capabilities(), [])


# ============================================================================ matcher
class TestInvocationMatcher(TempDirCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_class = tempfile.mkdtemp(prefix="sb_match_")
        cls.svc = SelfBuilderService(os.path.join(cls.tmp_class, "sb"))
        cls.ids = {}
        for text in CAPS:
            request = rp.parse_build_request(text)
            result = cls.svc.build(text, request)
            assert result["status"] == "applied", (text, result["error"])
            cls.ids[text] = result["capability_id"]

    @classmethod
    def tearDownClass(cls):
        cls.svc.close()
        shutil.rmtree(cls.tmp_class, ignore_errors=True)

    def match(self, text):
        return self.svc.match(text)

    def test_unit_questions_are_invoked_with_the_right_number(self):
        km = self.ids[KM_MI]
        for text, value in (("۱۰ کیلومتر چند مایل است؟", 10.0), ("۱۰ کیلومتر برابر چند مایل است", 10.0),
                            ("۲۰ کیلومتر را به مایل تبدیل کن", 20.0), ("کیلومتر ۱۰ چند مایل میشود", 10.0),
                            ("۲٫۵ کیلومتر چند مایل است", 2.5), ("-۵ کیلومتر چند مایل است؟", -5.0),
                            ("ده کیلومتر چند مایل است؟", 10.0), ("صد و بیست کیلومتر چند مایل است؟", 120.0),
                            ("دو و نیم کیلومتر چند مایل است؟", 2.5), ("۱٬۰۰۰ کیلومتر چند مایل است؟", 1000.0)):
            with self.subTest(text=text):
                m = self.match(text)
                self.assertEqual((m["status"], m["capability_id"], m["inputs"]), ("invoke", km, {"value": value}))

    def test_negative_temperatures_keep_their_sign(self):
        c_to_f = self.ids["یک مبدل سلسیوس به فارنهایت بساز"]
        for text, value in (("-۴۰ سانتی‌گراد چند فارنهایت است", -40.0), ("−۴۰ سلسیوس چند فارنهایت است", -40.0),
                            ("۱۰۰ سلسیوس چند فارنهایت است؟", 100.0)):
            with self.subTest(text=text):
                m = self.match(text)
                self.assertEqual((m["capability_id"], m["inputs"]), (c_to_f, {"value": value}))
        out = self.svc.invoke(c_to_f, {"value": -40.0})
        self.assertAlmostEqual(out["value"], -40.0, places=9)           # the classic fixed point

    def test_the_unit_after_how_many_is_the_target_not_the_source(self):
        m = self.match("کیلومتر ۱۰ چند مایل میشود")
        self.assertEqual(m["status"], "invoke")
        self.assertEqual(m["inputs"], {"value": 10.0})

    def test_a_missing_conversion_is_reported_as_a_buildable_gap(self):
        for text, a, b, value in (("۵ مایل چند کیلومتر است؟", "mi", "km", 5.0), ("۳ فوت چند متر است؟", "ft", "m", 3.0),
                                  ("۱۰ لیتر چند گالن است؟", "l", "gal", 10.0), ("۱۰ ساعت چند دقیقه است؟", "h", "min", 10.0),
                                  ("۱۲ کیلوگرم چند پوند است؟", "kg", "lb", 12.0), ("۱۰ کیلومتر چند متر است؟", "km", "m", 10.0)):
            with self.subTest(text=text):
                m = self.match(text)
                self.assertEqual((m["status"], m["archetype"], m["slots"], m["value"]),
                                 ("gap", "unit_conversion", {"from_unit": a, "to_unit": b}, value))

    def test_things_that_are_not_conversion_questions_do_not_match(self):
        for text in ("سلام", "۱۰ کیلومتر چند کیلومتر است؟", "چند مایل است؟", "کیلومتر به مایل", "10 km to mi",
                     "۱۰ کیلومتر", "امروز ۱۰ کیلومتر دویدم", "چه کارهایی بلدی؟", "", "   ", "؟"):
            with self.subTest(text=text):
                self.assertIsNone(self.match(text))

    def test_formulas(self):
        bmi, area = self.ids[BMI], self.ids[AREA]
        m = self.match("BMI با وزن ۷۰ و قد ۱٫۷۵ را حساب کن")
        self.assertEqual((m["status"], m["capability_id"], m["inputs"]), ("invoke", bmi, {"v1": 70.0, "v2": 1.75}))
        m = self.match("BMI وزن=۷۰ قد=۱٫۷۵")
        self.assertEqual((m["status"], m["inputs"]), ("invoke", {"v1": 70.0, "v2": 1.75}))
        m = self.match("مساحت دایره با r=3 را حساب کن")
        self.assertEqual((m["status"], m["capability_id"], m["inputs"]), ("invoke", area, {"r": 3.0}))
        m = self.match("مساحت دایره شعاع ۳")
        self.assertEqual((m["status"], m["inputs"]), ("invoke", {"r": 3.0}))
        m = self.match("مساحت دایره را حساب کن")
        self.assertEqual((m["status"], m["missing"]), ("needs_inputs", ["r"]))
        m = self.match("BMI من را حساب کن")
        self.assertEqual((m["status"], m["missing"]), ("needs_inputs", ["وزن", "قد"]))
        m = self.match("فرمول BMI چیست؟")
        self.assertEqual((m["status"], m["capability_id"]), ("describe", bmi))

    def test_text_tools(self):
        count, rev = self.ids[WORDS], self.ids[REVERSE]
        for text, cid, payload in (("تعداد کلمات را بشمار: سلام دنیای زیبا", count, "سلام دنیای زیبا"),
                                   ("تعداد کلمات «سلام دنیا» را بشمار", count, "سلام دنیا"),
                                   ("متن را معکوس کن: abc", rev, "abc")):
            with self.subTest(text=text):
                m = self.match(text)
                self.assertEqual((m["status"], m["capability_id"], m["inputs"]), ("invoke", cid, {"text": payload}))
        m = self.match("متن را معکوس کن")
        self.assertEqual((m["status"], m["capability_id"], m["missing"]), ("needs_inputs", rev, ["متن"]))

    def test_a_missing_text_tool_is_a_gap_only_with_a_payload(self):
        m = self.match("ارقام انگلیسی را فارسی کن: 123 abc")
        self.assertEqual((m["status"], m["archetype"], m["slots"]["ops"]), ("gap", "text_tool", ["to_fa_digits"]))
        self.assertEqual(m["text"], "123 abc")
        self.assertIsNone(self.match("ارقام انگلیسی را فارسی کن"))

    def test_capability_questions_are_answered_from_the_registry(self):
        km = self.ids[KM_MI]
        for text in ("آیا تبدیل کیلومتر به مایل را بلدی؟", "تبدیل کیلومتر به مایل چطور کار می‌کند؟",
                     "کیلومتر به مایل"):
            with self.subTest(text=text):
                q = self.svc.match_question(text)
                self.assertEqual((q["status"], q["capability_id"]), ("have", km))
        q = self.svc.match_question("آیا تبدیل متر به یارد را بلدی؟")
        self.assertEqual((q["status"], q["archetype"], q["slots"]), ("missing", "unit_conversion",
                                                                      {"from_unit": "m", "to_unit": "yd"}))
        self.assertIsNone(self.svc.match_question("آیا می‌توانی ایمیل بفرستی؟"))
        self.assertIsNone(self.svc.match_question("سلام"))

    def test_find_by_title(self):
        self.assertEqual(self.svc.find_capability("جزئیات تبدیل کیلومتر به مایل")["id"], self.ids[KM_MI])
        self.assertEqual(self.svc.find_capability("مساحت دایره")["id"], self.ids[AREA])
        self.assertIsNone(self.svc.find_capability("تبدیل متر به یارد"))

    def test_a_disabled_capability_no_longer_matches(self):
        with tempfile.TemporaryDirectory() as d:
            svc = SelfBuilderService(os.path.join(d, "sb"))
            try:
                request = rp.parse_build_request(KM_MI)
                cid = svc.build(KM_MI, request)["capability_id"]
                self.assertEqual(svc.match("۱۰ کیلومتر چند مایل است؟")["status"], "invoke")
                self.assertEqual(svc.disable(cid)["status"], "applied")
                m = svc.match("۱۰ کیلومتر چند مایل است؟")
                self.assertEqual(m["status"], "gap")                          # it can be built again
            finally:
                svc.close()

    def test_matching_is_total_on_random_text(self):
        import random
        rng = random.Random(7)
        words = ["کیلومتر", "مایل", "چند", "است", "۱۰", "5", "-3", "به", "BMI", "وزن", "قد", "=", "مساحت", "دایره",
                 "r", "بشمار", "متن", "را", "معکوس", "کن", ":", "«x»", "فوت", "متر", "؟"]
        for _ in range(300):
            text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 10)))
            m = self.match(text)
            self.assertTrue(m is None or m["status"] in ("invoke", "needs_inputs", "gap", "describe"))
            self.svc.match_question(text)


# ============================================================================ store
class TestStore(TempDirCase):
    def dbpath(self):
        return os.path.join(self.tmp, "s.db")

    def open(self, **kw):
        s = Store(self.dbpath(), **kw)
        self.addCleanup(s.close)
        return s

    def test_a_fresh_database_gets_the_whole_schema(self):
        s = self.open()
        self.assertEqual(s.schema_version(), 1)
        tables = {r["name"] for r in s.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"capabilities", "capability_versions", "upgrade_log", "checkpoints", "audit_log", "usage",
                         "feedback", "meta"} <= tables)
        self.assertEqual(s.query_one("PRAGMA synchronous")[0], 2)          # FULL: a committed change is on disk
        self.assertEqual(s.counts(), {"capabilities": 0, "capability_versions": 0, "upgrade_log": 0, "audit_log": 0,
                                      "checkpoints": 0})

    def test_reopening_keeps_everything_and_changes_nothing(self):
        s = self.open()
        s.audit("first", "cap_one", 1, None, {"a": 1})
        before = s.counts(), s.last_audit_hash()
        s.close()
        s2 = self.open()
        self.assertEqual((s2.counts(), s2.last_audit_hash()), before)
        self.assertEqual(s2.schema_version(), 1)

    def test_numbered_migrations_run_once_and_in_order(self):
        calls = []

        def m1(conn):
            calls.append(1)
            conn.execute("CREATE TABLE a(x)")

        def m2(conn):
            calls.append(2)
            conn.execute("CREATE TABLE b(y)")
        s = self.open(migrations={1: m1, 2: m2})
        self.assertEqual((calls, s.schema_version()), ([1, 2], 2))
        s.close()
        s2 = self.open(migrations={1: m1, 2: m2})
        self.assertEqual((calls, s2.schema_version()), ([1, 2], 2))          # not run again

    def test_a_failing_migration_changes_nothing(self):
        self.open().close()

        def m2(conn):
            conn.execute("CREATE TABLE half_done(z)")
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            Store(self.dbpath(), migrations={1: store_mod._migration_1, 2: m2})
        s = self.open()
        self.assertEqual(s.schema_version(), 1)
        self.assertEqual(s.query("SELECT name FROM sqlite_master WHERE name = 'half_done'"), [])

    def test_a_database_from_a_newer_build_is_refused_untouched(self):
        s = self.open()
        s.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
        s.close()
        with self.assertRaises(StoreError) as cm:
            Store(self.dbpath())
        self.assertEqual(cm.exception.code, "E_STORE_NEWER_SCHEMA")
        self.assertEqual((cm.exception.info["found"], cm.exception.info["supported"]), (99, 1))

    def test_a_file_that_is_not_a_database_is_an_error_not_a_crash(self):
        with open(self.dbpath(), "wb") as f:
            f.write(os.urandom(4096))
        with self.assertRaises((StoreError, sqlite3.DatabaseError)):
            Store(self.dbpath())

    def test_transactions_commit_or_roll_back_as_a_whole(self):
        s = self.open()
        with s.transaction():
            s.execute("INSERT INTO feedback(ts, capability_id, version, polarity, text) VALUES ('t','c',1,'positive','')")
        self.assertEqual(s.query_one("SELECT COUNT(*) AS n FROM feedback")["n"], 1)
        with self.assertRaises(ZeroDivisionError):
            with s.transaction():
                s.execute("INSERT INTO feedback(ts, capability_id, version, polarity, text) VALUES ('t','c',2,'negative','')")
                s.audit("inside", "c", 2)
                1 / 0
        self.assertEqual(s.query_one("SELECT COUNT(*) AS n FROM feedback")["n"], 1)
        self.assertEqual(s.query_one("SELECT COUNT(*) AS n FROM audit_log")["n"], 0)

    def test_an_inner_transaction_joins_the_outer_one(self):
        s = self.open()
        with self.assertRaises(RuntimeError):
            with s.transaction():
                s.audit("outer")
                with s.transaction():
                    s.audit("inner")
                raise RuntimeError("late failure")
        self.assertEqual(s.counts()["audit_log"], 0)                         # the inner one was rolled back too
        with s.transaction():
            with s.transaction():
                s.audit("a")
            s.audit("b")
        self.assertEqual(s.counts()["audit_log"], 2)

    def test_the_audit_log_is_a_hash_chain(self):
        s = self.open()
        for i in range(5):
            s.audit(f"event_{i}", "cap_one" if i % 2 else "cap_two", i, None, {"i": i})
        self.assertEqual(s.verify_audit_chain(), (True, None, 5))
        entries = s.audit_entries(limit=3)
        self.assertEqual([e["event"] for e in entries], ["event_4", "event_3", "event_2"])      # newest first
        self.assertEqual(entries[0]["entry_hash"], s.last_audit_hash())
        self.assertEqual(entries[0]["prev_hash"], entries[1]["entry_hash"])
        self.assertEqual({e["capability_id"] for e in s.audit_entries(capability_id="cap_one")}, {"cap_one"})
        self.assertEqual(s.query_one("SELECT prev_hash FROM audit_log WHERE seq = 1")["prev_hash"], "0" * 64)

    def test_every_kind_of_audit_tampering_is_detected(self):
        def fresh():
            if os.path.exists(self.dbpath()):
                os.unlink(self.dbpath())
            s = Store(self.dbpath())
            self.addCleanup(s.close)
            for i in range(5):
                s.audit(f"event_{i}", "cap_one", i, None, {"i": i})
            return s
        for label, sql, bad_seq in (
                ("detail edited", "UPDATE audit_log SET detail_json = '{\"i\":99}' WHERE seq = 3", 3),
                ("event renamed", "UPDATE audit_log SET event = 'harmless' WHERE seq = 2", 2),
                ("version edited", "UPDATE audit_log SET version = 42 WHERE seq = 4", 4),
                ("timestamp edited", "UPDATE audit_log SET ts = '2000-01-01' WHERE seq = 5", 5),
                ("entry deleted", "DELETE FROM audit_log WHERE seq = 2", 3),
                ("hash rewritten", "UPDATE audit_log SET entry_hash = '" + "a" * 64 + "' WHERE seq = 3", 3),
                ("link rewritten", "UPDATE audit_log SET prev_hash = '" + "b" * 64 + "' WHERE seq = 4", 4)):
            with self.subTest(label):
                s = fresh()
                s.execute(sql)
                ok, seq, _ = s.verify_audit_chain()
                self.assertFalse(ok)
                self.assertEqual(seq, bad_seq)

    def test_concurrent_writers_are_serialised(self):
        s = self.open()
        errors = []

        def worker(n):
            try:
                for i in range(25):
                    with s.transaction():
                        s.audit("w", f"cap_{n}", i, None, {"n": n})
            except Exception as e:           # pragma: no cover - the assertion below reports it
                errors.append(repr(e))
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(s.verify_audit_chain(), (True, None, 200))

    def test_json_helpers(self):
        self.assertEqual(store_mod.dumps({"b": 1, "a": "ی"}), '{"a":"ی","b":1}')
        self.assertEqual(store_mod.loads('{"a":1}'), {"a": 1})
        self.assertEqual(store_mod.loads("{broken", default="d"), "d")
        self.assertEqual(store_mod.loads(None, default=5), 5)
        self.assertRegex(store_mod.now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")


# ============================================================================ workspace
class TestWorkspace(TempDirCase):
    def ws(self):
        return Workspace(self.root)

    def test_construction_creates_exactly_the_allowed_directories(self):
        self.assertFalse(os.path.exists(self.root))
        self.ws()
        self.assertEqual(sorted(os.listdir(self.root)),
                         sorted([policy.SUBDIR_STAGING, policy.SUBDIR_MODULES, policy.SUBDIR_TESTS,
                                 policy.SUBDIR_SPECS, policy.SUBDIR_CHECKPOINTS, policy.SUBDIR_QUARANTINE]))

    def test_write_read_roundtrip_with_private_permissions(self):
        ws = self.ws()
        path = ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "x = 1\n", policy.OP_CREATE_MODULE)
        self.assertEqual(path, os.path.join(os.path.realpath(self.root), "modules", "abc_v1.py"))
        self.assertEqual(ws.read(policy.SUBDIR_MODULES, "abc_v1.py"), b"x = 1\n")
        self.assertTrue(ws.exists(policy.SUBDIR_MODULES, "abc_v1.py"))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        ws.write(policy.SUBDIR_TESTS, "abc_v1.json", b'{"a": "\xd8\xa7"}', policy.OP_CREATE_TESTS)
        self.assertEqual(json.loads(ws.read(policy.SUBDIR_TESTS, "abc_v1.json")), {"a": "ا"})

    def test_a_failed_write_leaves_neither_a_partial_nor_a_changed_file(self):
        ws = self.ws()
        ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "old\n", policy.OP_CREATE_MODULE)
        with mock.patch("self_builder.workspace.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "new\n", policy.OP_CREATE_MODULE)
            with self.assertRaises(OSError):
                ws.write(policy.SUBDIR_MODULES, "other_v1.py", "new\n", policy.OP_CREATE_MODULE)
        self.assertEqual(ws.read(policy.SUBDIR_MODULES, "abc_v1.py"), b"old\n")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "modules"))), ["abc_v1.py"])    # no .part files

    def test_size_limits(self):
        ws = self.ws()
        with self.assertRaises(PolicyViolation) as cm:
            ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "x" * (policy.MAX_SOURCE_BYTES + 1), policy.OP_CREATE_MODULE)
        self.assertEqual(cm.exception.code, "E_POLICY_SIZE")
        ws.write(policy.SUBDIR_MODULES, "abc_v2.py", "x" * policy.MAX_SOURCE_BYTES, policy.OP_CREATE_MODULE)
        with self.assertRaises(PolicyViolation):
            ws.write(policy.SUBDIR_TESTS, "abc_v1.json", "x" * (policy.MAX_TESTS_BYTES + 1), policy.OP_CREATE_TESTS)
        with self.assertRaises(PolicyViolation):
            ws.read(policy.SUBDIR_MODULES, "abc_v2.py", limit=100)

    def test_names_directories_suffixes_and_operations_are_enforced(self):
        ws = self.ws()
        for subdir, name in ((policy.SUBDIR_MODULES, "../escape_v1.py"), (policy.SUBDIR_MODULES, "/etc/passwd"),
                             (policy.SUBDIR_MODULES, "abc_v1.py/../../x"), (policy.SUBDIR_MODULES, "abc_v1.sh"),
                             (policy.SUBDIR_MODULES, "ABC_v1.py"), (policy.SUBDIR_MODULES, "abc_v1.py\x00"),
                             (policy.SUBDIR_MODULES, "..\\abc_v1.py"), (policy.SUBDIR_MODULES, "abc.py"),
                             (policy.SUBDIR_TESTS, "abc_v1.py"), ("..", "abc_v1.py"), ("etc", "abc_v1.py"),
                             (None, "abc_v1.py"), (policy.SUBDIR_STAGING, "abc.py")):
            with self.subTest(subdir=subdir, name=name), self.assertRaises(PolicyViolation):
                ws.write(subdir, name, "x", policy.OP_CREATE_MODULE)
        with self.assertRaises(PolicyViolation) as cm:
            ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "x", "delete_everything")
        self.assertEqual(cm.exception.code, "E_POLICY_OPERATION")
        self.assertEqual(os.listdir(os.path.join(self.root, "modules")), [])
        self.assertEqual(sorted(os.listdir(self.tmp)), ["self_builder"])                       # nothing outside the root

    def test_symlinks_are_never_followed(self):
        ws = self.ws()
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w") as f:
            f.write("secret")
        os.symlink(secret, os.path.join(self.root, "modules", "abc_v1.py"))                    # a symlinked file
        with self.assertRaises(PolicyViolation) as cm:
            ws.read(policy.SUBDIR_MODULES, "abc_v1.py")
        self.assertEqual(cm.exception.code, "E_POLICY_SYMLINK")
        with self.assertRaises(PolicyViolation):
            ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "overwrite", policy.OP_CREATE_MODULE)
        with open(secret) as f:
            self.assertEqual(f.read(), "secret")
        os.unlink(os.path.join(self.root, "modules", "abc_v1.py"))
        shutil.rmtree(os.path.join(self.root, "tests"))
        os.symlink(outside, os.path.join(self.root, "tests"))                                  # a symlinked directory
        with self.assertRaises(PolicyViolation) as cm:
            ws.write(policy.SUBDIR_TESTS, "abc_v1.json", "{}", policy.OP_CREATE_TESTS)
        self.assertEqual(cm.exception.code, "E_POLICY_SYMLINK")
        self.assertEqual(os.listdir(outside), ["secret.txt"])

    def test_move_remove_and_list(self):
        ws = self.ws()
        ws.write(policy.SUBDIR_STAGING, "stg_abc_v1.py", "x\n", policy.OP_STAGE)
        ws.move(policy.SUBDIR_STAGING, "stg_abc_v1.py", policy.SUBDIR_MODULES, "abc_v1.py", policy.OP_CREATE_MODULE)
        self.assertEqual((ws.listdir(policy.SUBDIR_STAGING), ws.listdir(policy.SUBDIR_MODULES)), ([], ["abc_v1.py"]))
        self.assertTrue(ws.remove(policy.SUBDIR_MODULES, "abc_v1.py"))
        self.assertFalse(ws.remove(policy.SUBDIR_MODULES, "abc_v1.py"))
        with self.assertRaises(PolicyViolation):
            ws.listdir("etc")

    def test_quarantine_moves_files_and_never_deletes_them(self):
        ws = self.ws()
        ws.write(policy.SUBDIR_MODULES, "abc_v1.py", "evidence\n", policy.OP_CREATE_MODULE)
        name = ws.quarantine(policy.SUBDIR_MODULES, "abc_v1.py", "integrity")
        self.assertRegex(name, r"^q_\d+_integrity_modules_abc_v1\.py$")
        self.assertEqual(ws.read(policy.SUBDIR_QUARANTINE, name), b"evidence\n")
        self.assertFalse(ws.exists(policy.SUBDIR_MODULES, "abc_v1.py"))
        self.assertIsNone(ws.quarantine(policy.SUBDIR_MODULES, "abc_v1.py", "again"))          # already gone
        # hostile reason / name text cannot change the destination
        ws.write(policy.SUBDIR_MODULES, "abc_v2.py", "x\n", policy.OP_CREATE_MODULE)
        name = ws.quarantine(policy.SUBDIR_MODULES, "abc_v2.py", "../../etc/x y")
        self.assertTrue(ws.exists(policy.SUBDIR_QUARANTINE, name))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["self_builder"])

    def test_quarantined_files_never_overwrite_each_other(self):
        ws = self.ws()
        # the same file name in two directories ...
        ws.write(policy.SUBDIR_TESTS, "abc_v1.json", '{"role": "tests"}', policy.OP_CREATE_TESTS)
        ws.write(policy.SUBDIR_SPECS, "abc_v1.json", '{"role": "spec"}', policy.OP_CREATE_SPEC)
        a = ws.quarantine(policy.SUBDIR_TESTS, "abc_v1.json", "orphan")
        b = ws.quarantine(policy.SUBDIR_SPECS, "abc_v1.json", "orphan")
        self.assertNotEqual(a, b)
        self.assertEqual(json.loads(ws.read(policy.SUBDIR_QUARANTINE, a)), {"role": "tests"})
        self.assertEqual(json.loads(ws.read(policy.SUBDIR_QUARANTINE, b)), {"role": "spec"})
        # ... and one file quarantined again within the same second
        names = set()
        for i in range(5):
            ws.write(policy.SUBDIR_MODULES, "abc_v1.py", f"version {i}\n", policy.OP_CREATE_MODULE)
            names.add(ws.quarantine(policy.SUBDIR_MODULES, "abc_v1.py", "integrity"))
        self.assertEqual(len(names), 5)
        self.assertEqual(sorted(ws.read(policy.SUBDIR_QUARANTINE, n) for n in names),
                         [f"version {i}\n".encode() for i in range(5)])
        for name in names:
            policy.Policy.check_file_name(policy.SUBDIR_QUARANTINE, name)      # every name stays inside the policy

    def test_a_quarantined_symlink_is_unlinked_not_followed(self):
        ws = self.ws()
        target = os.path.join(self.tmp, "target.txt")
        with open(target, "w") as f:
            f.write("keep")
        os.symlink(target, os.path.join(self.root, "modules", "abc_v1.py"))
        self.assertIsNone(ws.quarantine(policy.SUBDIR_MODULES, "abc_v1.py", "stray"))
        self.assertFalse(os.path.lexists(os.path.join(self.root, "modules", "abc_v1.py")))
        with open(target) as f:
            self.assertEqual(f.read(), "keep")

    def test_staging_and_partial_cleanup(self):
        ws = self.ws()
        ws.write(policy.SUBDIR_STAGING, "stg_a_v1.py", "x", policy.OP_STAGE)
        ws.write(policy.SUBDIR_STAGING, "stg_a_v1_tests.json", "{}", policy.OP_STAGE)
        self.assertEqual(sorted(ws.clear_staging()), ["stg_a_v1.py", "stg_a_v1_tests.json"])
        self.assertEqual(ws.listdir(policy.SUBDIR_STAGING), [])
        for sub in ("modules", "specs", "."):
            with open(os.path.join(self.root, sub, "x.part4242"), "w") as f:
                f.write("half")
        self.assertEqual(ws.listdir(policy.SUBDIR_MODULES), [])                                # partials are invisible
        self.assertEqual(sorted(ws.sweep_partials()), ["x.part4242"] * 3)
        self.assertEqual(ws.sweep_partials(), [])

    def test_the_manifest_and_the_two_root_files(self):
        ws = self.ws()
        self.assertIsNone(ws.read_manifest())
        ws.write_manifest({"capabilities": {"a": {"title": "ی"}}})
        self.assertEqual(ws.read_manifest(), {"capabilities": {"a": {"title": "ی"}}})
        self.assertEqual(os.path.basename(ws.manifest_path()), "manifest.json")
        self.assertEqual(os.path.basename(ws.db_path()), "self_builder.db")
        with open(ws.manifest_path(), "w") as f:
            f.write("{not json")
        self.assertIsNone(ws.read_manifest())
        with self.assertRaises(PolicyViolation):
            ws.write_root_file("evil.py", "x", policy.OP_WRITE_MANIFEST)
        with self.assertRaises(PolicyViolation):
            ws.write_root_file("manifest.json", "x", "not_an_operation")


# ============================================================================ the build pipeline
STAGES_CREATE = ["request", "analyze", "spec", "check_capabilities", "identify_gap", "plan", "generate", "validate",
                 "test", "checkpoint", "apply", "persist", "register", "version", "audit"]


def run_python(code, *args, timeout=120, cwd=None):
    """Run `code` in a fresh interpreter whose only import root is the source tree."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=SRC_DIR, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(code), *args], env=env, capture_output=True,
                          text=True, timeout=timeout, cwd=cwd or tempfile.gettempdir())


class TestBuildPipeline(TempDirCase):
    def test_a_formula_variable_may_not_start_with_an_underscore(self):
        svc = self.service()
        for expression in ("__builtins__ + 1", "_a * 2", "a + __import__"):
            with self.subTest(expression=expression):
                result = self.build(svc, f"فرمول تست را یاد بگیر: {expression}", confirmed=True)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "E_EXPR_TOKEN")
        self.assertEqual(svc.capabilities(), [])                   # nothing was created, not even a broken version
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])
        self.built(svc, "فرمول تست را یاد بگیر: a_1 * 2", confirmed=True)   # an inner underscore is fine

    def test_a_build_runs_every_stage_in_order_and_persists_everything(self):
        svc = self.service()
        r = self.built(svc, KM_MI)
        self.assertEqual([s["stage"] for s in r["stages"]], STAGES_CREATE)
        self.assertTrue(all(s["ok"] for s in r["stages"]))
        self.assertEqual((r["version"], r["action"], r["previous_version"], r["capability_id"]),
                         (1, "create", None, "unit_km_to_mi"))
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(self.files(policy.SUBDIR_TESTS), ["unit_km_to_mi_v1.json"])
        self.assertEqual(self.files(policy.SUBDIR_SPECS), ["unit_km_to_mi_v1.json"])
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertEqual(self.files(policy.SUBDIR_CHECKPOINTS), ["ck_1.json"])
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])
        record = svc.capability("unit_km_to_mi")
        with open(os.path.join(self.root, "modules", "unit_km_to_mi_v1.py"), "rb") as f:
            self.assertEqual(sandbox.sha256_bytes(f.read()), record["source"]["module_sha256"])
        # the registry record carries everything the master prompt lists
        for key in ("id", "title", "description", "version", "status", "inputs", "outputs", "dependencies", "source",
                    "tests", "permissions", "validation", "rollback", "kind", "latest_version", "usage", "versions"):
            self.assertIn(key, record, key)
        self.assertEqual((record["status"], record["version"], record["kind"]), ("active", 1, "unit_conversion"))
        self.assertEqual([i["name"] for i in record["inputs"]], ["value"])
        self.assertEqual(record["permissions"], ["compute"])
        self.assertEqual((record["tests"]["total"], record["tests"]["passed"], record["tests"]["ok"]),
                         (13, 13, True))
        self.assertTrue(record["validation"]["ok"])
        self.assertEqual(record["rollback"], {"previous_version": None, "checkpoint_id": 1, "restorable": False})
        # persisted run history, audit trail, manifest, checkpoint
        row = svc.history("unit_km_to_mi")[0]
        self.assertEqual((row["kind"], row["result"], row["version"], row["error_code"]), ("build", "applied", 1, None))
        self.assertEqual(row["plan"]["action"], "create")
        self.assertEqual([f["dir"] for f in row["plan"]["files"]], ["modules", "tests", "specs"])
        self.assertEqual([s["stage"] for s in row["attempts"]["stages"]], STAGES_CREATE)
        self.assertEqual([e["event"] for e in reversed(svc.audit_tail(20))],
                         ["upgrade_started", "checkpoint_created", "capability_registered", "upgrade_applied"])
        with open(os.path.join(self.root, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["capabilities"]["unit_km_to_mi"]["active_version"], 1)
        self.assertEqual(manifest["audit_head"], svc.audit_tail(1)[0]["entry_hash"])
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT status FROM checkpoints").fetchall(), [("applied",)])
        finally:
            con.close()
        out = svc.invoke("unit_km_to_mi", {"value": 10})
        self.assertEqual((out["ok"], out["version"]), (True, 1))
        self.assertAlmostEqual(out["value"], 6.21371192237334, places=12)

    def test_the_three_archetypes_build_and_run(self):
        svc = self.service()
        cid = self.built(svc, BMI)["capability_id"]
        self.assertAlmostEqual(svc.invoke(cid, {"v1": 70, "v2": 1.75})["value"], 22.857142857142858, places=9)
        cid = self.built(svc, WORDS)["capability_id"]
        self.assertEqual(svc.invoke(cid, {"text": "سلام دنیای زیبا"})["value"], 3.0)
        cid = self.built(svc, "یک ابزار بساز که متن را معکوس کند")["capability_id"]
        self.assertEqual(svc.invoke(cid, {"text": "abc"})["value"], "cba")
        self.assertEqual(len(svc.capabilities()), 3)

    def test_an_identical_request_is_a_noop(self):
        svc = self.service()
        self.built(svc, KM_MI)
        before = (self.files(policy.SUBDIR_MODULES), svc.capability("unit_km_to_mi")["versions"])
        for text in (KM_MI, "مبدل کیلومتر به مایل بساز", "یک مبدل km به mi بساز",
                     "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶۲۱۳۷۱۱۹۲۲۳۷۳۳۴ مایل است"):
            with self.subTest(text=text):
                r = self.build(svc, text)
                self.assertEqual((r["status"], r["action"], r["version"]), ("noop_identical", "noop", 1))
        self.assertEqual((self.files(policy.SUBDIR_MODULES), svc.capability("unit_km_to_mi")["versions"]), before)
        self.assertEqual([h["result"] for h in svc.history()][:2], ["noop", "noop"])
        self.assertIn("noop_identical", [e["event"] for e in svc.audit_tail(20)])

    def test_a_different_factor_is_confirmed_first_and_then_becomes_version_2(self):
        svc = self.service()
        self.built(svc, KM_MI)
        r = self.build(svc, KM_MI_06)
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertEqual(r["confirmation"]["reason"], "factor_deviation")
        self.assertAlmostEqual(r["confirmation"]["details"]["table_scale"], 0.621371192237334)
        self.assertEqual(r["confirmation"]["details"]["user_scale"], 0.6)
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 1)           # nothing changed
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(svc.history()[0]["result"], "needs_confirmation")
        r2 = self.build(svc, KM_MI_06, confirmed=True)
        self.assertEqual((r2["status"], r2["action"], r2["version"], r2["previous_version"]),
                         ("applied", "improve", 2, 1))
        self.assertEqual([c["field"] for c in r2["changes"]], ["scale"])
        self.assertEqual(r2["changes"][0]["new"], 0.6)
        record = svc.capability("unit_km_to_mi")
        self.assertEqual((record["version"], record["latest_version"]), (2, 2))
        self.assertEqual([(v["version"], v["status"], v["parent_version"]) for v in record["versions"]],
                         [(1, "superseded", None), (2, "active", 1)])
        self.assertEqual(record["rollback"]["previous_version"], 1)
        self.assertTrue(record["rollback"]["restorable"])
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py", "unit_km_to_mi_v2.py"])
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.0)
        self.assertEqual(self.files(policy.SUBDIR_CHECKPOINTS), ["ck_1.json", "ck_2.json"])
        with open(os.path.join(self.root, "checkpoints", "ck_2.json"), encoding="utf-8") as f:
            ck = json.load(f)
        self.assertEqual((ck["from_version"], ck["to_version"]), (1, 2))
        self.assertEqual([f["name"] for f in ck["files"]], ["unit_km_to_mi_v1.py", "unit_km_to_mi_v1.json",
                                                            "unit_km_to_mi_v1.json"])
        self.assertIn("capability_upgraded", [e["event"] for e in svc.audit_tail(20)])

    def test_rollback_restores_the_previous_version_and_keeps_the_rolled_back_one(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        r = svc.rollback("unit_km_to_mi")
        self.assertEqual((r["status"], r["action"], r["version"], r["from_version"]), ("applied", "rollback", 1, 2))
        self.assertTrue(r["verified"][0]["ok"])
        self.assertTrue(r["verified"][0]["tests"]["ok"])
        record = svc.capability("unit_km_to_mi")
        self.assertEqual([(v["version"], v["status"]) for v in record["versions"]],
                         [(1, "active"), (2, "rolled_back")])
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py", "unit_km_to_mi_v2.py"])
        self.assertEqual(svc.history()[0]["kind"], "rollback")
        self.assertIn("rolled_back", [e["event"] for e in svc.audit_tail(20)])
        # there is nothing older left: a second rollback fails and changes nothing
        r2 = svc.rollback("unit_km_to_mi")
        self.assertEqual((r2["status"], r2["error"]["code"]), ("failed", "E_ROLLBACK_NO_TARGET"))
        self.assertTrue(r2["error"]["info"]["can_disable"])
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 1)

    def test_rollback_to_an_explicit_version_and_forward_again(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        self.built(svc, "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۷ مایل است", confirmed=True)
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 3)
        self.assertEqual(svc.rollback("unit_km_to_mi", to_version=1)["version"], 1)
        self.assertEqual([v["status"] for v in svc.capability("unit_km_to_mi")["versions"]],
                         ["active", "superseded", "rolled_back"])
        self.assertEqual(svc.rollback("unit_km_to_mi", to_version=2)["version"], 2)       # roll forward to a healthy one
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.0)
        for bad in (99, 0, -1, 2):
            with self.subTest(to_version=bad):
                r = svc.rollback("unit_km_to_mi", to_version=bad)
                self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_ROLLBACK_BAD_TARGET"))
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 2)

    def test_going_forward_again_does_not_reject_the_version_that_is_left_behind(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        self.assertEqual(svc.rollback("unit_km_to_mi")["version"], 1)              # v2 judged bad
        self.assertEqual(svc.rollback("unit_km_to_mi", to_version=2)["version"], 2)  # the user changes their mind
        self.assertEqual([v["status"] for v in svc.capability("unit_km_to_mi")["versions"]], ["superseded", "active"])
        again = svc.rollback("unit_km_to_mi")                                      # "the previous version" is v1 again
        self.assertEqual((again["status"], again["version"], again["from_version"]), ("applied", 1, 2))
        self.assertEqual([v["status"] for v in svc.capability("unit_km_to_mi")["versions"]], ["active", "rolled_back"])
        self.assertTrue(svc.self_check()["ok"])

    def test_rollback_of_things_that_cannot_be_rolled_back(self):
        svc = self.service()
        r = svc.rollback("unit_km_to_mi")                                  # no registry yet: nothing is created
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_ROLLBACK_NO_REGISTRY"))
        self.assertFalse(os.path.exists(self.root))
        self.built(svc, KM_MI)
        for cid, code in (("no_such_capability", "E_ROLLBACK_UNKNOWN"), ("../x", "E_POLICY_ID"), ("", "E_POLICY_ID"),
                          ("Unit_KM", "E_POLICY_ID")):
            with self.subTest(cid=cid):
                r = svc.rollback(cid)
                self.assertEqual((r["status"], r["error"]["code"]), ("failed", code))

    def test_disable_and_rebuild(self):
        svc = self.service()
        self.built(svc, KM_MI)
        r = svc.disable("unit_km_to_mi")
        self.assertEqual((r["status"], r["action"]), ("applied", "disable"))
        record = svc.capability("unit_km_to_mi")
        self.assertEqual((record["status"], record["version"]), ("disabled", None))
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 1})["error"], "not_active")
        self.assertEqual(svc.match("۱۰ کیلومتر چند مایل است؟")["status"], "gap")
        self.assertFalse(svc.has_active_capabilities())
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])        # nothing was deleted
        for again in (svc.disable("unit_km_to_mi"), svc.disable("no_such_capability")):
            self.assertEqual((again["status"], again["error"]["code"]), ("failed", "E_DISABLE_NOT_ACTIVE"))
        r = self.built(svc, KM_MI)                                                       # building it again re-enables it
        self.assertEqual((r["action"], r["version"]), ("create", 2))
        self.assertEqual(svc.capability("unit_km_to_mi")["status"], "active")
        self.assertTrue(svc.has_active_capabilities())
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)

    def test_a_failed_improvement_leaves_the_previous_version_active(self):
        svc = self.service()
        self.built(svc, KM_MI)
        r = self.build(svc, KM_MI_06 + ". مثلاً ۱۰ کیلومتر می‌شود ۷", confirmed=True)
        self.assertEqual((r["status"], r["error"]["code"], r["active_version"]), ("failed", "E_BUILD_TESTS_FAILED", 1))
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 1)
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)
        self.assertEqual(svc.history()[0]["result"], "failed")

    def test_the_request_text_and_limits_are_bounded(self):
        svc = self.service()
        request = rp.parse_build_request(KM_MI)
        r = svc.build("x" * 5000, request)
        self.assertEqual(r["status"], "applied")
        self.assertLessEqual(len(r["request_text"]), policy.MAX_REQUEST_CHARS)
        incomplete = rp.parse_build_request("یک مبدل بساز")
        r = svc.build("یک مبدل بساز", incomplete)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_NOT_READY"))
        self.assertEqual(r["error"]["info"]["missing"], ["from_unit", "to_unit"])

    def test_the_capability_and_version_limits(self):
        svc = self.service()
        with mock.patch.object(policy, "MAX_CAPABILITIES", 2):
            self.built(svc, KM_MI)
            self.built(svc, M_FT)
            r = self.build(svc, WORDS)
            self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_LIMIT_CAPABILITIES"))
            self.assertEqual(len(svc.capabilities()), 2)
            self.assertEqual(self.build(svc, KM_MI)["status"], "noop_identical")        # existing ones still work
        with mock.patch.object(policy, "MAX_VERSIONS_PER_CAPABILITY", 2):
            self.built(svc, KM_MI_06, confirmed=True)
            r = self.build(svc, "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۷ مایل است", confirmed=True)
            self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_LIMIT_VERSIONS"))
            self.assertEqual(svc.capability("unit_km_to_mi")["version"], 2)

    def test_history_is_newest_first_and_limited(self):
        svc = self.service()
        for text in (KM_MI, M_FT, WORDS):
            self.built(svc, text)
        kinds = [(h["kind"], h["capability_id"]) for h in svc.history()]
        self.assertEqual(kinds, [("build", "text_count_words"), ("build", "unit_m_to_ft"), ("build", "unit_km_to_mi")])
        self.assertEqual(len(svc.history(limit=2)), 2)
        self.assertEqual([h["capability_id"] for h in svc.history("unit_m_to_ft")], ["unit_m_to_ft"])
        self.assertEqual(svc.history("no_such_capability"), [])


class TestInjectedFailures(TempDirCase):
    """A fault at any point of the pipeline must leave a consistent, usable Self-Builder."""

    def assert_nothing_was_activated(self, svc):
        self.assertEqual(svc.capabilities(), [])
        con = self.db()
        try:
            for table in ("capabilities", "capability_versions"):
                self.assertEqual(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
        finally:
            con.close()
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])

    def assert_still_usable(self, svc):
        r = self.built(svc, "یک مبدل سانتی‌متر به اینچ بساز")
        self.assertAlmostEqual(svc.invoke(r["capability_id"], {"value": 254})["value"], 100.0, places=9)
        self.assertEqual(svc.self_check()["ok"], True)

    def test_generated_code_that_the_validator_rejects_is_never_applied(self):
        svc = self.service()
        real = templates.generate_module
        evil = "import os\n"
        with mock.patch.object(templates, "generate_module", lambda spec, version: evil + real(spec, version)):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_VALIDATION"))
        self.assertTrue(r["error"]["info"]["violations"])
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])
        self.assert_nothing_was_activated(svc)
        self.assertIn("upgrade_failed", [e["event"] for e in svc.audit_tail(10)])
        self.assertEqual(svc.history()[0]["error_code"], "E_BUILD_VALIDATION")
        self.assert_still_usable(svc)

    def test_generated_code_that_fails_its_tests_is_never_applied(self):
        svc = self.service()
        real = templates.generate_module
        with mock.patch.object(templates, "generate_module",
                               lambda spec, version: real(spec, version).replace("x_value * SCALE", "x_value * SCALE * 2")):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_TESTS_FAILED"))
        self.assertEqual(r["error"]["info"]["failure_class"], "reference_mismatch")      # a generation bug: never repaired
        self.assertEqual(r["repairs"], [])
        self.assert_nothing_was_activated(svc)
        self.assert_still_usable(svc)

    def test_generated_code_that_crashes_when_run_is_never_applied(self):
        svc = self.service()
        real = templates.generate_module
        with mock.patch.object(templates, "generate_module",
                               lambda spec, version: real(spec, version).replace(
                                   '{"value": convert(_sb_number_input(inputs, "value"))}', '{"value": True}')):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_TESTS_FAILED"))
        self.assertEqual(r["error"]["info"]["failure_class"], "sandbox_fault")
        self.assert_nothing_was_activated(svc)

    def test_an_io_error_while_promoting_files_is_rolled_back(self):
        svc = self.service()
        real_move = Workspace.move
        calls = []

        def flaky(self_, src_sub, src_name, dst_sub, dst_name, op):
            calls.append(dst_name)
            if len(calls) == 2:
                raise OSError("disk went away")
            return real_move(self_, src_sub, src_name, dst_sub, dst_name, op)
        with mock.patch.object(Workspace, "move", flaky):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_INTERNAL"))
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])                      # the first promoted file was undone
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 1)               # ... by quarantine, not by deletion
        self.assert_nothing_was_activated(svc)
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT status FROM checkpoints").fetchall(), [("abandoned",)])
        finally:
            con.close()
        self.assert_still_usable(svc)

    def test_a_failure_inside_the_registration_transaction_leaves_no_trace(self):
        svc = self.service()
        real_audit = Store.audit

        def failing(self_, event, *a, **k):
            if event == "capability_registered":
                raise RuntimeError("fault between insert and commit")
            return real_audit(self_, event, *a, **k)
        with mock.patch.object(Store, "audit", failing):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_INTERNAL"))
        self.assert_nothing_was_activated(svc)
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 3)               # module, tests and spec
        self.assertTrue(all(n.startswith("q_") for n in self.files(policy.SUBDIR_QUARANTINE)))
        self.assertTrue(svc.status()["audit_chain"]["ok"])
        self.assert_still_usable(svc)

    def test_a_failure_while_improving_keeps_the_old_version_running(self):
        svc = self.service()
        self.built(svc, KM_MI)
        real_audit = Store.audit

        def failing(self_, event, *a, **k):
            if event == "capability_upgraded":
                raise RuntimeError("fault")
            return real_audit(self_, event, *a, **k)
        with mock.patch.object(Store, "audit", failing):
            r = self.build(svc, KM_MI_06, confirmed=True)
        self.assertEqual(r["status"], "failed")
        record = svc.capability("unit_km_to_mi")
        self.assertEqual((record["version"], [v["status"] for v in record["versions"]]), (1, ["active"]))
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(svc.self_check()["ok"], True)

    def test_an_interrupt_propagates_but_the_state_stays_consistent(self):
        svc = self.service()
        with mock.patch.object(loader, "verify_version", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.build(svc, KM_MI)
        self.assertEqual(self.files(policy.SUBDIR_MODULES), [])
        svc.close()
        restarted = self.service()                          # a restart settles the unfinished run
        self.assertEqual(restarted.capabilities(), [])
        self.assertGreaterEqual(restarted.status()["startup"]["interrupted_upgrades"], 1)
        self.assertEqual(restarted.history()[0]["result"], "interrupted")
        self.assert_still_usable(restarted)

    def test_a_process_that_dies_between_promotion_and_registration(self):
        code = """
            import os, sys
            from self_builder import request_parser as rp
            from self_builder.service import SelfBuilderService
            from self_builder.store import Store
            real = Store.audit
            def audit(self, event, *a, **k):
                if event == "capability_registered":
                    os._exit(9)                      # the process vanishes inside the registration transaction
                return real(self, event, *a, **k)
            Store.audit = audit
            svc = SelfBuilderService(sys.argv[1])
            text = "یک مبدل کیلومتر به مایل بساز"
            svc.build(text, rp.parse_build_request(text))
            os._exit(0)
        """
        proc = run_python(code, self.root)
        self.assertEqual(proc.returncode, 9, proc.stderr)
        # what the dead process left behind: promoted but unregistered files
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(self.files(policy.SUBDIR_TESTS), ["unit_km_to_mi_v1.json"])
        svc = self.service()                                  # the next start reconciles
        self.assertEqual(svc.capabilities(), [])
        startup = svc.status()["startup"]
        self.assertEqual(startup["interrupted_upgrades"], 1)
        self.assertEqual(len(startup["quarantined"]), 3)
        for sub in (policy.SUBDIR_MODULES, policy.SUBDIR_TESTS, policy.SUBDIR_SPECS):
            self.assertEqual(self.files(sub), [], sub)
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 3)
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT status FROM checkpoints").fetchall(), [("abandoned",)])
            self.assertEqual(con.execute("SELECT COUNT(*) FROM capability_versions").fetchone()[0], 0)
        finally:
            con.close()
        self.assertTrue(svc.status()["audit_chain"]["ok"])
        self.assert_still_usable(svc)


# ============================================================================ start-up reconciliation
class TestReconcile(TempDirCase):
    """What a restart must never be fooled by: modified, missing, forged, stray and half-written files."""

    EVIL = "import os\nCAPABILITY_ID = 'unit_km_to_mi'\n"

    def two_versions(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        svc.close()

    def one_version(self):
        svc = self.service()
        self.built(svc, KM_MI)
        svc.close()

    def path(self, sub, name):
        return os.path.join(self.root, sub, name)

    def tamper_append(self, sub, name, text="\n# modified by someone\n"):
        with open(self.path(sub, name), "a", encoding="utf-8") as f:
            f.write(text)

    def sql(self, statement, params=()):
        con = self.db()
        try:
            with con:
                con.execute(statement, params)
        finally:
            con.close()

    def assert_fell_back_to_v1(self, svc, error, broken=2):
        startup = svc.status()["startup"]
        self.assertEqual(len(startup["fallbacks"]), 1, startup)
        fb = startup["fallbacks"][0]
        self.assertEqual((fb["capability_id"], fb["broken_version"], fb["restored_version"], fb["error"]),
                         ("unit_km_to_mi", broken, 1, error))
        record = svc.capability("unit_km_to_mi")
        self.assertEqual([(v["version"], v["status"]) for v in record["versions"]], [(1, "active"), (2, "broken")])
        out = svc.invoke("unit_km_to_mi", {"value": 10})
        self.assertEqual((out["ok"], out["version"]), (True, 1))
        self.assertAlmostEqual(out["value"], 6.21371192237334, places=12)
        self.assertIn("reconcile_fallback", [e["event"] for e in svc.audit_tail(20)])
        self.assertTrue(svc.status()["audit_chain"]["ok"])

    def test_a_modified_active_module_is_replaced_by_the_previous_version(self):
        self.two_versions()
        evidence = "\n# modified by someone\n"
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py", evidence)
        svc = self.service()
        self.assert_fell_back_to_v1(svc, "E_VERIFY_MODULE_HASH")
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        (name,) = self.files(policy.SUBDIR_QUARANTINE)
        with open(self.path(policy.SUBDIR_QUARANTINE, name), encoding="utf-8") as f:
            self.assertIn(evidence, f.read())                                      # the evidence was kept
        with open(self.path(".", "manifest.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["capabilities"]["unit_km_to_mi"]["active_version"], 1)

    def test_reconciliation_is_idempotent(self):
        self.two_versions()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py")
        first = self.service()
        self.assertEqual(len(first.status()["startup"]["fallbacks"]), 1)          # the first start repairs it
        first.close()
        svc = self.service()                                                      # the second restart
        startup = svc.status()["startup"]
        self.assertEqual((startup["fallbacks"], startup["disabled"], startup["quarantined"],
                          startup["interrupted_upgrades"]), ([], [], [], 0))
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 1)
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 1)

    def test_a_missing_module_file(self):
        self.two_versions()
        os.unlink(self.path(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py"))
        self.assert_fell_back_to_v1(self.service(), "E_VERIFY_MODULE_MISSING")

    def test_a_modified_test_suite_file(self):
        self.two_versions()
        self.tamper_append(policy.SUBDIR_TESTS, "unit_km_to_mi_v2.json", "\n")
        self.assert_fell_back_to_v1(self.service(), "E_VERIFY_TESTS_HASH")

    def test_a_modified_spec_file(self):
        self.two_versions()
        self.tamper_append(policy.SUBDIR_SPECS, "unit_km_to_mi_v2.json", "\n")
        self.assert_fell_back_to_v1(self.service(), "E_VERIFY_SPEC_HASH")

    def test_a_forged_hash_cannot_make_a_malicious_module_trusted(self):
        self.two_versions()
        evil = self.EVIL
        with open(self.path(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py"), "w", encoding="utf-8") as f:
            f.write(evil)
        self.sql("UPDATE capability_versions SET module_sha256 = ? WHERE capability_id = 'unit_km_to_mi' AND version = 2",
                 (sandbox.sha256_bytes(evil.encode()),))                           # the attacker also fixes the registry
        svc = self.service()
        self.assert_fell_back_to_v1(svc, "E_VERIFY_LOAD")
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])

    def test_a_forged_spec_cannot_change_what_a_version_means(self):
        self.two_versions()
        self.sql("UPDATE capability_versions SET spec_json = replace(spec_json, '0.6', '0.5') WHERE version = 2")
        svc = self.service()          # the registry row is not what the files say: the files are authoritative
        out = svc.invoke("unit_km_to_mi", {"value": 10})
        self.assertTrue(out["ok"])
        self.assertEqual(out["value"], 6.0)                                        # the verified module, not the row

    def test_when_every_version_is_broken_the_capability_is_disabled_not_used(self):
        self.one_version()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v1.py")
        svc = self.service()
        startup = svc.status()["startup"]
        self.assertEqual([(d["capability_id"], d["broken_version"]) for d in startup["disabled"]],
                         [("unit_km_to_mi", 1)])
        record = svc.capability("unit_km_to_mi")
        self.assertEqual((record["status"], record["version"]), ("disabled", None))
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 1})["error"], "not_active")
        self.assertEqual(svc.match("۱۰ کیلومتر چند مایل است؟")["status"], "gap")      # it can be built again
        r = self.built(svc, KM_MI)
        self.assertEqual((r["action"], r["version"]), ("create", 2))
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)

    def test_a_version_the_user_rolled_back_is_not_a_fallback_target(self):
        self.two_versions()
        svc = self.service()
        self.built(svc, "یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۷ مایل است", confirmed=True)   # v3
        svc.rollback("unit_km_to_mi")                                              # v3 -> v2: the user judged v3 bad
        svc.rollback("unit_km_to_mi")                                              # v2 -> v1: ... and v2 as well
        svc.rollback("unit_km_to_mi", to_version=3)                                # then changes their mind about v3
        self.assertEqual([v["status"] for v in svc.capability("unit_km_to_mi")["versions"]],
                         ["superseded", "rolled_back", "active"])
        svc.close()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v3.py")
        svc = self.service()
        startup = svc.status()["startup"]
        self.assertEqual([(f["broken_version"], f["restored_version"]) for f in startup["fallbacks"]], [(3, 1)])
        self.assertEqual(startup["disabled"], [])                                  # v2 was judged bad: skipped
        record = svc.capability("unit_km_to_mi")
        self.assertEqual([(v["version"], v["status"]) for v in record["versions"]],
                         [(1, "active"), (2, "rolled_back"), (3, "broken")])
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["version"], 1)

    def test_a_rolled_back_version_alone_is_never_restored_by_a_fallback(self):
        self.two_versions()
        svc = self.service()
        svc.rollback("unit_km_to_mi")                                              # v1 active, v2 rolled back
        svc.rollback("unit_km_to_mi", to_version=2)                                # forward again
        svc.rollback("unit_km_to_mi")                                              # back to v1 once more
        svc.close()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v1.py")
        svc = self.service()
        startup = svc.status()["startup"]
        self.assertEqual(startup["fallbacks"], [])
        self.assertEqual([(d["capability_id"], d["broken_version"]) for d in startup["disabled"]],
                         [("unit_km_to_mi", 1)])
        self.assertEqual(svc.capability("unit_km_to_mi")["status"], "disabled")

    def test_a_modified_older_version_is_not_restored_by_a_fallback(self):
        self.two_versions()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v1.py")           # the fallback target is damaged ...
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py")           # ... and so is the active one
        svc = self.service()
        self.assertEqual(len(svc.status()["startup"]["disabled"]), 1)
        self.assertEqual(svc.capability("unit_km_to_mi")["status"], "disabled")

    def test_orphan_files_are_quarantined_never_loaded(self):
        self.one_version()
        with open(self.path(policy.SUBDIR_MODULES, "zzz_one_v1.py"), "w") as f:
            f.write("raise SystemExit('loaded!')\n")
        with open(self.path(policy.SUBDIR_TESTS, "zzz_one_v1.json"), "w") as f:
            f.write("{}")
        svc = self.service()
        startup = svc.status()["startup"]
        self.assertEqual(sorted(q["name"] for q in startup["quarantined"]), ["zzz_one_v1.json", "zzz_one_v1.py"])
        self.assertTrue(all(q["reason"] == "orphan" for q in startup["quarantined"]))
        self.assertEqual(self.files(policy.SUBDIR_MODULES), ["unit_km_to_mi_v1.py"])
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 2)
        self.assertIn("reconcile_quarantine", [e["event"] for e in svc.audit_tail(20)])

    def test_stray_files_of_any_name_or_type_cannot_stop_the_start(self):
        self.one_version()
        names = ["evil.sh", "UPPER.PY", "weird name ی.py", "x", "a" * 200 + ".py", "noext", ".hidden", "-rf",
                 "‮evil.py", "نام.json"]
        for name in names:
            with open(self.path(policy.SUBDIR_MODULES, name), "w") as f:
                f.write("print(1)\n")
        os.makedirs(self.path(policy.SUBDIR_MODULES, "a_directory"))
        svc = self.service()
        self.assertEqual(len(svc.capabilities()), 1)                                # (this opens and reconciles)
        self.assertIsNone(svc.open_error)
        self.assertEqual(sorted(self.files(policy.SUBDIR_MODULES)), ["a_directory", "unit_km_to_mi_v1.py"])
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), len(names))
        for name in self.files(policy.SUBDIR_QUARANTINE):
            policy.Policy.check_file_name(policy.SUBDIR_QUARANTINE, name)
        self.assertTrue(svc.invoke("unit_km_to_mi", {"value": 1})["ok"])

    def test_stray_symlinks_are_removed_without_touching_their_targets(self):
        self.one_version()
        target = os.path.join(self.tmp, "precious.txt")
        with open(target, "w") as f:
            f.write("keep me")
        os.symlink(target, self.path(policy.SUBDIR_MODULES, "link_v1.py"))
        os.symlink(self.tmp, self.path(policy.SUBDIR_SPECS, "dirlink_v1.json"))
        svc = self.service()
        self.assertEqual(len(svc.capabilities()), 1)                                # (this opens and reconciles)
        self.assertIsNone(svc.open_error)
        self.assertFalse(os.path.lexists(self.path(policy.SUBDIR_MODULES, "link_v1.py")))
        self.assertFalse(os.path.lexists(self.path(policy.SUBDIR_SPECS, "dirlink_v1.json")))
        with open(target) as f:
            self.assertEqual(f.read(), "keep me")
        self.assertTrue(os.path.isdir(self.tmp))

    def test_staging_and_partial_files_are_cleaned_up(self):
        self.one_version()
        for sub, name in ((policy.SUBDIR_STAGING, "stg_x_v1.py"), (policy.SUBDIR_STAGING, "anything.bin"),
                          (policy.SUBDIR_MODULES, "unit_km_to_mi_v9.py.part77"), (".", "manifest.json.part88")):
            with open(self.path(sub, name), "w") as f:
                f.write("half")
        svc = self.service()
        startup_report = svc._open(create=False) and svc.startup_report
        self.assertEqual(sorted(startup_report["partials_removed"]), ["manifest.json.part88", "unit_km_to_mi_v9.py.part77"])
        self.assertEqual(sorted(startup_report["staging_cleared"]), ["anything.bin", "stg_x_v1.py"])
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])

    def test_unfinished_runs_and_checkpoints_are_settled(self):
        self.one_version()
        self.sql("INSERT INTO upgrade_log(kind, capability_id, request_text, plan_json, changes_json, attempts_json, "
                 "validation_json, test_json, result, created_at) VALUES ('build','unit_x','r','{}','{}','[]','{}','{}','started','t')")
        self.sql("INSERT INTO checkpoints(upgrade_id, capability_id, from_version, to_version, files_json, registry_json, "
                 "status, created_at) VALUES (99, 'unit_km_to_mi', 1, 1, '[]', '{}', 'pending', 't')")     # registered
        self.sql("INSERT INTO checkpoints(upgrade_id, capability_id, from_version, to_version, files_json, registry_json, "
                 "status, created_at) VALUES (99, 'unit_km_to_mi', 1, 7, '[]', '{}', 'pending', 't')")     # never registered
        svc = self.service()
        self.assertEqual(svc.status()["startup"]["interrupted_upgrades"], 1)
        self.assertEqual(svc.history()[0]["result"], "interrupted")
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT to_version, status FROM checkpoints WHERE upgrade_id = 99 "
                                         "ORDER BY checkpoint_id").fetchall(), [(1, "applied"), (7, "abandoned")])
        finally:
            con.close()
        self.assertIn("reconcile_interrupted", [e["event"] for e in svc.audit_tail(20)])

    def test_a_broken_audit_chain_is_reported_but_does_not_stop_the_capabilities(self):
        self.one_version()
        self.sql("UPDATE audit_log SET detail_json = '{}' WHERE seq = 2")
        svc = self.service()
        chain = svc.status()["audit_chain"]
        self.assertEqual((chain["ok"], chain["first_bad_seq"]), (False, 2))
        self.assertFalse(svc.self_check()["ok"])
        self.assertTrue(svc.invoke("unit_km_to_mi", {"value": 1})["ok"])

    def test_a_corrupted_database_is_reported_never_overwritten_never_raised(self):
        self.one_version()
        db_path = self.path(".", "self_builder.db")
        garbage = os.urandom(8192)
        with open(db_path, "wb") as f:
            f.write(garbage)
        svc = self.service()
        self.assertEqual(svc.capabilities(), [])
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 1})["error"], "no_registry")
        self.assertFalse(svc.has_active_capabilities())
        self.assertIsNotNone(svc.status()["open_error"])
        r = svc.build(KM_MI, rp.parse_build_request(KM_MI))
        self.assertEqual(r["status"], "failed")
        self.assertTrue(r["error"]["code"])
        with open(db_path, "rb") as f:
            self.assertEqual(f.read(), garbage)                                    # the evidence is untouched

    def test_a_database_from_a_newer_version_is_left_alone(self):
        self.one_version()
        self.sql("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
        svc = self.service()
        self.assertEqual(svc.status()["open_error"]["code"], "E_STORE_NEWER_SCHEMA")
        self.assertEqual(svc.build(KM_MI, rp.parse_build_request(KM_MI))["status"], "failed")
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 1})["error"], "no_registry")
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0], "99")
        finally:
            con.close()

    def test_reconcile_called_directly_twice_changes_nothing_the_second_time(self):
        self.two_versions()
        self.tamper_append(policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py")
        ws = Workspace(self.root)
        st = Store(ws.db_path())
        self.addCleanup(st.close)
        reg = Registry(st)
        first = loader.reconcile(ws, st, reg)
        second = loader.reconcile(ws, st, reg)
        self.assertEqual(len(first["fallbacks"]), 1)
        for key in ("fallbacks", "disabled", "quarantined", "partials_removed", "staging_cleared"):
            self.assertEqual(second[key], [], key)
        self.assertEqual(second["interrupted_upgrades"], 0)
        self.assertEqual(second["audit_chain"]["ok"], True)

    def test_the_manifest_follows_the_registry(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)

        def manifest():
            with open(self.path(".", "manifest.json"), encoding="utf-8") as f:
                return json.load(f)["capabilities"]["unit_km_to_mi"]
        self.assertEqual((manifest()["active_version"], sorted(manifest()["versions"])), (2, ["1", "2"]))
        svc.rollback("unit_km_to_mi")
        self.assertEqual((manifest()["active_version"], manifest()["versions"]["2"]["status"]), (1, "rolled_back"))
        svc.disable("unit_km_to_mi")
        self.assertEqual((manifest()["active_version"], manifest()["status"]), (None, "disabled"))
        self.assertEqual(manifest()["versions"]["1"]["module_sha256"],
                         svc.capability("unit_km_to_mi")["versions"] and
                         [v for v in svc._registry.versions("unit_km_to_mi") if v["version"] == 1][0]["module_sha256"])


# ============================================================================ the service facade
class FakeMemory:
    """Anything with a `db_path` is enough for the service to locate its root."""

    def __init__(self, db_path):
        self.db_path = db_path


class TestServiceFacade(TempDirCase):
    def test_reading_never_creates_anything(self):
        svc = self.service()
        self.assertFalse(svc.exists())
        self.assertEqual(svc.capabilities(), [])
        self.assertIsNone(svc.capability("unit_km_to_mi"))
        self.assertEqual((svc.versions("unit_km_to_mi"), svc.history(), svc.audit_tail()), ([], [], []))
        self.assertEqual(svc.self_check(), {"ok": True, "checked": [], "audit_chain": None})
        self.assertFalse(svc.has_active_capabilities())
        self.assertIsNone(svc.find_capability("تبدیل کیلومتر به مایل"))
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 1})["error"], "no_registry")
        self.assertFalse(svc.feedback("unit_km_to_mi", 1, "positive"))
        self.assertEqual(svc.feedback_summary("unit_km_to_mi", 1), {})
        self.assertEqual(svc.rollback("unit_km_to_mi")["status"], "failed")
        self.assertEqual(svc.disable("unit_km_to_mi")["status"], "failed")
        status = svc.status()
        self.assertEqual((status["exists"], status["capabilities"], status["active"]), (False, 0, 0))
        # without a registry the matcher still recognises a buildable gap and a missing capability
        self.assertEqual(svc.match("۵ مایل چند کیلومتر است؟")["status"], "gap")
        self.assertEqual(svc.match_question("آیا تبدیل متر به یارد را بلدی؟")["status"], "missing")
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_only_a_build_creates_the_root(self):
        svc = self.service()
        svc.build("یک مبدل بساز", rp.parse_build_request("یک مبدل بساز"))              # even a refused build opens it
        self.assertTrue(os.path.isdir(self.root))
        self.assertEqual(sorted(os.listdir(self.root)),
                         ["checkpoints", "manifest.json", "modules", "quarantine", "self_builder.db",
                          "self_builder.lock", "specs", "staging", "tests"])

    def test_the_root_is_found_next_to_the_memory_database(self):
        db = os.path.join(self.tmp, "data", "memory.db")
        self.assertEqual(default_root(FakeMemory(db)), os.path.join(self.tmp, "data", "self_builder"))
        self.assertIsNone(default_root(FakeMemory(None)))
        self.assertIsNone(default_root(object()))
        self.assertIsNone(get_service(FakeMemory(None)))
        memory = FakeMemory(db)
        self.assertIs(get_service(memory), get_service(memory))                    # one service per memory object
        self.assertIsNot(get_service(FakeMemory(db)), get_service(memory))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data")))             # asking for it creates nothing

    def test_a_restart_serves_exactly_what_the_previous_process_persisted(self):
        svc = self.service()
        for text in CAPS:
            self.built(svc, text)
        self.built(svc, KM_MI_06, confirmed=True)
        svc.rollback("unit_km_to_mi", to_version=1)
        before = [(c["id"], c["version"], c["status"], [v["status"] for v in c["versions"]]) for c in svc.capabilities()]
        answers = {c["id"]: svc.invoke(c["id"], {"value": 4.0} if c["kind"] == "unit_conversion"
                                       else {"text": "سلام دنیا"} if c["kind"] == "text_tool"
                                       else {k["name"]: 2.0 for k in c["inputs"]}) for c in svc.capabilities()}
        svc.close()
        again = self.service()
        after = [(c["id"], c["version"], c["status"], [v["status"] for v in c["versions"]]) for c in again.capabilities()]
        self.assertEqual(after, before)
        for cid, first in answers.items():
            second = again.invoke(cid, {"value": 4.0} if first["kind"] == "unit_conversion"
                                  else {"text": "سلام دنیا"} if first["kind"] == "text_tool"
                                  else {k["name"]: 2.0 for k in again.capability(cid)["inputs"]})
            self.assertEqual((second["ok"], second["value"], second["version"]),
                             (first["ok"], first["value"], first["version"]), cid)
        startup = again.status()["startup"]
        self.assertEqual((startup["fallbacks"], startup["disabled"], startup["quarantined"]), ([], [], []))

    def test_usage_counters_and_feedback_are_persistent(self):
        svc = self.service()
        self.built(svc, KM_MI)
        for value in (1, 2, "abc"):
            svc.invoke("unit_km_to_mi", {"value": value})
        self.assertEqual(svc.capability("unit_km_to_mi")["usage"]["calls"], 3)
        self.assertEqual(svc.capability("unit_km_to_mi")["usage"]["failures"], 1)
        self.assertTrue(svc.feedback("unit_km_to_mi", 1, "positive", "ممنون"))
        self.assertTrue(svc.feedback("unit_km_to_mi", 1, "negative"))
        self.assertTrue(svc.feedback("unit_km_to_mi", 1, "negative"))
        self.assertFalse(svc.feedback("unit_km_to_mi", 1, "meh"))
        self.assertEqual(svc.feedback_summary("unit_km_to_mi", 1), {"negative": 2, "positive": 1})
        self.assertEqual(svc.feedback_summary("unit_km_to_mi", 2), {})
        self.assertEqual(sum(1 for e in svc.audit_tail(50) if e["event"] == "feedback"), 3)
        svc.close()
        again = self.service()
        self.assertEqual(again.capability("unit_km_to_mi")["usage"]["calls"], 3)
        self.assertEqual(again.feedback_summary("unit_km_to_mi", 1), {"negative": 2, "positive": 1})
        self.assertTrue(again.status()["audit_chain"]["ok"])

    def test_the_active_module_is_re_checked_on_every_call(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        first = svc.invoke("unit_km_to_mi", {"value": 10})
        self.assertEqual((first["value"], first["version"], first["fallback"]), (6.0, 2, None))
        # someone modifies the module file while the service is running (and has it cached)
        with open(os.path.join(self.root, "modules", "unit_km_to_mi_v2.py"), "a") as f:
            f.write("\n# tampered\n")
        out = svc.invoke("unit_km_to_mi", {"value": 10})
        self.assertEqual((out["ok"], out["version"]), (True, 1))
        self.assertAlmostEqual(out["value"], 6.21371192237334, places=12)
        self.assertEqual((out["fallback"]["broken_version"], out["fallback"]["restored_version"],
                          out["fallback"]["disabled"], out["fallback"]["error"]),
                         (2, 1, False, "E_VERIFY_MODULE_HASH"))
        self.assertEqual([v["status"] for v in svc.capability("unit_km_to_mi")["versions"]], ["active", "broken"])
        self.assertEqual(len(self.files(policy.SUBDIR_QUARANTINE)), 1)
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["fallback"], None)      # repaired once, not again
        self.assertIn("version_broken", [e["event"] for e in svc.audit_tail(20)])

    def test_the_only_version_modified_while_running_disables_the_capability(self):
        svc = self.service()
        self.built(svc, KM_MI)
        svc.invoke("unit_km_to_mi", {"value": 1})
        with open(os.path.join(self.root, "modules", "unit_km_to_mi_v1.py"), "a") as f:
            f.write("\n# tampered\n")
        out = svc.invoke("unit_km_to_mi", {"value": 1})
        self.assertEqual((out["ok"], out["error"], out["fallback"]["disabled"]), (False, "not_active", True))
        self.assertEqual(svc.capability("unit_km_to_mi")["status"], "disabled")

    def test_changes_invalidate_the_module_cache(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)
        self.built(svc, KM_MI_06, confirmed=True)
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.0)
        svc.rollback("unit_km_to_mi")
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)
        svc.disable("unit_km_to_mi")
        self.assertEqual(svc.invoke("unit_km_to_mi", {"value": 10})["error"], "not_active")

    def test_invoking_with_bad_inputs_never_raises(self):
        svc = self.service()
        self.built(svc, KM_MI)
        for inputs in (None, {}, {"value": None}, {"value": "x"}, {"value": [1]}, {"value": float("nan")},
                       {"value": float("inf")}, {"value": 1e308}, "text", 5, [], {"other": 1}, {"value": True}):
            with self.subTest(inputs=repr(inputs)):
                out = svc.invoke("unit_km_to_mi", inputs)
                self.assertFalse(out["ok"])
                self.assertIn(out["error"], ("bad_input", "overflow"))
        self.assertEqual(svc.invoke("no_such_capability", {"value": 1})["error"], "not_active")

    def test_a_service_without_memory_has_no_mirror(self):
        r = self.built(self.service(), KM_MI)
        self.assertNotIn("mirror", r)

    def test_threads_can_build_and_invoke_at_the_same_time(self):
        svc = self.service()
        self.built(svc, KM_MI)                                  # the root exists before the race starts
        pairs = ["متر به فوت", "سانتی‌متر به اینچ", "گرم به اونس", "لیتر به گالن", "پوند به کیلوگرم",
                 "ساعت به دقیقه", "متر به یارد", "کیلوگرم به پوند"]
        errors, results = [], {}

        def builder(pair):
            try:
                text = f"یک مبدل {pair} بساز"
                results[pair] = svc.build(text, rp.parse_build_request(text))["status"]
            except Exception as e:                              # pragma: no cover - reported below
                errors.append(repr(e))

        def reader():
            try:
                for _ in range(40):
                    svc.invoke("unit_km_to_mi", {"value": 10})
                    svc.match("۱۰ کیلومتر چند مایل است؟")
                    svc.capabilities()
            except Exception as e:                              # pragma: no cover
                errors.append(repr(e))
        threads = [threading.Thread(target=builder, args=(p,)) for p in pairs] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        self.assertEqual(set(results.values()), {"applied"})
        self.assertEqual(len(svc.capabilities()), 1 + len(pairs))
        self.assertTrue(svc.self_check()["ok"])
        self.assertEqual(svc.status()["audit_chain"]["ok"], True)
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])

    def test_two_services_building_the_same_capability_at_once_agree(self):
        first, second = self.service(), self.service()
        self.built(first, M_FT)                                 # create the root
        second.capabilities()                                   # open the second service before the race
        barrier = threading.Barrier(2)
        results = {}

        def go(name, svc):
            barrier.wait()
            results[name] = svc.build(KM_MI, rp.parse_build_request(KM_MI))
        threads = [threading.Thread(target=go, args=("a", first)), threading.Thread(target=go, args=("b", second))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(sorted(r["status"] for r in results.values()), ["applied", "noop_identical"])
        for svc in (first, second):
            record = svc.capability("unit_km_to_mi")
            self.assertEqual((record["version"], len(record["versions"])), (1, 1))
        self.assertTrue(first.self_check()["ok"])
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])

    def test_two_services_improving_the_same_capability_at_once_both_get_a_version(self):
        first, second = self.service(), self.service()
        self.built(first, KM_MI)
        second.capabilities()
        barrier = threading.Barrier(2)
        results = {}

        def go(name, svc, text):
            barrier.wait()
            results[name] = svc.build(text, rp.parse_build_request(text), confirmed=True)
        threads = [threading.Thread(target=go, args=("a", first, KM_MI_06)),
                   threading.Thread(target=go, args=("b", second, KM_MI_06.replace("۰٫۶", "۰٫۷")))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual({r["status"] for r in results.values()}, {"applied"}, results)
        record = first.capability("unit_km_to_mi")
        self.assertEqual((record["version"], [v["status"] for v in record["versions"]]),
                         (3, ["superseded", "superseded", "active"]))
        self.assertEqual(sorted(r["version"] for r in results.values()), [2, 3])
        self.assertTrue(second.self_check()["ok"])
        self.assertEqual(first.status()["audit_chain"]["ok"], True)
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])


# ============================================================================ the memory mirror
class TestMemoryMirror(TempDirCase):
    def setUp(self):
        super().setUp()
        from memory.memory_system import MemorySystem
        self.memory = MemorySystem(os.path.join(self.tmp, "data", "memory.db"))
        self.addCleanup(self.memory._conn.close)          # the legacy MemorySystem has no close()
        self.root = os.path.join(self.tmp, "data", "self_builder")

    def svc(self):
        svc = get_service(self.memory)
        self._services.append(svc)
        return svc

    def rows(self, sql, params=()):
        return [dict(r) for r in self.memory.query(sql, params)]

    def sb_versions(self):
        """The Self-Builder rows of the legacy `versions` table (the file ships with a seeded foundation row)."""
        return self.rows("SELECT * FROM versions WHERE version_label LIKE 'unit_km_to_mi@%' ORDER BY id")

    def test_a_build_is_mirrored_into_the_legacy_capability_upgrade_and_version_tables(self):
        svc = self.svc()
        self.assertEqual(svc.root, self.root)
        r = self.built(svc, KM_MI)
        self.assertEqual(set(r["mirror"]), {"upgrade_id", "version_id", "capability_row"})
        (cap,) = self.rows("SELECT * FROM capabilities WHERE name = 'unit_km_to_mi'")
        self.assertEqual((cap["enabled"], cap["status"]), (1, "active"))
        (up,) = self.rows("SELECT * FROM upgrades")
        self.assertEqual((up["name"], up["stage"], up["status"]), ("unit_km_to_mi", "version", "installed"))
        payload = json.loads(up["payload"])["self_builder"]
        self.assertEqual((payload["capability_id"], payload["version"], payload["status"]),
                         ("unit_km_to_mi", 1, "applied"))
        (ver,) = self.sb_versions()
        self.assertEqual(ver["version_label"], "unit_km_to_mi@v1")
        self.assertEqual(ver["is_active"], 1)
        self.assertEqual(ver["upgrade_id"], up["id"])
        snapshot = json.loads(ver["snapshot"])["self_builder"]
        self.assertEqual((snapshot["capability_id"], snapshot["version"], snapshot["upgrade_id"]),
                         ("unit_km_to_mi", 1, r["upgrade_id"]))

    def test_failed_and_pending_runs_are_mirrored_without_a_version(self):
        svc = self.svc()
        self.built(svc, KM_MI)
        pending = self.build(svc, KM_MI_06)
        failed = self.build(svc, "فرمول تست را یاد بگیر: foo(2)")
        self.assertEqual((pending["status"], failed["status"]), ("needs_confirmation", "failed"))
        rows = self.rows("SELECT * FROM upgrades ORDER BY id")
        self.assertEqual([(r["status"], r["stage"]) for r in rows][1:], [("pending", "plan"), ("failed", "sandbox_test")])
        self.assertEqual([v["version_label"] for v in self.sb_versions()], ["unit_km_to_mi@v1"])   # nothing was versioned for them

    def test_rollback_and_disable_keep_the_mirror_consistent(self):
        svc = self.svc()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        # VersionSystem.create_version activates the newest snapshot and deactivates every older one
        # (including the seeded foundation row), so exactly one row is active at any time.
        self.assertEqual([(v["version_label"], v["is_active"]) for v in self.sb_versions()],
                         [("unit_km_to_mi@v1", 0), ("unit_km_to_mi@v2", 1)])
        self.assertEqual([v["is_active"] for v in self.rows("SELECT is_active FROM versions ORDER BY id")], [0, 0, 1])
        svc.rollback("unit_km_to_mi")
        self.assertEqual([v["version_label"] for v in self.rows("SELECT version_label FROM versions WHERE is_active = 1")],
                         ["unit_km_to_mi@v1"])
        svc.disable("unit_km_to_mi")
        (cap,) = self.rows("SELECT * FROM capabilities WHERE name = 'unit_km_to_mi'")
        self.assertEqual((cap["enabled"], cap["status"]), (0, "disabled"))

    def test_a_failing_mirror_never_blocks_or_undoes_a_build(self):
        svc = self.svc()
        with mock.patch.object(mirror, "mirror_upgrade", side_effect=RuntimeError("memory is broken")):
            r = self.built(svc, KM_MI)
        self.assertEqual(r["mirror"], {"error": "RuntimeError"})
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 1)
        self.assertAlmostEqual(svc.invoke("unit_km_to_mi", {"value": 10})["value"], 6.21371192237334, places=12)


# ============================================================================ real processes
class TestPersistenceAcrossProcesses(TempDirCase):
    BUILD = """
        import os, sys
        from self_builder import request_parser as rp
        from self_builder.service import SelfBuilderService
        svc = SelfBuilderService(sys.argv[1])
        for text in sys.argv[2:]:
            r = svc.build(text, rp.parse_build_request(text), confirmed=True)
            print(r["status"], r["capability_id"], r.get("version"))
        sys.stdout.flush()
        os._exit(0)          # no close(), no cleanup: the process just disappears, like a killed app
    """
    USE = """
        import json, os, sys
        from self_builder.service import SelfBuilderService
        svc = SelfBuilderService(sys.argv[1])
        out = {"caps": [(c["id"], c["version"], c["status"]) for c in svc.capabilities()],
               "km": svc.invoke("unit_km_to_mi", {"value": 10}),
               "words": svc.invoke("text_count_words", {"text": "سلام دنیا"}),
               "startup": svc.status()["startup"]}
        if len(sys.argv) > 2 and sys.argv[2] == "rollback":
            out["rollback"] = svc.rollback("unit_km_to_mi")["status"]
        print(json.dumps(out, ensure_ascii=False))
        sys.stdout.flush()
        os._exit(0)
    """

    def test_a_capability_built_in_one_process_works_in_the_next_and_survives_a_rollback(self):
        proc = run_python(self.BUILD, self.root, KM_MI, KM_MI_06, WORDS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.split("\n")[:3],
                         ["applied unit_km_to_mi 1", "applied unit_km_to_mi 2", "applied text_count_words 1"])
        proc = run_python(self.USE, self.root, "rollback")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = json.loads(proc.stdout)
        self.assertEqual(sorted(state["caps"]), [["text_count_words", 1, "active"], ["unit_km_to_mi", 2, "active"]])
        self.assertEqual((state["km"]["version"], state["km"]["value"]), (2, 6.0))
        self.assertEqual(state["words"]["value"], 2.0)
        self.assertEqual(state["rollback"], "applied")
        self.assertEqual((state["startup"]["fallbacks"], state["startup"]["disabled"],
                          state["startup"]["quarantined"]), ([], [], []))
        proc = run_python(self.USE, self.root)                                      # a third process sees the rollback
        state = json.loads(proc.stdout)
        self.assertEqual((state["km"]["version"], round(state["km"]["value"], 9)), (1, 6.213711922))

    def test_the_root_written_by_a_process_is_complete_when_it_vanishes(self):
        proc = run_python(self.BUILD, self.root, KM_MI)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for sub, expected in ((policy.SUBDIR_MODULES, ["unit_km_to_mi_v1.py"]), (policy.SUBDIR_TESTS, ["unit_km_to_mi_v1.json"]),
                              (policy.SUBDIR_SPECS, ["unit_km_to_mi_v1.json"]), (policy.SUBDIR_STAGING, []),
                              (policy.SUBDIR_QUARANTINE, [])):
            self.assertEqual(self.files(sub), expected, sub)
        self.assertEqual([n for n in os.listdir(self.root) if ".part" in n], [])
        svc = self.service()
        self.assertTrue(svc.self_check()["ok"])
        self.assertEqual(svc.status()["startup"]["interrupted_upgrades"], 0)


# ============================================================================ the workspace lock
class TestWorkspaceLock(TempDirCase):
    """lock.py: one exclusive, re-entrant, crash-proof lock per workspace root."""

    def workspaces(self):
        a, b = Workspace(self.root), Workspace(self.root)       # two services / two processes would each have one
        return a, b

    def test_the_lock_is_exclusive_between_two_workspaces_of_one_root(self):
        a, b = self.workspaces()
        self.assertTrue(a.lock.acquire(1))
        self.assertFalse(b.lock.acquire(0.2))
        a.lock.release()
        self.assertTrue(b.lock.acquire(1))
        self.assertFalse(a.lock.acquire(0.2))
        b.lock.release()
        self.assertTrue(a.lock.acquire(1))
        a.lock.release()

    def test_it_is_reentrant_for_the_holding_thread_only(self):
        a, b = self.workspaces()
        self.assertFalse(a.lock.held_here())
        self.assertTrue(a.lock.acquire(1))
        self.assertTrue(a.lock.acquire(1))                      # nested use inside one operation (repair -> rollback)
        self.assertTrue(a.lock.held_here())
        seen = {}

        def other():
            seen["held_here"] = a.lock.held_here()
            seen["acquired"] = a.lock.acquire(0.2)
        t = threading.Thread(target=other)
        t.start()
        t.join(10)
        self.assertEqual(seen, {"held_here": False, "acquired": False})
        a.lock.release()
        self.assertFalse(b.lock.acquire(0.2))                   # still held: the outer level is open
        a.lock.release()
        self.assertFalse(a.lock.held_here())
        self.assertTrue(b.lock.acquire(1))
        b.lock.release()

    def test_releasing_a_lock_that_is_not_held_is_an_error(self):
        a, _ = self.workspaces()
        with self.assertRaises(RuntimeError):
            a.lock.release()

    def test_held_raises_a_classified_busy_error_after_the_timeout(self):
        a, b = self.workspaces()
        with a.lock.held(1):
            started = __import__("time").monotonic()
            with self.assertRaises(builder_mod.ApplyError) as ctx:
                with b.lock.held(0.3):
                    self.fail("the lock must not be available")
            self.assertEqual(ctx.exception.code, "E_BUILD_BUSY")
            self.assertGreaterEqual(__import__("time").monotonic() - started, 0.25)
        with b.lock.held(1):                                    # and it is free again afterwards
            pass

    def test_the_default_timeout_comes_from_the_policy(self):
        a, b = self.workspaces()
        with a.lock.held(1), mock.patch.object(policy, "LOCK_TIMEOUT_SECONDS", 0.2):
            self.assertFalse(b.lock.acquire())

    def test_a_waiting_thread_gets_the_lock_when_the_holder_lets_go(self):
        a, b = self.workspaces()
        a.lock.acquire(1)
        got = []

        def waiter():
            got.append(b.lock.acquire(10))
            if got[0]:
                b.lock.release()
        t = threading.Thread(target=waiter)
        t.start()
        t.join(0.3)
        self.assertTrue(t.is_alive())                           # still waiting
        a.lock.release()
        t.join(10)
        self.assertEqual(got, [True])

    def test_the_lock_dies_with_its_process(self):
        code = """
            import sys, time
            from self_builder.workspace import Workspace
            ws = Workspace(sys.argv[1])
            assert ws.lock.acquire(5)
            print("held", flush=True)
            time.sleep(120)
        """
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=SRC_DIR)
        proc = subprocess.Popen([sys.executable, "-B", "-c", textwrap.dedent(code), self.root], env=env,
                                stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "held")
            ws = Workspace(self.root)
            self.assertFalse(ws.lock.acquire(0.3))              # a live process holds it
            proc.kill()                                         # SIGKILL: no cleanup of any kind runs
            proc.wait(30)
            self.assertTrue(ws.lock.acquire(5))                 # the operating system released it
            ws.lock.release()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(30)
            proc.stdout.close()

    def test_nothing_is_ever_written_into_the_lock_file(self):
        a, b = self.workspaces()
        for ws in (a, b, a):
            with ws.lock.held(1):
                pass
        path = os.path.join(self.root, policy.ROOT_FILE_LOCK)
        self.assertEqual(os.path.getsize(path), 0)
        self.assertEqual([n for n in os.listdir(self.root) if "lock" in n or "journal" in n], [policy.ROOT_FILE_LOCK])

    def test_the_lock_file_is_a_policy_root_file_and_nothing_similar_is(self):
        self.assertEqual(policy.Policy.check_root_file("self_builder.lock"), "self_builder.lock")
        for bad in ("self_builder.lock2", "other.lock", "../self_builder.lock", "self_builder.db-journal"):
            with self.assertRaises(PolicyViolation):
                policy.Policy.check_root_file(bad)


# ============================================================================ concurrent changes
class TestConcurrentChanges(TempDirCase):
    """Two services (or processes) changing one root: they take turns, never share staging files."""

    def holding(self):
        """A workspace of the root whose lock this test holds, as a build in another process would."""
        ws = Workspace(self.root)
        self.assertTrue(ws.lock.acquire(5))
        self.addCleanup(lambda: ws.lock.held_here() and ws.lock.release())
        return ws

    def plant_staging(self, name="stg_other_build_v1.py"):
        path = os.path.join(self.root, policy.SUBDIR_STAGING, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# staged by a build that is still running elsewhere\n")
        return path

    def test_a_build_waits_for_the_running_one_and_then_completes(self):
        svc = self.service()
        self.built(svc, M_FT)
        ws = self.holding()
        planted = self.plant_staging()
        out = {}
        t = threading.Thread(target=lambda: out.update(r=self.service().build(KM_MI, rp.parse_build_request(KM_MI))))
        t.start()
        t.join(0.5)
        self.assertTrue(t.is_alive(), "the build must wait while another one is running")
        self.assertTrue(os.path.exists(planted), "the other build's staging file was touched")
        ws.lock.release()
        t.join(60)
        self.assertEqual(out["r"]["status"], "applied", out["r"].get("error"))
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])                  # the finished build cleaned up after itself
        self.assertEqual(sorted(c["id"] for c in svc.capabilities()), ["unit_km_to_mi", "unit_m_to_ft"])

    def test_a_busy_workspace_fails_the_build_cleanly_and_touches_nothing(self):
        svc = self.service()
        self.built(svc, M_FT)
        before_modules = self.files(policy.SUBDIR_MODULES)
        ws = self.holding()
        planted = self.plant_staging()
        with mock.patch.object(policy, "LOCK_TIMEOUT_SECONDS", 0.2):
            r = self.build(svc, KM_MI)
        self.assertEqual((r["status"], r["error"]["code"]), ("failed", "E_BUILD_BUSY"))
        self.assertTrue(os.path.exists(planted))                                 # not ours: left alone
        self.assertEqual(self.files(policy.SUBDIR_MODULES), before_modules)
        self.assertEqual([c["id"] for c in svc.capabilities()], ["unit_m_to_ft"])
        failed = svc.history(limit=1)[0]
        self.assertEqual((failed["result"], failed["error_code"]), ("failed", "E_BUILD_BUSY"))
        ws.lock.release()
        self.assertEqual(self.built(svc, KM_MI)["version"], 1)                   # nothing was lost by the refusal
        self.assertTrue(svc.self_check()["ok"])

    def test_rollback_and_disable_wait_for_the_lock_too(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        ws = self.holding()
        with mock.patch.object(policy, "LOCK_TIMEOUT_SECONDS", 0.2):
            rolled = svc.rollback("unit_km_to_mi")
            disabled = svc.disable("unit_km_to_mi")
        self.assertEqual((rolled["status"], rolled["error"]["code"]), ("failed", "E_BUILD_BUSY"))
        self.assertEqual((disabled["status"], disabled["error"]["code"]), ("failed", "E_BUILD_BUSY"))
        self.assertEqual(svc.capability("unit_km_to_mi")["version"], 2)          # nothing changed
        ws.lock.release()
        self.assertEqual(svc.rollback("unit_km_to_mi")["status"], "applied")
        self.assertEqual(svc.disable("unit_km_to_mi")["status"], "applied")

    def test_the_integrity_repair_runs_under_the_lock_without_deadlocking_itself(self):
        svc = self.service()
        self.built(svc, KM_MI)
        self.built(svc, KM_MI_06, confirmed=True)
        with open(os.path.join(self.root, policy.SUBDIR_MODULES, "unit_km_to_mi_v2.py"), "a", encoding="utf-8") as f:
            f.write("# tampered\n")
        svc.close()
        svc2 = self.service()
        result = svc2.invoke("unit_km_to_mi", {"value": 10})                      # verifies, repairs, falls back to v1
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["version"], 1)
        self.assertTrue(svc2.self_check()["ok"])

    def test_start_up_leaves_the_clean_up_to_later_while_a_build_is_running_elsewhere(self):
        first = self.service()
        self.built(first, KM_MI)
        first.close()
        ws = self.holding()
        planted = self.plant_staging()
        partial = os.path.join(self.root, policy.SUBDIR_MODULES, "unit_km_to_mi_v9.py.part1234")
        with open(partial, "w") as f:
            f.write("half of a write that is still going on")
        with mock.patch.object(policy, "RECONCILE_LOCK_SECONDS", 0.2):
            second = self.service()
            startup = second.status()["startup"]
        self.assertTrue(startup["deferred"])
        self.assertEqual((startup["staging_cleared"], startup["partials_removed"], startup["quarantined"],
                          startup["interrupted_upgrades"]), ([], [], [], 0))
        self.assertTrue(os.path.exists(planted) and os.path.exists(partial))
        self.assertEqual([v["ok"] for v in startup["verified"]], [True])
        self.assertTrue(second.invoke("unit_km_to_mi", {"value": 10})["ok"])      # reading works meanwhile
        ws.lock.release()
        second.close()
        third = self.service()                                                    # the next start does the clean-up
        startup = third.status()["startup"]
        self.assertFalse(startup["deferred"])
        self.assertEqual((startup["staging_cleared"], startup["partials_removed"]),
                         (["stg_other_build_v1.py"], ["unit_km_to_mi_v9.py.part1234"]))
        self.assertFalse(os.path.exists(planted) or os.path.exists(partial))

    def test_a_normal_start_up_holds_the_lock_only_while_it_reconciles(self):
        svc = self.service()
        self.built(svc, KM_MI)
        other = Workspace(self.root)
        self.assertTrue(other.lock.acquire(1))                                    # nobody keeps it afterwards
        other.lock.release()
        self.assertFalse(svc._ws.lock.held_here())

    def test_two_services_building_the_same_capability_agree_in_every_round(self):
        for n in range(6):
            root = os.path.join(self.tmp, f"race{n}")
            first, second = self.service(root), self.service(root)
            self.built(first, M_FT)
            second.capabilities()
            barrier = threading.Barrier(2)
            results = {}

            def go(name, svc):
                barrier.wait()
                results[name] = svc.build(KM_MI, rp.parse_build_request(KM_MI))
            threads = [threading.Thread(target=go, args=("a", first)), threading.Thread(target=go, args=("b", second))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(120)
            self.assertEqual(sorted(r["status"] for r in results.values()), ["applied", "noop_identical"], (n, results))
            for svc in (first, second):
                record = svc.capability("unit_km_to_mi")
                self.assertEqual((record["version"], len(record["versions"])), (1, 1))
            self.assertTrue(first.self_check()["ok"])
            self.assertEqual(os.listdir(os.path.join(root, policy.SUBDIR_QUARANTINE)), [])
            self.assertEqual(os.listdir(os.path.join(root, policy.SUBDIR_STAGING)), [])

    def test_many_services_and_threads_building_overlapping_capabilities_lose_nothing(self):
        services = [self.service() for _ in range(4)]
        self.built(services[0], WORDS)
        for svc in services:
            svc.capabilities()
        texts = [KM_MI, M_FT, BMI, AREA, REVERSE, "یک مبدل گرم به اونس بساز", "یک مبدل لیتر به گالن بساز"]
        results, errors = [], []

        def worker(svc, order):
            try:
                for i in order:
                    results.append((texts[i], svc.build(texts[i], rp.parse_build_request(texts[i]), confirmed=True)))
            except Exception as e:                                  # pragma: no cover - reported below
                errors.append(repr(e))
        threads = [threading.Thread(target=worker, args=(svc, [(k + j) % len(texts) for j in range(len(texts))]))
                   for k, svc in enumerate(services)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(300)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4 * len(texts))
        self.assertEqual({r["status"] for _, r in results} - {"applied", "noop_identical"}, set(),
                         [(t, r["status"], r["error"]) for t, r in results if r["status"] not in ("applied", "noop_identical")])
        for svc in services:
            self.assertEqual(len(svc.capabilities()), len(texts) + 1)
            self.assertTrue(svc.self_check()["ok"])
        for record in services[0].capabilities():
            self.assertEqual(record["version"], 1, record["id"])                  # identical requests never add versions
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])
        self.assertEqual(services[0].status()["audit_chain"]["ok"], True)


class TestConcurrentProcesses(TempDirCase):
    """The same, between real operating-system processes."""

    WORKER = """
        import json, os, sys
        from self_builder import request_parser as rp
        from self_builder.service import SelfBuilderService
        svc = SelfBuilderService(sys.argv[1])
        out = []
        for text in sys.argv[2:]:
            r = svc.build(text, rp.parse_build_request(text), confirmed=True)
            out.append([r["status"], r.get("capability_id"), (r.get("error") or {}).get("code")])
        print(json.dumps(out))
        sys.stdout.flush()
        os._exit(0)
    """
    SHARED = (KM_MI, M_FT, BMI)
    OWN = ("یک مبدل گرم به اونس بساز", "یک مبدل لیتر به گالن بساز", "یک مبدل سانتی‌متر به اینچ بساز",
           "یک مبدل پوند به کیلوگرم بساز")

    def test_parallel_processes_with_overlapping_builds_lose_nothing(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=SRC_DIR, PYTHONIOENCODING="utf-8")
        procs = []
        for own in self.OWN:
            procs.append(subprocess.Popen([sys.executable, "-B", "-c", textwrap.dedent(self.WORKER), self.root,
                                           *self.SHARED, own, WORDS], env=env, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True))
        outputs = []
        for p in procs:
            out, err = p.communicate(timeout=240)
            self.assertEqual(p.returncode, 0, err)
            outputs.append(json.loads(out))
        for results in outputs:
            for status, cid, code in results:
                self.assertIn(status, ("applied", "noop_identical"), (cid, code))
        svc = self.service()
        ids = sorted(c["id"] for c in svc.capabilities())
        self.assertEqual(len(ids), len(self.SHARED) + len(self.OWN) + 1, ids)
        for record in svc.capabilities():
            self.assertEqual((record["version"], record["status"]), (1, "active"), record["id"])
        startup = svc.status()["startup"]
        self.assertEqual((startup["interrupted_upgrades"], startup["quarantined"], startup["fallbacks"],
                          startup["disabled"], startup["deferred"]), (0, [], [], [], False))
        self.assertTrue(svc.self_check()["ok"])
        self.assertTrue(svc.status()["audit_chain"]["ok"])
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertEqual(self.files(policy.SUBDIR_QUARANTINE), [])
        self.assertEqual([n for n in os.listdir(self.root) if ".part" in n], [])
        con = self.db()
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM upgrade_log WHERE result = 'failed'").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM upgrade_log WHERE result = 'started'").fetchone()[0], 0)
        finally:
            con.close()

    def test_a_process_killed_while_building_blocks_nobody(self):
        code = """
            import os, sys
            from self_builder import request_parser as rp
            from self_builder.service import SelfBuilderService
            from self_builder.builder import Builder
            real = Builder._checkpoint
            def checkpoint(self, *a, **k):
                print("staged", flush=True)        # staging files exist, the workspace lock is held
                os.kill(os.getpid(), 9)
            Builder._checkpoint = checkpoint
            svc = SelfBuilderService(sys.argv[1])
            text = "یک مبدل کیلومتر به مایل بساز"
            svc.build(text, rp.parse_build_request(text))
        """
        proc = run_python(code, self.root)
        self.assertEqual(proc.returncode, -9, proc.stderr)
        self.assertIn("staged", proc.stdout)
        self.assertNotEqual(self.files(policy.SUBDIR_STAGING), [])                # what the killed build left behind
        svc = self.service()
        started = __import__("time").monotonic()
        r = self.built(svc, KM_MI)                                                # no waiting for a dead process
        self.assertLess(__import__("time").monotonic() - started, 5)
        self.assertEqual(r["version"], 1)
        self.assertEqual(svc.status()["startup"]["interrupted_upgrades"], 1)
        self.assertEqual(self.files(policy.SUBDIR_STAGING), [])
        self.assertTrue(svc.self_check()["ok"])
