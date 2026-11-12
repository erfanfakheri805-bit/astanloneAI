"""Prompt 959 (stage A) - the answers the app keeps for offline use (`brain_v2.learned`) and the privacy gate they depend on.

What matters here, in the user's terms: only a safe, general, complete answer to a real question is ever kept; a question is
recognised again only when it is the same question (filler words aside); nothing about the user, about "now" or about a secret
reaches the file; the file is private, bounded, and a damaged one never takes the app down.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v2 import learned as L
from brain_v2 import privacy


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="learned_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.clock = Clock()
        self.path = os.path.join(self.tmp, "brain_v2", L.FILE_NAME)
        self.mem = L.LearnedReplies(self.path, self.clock)

    def reopen(self):
        return L.LearnedReplies(self.path, self.clock)

    def read_file(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)


ANSWER = "پاریس است."


class EligibilityTests(Base):
    def test_general_questions_with_complete_answers_are_kept(self):
        for question in ("پایتخت فرانسه کجاست؟", "تفاوت ویروس و باکتری چیست؟", "چرا آسمان آبی است؟", "فاصله زمین تا ماه چقدر است؟",
                         "آموزش زبان انگلیسی چگونه شروع می‌شود؟", "پایتخت فرانسه کجاست"):
            with self.subTest(question=question):
                self.assertEqual(L.eligible(question, ANSWER), (True, ""))

    def test_every_refusal_has_its_own_stable_reason(self):
        table = (
            ("قیمت دلار امروز چنده؟", ANSWER, "timely"),
            ("هوای تهران الان چطور است؟", ANSWER, "timely"),
            ("جدیدترین گوشی سامسونگ چیست؟", ANSWER, "timely"),
            ("اسم من چیه؟", ANSWER, "personal"),
            ("برای دخترم چه هدیه‌ای بخرم؟", ANSWER, "personal"),
            ("و جمعیتش چقدره؟", ANSWER, "context"),
            ("معنی این کلمه چیست؟", ANSWER, "context"),
            ("پایتختش در اروپا کجاست؟", ANSWER, "context"),
            ("چرا " + "پ" * 41 + " درست است؟", ANSWER, "too_long"),
            ("یک شعر دربارهٔ بهار بنویس؟", ANSWER, "creative"),
            ("تو کی هستی و چه کاره‌ای؟", ANSWER, "assistant"),
            ("پایتخت فرانسه", ANSWER, "length"),
            ("چرا؟", ANSWER, "length"),
            ("فرانسه کشور زیبایی است", ANSWER, "not_a_question"),
            ("رمز من 1234 است چطور قوی کنم؟", ANSWER, "secret"),
            ("ایمیل من test@example.com است چرا اسپم می‌آید؟", ANSWER, "private"),
            ("چرا آسمان آبی است؟", "متاسفم، نمی‌دانم", "unsure_answer"),
            ("چرا آسمان آبی است؟", "من نمی‌توانم به این سؤال جواب بدهم.", "unsure_answer"),
            ("چرا آسمان آبی است؟", "I'm sorry, I can't help with that.", "unsure_answer"),
            ("چرا آسمان آبی است؟", "منظورتان دقیقاً چیست؟", "counter_question"),
            ("چرا آسمان آبی است؟", "", "empty"),
            ("چرا آسمان آبی است؟", "x" * (L.MAX_ANSWER_CHARS + 1), "too_long"),
            ("چرا " + "آسمان " * 60 + "آبی است؟", ANSWER, "too_long"),
            ("چرا آسمان آبی است؟", "کلید شما sk-" + "a1" * 20 + " است", "secret"),
        )
        for question, answer, reason in table:
            with self.subTest(question=question[:30], reason=reason):
                self.assertEqual(L.eligible(question, answer), (False, reason))

    def test_a_noun_ending_in_sh_is_not_the_pronoun_of_a_follow_up(self):
        self.assertEqual(L.eligible("آموزش زبان انگلیسی از کجا شروع می‌شود؟", ANSWER), (True, ""))
        self.assertEqual(L.eligible("روش ساخت کاغذ چیست؟", ANSWER), (True, ""))
        self.assertEqual(L.eligible("جمعیتش چقدر است؟", ANSWER), (False, "context"))

    def test_a_real_answer_that_merely_contains_a_question_is_kept(self):
        long_answer = "آسمان آبی است چون نور کوتاه‌موج بیشتر پراکنده می‌شود. آیا می‌خواهی بیشتر بدانی؟ " * 5
        self.assertEqual(L.eligible("چرا آسمان آبی است؟", long_answer), (True, ""))


class MatchingTests(Base):
    def test_a_kept_answer_is_given_again_with_its_age(self):
        self.assertTrue(self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER).ok)
        self.clock.advance(3600)
        hit = self.mem.find("پایتخت فرانسه کجاست؟")
        self.assertEqual((hit.answer, hit.exact, hit.uses), (ANSWER, True, 1))
        self.assertEqual(round(hit.age_s), 3600)
        self.clock.advance(60)
        self.assertEqual(self.mem.find("پایتخت فرانسه کجاست؟").uses, 2)

    def test_only_filler_words_and_punctuation_may_differ(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        for again in ("پایتخت فرانسه کجاست", "لطفا پایتخت فرانسه کجاست؟", "خب ببینم پایتخت فرانسه کجاست", "پایتخت فرانسه کجاست؟ ممنون",
                      "ببخشید پایتخت فرانسه کجاست؟"):
            with self.subTest(again=again):
                hit = self.mem.find(again)
                self.assertIsNotNone(hit, again)
        self.assertFalse(self.mem.find("لطفا پایتخت فرانسه کجاست؟").exact)
        self.assertTrue(self.mem.find("پایتخت فرانسه کجاست؟").exact)

    def test_anything_else_is_another_question(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        for other in ("پایتخت ایتالیا کجاست؟", "کجاست پایتخت فرانسه؟", "پایتخت قدیمی فرانسه کجاست؟", "پایتخت فرانسه چیست؟",
                      "پایتخت فرانسه", "فرانسه کجاست؟", "پایتخت فرانسه نه کجاست؟", "پایتخت فرانسه در ۱۸۰۰ کجاست؟"):
            with self.subTest(other=other):
                self.assertIsNone(self.mem.find(other), other)

    def test_a_negation_or_a_number_is_never_filler(self):
        self.mem.keep("آیا زمین از ماه بزرگ‌تر است؟", "بله")
        self.assertIsNone(self.mem.find("آیا زمین از ماه نه بزرگ‌تر است؟"))
        self.mem.keep("چند سیاره در منظومه شمسی وجود دارد؟", "هشت سیاره.")
        self.assertIsNone(self.mem.find("چند سیاره در منظومه شمسی وجود ندارد؟"))
        self.assertIsNone(self.mem.find("چند سیاره در منظومه شمسی ۹ وجود دارد؟"))

    def test_spelling_variants_are_the_same_question(self):
        self.mem.keep("تفاوت ویروس و باکتری چیه؟", "ویروس‌ها به میزبان نیاز دارند.")
        self.assertIsNotNone(self.mem.find("تفاوت ویروس و باکتری چیست؟"))
        self.mem.keep("کتاب خوب برای یادگیری پایتون چیست؟", "مثلاً کتاب‌های مقدماتی.")
        self.assertIsNotNone(self.mem.find("كتاب خوب براي يادگيري پايتون چيست؟"), "Arabic yeh/kaf")
        self.assertIsNotNone(self.mem.find("کتاب  خوب برای‌یادگیری پایتون چیست؟"), "extra spaces and ZWNJ")

    def test_asking_again_after_a_new_answer_replaces_the_old_one(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", "قدیمی")
        self.mem.keep("لطفا پایتخت فرانسه کجاست", "تازه")
        self.assertEqual(self.mem.count(), 1)
        self.assertEqual(self.mem.find("پایتخت فرانسه کجاست؟").answer, "تازه")

    @staticmethod
    def nth_question(i):
        letters = "ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی"
        return "چرا شهر %s بزرگ است؟" % (letters[i // len(letters)] + letters[i % len(letters)] + "ی")

    def test_the_least_recently_used_answer_leaves_first(self):
        for i in range(L.MAX_ITEMS):
            self.clock.advance(1)
            self.assertTrue(self.mem.keep(self.nth_question(i), "جواب %d" % i).ok, i)
        self.assertEqual(self.mem.count(), L.MAX_ITEMS)
        self.clock.advance(1)
        self.assertIsNotNone(self.mem.find(self.nth_question(0)), "using the oldest one makes it the newest")
        for i in range(L.MAX_ITEMS, L.MAX_ITEMS + 5):
            self.clock.advance(1)
            self.assertTrue(self.mem.keep(self.nth_question(i), "تازه %d" % i).ok, i)
        self.assertEqual(self.mem.count(), L.MAX_ITEMS, "the store is bounded")
        self.assertIsNotNone(self.mem.find(self.nth_question(0)), "a recently used answer survives")
        for i in range(1, 6):
            self.assertIsNone(self.mem.find(self.nth_question(i)), "the least recently used ones were dropped: %d" % i)
        self.assertIsNotNone(self.mem.find(self.nth_question(6)))
        self.assertIsNotNone(self.mem.find(self.nth_question(L.MAX_ITEMS + 4)))

    def test_drop_forgets_exactly_one_answer(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        self.mem.keep("پایتخت ایتالیا کجاست؟", "رم است.")
        hit = self.mem.find("پایتخت فرانسه کجاست؟")
        self.assertFalse(self.mem.drop(("پایتخت", "ایتالیا", "نه")))
        self.assertFalse(self.mem.drop(()))
        self.assertTrue(self.mem.drop(hit.key))
        self.assertIsNone(self.mem.find("پایتخت فرانسه کجاست؟"))
        self.assertIsNotNone(self.mem.find("پایتخت ایتالیا کجاست؟"))
        self.assertFalse(self.mem.drop(hit.key), "already gone")

    def test_clear_removes_everything_and_the_file(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        self.mem.keep("پایتخت ایتالیا کجاست؟", "رم است.")
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(self.mem.clear(), 2)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual((self.mem.count(), self.mem.clear()), (0, 0))
        self.assertIsNone(self.mem.find("پایتخت فرانسه کجاست؟"))


class StorageTests(Base):
    def test_the_answers_survive_a_restart(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        again = self.reopen()
        self.assertEqual(again.find("پایتخت فرانسه کجاست؟").answer, ANSWER)

    def test_the_file_is_private_and_holds_only_what_was_kept(self):
        self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode), 0o700)
        doc = self.read_file()
        self.assertEqual(sorted(doc), ["items", "schema"])
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(sorted(doc["items"][0]), ["a", "last", "q", "ts", "uses"])
        self.assertEqual(doc["items"][0]["a"], ANSWER)

    def test_things_that_are_not_eligible_never_reach_the_file(self):
        for question, answer in (("قیمت دلار امروز چنده؟", "۶۰"), ("اسم من چیه؟", "x"), ("رمز من 1234 است چطور قوی کنم؟", "y"),
                                 ("پایتخت فرانسه", "پاریس")):
            self.assertFalse(self.mem.keep(question, answer).ok)
        self.assertFalse(os.path.exists(self.path), "a refused answer must not even create the file")

    def test_a_damaged_file_is_set_aside_and_a_fresh_one_starts(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.mem.count(), 0)
        self.assertIsNotNone(self.mem.recovery)
        moved = os.path.join(os.path.dirname(self.path), self.mem.recovery["moved_to"])
        self.assertTrue(os.path.isfile(moved), "the old bytes are kept for inspection, not deleted")
        with open(moved, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{not json")
        self.assertTrue(self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER).ok)
        self.assertEqual(self.reopen().count(), 1)

    def test_one_bad_item_makes_the_whole_file_foreign(self):
        os.makedirs(os.path.dirname(self.path))
        good = {"q": ["پایتخت", "فرانسه", "کجاست"], "a": ANSWER, "ts": 1.0, "last": 1.0, "uses": 0}
        bad = dict(good, uses="many")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "items": [good, bad]}, handle)
        self.assertEqual(self.mem.count(), 0)
        self.assertIsNotNone(self.mem.recovery)

    def test_a_foreign_schema_is_not_trusted(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"schema": 2, "items": []}, handle)
        self.assertEqual(self.mem.count(), 0)
        self.assertIsNotNone(self.mem.recovery)

    def test_a_symlink_is_refused(self):
        os.makedirs(os.path.dirname(self.path))
        target = os.path.join(self.tmp, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "items": [{"q": ["الف", "ب", "ج"], "a": "x", "ts": 1, "last": 1, "uses": 0}]}, handle)
        os.symlink(target, self.path)
        self.assertEqual(self.mem.count(), 0)

    def test_a_failing_disk_never_raises_and_never_loses_what_is_in_memory(self):
        self.assertTrue(self.mem.keep("پایتخت فرانسه کجاست؟", ANSWER).ok)
        with mock.patch.object(L.store, "write_private_json", side_effect=OSError("disk full")):
            result = self.mem.keep("پایتخت ایتالیا کجاست؟", "رم است.")
            self.assertEqual((result.ok, result.reason), (False, "write_failed"))
            self.assertEqual(self.mem.find("پایتخت فرانسه کجاست؟").answer, ANSWER, "a failed touch must not hide the answer")
            self.assertFalse(self.mem.drop(("پایتخت", "فرانسه", "کجاست")), "a drop that could not be saved is not reported as done")

    def test_a_threads_race_keeps_the_file_valid(self):
        import threading
        errors = []

        def work(n):
            try:
                for i in range(15):
                    question = "چرا مثال شمارهٔ %s درست است؟" % ("پ" * ((n * 15 + i) % 30 + 1) + "ت" * (n + 1))
                    self.assertTrue(self.mem.keep(question, "جواب").ok)
                    self.assertIsNotNone(self.mem.find(question))
            except Exception as exc:                      # pragma: no cover - the assertion below reports it
                errors.append(exc)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.reopen().count(), self.mem.count())
        self.assertGreater(self.mem.count(), 20)


class AgeLabelTests(unittest.TestCase):
    def test_the_age_is_said_in_plain_persian(self):
        table = ((0, "همین الان"), (89, "همین الان"), (300, "۵ دقیقه پیش"), (3 * 3600, "۳ ساعت پیش"), (3 * 86400, "۳ روز پیش"),
                 (86400 * 90, "۳ ماه پیش"), (-5, "همین الان"))
        for seconds, text in table:
            with self.subTest(seconds=seconds):
                self.assertEqual(L.age_label(seconds), text)


class PrivacyGateRegressionTests(unittest.TestCase):
    """Found while testing the answer memory: short passwords written with the plain word «رمز» were not recognised."""

    def test_a_secret_next_to_a_plain_password_word_is_blocked(self):
        for text in ("رمز من 1234 است چطور قوی کنم؟", "رمز من ۱۲۳۴ است", "رمزم ۱۲۳۴ است", "رمز 1234", "رمز1234", "۱۲۳۴ رمز من است",
                     "رمز اینستاگرامم qwerty123 است", "رمز عبورم abc12345 هست", "cvv2 456", "CVV 4567", "پین ۱۲۳۴", "pin is 8841",
                     "my password is hunter2"):
            with self.subTest(text=text):
                verdict = privacy.check(text, True)
                self.assertFalse(verdict.ok, text)
                self.assertEqual((verdict.kind, verdict.secret), ("credential", True))

    def test_everyday_words_that_only_look_alike_are_not_blocked(self):
        for text in ("رمزارز بیتکوین در سال 2024 چقدر رشد کرد؟", "رمزنگاری AES چگونه کار می‌کند؟", "رمز سزار چیست؟", "رمز موفقیت چیست؟",
                     "پینگ پنگ در سال 2024 کجا برگزار شد؟", "spinning 2024 chart", "تفاوت پین و پیچ چیست؟", "کد ورود به ایران برای گردشگران چیست؟",
                     "پایتخت فرانسه کجاست؟"):
            with self.subTest(text=text):
                self.assertTrue(privacy.check(text, True).ok, text)


if __name__ == "__main__":
    unittest.main()
